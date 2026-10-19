# agents/self_evaluator.py
"""
自我评估模块 (Self-Evaluator)

在 Agent 每一步工具执行后，对结果进行质量评估：
1. 判断工具调用是否成功（成功 / 失败 / 需要重试）
2. 判断结果质量（高 / 中 / 低）
3. 决定是否需要重试（最多 N 次）或继续下一步

评估策略：
- ask_paper: 检查 answer 非空、sources 有引用、confidence 不为 low
- get_recently_submitted_cs_papers: 检查返回论文数量 > 0
- download_arxiv_pdf: 检查 paper_id 存在、status 为 READY 或已入队
- translate_arxiv_pdf: 检查 task_id 返回、非错误信息
- 其他工具: 检查返回非 error 字符串、长度合理
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional, List
import re

from utils.logger import log
from tools.tool_registry import registry


# ============ 数据结构 ============

@dataclass
class EvaluationResult:
    """单步评估结果"""
    tool_name: str
    success: bool                    # 工具是否成功执行
    quality: str                     # "high" | "medium" | "low"
    quality_score: float = 0.5        # 数值分 0.0-1.0（供 RetryDecider 使用）
    need_retry: bool = False          # 是否需要重试
    retry_count: int = 0              # 当前重试次数
    reason: str = ""                  # 评估理由
    improvement_hint: str = ""        # 改进建议（用于重试时优化参数）

    def __post_init__(self):
        # 从 quality 字段自动推导 quality_score（未显式设置时）
        if self.quality_score == 0.5 and self.quality:
            score_map = {"high": 0.9, "medium": 0.5, "low": 0.2}
            self.quality_score = score_map.get(self.quality, 0.5)


@dataclass
class StepEvaluation:
    """一步的完整评估报告"""
    step_index: int
    tool_name: str
    action_args: dict
    observation: str
    eval_result: EvaluationResult
    retry_history: List[EvaluationResult] = field(default_factory=list)


# ============ 评估器基类 ============

class BaseEvaluator:
    """工具评估器基类，子类实现具体工具的评估逻辑"""

    def evaluate(
        self,
        tool_name: str,
        args: dict,
        observation: str,
        retry_count: int,
    ) -> EvaluationResult:
        """
        对工具执行结果进行评估。

        参数:
            tool_name: 工具名称
            args: 工具调用参数
            observation: 工具执行后的原始返回（字符串）
            retry_count: 当前已重试次数

        返回:
            EvaluationResult
        """
        # 通用评估：检查是否包含错误信息
        if self._is_error(observation):
            return EvaluationResult(
                tool_name=tool_name,
                success=False,
                quality="low",
                need_retry=False,  # 错误通常是参数问题，重试可能无效
                retry_count=retry_count,
                reason=f"工具返回错误信息: {observation[:100]}",
                improvement_hint="检查工具参数是否正确，或工具是否可用",
            )

        # 分发到具体工具评估
        method_name = f"_eval_{tool_name}"
        if hasattr(self, method_name):
            return getattr(self, method_name)(args, observation, retry_count)
        else:
            return self._eval_generic(tool_name, args, observation, retry_count)

    def _is_error(self, observation: str) -> bool:
        """判断返回是否包含错误"""
        if not isinstance(observation, str):
            return False
        # 常见错误关键词
        error_patterns = [
            r"^错误[:：]",
            r"^Error[:：]",
            r"失败",
            r"not found",
            r"not exist",
            r"invalid",
            r"exception",
            r"traceback",
            r"HTTP [45]\d{2}",
            r"api_key",
            r"timeout",
            r"connection",
        ]
        for pattern in error_patterns:
            if re.search(pattern, observation, re.IGNORECASE):
                return True
        return False

    def _eval_generic(
        self, tool_name: str, args: dict, observation: str, retry_count: int
    ) -> EvaluationResult:
        """通用评估策略：非空、有内容即算成功"""
        if not observation or len(observation.strip()) < 5:
            return EvaluationResult(
                tool_name=tool_name,
                success=False,
                quality="low",
                quality_score=0.1,
                need_retry=True,
                retry_count=retry_count,
                reason="返回内容过少或为空",
                improvement_hint="检查工具调用参数是否正确",
            )

        return EvaluationResult(
            tool_name=tool_name,
            success=True,
            quality="medium",
            quality_score=0.5,
            need_retry=False,
            retry_count=retry_count,
            reason="工具正常执行",
        )


# ============ 具体工具评估器 ============

class ReActEvaluator(BaseEvaluator):
    """
    ReAct Agent 专用评估器。

    评估策略：
    - ask_paper: 要求 answer 非空、sources 非空、confidence 不是 low
    - get_recently_submitted_cs_papers: 要求返回论文列表，非空
    - download_arxiv_pdf: 要求 paper_id 存在、status OK
    - translate_arxiv_pdf: 要求 task_id 返回
    - cache_status: 要求返回有效状态
    """

    def _eval_ask_paper(
        self, args: dict, observation: str, retry_count: int
    ) -> EvaluationResult:
        """评估 ask_paper 返回结果"""
        if not isinstance(observation, str):
            observation = str(observation)

        # 检查是否包含答案内容
        has_answer = (
            "answer" in observation.lower()
            or len(observation) > 20
        )

        # 检查是否提到了 chunk_count（表示索引成功）
        has_chunks = "chunk" in observation.lower() or "检索" in observation

        # 检查置信度（通过关键词判断）
        confidence_high = any(kw in observation for kw in ["high", "高", "置信", "可信"])
        confidence_low = any(kw in observation for kw in ["low", "低", "不足", "未涉及"])

        if not has_answer and not has_chunks:
            return EvaluationResult(
                tool_name="ask_paper",
                success=False,
                quality="low",
                need_retry=False,
                retry_count=retry_count,
                reason="ask_paper 返回内容异常，可能是 PDF 未下载或 chunk 为空",
                improvement_hint="先确保 PDF 已下载（download_arxiv_pdf），或检查 paper_id 是否正确",
            )

        if confidence_low or (not has_chunks and len(observation) < 50):
            return EvaluationResult(
                tool_name="ask_paper",
                success=True,
                quality="low",
                need_retry=True,
                retry_count=retry_count,
                reason="检索置信度低，可能没有找到相关内容",
                improvement_hint="尝试用更具体的关键词重写问题，或增大 top_k 参数",
            )

        if confidence_high or has_chunks:
            return EvaluationResult(
                tool_name="ask_paper",
                success=True,
                quality="high",
                need_retry=False,
                retry_count=retry_count,
                reason="ask_paper 成功返回了高质量答案",
            )

        return EvaluationResult(
            tool_name="ask_paper",
            success=True,
            quality="medium",
            need_retry=False,
            retry_count=retry_count,
            reason="ask_paper 返回了答案",
        )

    def _eval_get_recently_submitted_cs_papers(
        self, args: dict, observation: str, retry_count: int
    ) -> EvaluationResult:
        """评估 arXiv 搜索结果"""
        if not isinstance(observation, str):
            observation = str(observation)

        # 提取论文数量
        match = re.search(r"(\d+)\s*篇论文", observation)
        if match:
            count = int(match.group(1))
            if count == 0:
                return EvaluationResult(
                    tool_name="get_recently_submitted_cs_papers",
                    success=False,
                    quality="low",
                    need_retry=True,
                    retry_count=retry_count,
                    reason="未获取到任何论文",
                    improvement_hint="尝试扩大搜索范围（增加 days 参数）或调整关键词",
                )
            elif count >= 5:
                return EvaluationResult(
                    tool_name="get_recently_submitted_cs_papers",
                    success=True,
                    quality="high",
                    need_retry=False,
                    retry_count=retry_count,
                    reason=f"成功获取 {count} 篇论文",
                )
            else:
                return EvaluationResult(
                    tool_name="get_recently_submitted_cs_papers",
                    success=True,
                    quality="medium",
                    need_retry=False,
                    retry_count=retry_count,
                    reason=f"获取到 {count} 篇论文（较少）",
                    improvement_hint="可尝试扩大搜索范围以获取更多结果",
                )

        # 检查是否有错误提示
        if "未获取" in observation or "失败" in observation:
            return EvaluationResult(
                tool_name="get_recently_submitted_cs_papers",
                success=False,
                quality="low",
                need_retry=True,
                retry_count=retry_count,
                reason="获取论文失败",
                improvement_hint="检查 API 是否可用，或尝试调整 aspect/keywords 参数",
            )

        # 有内容但没解析出数量
        return EvaluationResult(
            tool_name="get_recently_submitted_cs_papers",
            success=True,
            quality="medium",
            need_retry=False,
            retry_count=retry_count,
            reason="获取到论文结果",
        )

    def _eval_download_arxiv_pdf(
        self, args: dict, observation: str, retry_count: int
    ) -> EvaluationResult:
        """评估 PDF 下载结果"""
        if not isinstance(observation, str):
            observation = str(observation)

        # 成功标志
        success_keywords = ["READY", "task_id", "成功", "创建任务", "pending", "PENDING"]
        failure_keywords = ["失败", "不存在", "not exist", "error", "错误"]

        has_success = any(kw.lower() in observation.lower() for kw in success_keywords)
        has_failure = any(kw.lower() in observation.lower() for kw in failure_keywords)

        if has_failure:
            return EvaluationResult(
                tool_name="download_arxiv_pdf",
                success=False,
                quality="low",
                need_retry=False,
                retry_count=retry_count,
                reason="PDF 下载失败",
                improvement_hint="检查 paper_id/ref 是否正确，或网络连接是否正常",
            )

        if has_success:
            return EvaluationResult(
                tool_name="download_arxiv_pdf",
                success=True,
                quality="high",
                need_retry=False,
                retry_count=retry_count,
                reason="PDF 下载已启动或完成",
            )

        # 解析状态
        match = re.search(r"status[=:\s]+(\w+)", observation, re.IGNORECASE)
        if match:
            status = match.group(1).upper()
            if status == "READY":
                return EvaluationResult(
                    tool_name="download_arxiv_pdf",
                    success=True,
                    quality="high",
                    need_retry=False,
                    retry_count=retry_count,
                    reason=f"PDF 状态为 READY",
                )
            elif status in ("PENDING", "DOWNLOADING"):
                return EvaluationResult(
                    tool_name="download_arxiv_pdf",
                    success=True,
                    quality="medium",
                    need_retry=False,
                    retry_count=retry_count,
                    reason=f"PDF 下载中 (status={status})",
                )

        return EvaluationResult(
            tool_name="download_arxiv_pdf",
            success=True,
            quality="medium",
            need_retry=False,
            retry_count=retry_count,
            reason="下载工具已执行",
        )

    def _eval_translate_arxiv_pdf(
        self, args: dict, observation: str, retry_count: int
    ) -> EvaluationResult:
        """评估翻译任务结果"""
        if not isinstance(observation, str):
            observation = str(observation)

        if "task_id" in observation and "失败" not in observation:
            return EvaluationResult(
                tool_name="translate_arxiv_pdf",
                success=True,
                quality="high",
                need_retry=False,
                retry_count=retry_count,
                reason="翻译任务已创建（异步）",
            )

        if "失败" in observation or "错误" in observation:
            return EvaluationResult(
                tool_name="translate_arxiv_pdf",
                success=False,
                quality="low",
                need_retry=False,
                retry_count=retry_count,
                reason="翻译任务创建失败",
                improvement_hint="检查 PDF 是否已下载，或 paper_id/ref 是否正确",
            )

        return EvaluationResult(
            tool_name="translate_arxiv_pdf",
            success=True,
            quality="medium",
            need_retry=False,
            retry_count=retry_count,
            reason="翻译工具已执行",
        )

    def _eval_search_papers_nl(
        self, args: dict, observation: str, retry_count: int
    ) -> EvaluationResult:
        """评估 search_papers_nl 自然语言搜索结果"""
        if not isinstance(observation, str):
            observation = str(observation)

        # 检查是否为空结果
        if "未获取到" in observation or "0 篇" in observation:
            return EvaluationResult(
                tool_name="search_papers_nl",
                success=False,
                quality="low",
                quality_score=0.1,
                need_retry=True,
                retry_count=retry_count,
                reason="搜索返回 0 篇论文",
                improvement_hint="尝试用更简短的核心词搜索，或换用 get_recently_submitted_cs_papers 配合同义关键词组合",
            )

        # 检查论文相关性：observation 里如果有标题带分
        import re
        high_score_matches = re.findall(r"\[([0-9.]+)分\]", observation)
        if high_score_matches:
            scores = [float(s) for s in high_score_matches]
            avg = sum(scores) / len(scores)
            max_score = max(scores)
            # 映射到 0-1：5分→1.0, 3分→0.6
            normalized_avg = avg / 5.0
            if max_score >= 4.5 and avg >= 3.5:
                return EvaluationResult(
                    tool_name="search_papers_nl",
                    success=True,
                    quality="high",
                    quality_score=max(0.7, normalized_avg),
                    need_retry=False,
                    retry_count=retry_count,
                    reason=f"搜索到 {len(scores)} 篇论文，top={max_score:.1f}分，avg={avg:.1f}分，质量高",
                )
            elif max_score >= 3.5:
                return EvaluationResult(
                    tool_name="search_papers_nl",
                    success=True,
                    quality="medium",
                    quality_score=normalized_avg,
                    need_retry=False,
                    retry_count=retry_count,
                    reason=f"搜索到 {len(scores)} 篇论文，top={max_score:.1f}分，结果相关性一般",
                    improvement_hint="如需更精确匹配，可换用 search_openalex_papers 布尔精确语法，如: query=\"soft tissue deformation\" AND neural network",
                )
            else:
                # 最高分 < 3.5，相关性偏低，重试
                return EvaluationResult(
                    tool_name="search_papers_nl",
                    success=True,
                    quality="low",
                    quality_score=0.3,
                    need_retry=True,
                    retry_count=retry_count,
                    reason=f"搜索到 {len(scores)} 篇论文，但相关性偏低（top={max_score:.1f}分），与查询意图不匹配",
                    improvement_hint="改用更精确的关键词组合，如 'soft tissue deformation modeling' AND neural network，或换用 search_openalex_papers 精确布尔查询",
                )

        # 有论文但没解析到分数
        if "成功获取" in observation and "篇论文" in observation:
            return EvaluationResult(
                tool_name="search_papers_nl",
                success=True,
                quality="medium",
                quality_score=0.5,
                need_retry=False,
                retry_count=retry_count,
                reason="搜索成功返回论文",
            )

        return self._eval_generic("search_papers_nl", args, observation, retry_count)

    def _eval_search_openalex_papers(
        self, args: dict, observation: str, retry_count: int
    ) -> EvaluationResult:
        """评估 search_openalex_papers 布尔关键词搜索结果"""
        if not isinstance(observation, str):
            observation = str(observation)
        if "未获取到" in observation or "0 篇" in observation:
            return EvaluationResult(
                tool_name="search_openalex_papers",
                success=False,
                quality="low",
                need_retry=True,
                retry_count=retry_count,
                reason="搜索返回 0 篇论文",
                improvement_hint="检查查询词是否拼写正确，或放宽布尔条件（如去掉 NOT）",
            )
        if "成功获取" in observation and "篇论文" in observation:
            return EvaluationResult(
                tool_name="search_openalex_papers",
                success=True,
                quality="medium",
                need_retry=False,
                retry_count=retry_count,
                reason="布尔关键词搜索成功",
            )
        return self._eval_generic("search_openalex_papers", args, observation, retry_count)

    def _eval_summarize_paper(
        self, args: dict, observation: str, retry_count: int
    ) -> EvaluationResult:
        """评估摘要生成结果"""
        if not isinstance(observation, str):
            observation = str(observation)

        # 检查是否有实质性内容（摘要通常较长）
        if len(observation) < 30:
            return EvaluationResult(
                tool_name="summarize_paper",
                success=False,
                quality="low",
                need_retry=True,
                retry_count=retry_count,
                reason="摘要内容过少，可能 PDF 未下载或 chunk 为空",
                improvement_hint="确保 PDF 已下载后再调用 summarize_paper",
            )

        if "error" in observation.lower():
            return EvaluationResult(
                tool_name="summarize_paper",
                success=False,
                quality="low",
                need_retry=False,
                retry_count=retry_count,
                reason="摘要生成失败",
                improvement_hint="检查 paper_id 和 PDF 下载状态",
            )

        return EvaluationResult(
            tool_name="summarize_paper",
            success=True,
            quality="high" if len(observation) > 100 else "medium",
            need_retry=False,
            retry_count=retry_count,
            reason="摘要生成成功",
        )

    def _eval_get_paper_cache_status(
        self, args: dict, observation: str, retry_count: int
    ) -> EvaluationResult:
        """评估缓存状态查询结果"""
        if not isinstance(observation, str):
            observation = str(observation)

        # 检查是否有状态信息
        has_status = any(kw in observation.lower() for kw in ["ready", "pending", "status", "状态", "pdf"])
        if not has_status:
            return EvaluationResult(
                tool_name="get_paper_cache_status",
                success=False,
                quality="low",
                need_retry=True,
                retry_count=retry_count,
                reason="状态返回内容异常",
                improvement_hint="检查 paper_id/ref 是否正确",
            )

        return EvaluationResult(
            tool_name="get_paper_cache_status",
            success=True,
            quality="medium",
            need_retry=False,
            retry_count=retry_count,
            reason="状态查询成功",
        )


# ============ 重试决策器 ============

@dataclass
class RetryPolicy:
    """重试策略配置"""
    max_retries: int = 2                      # 单工具最多重试次数
    retry_on_quality_low: bool = True        # quality=low 时是否重试
    retry_on_success_false: bool = True       # success=False 时是否重试
    backoff_multiplier: float = 1.5          # 重试间隔倍数（当前版本未用，预留）


class RetryDecider:
    """根据评估结果决定是否重试"""

    def __init__(self, policy: Optional[RetryPolicy] = None):
        self.policy = policy or RetryPolicy()

    def should_retry(
        self, eval_result: EvaluationResult
    ) -> bool:
        """
        判断是否应该重试。

        规则：
        1. 已达到最大重试次数 → 不重试
        2. 工具明确失败（错误信息）→ 不重试（参数问题）
        3. quality=low + retry_on_quality_low=True → 可以重试
        4. success=False + retry_on_success_false=True → 可以重试
        5. 其他情况 → 不重试
        """
        if eval_result.retry_count >= self.policy.max_retries:
            log.info(
                f"[SelfEval] {eval_result.tool_name} 已重试 "
                f"{eval_result.retry_count}/{self.policy.max_retries} 次，放弃重试"
            )
            return False

        # 工具返回错误（参数问题等），不建议重试
        if "错误" in eval_result.reason and "重试" not in eval_result.reason:
            return False

        # 低质量且允许重试
        if eval_result.quality == "low" and self.policy.retry_on_quality_low:
            return True

        # 明确失败
        if not eval_result.success and self.policy.retry_on_success_false:
            return True

        return False

    def get_retry_hint(self, eval_result: EvaluationResult, args: dict) -> dict:
        """
        根据评估结果生成重试时的参数优化建议。

        目前支持对 ask_paper 的 top_k 参数自动调整。
        """
        tool_name = eval_result.tool_name
        hint = eval_result.improvement_hint

        if tool_name == "ask_paper":
            # 置信度低时尝试增大 top_k
            if "top_k" in args:
                current_k = args.get("top_k", 5)
                return {
                    "args": {"top_k": min(current_k + 3, 10)},
                    "reason": f"置信度低，增大 top_k 从 {current_k} → {min(current_k + 3, 10)} 以获取更多上下文",
                }

        # 其他工具暂不自动调整参数
        return {"args": args, "reason": hint}


# ============ 自我评估器（对外统一接口） ============

class SelfEvaluator:
    """
    自我评估器（对外统一接口）。

    使用方式：
        evaluator = SelfEvaluator()
        result = evaluator.evaluate_step(
            step_index=0,
            tool_name="ask_paper",
            args={"paper_id": "2301.12345", "question": "方法是什么", "top_k": 5},
            observation="成功获取了答案...",
            retry_count=0,
        )

        if result.eval_result.need_retry:
            retry_args = decider.get_retry_hint(result.eval_result, args)
            # 重试调用...
    """

    def __init__(self, policy: Optional[RetryPolicy] = None):
        self.evaluator = ReActEvaluator()
        self.decider = RetryDecider(policy or RetryPolicy())

    def evaluate_step(
        self,
        step_index: int,
        tool_name: str,
        args: dict,
        observation: str,
        retry_count: int = 0,
    ) -> StepEvaluation:
        """
        对单步执行结果进行评估。

        参数:
            step_index: 当前步序号（从 0 开始）
            tool_name: 工具名称
            args: 工具调用参数
            observation: 工具执行返回的原始字符串
            retry_count: 当前已重试次数

        返回:
            StepEvaluation: 包含评估结果的完整报告
        """
        eval_result = self.evaluator.evaluate(tool_name, args, observation, retry_count)

        # 评估完成后判断是否需要重试（但不自动重试）
        need_retry = self.decider.should_retry(eval_result)

        step_eval = StepEvaluation(
            step_index=step_index,
            tool_name=tool_name,
            action_args=args,
            observation=observation,
            eval_result=eval_result,
            retry_history=[],
        )

        log.info(
            f"[SelfEval] step={step_index} tool={tool_name} "
            f"success={eval_result.success} quality={eval_result.quality} "
            f"need_retry={need_retry} reason={eval_result.reason[:80]}"
        )

        return step_eval

    def build_evaluation_prompt(
        self,
        tool_name: str,
        args: dict,
        observation: str,
        quality: str,
    ) -> str:
        """
        生成评估提示词（用于 LLM 辅助评估）。

        当规则评估不确定时，可以让 LLM 进一步判断。
        当前版本暂不使用，预留给未来扩展。
        """
        return f"""请评估以下工具执行结果的质量：

