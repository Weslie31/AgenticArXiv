# AgenticArxiv/tools/openalex_tool.py
"""
OpenAlex 论文搜索引擎

API 文档: https://api.openalex.org
数据覆盖: arXiv、PubMed、CrossRef、IEEE、Springer 等所有主要学术来源
特点:
  - 全学科覆盖（不只是 CS）
  - 支持 DOI / ORCID / institution 等多维度过滤
  - 全文 PDF 链接（best_oa_location / best_location）
  - 免费，无需 API Key（建议加 User-Agent 头并加入 polite pool）
"""
from __future__ import annotations

import sys
import os
import json
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.tool_registry import registry
from utils.file_writer import save_papers_to_file
from utils.logger import log
from config import settings

# OpenAlex API 配置
OPENALEX_BASE_URL = "https://api.openalex.org"
OPENALEX_HEADERS = {
    "User-Agent": "AgenticArxiv/1.0 (mailto:your@email.com; https://github.com/yourname/agenticarxiv)",  # 必加，OpenAlex 要求
    "Accept": "application/json",
}
REQUEST_DELAY = 0.1  # 两次请求间至少间隔 100ms，遵守 polite pool 限制


# ============ OpenAlex 字段映射 ============

def _extract_authors(authorships) -> List[str]:
    """从 OpenAlex authorships 结构提取作者名列表"""
    if not isinstance(authorships, (list, tuple)):
        return []
    return [
        au.get("author", {}).get("display_name", "Unknown")
        for au in authorships
        if isinstance(au, dict) and au.get("author")
    ]


def _extract_pdf_url(work: Dict) -> Optional[str]:
    """提取 PDF 链接：优先 OA 全文 > best_location > 无"""
    # 优先 open access 全文
    best_oa = work.get("best_oa_location")
    if best_oa and best_oa.get("pdf_url"):
        return best_oa["pdf_url"]

    # 其次 best location 中的 pdf
    best_loc = work.get("best_location")
    if best_loc and best_loc.get("pdf_url"):
        return best_loc["pdf_url"]

    # 最后 primary location
    primary = work.get("primary_location")
    if primary and primary.get("pdf_url"):
        return primary["pdf_url"]

    return None


def _extract_link(work: Dict) -> str:
    """提取论文主页链接"""
    if work.get("doi"):
        return work["doi"]
    if work.get("id"):
        return work["id"]
    return ""


def _extract_concepts(work: Dict) -> List[str]:
    """提取主题分类标签（OpenAlex 用 topics 而非 concepts）"""
    topics = work.get("topics", [])
    if not isinstance(topics, (list, tuple)):
        return []
    return [
        c.get("display_name", "")
        for c in topics
        if isinstance(c, dict) and c.get("display_name")
    ]


def _inverted_index_to_text(index: Dict) -> str:
    """
    OpenAlex 的 abstract_inverted_index 是倒排索引格式:
      {"word": [position1, position2], "word2": [position3]}
    每个词对应一个位置列表（不是嵌套列表）。还原为原始顺序的文本。
    """
    if not index or not isinstance(index, dict):
        return ""
    # 将每个词和它的所有位置收集为 (位置, 词) 元组列表
    tokens = []
    for word, positions in index.items():
        if not isinstance(positions, (list, tuple)):
            continue
        for pos in positions:
            if isinstance(pos, int):
                tokens.append((pos, word))
    # 按原始位置排序后拼接
    tokens.sort(key=lambda x: x[0])
    return " ".join(word for _, word in tokens)


def _work_to_paper(work: Dict) -> Dict:
    """将 OpenAlex work 对象转换为统一的论文字典格式"""
    # 摘要处理：可能是纯文本字符串，也可能是倒排索引
    raw_abstract = work.get("abstract_inverted_index")
    if isinstance(raw_abstract, dict):
        summary = _inverted_index_to_text(raw_abstract)
        if len(summary) > 300:
            summary = summary[:300] + "..."
    elif isinstance(raw_abstract, str):
        summary = raw_abstract[:300] + "..." if len(raw_abstract) > 300 else raw_abstract
    else:
        summary = ""

    return {
        "id": work.get("doi", work.get("id", "")),
        "openalex_id": work.get("id", "").replace("https://openalex.org/", ""),
        "title": work.get("display_name", work.get("title", "")),
        "authors": _extract_authors(work.get("authorships", [])),
        "summary": summary,
        "published": work.get("publication_date", ""),
        "published_date": work.get("publication_date", ""),
        "year": work.get("publication_year"),
        "pdf_url": _extract_pdf_url(work),
        "link": _extract_link(work),
        "doi": work.get("doi"),
        "source": work.get("primary_location", {}).get("source", {}).get("display_name", ""),
        "primary_category": work.get("primary_location", {}).get("source", {}).get("display_name", ""),
        "categories": _extract_concepts(work),
        "cited_by_count": work.get("cited_by_count", 0),
        "is_open_access": work.get("open_access", {}).get("is_oa", False),
        "type": work.get("type"),
        "keywords": _extract_concepts(work),
    }


# ============ 核心搜索函数 ============

