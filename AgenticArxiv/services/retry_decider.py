"""RetryDecider：根据自我评估结果与重试历史，决定是否对当前步骤重试。

设计原则：
- 安全优先：默认不强制重试（避免破坏 Agent 主循环）
- 重试上限：同一 tool 在一次 run 内最多重试 N 次（默认 1）
- 仅在以下情况建议重试：
    1) 评估 should_retry=True 且质量分 < 阈值
    2) 工具明确报错
    3) 同一工具连续 retry_count 次仍失败
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class RetryDecision:
    should_retry: bool
    reason: str
    retry_budget_left: int


class RetryDecider:
    """基于规则的轻量重试决策器"""

    def __init__(
        self,
        quality_threshold: float = 0.5,
        max_retries_per_tool: int = 1,
    ):
        self.quality_threshold = quality_threshold
        self.max_retries_per_tool = max_retries_per_tool

    def decide(
        self,
        tool_name: str,
        evaluation: Any,
        retry_count: int,
        observation: str = "",
    ) -> RetryDecision:
        # 统一评估字段
        if isinstance(evaluation, dict):
            quality = float(evaluation.get("quality_score", 0.5))
            eval_retry = bool(evaluation.get("should_retry", False))
            issues = evaluation.get("issues") or []
        else:
            quality = float(getattr(evaluation, "quality_score", 0.5))
            eval_retry = bool(getattr(evaluation, "should_retry", False))
            issues = list(getattr(evaluation, "issues", []) or [])

        budget_left = max(0, self.max_retries_per_tool - retry_count)

        # 1) 预算耗尽
        if budget_left <= 0:
            return RetryDecision(False, "重试预算耗尽", 0)

        # 2) 评估器明确要求重试 + 质量低于阈值
        if eval_retry and quality < self.quality_threshold:
            return RetryDecision(
                True,
                f"评估器建议重试（质量分 {quality:.2f} < {self.quality_threshold}）",
                budget_left - 1,
            )

        # 3) 工具明显失败
        fail_keywords = ("错误", "执行失败", "不存在", "未获取到")
        if any(k in (observation or "") for k in fail_keywords):
            return RetryDecision(
                True,
                "工具返回包含失败标识",
                budget_left - 1,
            )

        # 4) 连续低质量
        if quality < self.quality_threshold and "质量" in str(issues):
            return RetryDecision(True, "整体质量偏低", budget_left - 1)

        return RetryDecision(False, "无需重试", budget_left)


class SimpleRetryDecider:
    """最简决策器：仅当 observation 含错误关键字才重试"""

    def decide(
        self,
        tool_name: str,
        evaluation: Any,
        retry_count: int,
        observation: str = "",
    ) -> RetryDecision:
        budget_left = max(0, 1 - retry_count)
        is_error = any(
            k in (observation or "")
            for k in ("错误", "执行失败", "不存在", "未获取到")
        )
        if is_error and budget_left > 0:
            return RetryDecision(True, "工具返回失败", budget_left - 1)
        return RetryDecision(False, "无需重试", budget_left)
