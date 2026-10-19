# AgenticArxiv/scheduler/subscription.py
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Subscription(BaseModel):
    """用户订阅配置"""
    id: str = Field(default=None)
    name: str = Field(..., description="订阅名称")

    def __init__(self, **data):
        if "id" not in data or data["id"] is None:
            data["id"] = uuid.uuid4().hex[:8]
        super().__init__(**data)
    aspects: List[str] = Field(
        default_factory=list,
        description="arXiv 领域代码列表，如 ['LG', 'CV', 'CL']（无需 cs. 前缀）"
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="关键词过滤列表，标题包含任一关键词则保留"
    )
    exclude_keywords: List[str] = Field(
        default_factory=list,
        description="排除关键词，标题包含任一关键词则过滤掉"
    )
    # 关键词匹配模式：any = 任一命中（默认），all = 全部命中
    match_mode: str = Field(default="any", description="关键词匹配模式：any | all")
    days: int = Field(default=7, ge=1, le=30, description="拉取天数")
    max_results: int = Field(default=15, ge=1, le=100, description="最大条数")
    enabled: bool = Field(default=True, description="是否启用")
    session_id: str = Field(default="default", description="关联的 session")
    # 用户在设置面板配置的周期（分钟）。None 表示跟随默认周期（每 6 小时 + 08/14/20）
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=10080, description="调度周期（分钟）")
    last_run_at: Optional[datetime] = None
    last_run_count: int = Field(default=0, description="上次拉取到的论文数")
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class SubscriptionResult(BaseModel):
    """订阅执行结果"""
    subscription_id: str
    subscription_name: str
    papers_count: int
    new_papers_count: int
    papers: List[dict] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    duration_ms: int = 0
    run_at: datetime = Field(default_factory=datetime.now)


# 默认订阅配置（可自定义修改）
DEFAULT_SUBSCRIPTIONS = [
    Subscription(
        id="daily_ml",
        name="机器学习每日精选",
        aspects=["LG"],  # cs.LG
        keywords=["neural", "deep learning", "transformer", "LLM", "diffusion", "generative"],
        exclude_keywords=["survey", "review"],
        days=3,
        max_results=20,
    ),
    Subscription(
        id="daily_cv",
        name="计算机视觉每日精选",
        aspects=["CV"],  # cs.CV
        keywords=["image", "video", "object detection", "segmentation", "diffusion model"],
        exclude_keywords=["survey", "review"],
        days=3,
        max_results=15,
    ),
    Subscription(
        id="daily_nlp",
        name="自然语言处理每日精选",
        aspects=["CL"],  # cs.CL
        keywords=["language model", "LLM", "transformer", "text", "dialogue", "reasoning"],
        days=3,
        max_results=15,
    ),
    Subscription(
        id="daily_ai",
        name="人工智能综合",
        aspects=["AI"],  # cs.AI
        keywords=["reinforcement learning", "robotics", "planning", "knowledge"],
        days=5,
        max_results=10,
    ),
]