def search_openalex_papers(
    query: str,
    max_results: int = 50,
    domains: Optional[List[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    source_types: Optional[List[str]] = None,
    is_oa_only: bool = False,
    exclude_paper_ids: Optional[List[str]] = None,
    exclude_keywords: Optional[List[str]] = None,
    sort_by: str = "relevance",
    output_path: Optional[str] = None,
    save_to_file: bool = True,
) -> List[Dict]:
    """
    通过 OpenAlex 搜索学术论文，支持全学科、多维度过滤。

    参数:
        query:              搜索关键词（支持 AND/OR/not 布尔语法）
        max_results:        最大返回数量，默认 50（OpenAlex 单次最多 200）
        domains:            学科领域过滤，如 ["computer science", "artificial intelligence"]
        year_from:          最早发表年份
        year_to:            最晚发表年份
        source_types:       文献类型过滤，如 ["journal-article", "conference", "preprint"]
        is_oa_only:         是否只返回开放获取论文
        exclude_paper_ids: 要排除的论文 ID 列表（DOI 或 OpenAlex ID）
        exclude_keywords:   排除关键词列表（匹配标题则排除）
        sort_by:            relevance（默认，按相关度，同分新论文在前）| date（按发表时间倒序）
        output_path:        保存路径，不传则用默认
        save_to_file:       是否保存到文件，默认 True
    """
    if not query or not query.strip():
        return []

    exclude_ids: set = set(exclude_paper_ids or [])
    ekw_list = [kw.lower().strip() for kw in (exclude_keywords or [])]

    all_papers: List[Dict] = []
    seen_ids: set = set()

    # OpenAlex filter 字符串构建
    filters: List[str] = []

    # 注意：OpenAlex works 端点不支持 domains / host_venue 等过滤字段
    # 学科约束完全通过关键词 + source_types 实现，不加强制 domain filter
    # （强行加 domains filter 会触发 HTTP 400 导致整次搜索失败）

    # 年份过滤：OpenAlex 字段是 publication_year，用 P2021-P2026 范围格式
    if year_from and year_to:
        filters.append(f"publication_year:{year_from}-{year_to}")
    elif year_from:
        filters.append(f"publication_year:{year_from}-")

    if source_types:
        filters.append(f"type:{','.join(source_types)}")

    if is_oa_only:
        filters.append("is_oa:true")
    filter_str = ",".join(filters)

    # 分页获取（OpenAlex 单次最多 200 条）
    per_page = min(max_results, 200)
    total_fetched = 0

    page = 1
    while total_fetched < max_results:
        if str(sort_by).lower() in ("date", "time", "year", "newest"):
            sort_expr = "publication_date:desc,cited_by_count:desc"
        else:
            sort_expr = "relevance_score:desc,publication_date:desc,cited_by_count:desc"

        params = {
            "search": query.strip(),
            "per-page": per_page,
            "page": page,
            # 优先按发表日期倒序（新论文在前），然后被引次数，避免综述论文霸榜。
            # 同时给定 relevance_score:desc，OpenAlex 会基于查询相关性做轻量排序
            "sort": sort_expr,
            "select": (
                "id,doi,display_name,abstract_inverted_index,"
                "publication_date,publication_year,authorships,"
                "best_oa_location,primary_location,"
                "open_access,type,cited_by_count,topics,relevance_score"
            ),
        }
        if filter_str:
            params["filter"] = filter_str

        try:
            resp = requests.get(
                f"{OPENALEX_BASE_URL}/works",
                params=params,
                headers=OPENALEX_HEADERS,
                timeout=20,
            )
            time.sleep(REQUEST_DELAY)  # polite pool 限速

            if resp.status_code == 404:
                log.warning(f"[openalex] 404 查询失败: {query}")
                break
            if resp.status_code == 429:
                log.warning("[openalex] 触发限流，等待 5s...")
                time.sleep(5)
                continue
            if resp.status_code != 200:
                log.error(f"[openalex] 请求失败 HTTP {resp.status_code}: {resp.text[:200]}")
                break

            data = resp.json()
            results: List[Dict] = data.get("results", [])
            if not results:
                break

            for work in results:
                paper_id = work.get("doi") or work.get("id", "")

                # 全局去重
                if paper_id in seen_ids:
                    continue
                seen_ids.add(paper_id)

                # 指定排除
                if paper_id and paper_id in exclude_ids:
                    continue
                if paper_id.replace("https://openalex.org/", "") in exclude_ids:
                    continue

                try:
                    paper = _work_to_paper(work)
                except Exception as e:
                    log.warning(f"[openalex] _work_to_paper 异常（跳过）: {e}")
                    continue

                # 排除关键词过滤
                title_lower = paper.get("title", "").lower()
                if ekw_list and any(ekw in title_lower for ekw in ekw_list):
                    continue

                all_papers.append(paper)
                total_fetched += 1

                if total_fetched >= max_results:
                    break

            # 检查是否还有下一页
            meta = data.get("meta", {})
            next_page = meta.get("next_cursor")
            if not next_page or len(results) < per_page:
                break

            page += 1

        except requests.exceptions.Timeout:
            log.warning("[openalex] 请求超时，重试中...")
            time.sleep(2)
            continue
        except Exception as e:
            log.error(f"[openalex] 异常: {e}")
            break

    if save_to_file:
        path = output_path or _default_output_path()
        try:
            save_papers_to_file(all_papers, path)
            log.info(f"[openalex] 搜索 '{query}' 返回 {len(all_papers)} 篇，已保存到 {path}")
        except (TypeError, ValueError) as e:
            log.warning(f"[openalex] 保存文件失败（跳过）: {e}")

    return all_papers


def _default_output_path() -> str:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "output", "openalex_papers.json")


def _resolve_domain(domain: str) -> Optional[str]:
    """
    将人类可读的学科名解析为 OpenAlex domain id
    常见 domain id:
      12  - Computer and Information Science
      4   - Artificial Intelligence
      11  - Computer Vision
      5   - Computational Linguistics
      13  - Human-Computer Interaction
    """
    domain_map: Dict[str, str] = {
        # CS / AI
        "computer science": "12",
        "cs": "12",
        "ai": "4",
        "artificial intelligence": "4",
        "machine learning": "4",
        "deep learning": "4",
        "computer vision": "11",
        "cv": "11",
        "natural language processing": "5",
        "nlp": "5",
        "computational linguistics": "5",
        "human-computer interaction": "13",
        "hci": "13",
        "robotics": "12",
        "software engineering": "12",
        "data mining": "12",
        "information retrieval": "12",
        "multimedia": "12",
        # 医学 / 生物 / 工程
        "medicine": "12",  # OpenAlex domain 体系下医学归属 cs 大类
        "medical": "12",
        "biology": "3",     # 3 = Biological Sciences
        "biological": "3",
        "biomedical": "3",
        "bioengineering": "3",
        "biochemistry": "3",
        "genomics": "3",
        "engineering": "12",
        "mechanical engineering": "12",
        "biochemistry": "3",
        # 神经科学
        "neuroscience": "4",
        "neurology": "12",
    }
    return domain_map.get(domain.lower().strip())


# ============ 按 DOI 精确查找 ============

def get_paper_by_doi(doi: str) -> Optional[Dict]:
    """
    通过 DOI 精确获取单篇论文信息
    DOI 示例: "10.48550/arXiv.2301.00001" 或 "10.1145/3442188.3445922"
    """
    if not doi:
        return None
    # DOI 本身即是 OpenAlex ID 格式
    try:
        resp = requests.get(
            f"{OPENALEX_BASE_URL}/works/https://doi.org/{doi.strip()}",
            headers=OPENALEX_HEADERS,
            timeout=15,
        )
        time.sleep(REQUEST_DELAY)
        if resp.status_code == 200:
            return _work_to_paper(resp.json())
        return None
    except Exception as e:
        log.error(f"[openalex] get_paper_by_doi 失败: {e}")
        return None


# ============ 按作者搜索 ============

def search_by_author(author_name: str, max_results: int = 50) -> List[Dict]:
    """
    通过作者姓名搜索其论文
    """
    try:
        # 先找作者 ID
        author_resp = requests.get(
            f"{OPENALEX_BASE_URL}/authors",
            params={"search": author_name, "per-page": 1},
            headers=OPENALEX_HEADERS,
            timeout=15,
        )
        time.sleep(REQUEST_DELAY)
        if author_resp.status_code != 200:
            return []
        authors = author_resp.json().get("results", [])
        if not authors:
            return []
        author_id = authors[0]["id"]
        author_id_short = author_id.replace("https://openalex.org/", "")

        # 再查该作者的论文
        works_resp = requests.get(
            f"{OPENALEX_BASE_URL}/works",
            params={
                "filter": f"author.id:{author_id_short}",
                "per-page": max_results,
                "sort": "publication_date:desc",
                "select": (
                    "id,doi,title,display_name,abstract_inverted_index,"
                    "publication_date,publication_year,authorships,"
                    "best_oa_location,open_access,type,cited_by_count,topics"
                ),
            },
            headers=OPENALEX_HEADERS,
            timeout=15,
        )
        time.sleep(REQUEST_DELAY)
        if works_resp.status_code != 200:
            return []
        results = works_resp.json().get("results", [])
        return [_work_to_paper(w) for w in results]
    except Exception as e:
        log.error(f"[openalex] search_by_author 失败: {e}")
        return []


# ============ 自然语言查询 → OpenAlex 参数 ============

# ---- 规则化中文关键词词典（不依赖 LLM） ----
_METHOD_TERMS = [
    # 神经网络 / AI  -- 英文
    "neural network", "neural networks", "deep learning", "cnn",
    "convolutional neural network", "rnn", "recurrent neural network",
    "lstm", "gru", "transformer", "attention mechanism",
    "encoder-decoder", "resnet", "u-net", "unet",
    "gan", "generative adversarial", "diffusion model",
    "gnn", "graph neural network", "vision transformer", "vit",
    "reinforcement learning", "supervised learning", "self-supervised",
    "transfer learning", "foundation model", "large language model", "llm",
    # 建模
    "modeling", "modelling", "simulation", "reconstruction", "generation",
    "prediction", "estimation", "representation learning",
]

# 中文方法别名 → 英文搜索词（供规则解析用）
_METHOD_CN_ALIASES = {
    "神经网络": ["neural network", "deep learning"],
    "深度学习": ["deep learning", "neural network"],
    "卷积神经网络": ["cnn", "convolutional neural network"],
    "卷积": ["cnn", "convolutional neural network"],
    "循环神经网络": ["rnn", "recurrent neural network"],
    "循环网络": ["rnn", "recurrent neural network"],
    "长短期记忆": ["lstm"],
    "LSTM": ["lstm"],
    "GRU": ["gru"],
    "Transformer": ["transformer"],
    "注意力机制": ["attention mechanism", "attention"],
    "注意力": ["attention mechanism", "attention"],
    "残差网络": ["resnet"],
    "ResNet": ["resnet"],
    "U-Net": ["u-net", "unet"],
    "GAN": ["gan", "generative adversarial"],
    "生成对抗网络": ["gan", "generative adversarial"],
    "扩散模型": ["diffusion model", "denoising diffusion"],
    "Diffusion": ["diffusion model"],
    "图神经网络": ["gnn", "graph neural network"],
    "GNN": ["gnn", "graph neural network"],
    "强化学习": ["reinforcement learning"],
    "强化学习": ["reinforcement learning"],
    "RL": ["reinforcement learning"],
    "监督学习": ["supervised learning"],
    "无监督学习": ["unsupervised learning"],
    "自监督": ["self-supervised"],
    "迁移学习": ["transfer learning"],
    "对比学习": ["contrastive learning"],
    "知识蒸馏": ["knowledge distillation"],
    "基础模型": ["foundation model"],
    "大语言模型": ["large language model", "llm"],
    "LLM": ["large language model", "llm"],
    "GPT": ["gpt", "large language model"],
    "CLIP": ["clip"],
    "图像分割": ["segmentation", "image segmentation"],
    "目标检测": ["object detection", "detection"],
    "图像生成": ["image generation", "generative model"],
    "超分辨率": ["super-resolution", "sr"],
    "去噪": ["denoising", "denoise"],
    "重建": ["reconstruction", "modeling"],
    "三维重建": ["3d reconstruction", "novel view synthesis"],
    "点云": ["point cloud", "pointcloud"],
    "NeRF": ["nerf", "neural radiance field"],
    "渲染": ["rendering", "neural rendering"],
}

_APP_TERMS = {
    "软组织": ["soft tissue", "soft-organ", "biomechanics", "biomechanical",
               "organ simulation", "muscle", "skin", "tumor", "lesion"],
    "医学": ["medical", "healthcare", "clinical", "diagnosis", "radiology"],
    "医疗": ["medical", "healthcare", "clinical"],
    "医学影像": ["medical imaging", "medical image", "radiology"],
    "影像": ["imaging", "image"],
    "生物": ["biology", "biological", "biomedical", "cellular", "protein"],
    "物理": ["physics", "mechanics", "dynamics", "simulation", "materials"],
    "工程": ["engineering", "structural", "aerodynamics", "finite element"],
    "心脏": ["cardiac", "heart", "cardiovascular", "electrocardiogram"],
    "脑": ["brain", "cerebral", "neuronal", "neuroimaging", "fmri"],
    "肿瘤": ["tumor", "tumour", "cancer", "neoplasm"],
    "机器人": ["robotics", "robot control", "manipulation"],
    "自动驾驶": ["autonomous driving", "self-driving", "autonomous vehicle"],
    "NLP": ["nlp", "natural language processing"],
    "自然语言": ["nlp", "natural language processing", "language model"],
    "语音": ["speech", "voice", "audio"],
    "推荐系统": ["recommender system", "recommendation"],
    "药物发现": ["drug discovery", "drug design", "pharmaceutical"],
}

_SOURCE_TYPE_TERMS = {
    "期刊": ["journal-article"],
    "会议": ["conference", "proceedings"],
    "预印本": ["preprint"],
    "综述": ["review"],
}


def _rule_based_parse(nl_query: str) -> Dict:
    """
    纯规则解析中文查询，不依赖任何外部服务。
    通过词典匹配 + 正则规则，将中文研究需求转换为英文关键词。
    """
    import re
    q = nl_query.lower().strip()

    # 提取年份约束
    year_from, year_to = None, None
    current_year = datetime.now().year
    m = re.search(r"近(\d+)年", q)
    if m:
        year_from = current_year - int(m.group(1))
    m = re.search(r"(\d{4})\s*年?\s*(?:以来|之后|至今)", q)
    if m:
        year_from = int(m.group(1))
    m = re.search(r"(\d{4})-(\d{4})", q)
    if m:
        year_from, year_to = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{4})\s*年", q)
    if m:
        year_from = int(m.group(1))
    if not year_from:
        year_from = current_year - 5
    if not year_to:
        year_to = current_year

    # 提取应用领域关键词（英文词典匹配 + 中文别名）
    app_keywords = []
    seen_en = set()
    for domain_cn, en_terms in _APP_TERMS.items():
        if domain_cn.lower() in q:
            for en in en_terms:
                if en.lower() not in seen_en:
                    app_keywords.append(en)
                    seen_en.add(en.lower())

    # 提取方法关键词：英文词典 + 中文别名词典（大小写不敏感）
    method_keywords = []
    for term in _METHOD_TERMS:
        if term.lower() in q:
            if term.lower() not in seen_en:
                method_keywords.append(term)
                seen_en.add(term.lower())

    for cn_term, en_terms in _METHOD_CN_ALIASES.items():
        if cn_term.lower() in q:
            for en in en_terms:
                if en.lower() not in seen_en:
                    method_keywords.append(en)
                    seen_en.add(en.lower())

    # 提取文献类型
    source_types = []
    for type_cn, en_terms in _SOURCE_TYPE_TERMS.items():
        if type_cn in q:
            source_types.extend(en_terms)

    # 排除关键词：默认不排除（让 LLM 打分决定）
    exclude_kw: List[str] = []
    if "排除综述" in q or "不要综述" in q or "非综述" in q:
        exclude_kw = ["survey", "review", "tutorial", "overview"]

    # OA 判断
    is_oa = "开放获取" in q or " oa " in q or "开源" in q

    # 提取数量约束：支持 "5篇" / "5 个" / "5 篇文章" / "5 篇论文" / "找 5 篇"
    # 注意：年份正则 (YYYY) 已经吃掉 "2020篇" 这种边界，因此这里只匹配明显带量词的
    # 量词优先级（先长后短）："篇文章" > "篇论文" > "篇" > "个" > "条"
    user_max_results: Optional[int] = None
    m = re.search(r"(\d+)\s*(?:篇文章|篇论文|篇|个|条|份|项)", q)
    if m:
        n = int(m.group(1))
        # 防御性：上限 50（与 schema 一致）
        user_max_results = max(1, min(n, 50))

    # 组装英文查询词（全局去重 + 过滤残留中文）
    all_parts = method_keywords + app_keywords
    seen_q = set()
    clean_parts = []
    for part in all_parts:
        p = part.strip().lower()
        # 过滤残留中文和已重复
        if p and p not in seen_q and not any("\u4e00" <= c <= "\u9fff" for c in p):
            clean_parts.append(part)
            seen_q.add(p)
    query = " ".join(clean_parts)

    # 若关键词全为空，兜底提取非停用词
    if not query.strip():
        stopwords = {"的", "在", "和", "与", "或", "用于", "基于", "研究", "论文",
                     "文章", "搜索", "查找", "请", "帮我", "一下", "帮我搜索"}
        terms = [t.strip() for t in re.split(r"[\s,，、]+", q)
                 if t.strip() and t.strip() not in stopwords
                 and not any("\u4e00" <= c <= "\u9fff" for c in t)]
        query = " ".join(terms)

    # 学科判断
    domains = []
    if any(w in q for w in ["医学", "医疗", "临床", "诊断", "影像", "ct", "mri"]):
        domains.append("medicine")
    if any(w in q for w in ["生物", "细胞", "蛋白", "基因", "dna"]):
        domains.append("biology")
    if any(w in q for w in ["神经", "脑", "认知"]):
        domains.append("artificial intelligence")
    if not domains:
        domains.append("computer science")

    reasoning = (
        f"规则解析: 方法={method_keywords or '无'}, "
        f"应用={app_keywords or '通用'}, 年={year_from}-{year_to}, "
        f"数量={user_max_results or '默认'}"
    )

    return {
        "query": query,
        "year_from": year_from,
        "year_to": year_to,
        "domains": domains,
        "source_types": source_types,
        "is_oa_only": is_oa,
        "exclude_keywords": exclude_kw,
        "user_max_results": user_max_results,
        "reasoning": reasoning,
    }


