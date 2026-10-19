# AgenticArxiv/tools/arxiv_tool.py
import arxiv  # type: ignore
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.tool_registry import registry
from utils.file_writer import save_papers_to_file

cs_categories = {
    "*": "All Computer Science",
    "AI": "Artificial Intelligence",
    "AR": "Hardware Architecture",
    "CC": "Computational Complexity",
    "CE": "Computational Engineering, Finance, and Science",
    "CG": "Computational Geometry",
    "CL": "Computation and Language",
    "CR": "Cryptography and Security",
    "CV": "Computer Vision and Pattern Recognition",
    "CY": "Computers and Society",
    "DB": "Databases",
    "DC": "Distributed, Parallel, and Cluster Computing",
    "DL": "Digital Libraries",
    "DM": "Discrete Mathematics",
    "DS": "Data Structures and Algorithms",
    "ET": "Emerging Technologies",
    "FL": "Formal Languages and Automata Theory",
    "GL": "General Literature",
    "GR": "Graphics",
    "GT": "Computer Science and Game Theory",
    "HC": "Human-Computer Interaction",
    "IR": "Information Retrieval",
    "IT": "Information Theory",
    "LG": "Machine Learning",
    "LO": "Logic in Computer Science",
    "MA": "Multiagent Systems",
    "MM": "Multimedia",
    "MS": "Mathematical Software",
    "NA": "Numerical Analysis",
    "NE": "Neural and Evolutionary Computing",
    "NI": "Networking and Internet Architecture",
    "OH": "Other Computer Science",
    "OS": "Operating Systems",
    "PF": "Performance",
    "PL": "Programming Languages",
    "RO": "Robotics",
    "SC": "Symbolic Computation",
    "SD": "Sound",
    "SE": "Software Engineering",
    "SI": "Social and Information Networks",
    "SY": "Systems and Control",
}


def _default_output_path() -> str:
    # 项目根目录 = tools/ 的上一级
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "output", "recent_cs_papers.txt")


def _search_papers_with_dedup(
    query: str,
    max_results: int,
    exclude_ids: set,
) -> List[Dict]:
    """执行单次搜索并去重"""
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: List[Dict] = []
    for result in client.results(search):
        paper_id = result.get_short_id()

        if paper_id in exclude_ids:
            continue
        exclude_ids.add(paper_id)

        paper_info = {
            "id": paper_id,
            "title": result.title,
            "authors": [author.name for author in result.authors],
            "summary": (result.summary[:200] + "...")
            if len(result.summary) > 200
            else result.summary,
            "published": result.published.strftime("%Y-%m-%d %H:%M:%S"),
            "updated": result.updated.strftime("%Y-%m-%d %H:%M:%S")
            if result.updated
            else None,
            "pdf_url": result.pdf_url,
            "primary_category": result.primary_category,
            "categories": result.categories,
            "comment": result.comment,
            "links": [link.href for link in result.links],
        }
        papers.append(paper_info)
    return papers