工具名称: {tool_name}
调用参数: {args}
执行结果: {observation[:500]}

评估要求：
1. 判断执行是否成功（成功/失败/部分成功）
2. 判断结果质量（高/中/低）
3. 如果需要改进，给出具体建议

请用以下格式回复：
评估: [成功/失败/部分成功]
质量: [高/中/低]
建议: [具体改进建议或留空]"""

    def get_overall_assessment(self, step_evals: List[StepEvaluation]) -> dict:
        """
        对整个 Agent 执行过程进行综合评估。

        参数:
            step_evals: 所有步骤的评估结果列表

        返回:
            dict: {
                "overall_quality": "high" | "medium" | "low",
                "success_rate": float,
                "failed_steps": List[step_index],
                "summary": str,
            }
        """
        if not step_evals:
            return {
                "overall_quality": "unknown",
                "success_rate": 0.0,
                "failed_steps": [],
                "summary": "无执行记录",
            }

        total = len(step_evals)
        successful = sum(1 for e in step_evals if e.eval_result.success)
        high_quality = sum(1 for e in step_evals if e.eval_result.quality == "high")
        failed_steps = [
            e.step_index for e in step_evals if not e.eval_result.success
        ]

        if high_quality == total:
            overall = "high"
        elif successful >= total * 0.7:
            overall = "medium"
        else:
            overall = "low"

        summary_parts = [
            f"共 {total} 步执行，{successful} 步成功",
            f"高质量步骤 {high_quality}/{total}",
        ]
        if failed_steps:
            summary_parts.append(f"失败步骤: {failed_steps}")

        return {
            "overall_quality": overall,
            "success_rate": round(successful / total, 2),
            "failed_steps": failed_steps,
            "summary": "，".join(summary_parts),
        }