_BOOL_TOKEN_RE = re.compile(r"\b(?:AND|OR|NOT)\b", re.IGNORECASE)


def _sanitize_query(query: str) -> str:
    """把 LLM 生成的引号/布尔查询压成纯关键词串。

    实测 OpenAlex 的 search 对带引号的短语和嵌套布尔分组排序很差，例如
    '"soft tissue" AND ("neural network" OR ...)' 的前几条是土壤结构、宫颈癌分割，
    而 'soft tissue deformation neural network' 能直接命中目标论文。
    """
    if not query:
        return ""
    t = query
    for ch in ('"', "'", "(", ")", "[", "]"):
        t = t.replace(ch, " ")
    t = _BOOL_TOKEN_RE.sub(" ", t)
    t = re.sub(r"\b(?:ti|abs|title|abstract)\s*:\s*", " ", t, flags=re.IGNORECASE)

    words: List[str] = []
    seen = set()
    for raw in t.split():
        w = raw.strip(" ,;:|")
        if len(w) < 2:
            continue
        lw = w.lower()
        if lw in seen:
            continue
        seen.add(lw)
        words.append(w)
    return " ".join(words)


def analyze_nl_query(nl_query: str) -> Dict:
    """
    将自然语言研究需求解析为 OpenAlex 搜索参数。

    策略：优先规则解析（完全不依赖网络），LLM 仅在规则解析结果
    质量不足时作为增强。保证在任何网络环境下都能工作。
    """
    # Step 1: 规则解析（始终执行，本地运行）
    parsed = _rule_based_parse(nl_query)
    parsed["query"] = _sanitize_query(parsed.get("query", ""))
    log.info(f"[openalex] NL 规则解析: {parsed.get('reasoning')}")

    # Step 2: 尝试 LLM 增强（可选，仅当网络可用时）
    try:
        from utils.llm_client import get_env_llm_client

        prompt = f"""你是一个学术论文搜索引擎的参数生成器。

用户输入的自然语言查询：
"{nl_query}"

请分析并生成以下 JSON（无任何其他文字）：
{{
  "query": "OpenAlex 搜索关键词：只写 3-6 个英文核心术语，用空格分隔。不要引号、括号、AND/OR/NOT，不要写年份和数量。示例：soft tissue deformation neural network deep learning",
  "year_from": 最早发表年份（整数，如 2020，无则 null）,
  "year_to": 最新发表年份（整数，如 2026，无则 null）,
  "domains": ["相关学科领域，如 computer science / medicine / biology 等，留空表示不限"],
  "source_types": ["文献类型，如 conference / journal-article / preprint 等，留空表示不限"],
  "is_oa_only": 是否只搜开放获取论文（true/false）,
  "max_results": 用户想要的数量（整数，如 5、10、20；用户没明确说则 null，函数会取默认 20；上限 50）,
  "reasoning": "一句简短说明：解析出了哪些关键信息"
}}
"""
        from utils.llm_client import get_app_llm_client
        from services.app_settings import get_llm_config

        client = get_app_llm_client()
        user_cfg = get_llm_config()
        default_model = get_llm_config().model or settings.models.agent_model
        messages = [
            {
                "role": "system",
                "content": "你是一个严谨的学术助手。请严格按照 JSON 格式返回分析结果，"
                           "不要输出任何 JSON 以外的内容。字段 reasoning 需用中文。",
            },
            {"role": "user", "content": prompt},
        ]
        resp = client.chat_completions(
            model=os.getenv("LLM_MODEL") or default_model,
            messages=messages,
            temperature=0.1,
            max_tokens=500,
        )
        content = resp["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(
                lines[1:] if "json" in lines[0].lower() else lines
            )
            content = content.strip("```").strip()

        import json
        llm_parsed = json.loads(content)
        if llm_parsed.get("query"):
            # 保留原始写法便于排查；实际检索统一用清洗后的关键词串
            llm_parsed["query_raw"] = llm_parsed["query"]
            llm_parsed["query"] = _sanitize_query(llm_parsed["query"])
            log.info(f"[openalex] LLM query: raw={llm_parsed['query_raw']!r} -> "
                     f"clean={llm_parsed['query']!r}")
        if llm_parsed.get("query") and len(llm_parsed["query"]) > 5:
            # LLM 成功时融合：保留规则解析的默认值兜底（setdefault 对 None 值无效）
            if llm_parsed.get("year_from") is None:
                llm_parsed["year_from"] = parsed.get("year_from")
            if llm_parsed.get("year_to") is None:
                llm_parsed["year_to"] = parsed.get("year_to")
            if not llm_parsed.get("exclude_keywords"):
                llm_parsed["exclude_keywords"] = parsed.get("exclude_keywords")
            # max_results 兜底：LLM 没识别到数量时，回退到规则解析识别的数量
            # 规则解析的优先级（用户文本里明确写了"X 篇"）通常比 LLM 推断更准
            if llm_parsed.get("max_results") is None and parsed.get("user_max_results"):
                llm_parsed["max_results"] = parsed["user_max_results"]
            llm_parsed["_llm_enhanced"] = True
            log.info(f"[openalex] LLM 增强: {llm_parsed.get('reasoning', '')}")
            return llm_parsed
    except Exception as e:
        log.warning(f"[openalex] LLM 增强不可用（{e}），使用规则解析")

    return parsed