def get_recently_submitted_cs_papers(
    max_results: int = 50,
    aspect: str = "*",
    days: int = 7,
    output_path: Optional[str] = None,
    save_to_file: bool = True,
    exclude_paper_ids: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    exclude_keywords: Optional[List[str]] = None,
    match_mode: str = "any",
) -> List[Dict]:
    """
    获取最近 days 天内提交的 cs.<aspect> 论文列表，支持关键词过滤
    exclude_paper_ids: 要排除的论文 ID 列表，用于避免返回已获取过的论文
    keywords: 关键词列表，满足任意一个即匹配（如 ["medical image", "segmentation"]）
    exclude_keywords: 排除关键词列表，包含任意一个即排除
    """
    now_utc = datetime.now(timezone.utc)
    end_date = now_utc.strftime("%Y%m%d")

    exclude_ids: set = set(exclude_paper_ids or [])
    kw_list = keywords or []
    papers: List[Dict] = []
    seen_ids: set = set()

    def _run_query(query: str, limit: int) -> List[Dict]:
        """执行单次查询，返回去重后的论文"""
        result = []
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=limit,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        for r in client.results(search):
            pid = r.get_short_id()
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            if pid in exclude_ids:
                continue
            info = {
                "id": pid,
                "title": r.title,
                "authors": [a.name for a in r.authors],
                "summary": r.summary[:200] + "..." if len(r.summary) > 200 else r.summary,
                "published": r.published.strftime("%Y-%m-%d %H:%M:%S"),
                "updated": r.updated.strftime("%Y-%m-%d %H:%M:%S") if r.updated else None,
                "pdf_url": r.pdf_url,
                "primary_category": r.primary_category,
                "categories": r.categories,
                "comment": r.comment,
                "links": [link.href for link in r.links],
            }
            result.append(info)
        return result

    def _score_paper(paper: Dict) -> tuple:
        """关键词相关性评分：标题命中 > 摘要命中，匹配越多越好"""
        title = paper.get("title", "").lower()
        abstract = paper.get("summary", "").lower()
        title_score = 0
        abstract_score = 0
        for kw in kw_list:
            k = kw.lower()
            if k in title:
                title_score += 10
            if k in abstract:
                abstract_score += 1
        return (title_score + abstract_score, title_score)

    for attempt in range(3):
        if attempt == 0:
            start_date = (now_utc - timedelta(days=days)).strftime("%Y%m%d")
        elif attempt == 1:
            start_date = (now_utc - timedelta(days=days * 2)).strftime("%Y%m%d")
        else:
            start_date = (now_utc - timedelta(days=days * 4)).strftime("%Y%m%d")

        date_range = f"submittedDate:[{start_date} TO {end_date}]"

        # 多轮查询策略：标题精确匹配 → 摘要匹配 → 扩大类别
        search_strategies = []

        if kw_list and str(match_mode).lower() == "all":
            # 全部关键词都要命中（标题或摘要各出现一次即可）
            groups = [f'(ti:"{kw}" OR abs:"{kw}")' for kw in kw_list]
            all_query = " AND ".join(groups)
            search_strategies.append(
                (f"{all_query} AND {date_range}", max_results)
            )
            search_strategies.append(
                (
                    f"{all_query} AND (cat:cs.CV OR cat:cs.LG OR cat:cs.AI) "
                    f"AND {date_range}",
                    max_results * 2,
                )
            )
        elif kw_list:
            # 策略1：标题中含关键词（最相关）
            title_parts = [f'ti:"{kw}"' for kw in kw_list]
            title_query = " OR ".join(title_parts)
            search_strategies.append(
                (f"({title_query}) AND {date_range}", max_results)
            )
            # 策略2：标题+摘要中含关键词
            abs_parts = [f'abs:"{kw}"' for kw in kw_list]
            abs_query = " OR ".join(abs_parts)
            search_strategies.append(
                (f"({title_query} OR {abs_query}) AND {date_range}", max_results * 2)
            )
            # 策略3：扩大类别到 AI/LG/CV
            search_strategies.append(
                (f"({title_query} OR {abs_query}) AND (cat:cs.CV OR cat:cs.LG OR cat:cs.AI) AND {date_range}", max_results * 2)
            )
        else:
            # 无关键词时按类别搜索
            if aspect == "*":
                search_strategies.append((date_range, max_results))
            else:
                search_strategies.append((f"cat:cs.{aspect} AND {date_range}", max_results))

        all_new: List[Dict] = []
        for query_str, limit in search_strategies:
            if aspect != "*" and "cat:cs." not in query_str:
                query_str = f"cat:cs.{aspect} AND {query_str}"
            new = _run_query(query_str, limit)
            all_new.extend(new)
            if len(all_new) >= max_results * 3:
                break

        papers.extend(all_new)

        if len(papers) >= max_results:
            break

    # 关键词 NOT 过滤
    if exclude_keywords:
        for ekw in exclude_keywords:
            papers = [p for p in papers if ekw.lower() not in p.get("title", "").lower()]

    # 按关键词相关性重排序
    if kw_list:
        papers.sort(key=_score_paper, reverse=True)

    papers = papers[:max_results]

    # 按 primary_category 排序（目标类别优先）
    if aspect != "*":
        target_cat = f"cs.{aspect}"
        papers.sort(key=lambda p: 0 if p.get("primary_category") == target_cat else 1)

    if save_to_file:
        path = output_path or _default_output_path()
        save_papers_to_file(papers, path)

    return papers


ARXIV_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "max_results": {
            "type": "integer",
            "description": "最大返回结果数",
            "minimum": 1,
            "maximum": 100,
            "default": 50,
        },
        "aspect": {
            "type": "string",
            "description": "计算机科学子领域代码",
            "enum": list(cs_categories.keys()),
            "default": "*",
        },
        "days": {
            "type": "integer",
            "description": "查询最近多少天的论文",
            "minimum": 1,
            "maximum": 30,
            "default": 7,
        },
        "output_path": {
            "type": "string",
            "description": "可选：保存到指定文件路径；不传则用项目 output/recent_cs_papers.txt",
        },
        "save_to_file": {
            "type": "boolean",
            "description": "是否将论文列表写入文件",
            "default": True,
        },
        "exclude_paper_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选：要排除的论文 ID 列表，用于避免返回已获取过的重复论文",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选：关键词列表，论文标题或摘要包含任一关键词即匹配（如 [\"medical image\", \"segmentation\"]）",
        },
        "exclude_keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选：排除关键词列表，包含任一关键词的论文将被排除",
        },
        "match_mode": {
            "type": "string",
            "enum": ["any", "all"],
            "default": "any",
            "description": (
                "关键词匹配模式：any=任一关键词命中（默认，召回高），"
                "all=所有关键词都要命中（精确，适合同一主题的多个限定词）"
            ),
        },
    },
    "required": [],
}

registry.register_tool(
    name="get_recently_submitted_cs_papers",
    description="获取最近提交的计算机科学领域论文列表，支持按子领域筛选",
    parameter_schema=ARXIV_TOOL_SCHEMA,
    func=get_recently_submitted_cs_papers,
)


if __name__ == "__main__":
    ASPECT = "CL"
    papers = get_recently_submitted_cs_papers(max_results=20, aspect=ASPECT)
    print(f"获取到 {len(papers)} 篇论文")
