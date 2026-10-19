# AgenticArxiv/services/paper_comparison_service.py
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy.orm import Session as DBSession

from models.schemas import (
    PaperComparison, ComparisonReport, ComparisonDimension,
    ComparisonStatus, Paper, PaperComparisonWithReport,
)
from models.orm import ComparisonRow, ComparisonDimensionRow, SessionPaperRow
from models.store import store
from models.db import get_sync_session
from utils.logger import log
from config import settings


class PaperComparisonService:
    """论文对比服务。"""

    def __init__(self):
        pass

    def _generate_comparison_id(self) -> str:
        """生成唯一的对比 ID"""
        return f"cmp_{uuid.uuid4().hex[:12]}"

    def create_comparison(
        self,
        session_id: str,
        paper_ids: List[str],
    ) -> PaperComparison:
        """
        创建新的论文对比会话

        Args:
            session_id: 会话 ID
            paper_ids: 要对比的论文 ID 列表 (2-10 篇)

        Returns:
            PaperComparison: 创建的对比会话
        """
        if len(paper_ids) < 2:
            raise ValueError("至少需要 2 篇论文才能进行对比")
        if len(paper_ids) > 10:
            raise ValueError("最多支持 10 篇论文同时对比")

        comparison_id = self._generate_comparison_id()
        comparison = PaperComparison(
            comparison_id=comparison_id,
            session_id=session_id,
            paper_ids=paper_ids,
            status="PENDING",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        # 保存到数据库
        db: DBSession = get_sync_session()
        try:
            row = ComparisonRow(
                comparison_id=comparison_id,
                session_id=session_id,
                paper_ids=json.dumps(paper_ids),
                status="PENDING",
                created_at=comparison.created_at,
                updated_at=comparison.updated_at,
            )
            db.add(row)
            db.commit()
            log.info(f"创建论文对比会话: {comparison_id}, 论文数: {len(paper_ids)}")
        except Exception as e:
            db.rollback()
            log.error(f"创建论文对比失败: {e}")
            raise
        finally:
            db.close()

        return comparison

    def get_comparison(self, comparison_id: str) -> Optional[PaperComparison]:
        """获取对比会话。"""
        db: DBSession = get_sync_session()
        try:
            row = db.query(ComparisonRow).filter(
                ComparisonRow.comparison_id == comparison_id,
            ).first()
            if not row:
                return None

            return PaperComparison(
                comparison_id=row.comparison_id,
                session_id=row.session_id,
                paper_ids=json.loads(row.paper_ids),
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                error=row.error,
            )
        finally:
            db.close()

    def get_comparison_with_report(
        self,
        comparison_id: str,
    ) -> Optional[PaperComparisonWithReport]:
        """获取包含完整报告的对比结果"""
        comparison = self.get_comparison(comparison_id)
        if not comparison:
            return None

        papers = self.get_papers_for_comparison(comparison.paper_ids)
        report = self.get_report(comparison_id)

        return PaperComparisonWithReport(
            comparison=comparison,
            report=report,
            papers=papers,
        )

    def get_papers_for_comparison(self, paper_ids: List[str]) -> List[Paper]:
        """获取对比所需的论文列表"""
        db: DBSession = get_sync_session()
        try:
            rows = db.query(SessionPaperRow).filter(
                SessionPaperRow.paper_id.in_(paper_ids),
            ).all()

            papers = []
            for row in rows:
                papers.append(Paper(
                    id=row.paper_id,
                    title=row.title,
                    authors=json.loads(row.authors) if row.authors else [],
                    summary=row.summary,
                    published=row.published,
                    updated=row.updated,
                    pdf_url=row.pdf_url,
                    primary_category=row.primary_category,
                    categories=json.loads(row.categories) if row.categories else [],
                    comment=row.comment,
                    links=json.loads(row.links) if row.links else [],
                    fetched_at=row.fetched_at,
                    fetch_type=row.fetch_type,
                ))

            # 按原始顺序排序
            paper_map = {p.id: p for p in papers}
            return [paper_map[pid] for pid in paper_ids if pid in paper_map]
        finally:
            db.close()

    def list_comparisons(
        self,
        session_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[PaperComparison]:
        """列出系统的对比会话"""
        db: DBSession = get_sync_session()
        try:
            query = db.query(ComparisonRow)
            if session_id:
                query = query.filter(ComparisonRow.session_id == session_id)
            query = query.order_by(ComparisonRow.created_at.desc()).limit(limit)
            rows = query.all()

            comparisons = []
            for row in rows:
                comparisons.append(PaperComparison(
                    comparison_id=row.comparison_id,
                    session_id=row.session_id,
                    paper_ids=json.loads(row.paper_ids),
                    status=row.status,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    error=row.error,
                ))
            return comparisons
        finally:
            db.close()

    def update_status(
        self,
        comparison_id: str,
        status: ComparisonStatus,
        error: Optional[str] = None,
    ) -> Optional[PaperComparison]:
        """更新对比状态"""
        db: DBSession = get_sync_session()
        try:
            row = db.query(ComparisonRow).filter(
                ComparisonRow.comparison_id == comparison_id,
            ).first()
            if not row:
                return None

            row.status = status
            row.updated_at = datetime.now()
            if error:
                row.error = error
            if status == "SUCCEEDED":
                row.updated_at = datetime.now()

            db.commit()

            return PaperComparison(
                comparison_id=row.comparison_id,
                session_id=row.session_id,
                paper_ids=json.loads(row.paper_ids),
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                error=row.error,
            )
        finally:
            db.close()

    def save_report(
        self,
        comparison_id: str,
        overview: Optional[str] = None,
        recommendations: Optional[str] = None,
        dimensions: Optional[List[ComparisonDimension]] = None,
    ) -> bool:
        """保存对比报告"""
        db: DBSession = get_sync_session()
        try:
            # 更新主表
            row = db.query(ComparisonRow).filter(
                ComparisonRow.comparison_id == comparison_id,
            ).first()
            if not row:
                return False

            row.overview = overview
            row.recommendations = recommendations
            row.status = "SUCCEEDED"
            row.updated_at = datetime.now()

            # 保存维度数据
            if dimensions:
                # 先删除旧的维度
                db.query(ComparisonDimensionRow).filter(
                    ComparisonDimensionRow.comparison_id == comparison_id,
                ).delete()

                # 插入新的维度
                for dim in dimensions:
                    dim_row = ComparisonDimensionRow(
                        comparison_id=comparison_id,
                        dimension_name=dim.name,
                        paper_values=json.dumps(dim.paper_values),
                        ranking=json.dumps(dim.ranking),
                        summary=dim.summary,
                        created_at=datetime.now(),
                    )
                    db.add(dim_row)

            db.commit()
            log.info(f"保存对比报告: {comparison_id}")
            return True
        except Exception as e:
            db.rollback()
            log.error(f"保存对比报告失败: {e}")
            return False
        finally:
            db.close()

    def get_report(self, comparison_id: str) -> Optional[ComparisonReport]:
        """获取对比报告"""
        db: DBSession = get_sync_session()
        try:
            row = db.query(ComparisonRow).filter(
                ComparisonRow.comparison_id == comparison_id,
            ).first()
            if not row:
                return None

            # 获取维度数据
            dim_rows = db.query(ComparisonDimensionRow).filter(
                ComparisonDimensionRow.comparison_id == comparison_id,
            ).order_by(ComparisonDimensionRow.id).all()

            dimensions = []
            for dim_row in dim_rows:
                dimensions.append(ComparisonDimension(
                    name=dim_row.dimension_name,
                    paper_values=json.loads(dim_row.paper_values),
                    ranking=json.loads(dim_row.ranking),
                    summary=dim_row.summary,
                ))

            return ComparisonReport(
                comparison_id=comparison_id,
                overview=row.overview,
                dimensions=dimensions,
                recommendations=row.recommendations,
                created_at=row.created_at,
            )
        finally:
            db.close()

    def delete_comparison(self, comparison_id: str) -> bool:
        """删除对比会话及其报告"""
        db: DBSession = get_sync_session()
        try:
            # 删除维度
            db.query(ComparisonDimensionRow).filter(
                ComparisonDimensionRow.comparison_id == comparison_id,
            ).delete()

            # 删除主记录
            deleted = db.query(ComparisonRow).filter(
                ComparisonRow.comparison_id == comparison_id,
            ).delete()

            db.commit()
            log.info(f"删除对比会话: {comparison_id}")
            return deleted > 0
        except Exception as e:
            db.rollback()
            log.error(f"删除对比会话失败: {e}")
            return False
        finally:
            db.close()

    def add_papers_to_comparison(
        self,
        comparison_id: str,
        paper_ids: List[str],
    ) -> Optional[PaperComparison]:
        """向现有对比添加论文"""
        db: DBSession = get_sync_session()
        try:
            row = db.query(ComparisonRow).filter(
                ComparisonRow.comparison_id == comparison_id,
            ).first()
            if not row:
                return None

            existing_ids = json.loads(row.paper_ids)
            new_ids = list(set(existing_ids + paper_ids))  # 去重

            if len(new_ids) < 2:
                raise ValueError("至少需要 2 篇论文才能进行对比")
            if len(new_ids) > 10:
                raise ValueError("最多支持 10 篇论文同时对比")

            row.paper_ids = json.dumps(new_ids)
            row.updated_at = datetime.now()
            db.commit()

            return PaperComparison(
                comparison_id=row.comparison_id,
                session_id=row.session_id,
                paper_ids=new_ids,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                error=row.error,
            )
        finally:
            db.close()

    # ============ LLM 对比分析核心方法 ============

    def _build_paper_content(self, papers: List[Paper]) -> str:
        """构建论文内容字符串，用于 LLM 分析"""
        contents = []
        for i, paper in enumerate(papers, 1):
            content = f"""【论文 {i}】ID: {paper.id}
标题: {paper.title or "未知"}
作者: {", ".join(paper.authors) if paper.authors else "未知"}
摘要: {paper.summary or "无摘要"}"""
            contents.append(content)
        return "\n\n".join(contents)

    def _call_llm(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> str:
        """调用 LLM 生成文本。"""
        from utils.llm_client import get_env_llm_client
        from services.app_settings import get_llm_config

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            client = get_env_llm_client()
            model = get_llm_config().model
            response = client.chat_completions(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response["choices"][0]["message"]["content"]
            if not content or not content.strip():
                finish_reason = response["choices"][0].get("finish_reason")
                usage = response.get("usage", {})
                raise RuntimeError(
                    f"LLM 返回空内容 (model={model}, finish_reason={finish_reason}, "
                    f"usage={usage}, prompt_len≈{len(prompt)})"
                )
            return content
        except Exception as e:
            log.error(f"LLM 调用失败: {e}")
            raise

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 内容（兼容 markdown 代码块、截断重试等）"""
        import re

        original = content
        text = content.strip()

        # 去除 ```json ... ``` 或 ``` ... ``` 包裹
        fence_match = re.search(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", text)
        if fence_match:
            text = fence_match.group(1).strip()

        # 优先尝试整段解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 回退：截取第一个完整 JSON 对象
        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            candidate = brace_match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # 回退：截取第一个完整 JSON 数组
        bracket_match = re.search(r"\[[\s\S]*\]", text)
        if bracket_match:
            candidate = bracket_match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # 全部失败时记录原始内容片段便于排查
        log.error(
            f"JSON 解析失败: 内容前300字符={original[:300]!r}, "
            f"去除包裹后前200字符={text[:200]!r}"
        )
        raise ValueError(f"无法解析 LLM 返回的 JSON")

    def _analyze_dimension(
        self,
        dimension_name: str,
        papers: List[Paper],
    ) -> ComparisonDimension:
        """分析单个维度的对比"""
        from agents.prompt_templates import (
            COMPARISON_SYSTEM_PROMPT,
            COMPARISON_DIMENSION_PROMPT,
        )

        paper_contents = self._build_paper_content(papers)
        dimension_count = len(papers)
        paper_ids = [p.id for p in papers]

        prompt = COMPARISON_DIMENSION_PROMPT.format(
            dimension_count=dimension_count,
            dimension_name=dimension_name,
            paper_contents=paper_contents,
        )

        try:
            response = self._call_llm(
                prompt=prompt,
                system_prompt=COMPARISON_SYSTEM_PROMPT,
                temperature=0.3,
            )
            result = self._parse_json_response(response)

            # 容错：把 paper_values / ranking 中无法识别的 key 重映射到真实论文 id
            raw_values = result.get("paper_values", {}) or {}
            mapped_values = self._remap_paper_keys(raw_values, paper_ids)
            raw_ranking = result.get("ranking", []) or []
            mapped_ranking = self._remap_paper_keys(raw_ranking, paper_ids)

            return ComparisonDimension(
                name=result.get("dimension_name", dimension_name),
                paper_values=mapped_values,
                ranking=mapped_ranking,
                summary=result.get("summary"),
            )
        except Exception as e:
            log.error(f"维度分析失败 [{dimension_name}]: {e}")
            return ComparisonDimension(
                name=dimension_name,
                paper_values={p.id: f"分析失败: {str(e)}" for p in papers},
                ranking=[],
                summary=f"分析失败: {str(e)}",
            )

    @staticmethod
    def _remap_paper_keys(values, paper_ids: List[str]):
        """把 LLM 返回中的占位 key (paper_id_1, 1, 论文1 等) 重映射到真实 paper id。
        - values 可以是 dict 或 list
        - 已知真实 id 直接保留
        - 占位形式按位置映射：paper_id_1 -> paper_ids[0]
        """
        if isinstance(values, dict):
            out = {}
            for k, v in values.items():
                real = PaperComparisonService._resolve_key(k, paper_ids)
                if real is None:
                    # 未知 key，跳过避免污染
                    continue
                out[real] = v
            return out
        if isinstance(values, list):
            out = []
            seen = set()
            for k in values:
                real = PaperComparisonService._resolve_key(k, paper_ids)
                if real is None or real in seen:
                    continue
                seen.add(real)
                out.append(real)
            return out
        return values

    @staticmethod
    def _resolve_key(key, paper_ids: List[str]):
        """将 LLM 输出的 key 解析为真实论文 id；解析不到返回 None。"""
        if not isinstance(key, str):
            return None
        k = key.strip()
        if not k:
            return None
        # 1) 直接命中真实 id
        if k in paper_ids:
            return k
        # 2) 占位符 paper_id_1 / paper_id_2 ... (1-based)
        import re
        m = re.match(r"^paper[_]?id[_]?(\d+)$", k, re.IGNORECASE)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(paper_ids):
                return paper_ids[idx]
        # 3) "论文1" / "Paper 1"
        m = re.match(r"^(?:论文|paper)\s*(\d+)$", k, re.IGNORECASE)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(paper_ids):
                return paper_ids[idx]
        # 4) 纯数字（1-based）
        if k.isdigit():
            idx = int(k) - 1
            if 0 <= idx < len(paper_ids):
                return paper_ids[idx]
        return None

    def _generate_overview_and_recommendations(
        self,
        dimensions: List[ComparisonDimension],
        papers: List[Paper],
    ) -> tuple[str, str]:
        """生成综合概述和推荐"""
        from agents.prompt_templates import (
            COMPARISON_SYSTEM_PROMPT,
            COMPARISON_OVERVIEW_PROMPT,
        )

        dimensions_summary = []
        for dim in dimensions:
            summary_lines = [f"【{dim.name}】"]
            for pid, value in dim.paper_values.items():
                paper_title = next((p.title for p in papers if p.id == pid), pid)
                summary_lines.append(f"  {paper_title}: {value[:100]}...")
            if dim.summary:
                summary_lines.append(f"  总结: {dim.summary}")
            dimensions_summary.append("\n".join(summary_lines))

        paper_list = "\n".join([
            f"- {p.id}: {p.title or '未知标题'}"
            for p in papers
        ])

        prompt = COMPARISON_OVERVIEW_PROMPT.format(
            dimensions_summary="\n\n".join(dimensions_summary),
            paper_list=paper_list,
        )

        try:
            response = self._call_llm(
                prompt=prompt,
                system_prompt=COMPARISON_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=2000,
            )
            result = self._parse_json_response(response)
            return (
                result.get("overview", "生成失败"),
                result.get("recommendations", "生成失败"),
            )
        except Exception as e:
            log.error(f"概述生成失败: {e}")
            return (
                f"概述生成失败: {str(e)}",
                f"推荐生成失败: {str(e)}",
            )

    def execute_comparison(
        self,
        comparison_id: str,
        dimensions: Optional[List[str]] = None,
    ) -> bool:
        """
        执行论文对比分析（同步版本）

        Args:
            comparison_id: 对比会话 ID
            dimensions: 要分析的维度列表，默认为 [方法论, 性能表现, 创新点]

        Returns:
            bool: 是否成功
        """
        from agents.prompt_templates import DEFAULT_COMPARISON_DIMENSIONS

        if dimensions is None:
            dimensions = DEFAULT_COMPARISON_DIMENSIONS

        log.info(f"开始执行对比: {comparison_id}, 维度: {dimensions}")

        self.update_status(comparison_id, "RUNNING")

        try:
            comparison = self.get_comparison(comparison_id)
            if not comparison:
                raise ValueError(f"对比会话不存在: {comparison_id}")

            papers = self.get_papers_for_comparison(comparison.paper_ids)
            if len(papers) < 2:
                raise ValueError("至少需要 2 篇论文才能进行对比")

            dimension_results = []
            for dim_name in dimensions:
                log.info(f"分析维度: {dim_name}")
                dim_result = self._analyze_dimension(dim_name, papers)
                dimension_results.append(dim_result)

            overview, recommendations = self._generate_overview_and_recommendations(
                dimension_results, papers
            )

            self.save_report(
                comparison_id=comparison_id,
                overview=overview,
                recommendations=recommendations,
                dimensions=dimension_results,
            )

            log.info(f"对比完成: {comparison_id}")
            return True

        except Exception as e:
            log.error(f"对比执行失败: {comparison_id}, {e}")
            self.update_status(comparison_id, "FAILED", error=str(e))
            return False

    def execute_comparison_async(
        self,
        comparison_id: str,
        dimensions: Optional[List[str]] = None,
    ) -> None:
        """异步执行论文对比（在后台线程中运行）"""
        import threading

        def run():
            try:
                self.execute_comparison(comparison_id, dimensions)
            except Exception as e:
                log.error(f"异步对比执行异常: {comparison_id}, {e}")
                self.update_status(comparison_id, "FAILED", error=str(e))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        log.info(f"启动异步对比任务: {comparison_id}")


# Singleton instance
paper_comparison_service = PaperComparisonService()