# ============ LLM 相关性重排序 ============

def _extract_json_array(text: str) -> Optional[List[Dict]]:
    """从 LLM 输出中提取 JSON 数组。

    兼容 ```json 代码块、前后夹杂说明文字的情况，避免一次格式偏差就让整批降级。
    """
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    start = t.find("[")
    end = t.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def rerank_by_relevance(
    papers: List[Dict],
    nl_query: str,
    min_score: float = 3.0,
    sort_by: str = "relevance",
) -> List[Dict]:
    """
    用 LLM 对论文列表进行相关性评分和排序。

    策略：
      1. 将论文分批（每批 5 篇），每篇附带标题+摘要+用户查询发给 LLM
      2. LLM 打 1-5 分（1=完全不相关，5=高度相关）
      3. 过滤掉 < min_score 的论文
      4. 按分数降序排列

    对于"神经网络软组织建模"这类专业查询，能有效排除：
      - 标题碰巧含"神经网络"但实际不相关的
      - 医学影像领域但非软组织的
      - 综述/教程类（方法未用在目标领域）
    """
    if not papers:
        return []

    try:
        from utils.llm_client import get_app_llm_client
        from services.app_settings import get_llm_config

        client = get_app_llm_client()
        user_cfg = get_llm_config()
        default_model = get_llm_config().model or settings.models.agent_model
        scored: List[Dict] = []

        # 分批处理，每批 5 篇
        batch_size = 5
        for i in range(0, len(papers), batch_size):
            batch = papers[i : i + batch_size]

            # 构建每批的评分 prompt
            paper_lines = []
            for j, p in enumerate(batch):
                title = p.get("title", "") or ""
                summary = p.get("summary", "") or ""
                authors = ", ".join((p.get("authors") or [])[:3])
                year = p.get("year", "")
                source = p.get("source", "")
                paper_lines.append(
                    f"[{j+1}] 标题: {title}\n    作者: {authors} | {year} | {source}\n"
                    f"    摘要: {summary[:200]}"
                )

            score_prompt = f"""用户研究需求："{nl_query}"

以下是待评分的论文：

{chr(10).join(paper_lines)}

请对每篇论文的相关性打分（1-5分），1=完全不相关，5=高度相关。
只返回 JSON 数组，无其他文字：
[{{"index": 1, "score": 分数, "reason": "一句简短理由"}}]

要求：
- 如果论文标题和摘要都围绕用户需求中的核心主题，给 4-5 分
- 如果论文涉及部分关键词但核心不匹配，给 2-3 分
- 如果论文完全不相关（如领域完全不同或只是综述但没有具体应用），给 1 分
"""

            messages = [
                {
                    "role": "system",
                    "content": "你是一个严谨的学术论文评审专家，评分公正客观。",
                },
                {"role": "user", "content": score_prompt},
            ]

            # 打分：失败重试一次；仍失败则标记为「未评分」，不要伪造 3.0
            scores = None
            last_err: Optional[Exception] = None
            # 注意：deepseek-v4-flash 这类模型会先输出 reasoning_content，
            # 思考 token 同样计入 max_tokens。实测 900 预算里 882 用于思考，
            # 正文只剩 41 字符就被 length 截断，所以这里要给足预算。
            budgets = (2500, 4000)
            for attempt, budget in enumerate(budgets, start=1):
                try:
                    resp = client.chat_completions(
                        model=os.getenv("LLM_MODEL") or default_model,
                        messages=messages,
                        temperature=0.1 if attempt == 1 else 0.0,
                        max_tokens=budget,
                    )
                    choice = resp["choices"][0]
                    content = (choice.get("message", {}).get("content") or "").strip()
                    scores = _extract_json_array(content)
                    if scores is None:
                        raise ValueError(
                            "未能解析 JSON"
                            f"（finish_reason={choice.get('finish_reason')}, "
                            f"len={len(content)}, head={content[:80]!r}）"
                        )
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    log.warning(f"[openalex] 批次评分第 {attempt} 次失败: {e}")
                    if attempt == 1:
                        time.sleep(0.3)

            if scores is None:
                log.warning(f"[openalex] 批次评分放弃（标记未评分）: {last_err}")
                for p in batch:
                    paper = dict(p)
                    paper["_relevance_score"] = None
                    paper["_relevance_reason"] = "LLM评分失败，未评分"
                    scored.append(paper)
            else:
                for item in scores:
                    if not isinstance(item, dict):
                        continue
                    idx = item.get("index", 1) - 1  # 0-indexed
                    if 0 <= idx < len(batch):
                        try:
                            score = float(item.get("score", 0))
                        except (TypeError, ValueError):
                            continue
                        if score >= min_score:
                            paper = dict(batch[idx])
                            paper["_relevance_score"] = score
                            paper["_relevance_reason"] = item.get("reason", "")
                            scored.append(paper)

            time.sleep(0.2)

        def _year_of(p: Dict) -> int:
            try:
                return int(str(p.get("year") or 0)[:4])
            except (TypeError, ValueError):
                return 0

        if str(sort_by).lower() in ("date", "time", "year", "newest"):
            # 时间优先：新的在前；同年再按相关度
            scored.sort(
                key=lambda p: (_year_of(p), p.get("_relevance_score") or 0),
                reverse=True,
            )
        else:
            # 相关度优先：同分时新论文在前；未评分的排最后
            scored.sort(
                key=lambda p: (
                    p.get("_relevance_score") is not None,
                    p.get("_relevance_score") or 0,
                    _year_of(p),
                ),
                reverse=True,
            )
        return scored

    except Exception as e:
        log.error(f"[openalex] rerank_by_relevance 整体失败: {e}")
        return papers  # 降级：返回原顺序


