"""SelfEvaluator：对 Agent 每一步的工具调用进行自我评估。

设计目标：
- 极轻量、零额外配置即可用（无 LLM 时退化为启发式）
- 接口稳定：始终返回带 to_dict() / quality_score / should_retry / issues / suggestion 的对象
- 评估结果用于：
    1) 实时推送给前端 (SSE 'self_evaluation' 事件)
    2) 回填到 history，让 LLM 在下一步看到上一次评估（自纠错）
    3) 汇总生成整体报告
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from utils.logger import log


@dataclass
class StepEvaluation:
    """单步评估结果，统一的输出结构"""
    quality_score: float = 0.5          # 0~1，越高越好
    should_retry: bool = False          # 是否建议重试
    issues: List[str] = field(default_factory=list)
    suggestion: str = ""
    # 元信息
    step_index: int = 0
    tool_name: str = ""
    used_llm: bool = False
    fallback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------- 提示词模板 ----------

_EVAL_PROMPT = """你是 Agent 步骤评估器。请评估 Agent 刚刚执行的这一步是否成功且高效。

【任务上下文】
{context}

【本步信息】
- Step: {step_index}
- 工具: {tool_name}
- 参数: {tool_args}
- 观察(截断): {observation}

【评估维度】（每项 0-1）
1. tool_success: 工具调用是否成功（无报错/格式异常）
2. relevance: 工具选择和参数是否契合任务目标
3. efficiency: 是否存在重复/冗余/无意义的调用

【输出 JSON 字段】
- quality_score: 综合分（0-1）
- should_retry: 是否建议立即重试（true/false）
- issues: 问题列表（数组，简洁中文）
- suggestion: 改进建议（一句话中文）

仅输出 JSON，不要解释。
"""


class SelfEvaluator:
    """基于 LLM 的自我评估器"""

    def __init__(self, llm_client: Any = None, model: Optional[str] = None, max_obs_chars: int = 1500):
        self.llm_client = llm_client
        # 没有显式传 model 时回落到环境变量 / 系统默认，避免请求体里发送 model=null
        if not model:
            from config import settings
            model = os.getenv("LLM_MODEL") or settings.models.agent_model
        self.model = model
        self.max_obs_chars = max_obs_chars

    def evaluate_step(
        self,
        step_index: int,
        tool_name: str,
        args: Dict[str, Any],
        observation: str,
        retry_count: int = 0,
        context: str = "",
    ) -> StepEvaluation:
        if self.llm_client is None:
            return SimpleSelfEvaluator().evaluate_step(
                step_index=step_index, tool_name=tool_name,
                args=args, observation=observation, retry_count=retry_count,
            )

        prompt = _EVAL_PROMPT.format(
            context=context or "(无)",
            step_index=step_index,
            tool_name=tool_name,
            tool_args=json.dumps(args, ensure_ascii=False)[:500],
            observation=(observation or "")[: self.max_obs_chars],
        )

        try:
            response = self.llm_client.chat_completions(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是严格的 Agent 步骤评估器。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=400,
                stream=False,
            )
            content = (
                response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            data = _safe_parse_json(content)
            if data is None:
                # JSON 解析失败 → 退化
                ev = SimpleSelfEvaluator().evaluate_step(
                    step_index, tool_name, args, observation, retry_count,
                )
                ev.used_llm = False
                ev.fallback_reason = "json_parse_failed"
                return ev

            quality = float(data.get("quality_score", 0.5))
            quality = max(0.0, min(1.0, quality))
            return StepEvaluation(
                quality_score=quality,
                should_retry=bool(data.get("should_retry", False)),
                issues=[str(x) for x in (data.get("issues") or [])][:5],
                suggestion=str(data.get("suggestion", "") or ""),
                step_index=step_index,
                tool_name=tool_name,
                used_llm=True,
            )
        except Exception as e:
            log.warning(f"[SelfEvaluator] LLM 评估失败，切换 SimpleSelfEvaluator: {e}")
            ev = SimpleSelfEvaluator().evaluate_step(
                step_index, tool_name, args, observation, retry_count,
            )
            ev.used_llm = False
            ev.fallback_reason = f"llm_error: {e}"
            return ev


class SimpleSelfEvaluator:
    """无 LLM 时的启发式评估，基于观察文本特征打分"""

    _ERROR_PATTERNS = [
        r"错误[:：]",
        r"执行失败",
        r"Tool execution failed",
        r"Exception",
        r"Traceback",
        r"格式异常",
        r"不存在",
        r"未获取到",
    ]

    def evaluate_step(
        self,
        step_index: int,
        tool_name: str,
        args: Dict[str, Any],
        observation: str,
        retry_count: int = 0,
        **_kwargs,
    ) -> StepEvaluation:
        obs = observation or ""
        issues: List[str] = []

        # 检测错误
        is_error = any(re.search(p, obs) for p in self._ERROR_PATTERNS)
        if is_error:
            issues.append("工具返回包含错误信息")

        # 工具未匹配
        if "工具 '" in obs and "' 不存在" in obs:
            issues.append("工具名无效")

        # 极短输出 / 空输出
        if not obs.strip():
            issues.append("观察为空")
            quality = 0.2
        elif is_error:
            quality = 0.3
        else:
            # 长度启发：正常成功返回一般 >= 10 字符
            if len(obs) < 10:
                issues.append("返回内容过短，可能信息不足")
                quality = 0.5
            else:
                quality = 0.8

        # 重复检索启发：如果同一 tool 在 retry_count>0 后仍失败
        should_retry = is_error and retry_count < 1 and quality < 0.4

        suggestion = ""
        if is_error:
            suggestion = "建议检查工具名/参数/网络，或更换检索策略"
        elif quality < 0.6:
            suggestion = "建议调整参数以获取更丰富的结果"

        return StepEvaluation(
            quality_score=quality,
            should_retry=should_retry,
            issues=issues,
            suggestion=suggestion,
            step_index=step_index,
            tool_name=tool_name,
            used_llm=False,
        )


# ---------- 工具函数 ----------

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _safe_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出中尽量抽取 JSON"""
    if not text:
        return None
    text = text.strip()
    # 1) 直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2) 抽取第一个 {...} 块
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None