# ============ 自然语言搜索（组合方案） ============

def search_papers_nl(
    nl_query: Optional[str] = None,
    max_results: int = 20,
    min_relevance_score: float = 3.0,
    sort_by: str = "relevance",
    output_path: Optional[str] = None,
    save_to_file: bool = True,
    exclude_paper_ids: Optional[List[str]] = None,
) -> List[Dict]:
    """
    用自然语言搜索学术论文（对用户暴露的入口函数）。
    """
    if not nl_query or not nl_query.strip():
        raise ValueError(
            "search_papers_nl 需要传入 nl_query 参数（自然语言查询），"
            "例如: search_papers_nl(nl_query='帮我搜索使用神经网络进行软组织建模的论文')"
        )
    log.info(f"[openalex] NL 搜索开始: {nl_query}")

    # Step 1: LLM 分析查询
    params = analyze_nl_query(nl_query)
    log.info(f"[openalex] 解析参数: query={params.get('query')}, "
             f"years={params.get('year_from')}-{params.get('year_to')}, "
             f"domains={params.get('domains')}")

    # 优先级：调用方显式传 max_results > LLM/规则解析出的 max_results > 默认 20
    parsed_max = params.get("max_results")
    if parsed_max and (max_results == 20 or max_results is None):
        # 函数默认是 20，调用方没显式改 → 让 LLM 解析值生效
        try:
            n = int(parsed_max)
            if 1 <= n <= 50:
                max_results = n
                log.info(f"[openalex] 使用 NL 解析的数量: max_results={max_results}")
        except (TypeError, ValueError):
            pass

    # Step 2+3: 年份窗口从新到旧逐级放宽
    #   - 用户明确提到年份 → 只搜该区间
    #   - 否则：今年 → 近两年 → 近五年，凑够 max_results 就停
    if re.search(r"(?:19|20)\d{2}", nl_query or ""):
        windows = [(params.get("year_from"), params.get("year_to"))]
    else:
        y = datetime.now().year
        windows = [(y, y), (y - 1, y), (y - 4, y)]

    result: List[Dict] = []
    for w_from, w_to in windows:
        raw_papers = search_openalex_papers(
            query=params["query"],
            # 多取候选用于筛选：查询再好，15 条候选也不够挑 5 篇相关的
            max_results=min(max(30, max_results * 5), 200),
            year_from=w_from,
            year_to=w_to,
            domains=params.get("domains"),
            source_types=params.get("source_types"),
            is_oa_only=params.get("is_oa_only", False),
            exclude_paper_ids=exclude_paper_ids,
            exclude_keywords=params.get("exclude_keywords"),  # 空列表时不启用
            sort_by=sort_by,
            save_to_file=False,  # 最终再统一保存
        )
        log.info(f"[openalex] 年份窗口 {w_from}-{w_to}: {len(raw_papers)} 篇候选")
        if not raw_papers:
            continue

        scored_papers = rerank_by_relevance(
            raw_papers,
            nl_query=nl_query,
            min_score=min_relevance_score,
            sort_by=sort_by,
        )
        log.info(
            f"[openalex] 窗口 {w_from}-{w_to} 相关性过滤后剩余 "
            f"{len(scored_papers)} 篇（min_score={min_relevance_score}）"
        )
        result = scored_papers[:max_results]
        if len(result) >= max_results:
            break

    if save_to_file:
        path = output_path or _default_output_path()
        try:
            save_papers_to_file(result, path)
            log.info(f"[openalex] NL 搜索完成，共 {len(result)} 篇，保存到 {path}")
        except (TypeError, ValueError) as e:
            log.warning(f"[openalex] 保存文件失败（跳过）: {e}")

    return result


# ============ 工具 Schema（供 Agent 发现） ============

OPENALEX_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词（支持 AND / OR / NOT 布尔语法，如 'transformer AND image AND NOT caption'）",
        },
        "max_results": {
            "type": "integer",
            "description": "最大返回结果数，默认 50，上限 200",
            "minimum": 1,
            "maximum": 200,
            "default": 50,
        },
        "domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "学科领域过滤，可选值: computer science / ai / machine learning / "
                "deep learning / computer vision / nlp / natural language processing / "
                "human-computer interaction / robotics 等"
            ),
        },
        "year_from": {
            "type": "integer",
            "description": "最早发表年份，如 2020",
        },
        "year_to": {
            "type": "integer",
            "description": "最晚发表年份，如 2026",
        },
        "source_types": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "文献类型过滤，可选值: journal-article / conference / "
                "preprint / book-chapter / book / review"
            ),
        },
        "is_oa_only": {
            "type": "boolean",
            "description": "是否只返回开放获取（Open Access）论文，默认 False",
            "default": False,
        },
        "sort_by": {
            "type": "string",
            "enum": ["relevance", "date"],
            "description": (
                "结果排序方式。relevance（默认）：按相关度，同分时新论文在前；"
                "date：按发表时间倒序（最新优先）。用户说“最新的 / 按时间排”时用 date。"
            ),
            "default": "relevance",
        },
        "exclude_paper_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "要排除的论文 ID 列表（DOI 或 OpenAlex ID）",
        },
        "exclude_keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "排除关键词列表，标题匹配任一关键词则排除（如 survey / review）",
        },
        "output_path": {
            "type": "string",
            "description": "可选：保存到指定路径；不传则默认 output/openalex_papers.json",
        },
        "save_to_file": {
            "type": "boolean",
            "description": "是否将结果写入文件，默认 True",
            "default": True,
        },
    },
    "required": ["query"],
}

registry.register_tool(
    name="search_openalex_papers",
    description=(
        "通过 OpenAlex API 搜索全球学术论文（覆盖 arXiv、PubMed、IEEE、Springer、CrossRef 等所有主要来源）。"
        "支持全学科（不限于 CS）、布尔关键词过滤、年份/文献类型/开放获取等多维度筛选。"
        "返回结果包含 DOI、PDF 链接、被引次数、作者、主题分类等丰富元数据。"
        "sort_by 可选 relevance（相关度优先）或 date（发表时间倒序）。"
    ),
    parameter_schema=OPENALEX_SEARCH_SCHEMA,
    func=search_openalex_papers,
)

registry.register_tool(
    name="get_paper_by_doi",
    description="通过 DOI 精确获取单篇论文的完整元数据（作者、摘要、PDF链接、被引次数等）",
    parameter_schema={
        "type": "object",
        "properties": {
            "doi": {
                "type": "string",
                "description": "论文的 DOI，如 10.48550/arXiv.2301.00001",
            },
        },
        "required": ["doi"],
    },
    func=get_paper_by_doi,
)

registry.register_tool(
    name="search_papers_by_author",
    description="通过作者姓名搜索该作者的所有论文（按发表时间倒序）",
    parameter_schema={
        "type": "object",
        "properties": {
            "author_name": {
                "type": "string",
                "description": "作者姓名（支持模糊匹配）",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回数量，默认 50",
                "minimum": 1,
                "maximum": 200,
                "default": 50,
            },
        },
        "required": ["author_name"],
    },
    func=search_by_author,
)

registry.register_tool(
    name="search_papers_nl",
    description=(
        "用自然语言搜索学术论文（推荐优先使用）。"
        "输入类似「帮我搜索使用神经网络进行软组织建模的论文」这样的口语化需求，"
        "工具会：① 用 LLM 解析出真正的研究意图和关键词，"
        "② 调用 OpenAlex API 搜索，"
        "③ 再用 LLM 对每篇论文的相关性打分，过滤掉不相关的，确保返回的论文都是真正的相关研究。"
        "适合「我想找某方向的前沿工作」这类模糊但具体的搜索需求。"
        "sort_by=date 可按发表时间倒序（最新优先），默认按相关度。"
        "未指定年份时默认从最近一年开始检索，结果不足会自动逐年放宽到近五年。"
    ),
    parameter_schema={
        "type": "object",
        "properties": {
            "nl_query": {
                "type": "string",
                "description": (
                    "自然语言研究需求描述，如：'使用神经网络进行软组织建模的论文' / "
                    "'transformer 在医学图像分割上的最新进展' / "
                    "'强化学习用于机器人控制的开创性工作'"
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "最多返回多少篇高相关论文，默认 20",
                "minimum": 1,
                "maximum": 50,
                "default": 20,
            },
            "min_relevance_score": {
                "type": "number",
                "description": "LLM 相关性最低评分阈值（1-5），低于此分的论文会被过滤掉，默认 3.0",
                "minimum": 1.0,
                "maximum": 5.0,
                "default": 3.0,
            },
            "sort_by": {
                "type": "string",
                "enum": ["relevance", "date"],
                "description": (
                    "结果排序方式。relevance（默认）：按相关度，同分时新论文在前；"
                    "date：按发表时间倒序（最新优先）。用户说“最新的 / 按时间排”时用 date。"
                ),
                "default": "relevance",
            },
            "exclude_paper_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "要排除的论文 ID 列表（DOI 或 OpenAlex ID）。"
                    "用于避免返回会话内已经显示过的论文；通常由 agent 层从 store.get_last_papers 自动注入，"
                    "一般无需手动传。"
                ),
            },
            "output_path": {
                "type": "string",
                "description": "可选：保存到指定路径",
            },
            "save_to_file": {
                "type": "boolean",
                "description": "是否写入文件，默认 True",
                "default": True,
            },
        },
        "required": ["nl_query"],
    },
    func=search_papers_nl,
)


# ============ 本地测试 ============
if __name__ == "__main__":
    print("=" * 60)
    print("OpenAlex 搜索测试")
    print("=" * 60)

    # 测试1: 基础搜索
    print("\n[测试1] 搜索 'transformer vision language' 最新论文 5 篇:")
    papers = search_openalex_papers(
        query="transformer vision language",
        max_results=5,
        year_from=2023,
    )
    for i, p in enumerate(papers, 1):
        print(f"\n  [{i}] {p['title']}")
        print(f"      作者: {', '.join(p['authors'][:3])}{'...' if len(p['authors']) > 3 else ''}")
        print(f"      年份: {p.get('year')},  来源: {p.get('source')}")
        print(f"      被引: {p.get('cited_by_count', 0)},  OA: {p.get('is_open_access')}")
        print(f"      DOI: {p.get('doi', 'N/A')}")
        print(f"      PDF: {p.get('pdf_url', 'N/A')}")

    # 测试2: 只搜 OA 论文
    print("\n[测试2] 搜索 'diffusion model' 仅开放获取 3 篇:")
    oa_papers = search_openalex_papers(
        query="diffusion model image generation",
        max_results=3,
        is_oa_only=True,
    )
    for p in oa_papers:
        print(f"  - {p['title'][:60]}... | OA: {p['pdf_url'] is not None}")

    # 测试3: 指定作者
    print("\n[测试3] 按作者搜索 'Yoshua Bengio' 的论文:")
    author_papers = search_by_author("Yoshua Bengio", max_results=3)
    for p in author_papers:
        print(f"  - [{p.get('year')}] {p['title'][:70]}")

    # 测试4: DOI 精确查找
    print("\n[测试4] DOI 精确查找 10.48550/arXiv.2303.17760:")
    paper = get_paper_by_doi("10.48550/arXiv.2303.17760")
    if paper:
        print(f"  标题: {paper['title']}")
        print(f"  作者: {paper['authors']}")
        print(f"  PDF:  {paper.get('pdf_url', 'N/A')}")
    else:
        print("  未找到")

    print("\n✅ 测试完成")
