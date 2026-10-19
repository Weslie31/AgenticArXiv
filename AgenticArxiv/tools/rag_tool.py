# AgenticArxiv/tools/rag_tool.py
"""
RAG 论文问答工具
- PDF 全量解析 + 滑动窗口切块
- 混合检索：TF-IDF (0.3) + 语义嵌入 (0.7)
- LLM 综合 Top-K 段落生成答案
"""
from __future__ import annotations

import hashlib
import os
import pickle
import re
import threading
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import settings
from models.db import get_sync_session
from models.orm import PaperAnnotationRow, PaperChunkRow, PdfAssetRow
from models.store import store
from tools.tool_registry import registry
from utils.logger import log
from utils.llm_client import get_env_llm_client

# ---- 全局语义嵌入模型（延迟加载，线程安全）----
_embedder_lock = threading.Lock()
_embedder: Optional[Any] = None


def _get_embedder():
    """延迟加载 sentence-transformers 模型（单例，线程安全）"""
    global _embedder
    if _embedder is not None:
        return _embedder
    with _embedder_lock:
        if _embedder is not None:
            return _embedder
        try:
            from sentence_transformers import SentenceTransformer
            # all-MiniLM-L6-v2: 384 维，速度快，适合学术论文
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
            log.info("[RAG] 语义嵌入模型加载完成: all-MiniLM-L6-v2")
        except Exception as e:
            log.error(f"[RAG] 语义嵌入模型加载失败: {e}")
            _embedder = None
        return _embedder


def _encode_texts(texts: List[str]) -> Optional[np.ndarray]:
    """批量编码文本为语义向量，失败时返回 None"""
    embedder = _get_embedder()
    if embedder is None:
        return None
    try:
        return embedder.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    except Exception as e:
        log.error(f"[RAG] 语义编码失败: {e}")
        return None


# ---- 1. PDF 全量解析 + 滑动切块 ----

def _extract_all_pages(pdf_path: str) -> List[Dict[str, Any]]:
    """
    用 pymupdf 逐页抽取全文，识别 section 标题。
    返回: [{"page": int, "text": str, "section": str}, ...]
    """
    try:
        import fitz
    except ImportError:
        import pymupdf as fitz

    doc = fitz.open(pdf_path)
    pages: List[Dict[str, Any]] = []

    # 识别 section 标题的正则（常见学术论文格式）
    SECTION_PAT = re.compile(
        r"^\s*(?:\d+\.?\s+)?([A-Z][A-Z\s\-]{3,45}?)(?:\s*(?:\d+|arXiv|$))?$",
        re.MULTILINE,
    )

    for page_idx, page in enumerate(doc):
        # PyMuPDF 默认 text 模式按源码流顺序，可能产生乱码（如字符错位、单词截断）。
        # 改用 blocks 模式按阅读顺序重建文本，对大多数 PDF 更可靠。
        try:
            blocks = page.get_text("blocks", sort=True)
        except Exception:
            blocks = []

        if blocks:
            lines: List[str] = []
            for block in blocks:
                # block[0..4] = x0,y0,x1,y1,text；block[5] = block_number（数字）
                if len(block) >= 5 and isinstance(block[4], str):
                    text = block[4].strip()
                    if text:
                        lines.append(text)
            raw_text = "\n".join(lines)
        else:
            raw_text = page.get_text("text").strip()

        # 识别当前页的 section
        section = "Unknown"
        for line in raw_text.split("\n")[:15]:
            m = SECTION_PAT.match(line.strip())
            if m:
                candidate = m.group(1).strip()
                # 过滤页码、URL、空行
                if len(candidate) > 3 and not candidate.isdigit():
                    section = candidate
                    break
        pages.append({
            "page": page_idx + 1,       # 1-based
            "text": raw_text.strip(),
            "section": section,
        })
    doc.close()
    return pages


def _chunk_pages(
    pages: List[Dict[str, Any]],
    chunk_size: int = 1200,
    overlap: int = 200,
) -> List[Dict[str, Any]]:
    """
    将 pages 合并为带 section 标注的文本块。

    - 按段落自然切分；
    - 单段落超长时按"句末软切 + overlap"递归切分，避免在词/句中间截断；
    - 相邻同 section 的块会合并（保留 section 标注）。
    """
    chunks: List[Dict[str, Any]] = []
    buffer: List[str] = []
    buf_pages: List[int] = []
    buf_section = "Unknown"

    def _flush():
        if not buffer:
            return
        text = "\n\n".join(buffer)
        chunks.append({
            "page_start": buf_pages[0],
            "page_end": buf_pages[-1],
            "section": buf_section,
            "text": text,
        })

    def _soft_split_long_para(para: str) -> List[str]:
        """把超长段落按句末软切为多个子段，相邻子段保留 overlap 字符。

        中文以 。！？ 切；英文以 . ! ? 切；都没有就退化为硬切。
        """
        if len(para) <= chunk_size:
            return [para]

        # 中英文统一句子终止符集合
        sentence_ends = r"[。！？!?\.]"
        # 切分点 = 句末字符及其后紧邻的空白
        parts = re.split(f"({sentence_ends}\\s*)", para)
        # 把"句子+终止符"重新配对
        sentences: List[str] = []
        for i in range(0, len(parts) - 1, 2):
            sentences.append((parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")).strip())
        if len(parts) % 2 == 1 and parts[-1].strip():
            sentences.append(parts[-1].strip())

        # 没有任何终止符（极少见，比如全角空格分的长串）— 退化到硬切
        if len(sentences) <= 1:
            return [para[i : i + chunk_size] for i in range(0, len(para), chunk_size)]

        # 按 chunk_size 累加成块，相邻块之间保留 overlap 字符
        result: List[str] = []
        cur = ""
        cur_tail = ""
        for s in sentences:
            if not s:
                continue
            # 加入下一句后超长 → 推入当前块，开新块时携带上一块尾部 overlap
            if len(cur) + len(s) > chunk_size and cur:
                result.append(cur)
                # overlap = 上一块最后 overlap 个字符
                tail = cur[-overlap:] if overlap > 0 else ""
                cur = (tail + " " + s).strip() if tail else s
            else:
                cur = s if not cur else (cur + " " + s).strip() if cur.endswith((" ", "\n")) or s.startswith((" ", "\n")) else cur + " " + s
            cur_tail = cur[-overlap:]
        if cur:
            result.append(cur)
        return result

    for pg in pages:
        text = pg["text"]
        section = pg["section"]
        page_no = pg["page"]

        # 跳过空白页
        if len(text) < 20:
            continue

        # 切换页时优先 flush，避免跨页聚合（保留 section 与页边界清晰）
        if buffer and buf_pages and buf_pages[-1] != page_no:
            _flush()

        # 按段落分割
        paras = re.split(r"\n{2,}", text)
        for para in paras:
            para = para.strip()
            if not para:
                continue

            # 超长段落：句末软切 + overlap；保持 page_no 不变
            sub_paras = _soft_split_long_para(para)

            for sub in sub_paras:
                if len(buffer) == 0:
                    buffer.append(sub)
                    buf_pages = [page_no]
                    buf_section = section
                elif len("\n\n".join(buffer)) + len(sub) + 2 <= chunk_size:
                    buffer.append(sub)
                    buf_pages.append(page_no)
                    if section not in ("Unknown", buf_section) and len(section) < len(buf_section):
                        buf_section = section
                else:
                    _flush()
                    # overlap：保留上一个小块末尾作为热身上下文
                    overlap_text = (chunks[-1]["text"][-overlap:] if overlap > 0 and chunks else "")
                    buffer = ([overlap_text] if overlap_text else []) + [sub]
                    buf_pages = [page_no]
                    buf_section = section

    _flush()
    return chunks


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


# ---- 2. 增量索引（写 DB） ----

def index_paper_chunks(paper_id: str, pdf_path: str) -> int:
    """
    解析 PDF 并写入 paper_chunks 表（幂等：重复调用不会重复写入）。
    已有 chunks 但无 embedding 时，补充计算并缓存语义嵌入。
    返回: 写入的 chunk 数量
    """
    pages = _extract_all_pages(pdf_path)
    chunks = _chunk_pages(pages)

    with get_sync_session() as s:
        existing_rows = (
            s.query(PaperChunkRow)
            .filter_by(paper_id=paper_id)
            .order_by(PaperChunkRow.chunk_index)
            .all()
        )

    if existing_rows:
        # 幂等：已存在则跳过写入（但可能补充 embedding）
        has_missing_emb = any(r.embedding_blob is None for r in existing_rows)
        if not has_missing_emb:
            log.info(f"[RAG] {paper_id} 已完全索引（含 embedding），跳过")
            return len(existing_rows)

        # 补充缺失的 embedding
        log.info(f"[RAG] {paper_id} 补充计算缺失的 embedding...")
        texts = [r.text for r in existing_rows]
        emb_vectors = _encode_texts(texts)
        has_emb = emb_vectors is not None

        for idx, row in enumerate(existing_rows):
            if row.embedding_blob is None and has_emb:
                row.embedding_blob = pickle.dumps(emb_vectors[idx].astype(np.float32))
                row.embedding_model = "sentence-transformer"

        with get_sync_session() as s:
            for row in existing_rows:
                s.add(row)
            s.commit()
        log.info(f"[RAG] {paper_id} embedding 补充完成")
        return len(existing_rows)

    # ---- 全新写入 ----
    texts = [ch["text"] for ch in chunks]
    emb_vectors = _encode_texts(texts)
    has_emb = emb_vectors is not None

    rows_to_insert = []
    for idx, ch in enumerate(chunks):
        text = ch["text"]
        h = _text_hash(text)
        emb_blob = None
        if has_emb:
            emb_blob = pickle.dumps(emb_vectors[idx].astype(np.float32))
        rows_to_insert.append(PaperChunkRow(
            paper_id=paper_id,
            chunk_index=idx,
            page_start=ch["page_start"],
            page_end=ch["page_end"],
            section=ch["section"],
            text=text,
            text_hash=h,
            token_count=len(text.split()),
            embedding_model="sentence-transformer" if has_emb else "none",
            embedding_blob=emb_blob,
        ))

    with get_sync_session() as s:
        for row in rows_to_insert:
            s.add(row)
        s.commit()

    log.info(f"[RAG] {paper_id} 索引完成，共 {len(rows_to_insert)} chunks，语义嵌入={'是' if has_emb else '否'}")
    return len(rows_to_insert)


# ---- 3. TF-IDF 检索 ----

def _build_tfidf_index(
    rows: List[PaperChunkRow],
    *,
    analyzer: str = "word",
    ngram_range: tuple[int, int] = (1, 2),
) -> tuple:
    """对 chunks 构建内存 TF-IDF 索引"""
    corpus = [r.text for r in rows]
    vec = TfidfVectorizer(
        max_features=5000,
        stop_words="english",
        analyzer=analyzer,
        ngram_range=ngram_range,
        lowercase=True,
    )
    matrix = vec.fit_transform(corpus)
    return vec, matrix


def _is_chinese_text(text: str, threshold: float = 0.3) -> bool:
    """判断文本是否以中文为主（中文字符占比超过 threshold）"""
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return False
    cn_chars = sum(1 for c in non_space if "\u4e00" <= c <= "\u9fff")
    return cn_chars / len(non_space) >= threshold


def _translate_question_cn_to_keywords(text: str) -> str:
    """将中文问题转换为英文检索关键词（本地词表，无外部 API 依赖）。

    策略：精确字符串替换，顺序无关。
    包含：
    - 论文阅读常见问法词映射（中→英）
    - 句子级模式（覆盖完整问句）
    """
    import re

    # ---- 句级模式（优先匹配完整问句）----
    SENTENCE_PATTERNS = [
        # 方法/模型/算法
        (r"作者提出了什么方法", "propose method"),
        (r"作者提出了什么算法", "propose algorithm"),
        (r"作者提出了什么模型", "propose model"),
        (r"作者提出了什么技术", "propose technique"),
        (r"本文提出了什么方法", "propose method"),
        (r"本文提出了什么模型", "propose model"),
        (r"这篇论文提出了什么", "propose method model"),
        (r"提出了什么方法", "propose method"),
        (r"提出了什么算法", "propose algorithm"),
        # 创新点
        (r"创新点是什么", "novelty innovation contribution"),
        (r"主要创新点", "main innovation contribution"),
        (r"核心创新", "key innovation"),
        (r"有什么创新", "novelty innovation"),
        # 数据集
        (r"用了哪些数据集", "dataset benchmark evaluation dataset"),
        (r"使用了哪些数据集", "dataset benchmark evaluation dataset"),
        (r"有哪些数据集", "dataset benchmark evaluation"),
        (r"数据集有哪些", "dataset benchmark evaluation"),
        (r"数据来源", "dataset data source"),
        # 实验/结果
        (r"实验结果如何", "experiment result performance evaluation"),
        (r"实验结果怎么样", "experiment result performance"),
        (r"性能如何", "performance accuracy result"),
        (r"准确率如何", "accuracy precision result"),
        (r"精度如何", "accuracy precision result"),
        # 方法相关
        (r"核心方法", "core method approach key method"),
        (r"主要方法", "main method approach"),
        (r"模型架构", "model architecture"),
        (r"技术路线", "technical approach method"),
        (r"技术方案", "technical approach method"),
        # 结构/章节
        (r"摘要", "abstract"),
        (r"结论", "conclusion"),
        (r"总结", "summary conclusion"),
        (r"未来工作", "future work"),
        (r"展望", "future work prospect outlook"),
        (r"未来展望", "future work prospect outlook"),
        (r"局限性", "limitation weakness"),
        (r"不足之处", "limitation weakness"),
        # 背景
        (r"研究背景", "background motivation"),
        (r"解决的问题", "problem research question"),
        (r"目标是什么", "goal objective aim"),
        # 泛化/介绍类（优先匹配，防止翻译残渣干扰检索）
        (r"详细介绍", "introduction abstract method model result"),
        (r"详细描述", "introduction abstract describe method"),
        (r"详细说明", "introduction abstract describe method"),
        (r"概述", "overview abstract introduction"),
        (r"概括", "overview abstract summary"),
        (r"整体介绍", "overview abstract introduction summary"),
        (r"综述", "overview survey summary review"),
        (r"方法与模型", "method model architecture approach algorithm framework"),
        (r"核心方法", "core method approach architecture framework"),
        (r"模型细节", "model architecture details network layers"),
        # 其他
        (r"相关内容", ""),
        (r"这篇论文", ""),
        (r"本文", ""),
    ]

    result = text
    for pattern, replacement in SENTENCE_PATTERNS:
        result = result.replace(pattern, replacement)

    # ---- 词级映射（处理剩余中文词）----
    WORD_PATTERNS = [
        # 方法/技术
        ("方法", "method"), ("算法", "algorithm"), ("模型", "model"),
        ("技术", "technique"), ("框架", "framework"), ("架构", "architecture"),
        ("提出", "propose"), ("提出一种", "propose"), ("设计", "design"),
        ("创新", "innovation"), ("创新点", "novelty"),
        # 数据
        ("数据", "data dataset"), ("数据集", "dataset benchmark"),
        ("实验", "experiment evaluation"), ("结果", "result performance"),
        ("性能", "performance accuracy"), ("指标", "metric evaluation"),
        ("对比", "compare comparison baseline"), ("基线", "baseline comparison"),
        ("消融", "ablation study"),
        # 背景/目的
        ("背景", "background motivation"), ("目标", "goal objective aim"),
        ("任务", "task"), ("贡献", "contribution"),
        ("解决了", "solve address"),
        # 结构/总结
        ("摘要", "abstract"), ("总结", "summary"), ("结论", "conclusion"),
        ("未来", "future work"), ("局限", "limitation"),
        # 通用疑问
        ("是什么", "what is"), ("如何", "how"), ("为什么", "why"),
        ("哪些", "which what"), ("哪个", "which"),
        # 作者/我们
        ("作者", "authors we"), ("本文", ""), ("这篇论文", ""),
        # 训练/优化
        ("训练", "training"), ("优化", "optimization"),
        ("损失函数", "loss function"), ("损失", "loss"),
        # 补充
        ("主要", "main key"), ("核心", "core key"),
        ("相关", "related relevant"), ("介绍", "introduction describe"),
        ("概述", "overview summary"), ("比较", "compare"),
    ]

    for cn, en in WORD_PATTERNS:
        result = result.replace(cn, en)

    # 去掉标点符号
    result = re.sub(r"[，。？！、；：""''（）【】《》]", " ", result)
    # 去掉多余空格
    result = re.sub(r"\s+", " ", result).strip()
    return result


def _sanitize_chunk_text(text: str) -> str:
    """去除 PDF chunk 中的页眉/页脚干扰文本，避免 LLM 混淆。

    去除内容：
    - 页眉行：单行包含 1-2 个单词 + 单独一行的阿拉伯数字页码（如 "Wat3R\n3"）
    - 孤立的纯数字行（页码误切）
    - 行首/行尾的括号引用标记（如 "[3]"）
    - 表格标题行（包含 "↓" 等表格符号）
    """
    import re
    lines = text.split("\n")
    cleaned = []
    prev_was_short = False

    for line in lines:
        stripped = line.strip()
        # 跳过空行（保留最多连续 1 个空行）
        if not stripped:
            if prev_was_short:
                continue
            prev_was_short = True
            cleaned.append("")
            continue
        prev_was_short = False

        # 跳过纯数字行（页码）
        if re.fullmatch(r"\d+", stripped):
            continue

        # 跳过短标题行（典型页眉：论文名 + 页码，或纯 URL/doi 行）
        # 判断标准：不含句号/问号（不是完整句子），且长度 <= 30
        # 匹配：arXiv:xxx、doi:xxx、https://xxx、或单行标题（如 "Wat3R"）
        if (
            re.match(r"^(arXiv:|https?://|doi:)", stripped)
            or (re.match(r"^[A-Za-z][A-Za-z0-9 _-]*$", stripped) and len(stripped) <= 30)
        ):
            if "." not in stripped and "?" not in stripped and "," not in stripped:
                continue

        # 跳过表格列头行（包含 ↓ ↑ 等符号）
        if re.search(r"[↓↑→←]", stripped):
            continue

        # 跳过 "Fig." / "Table " 纯标题行（仅图注编号，无描述内容）
        # 判断标准：以 Fig./Table 开头，但长度 <= 25（典型格式：Fig. 1.）
        # 带完整描述的图注（> 25字符）应该保留给 LLM
        if re.match(r"^(Fig\.\s*\d+[\.:]|Table\s+\d+[\.:])", stripped) and len(stripped) <= 25:
            continue

        # 清理行内残留的引用标记（如 "[3]" 出现在行尾）
        cleaned_line = re.sub(r"\s*\[\d+\]\s*$", "", stripped)
        # 清理行内残留的作者引用（行尾括号）
        cleaned_line = re.sub(r"\s*\([A-Z][a-z]+ et al\.\)\s*$", "", cleaned_line)
        # 清理行内孤立的 DOI / arxiv 链接
        cleaned_line = re.sub(r"https?://\S+", "", cleaned_line)

        if cleaned_line.strip():
            cleaned.append(cleaned_line)

    # 合并，空行保留但不超过两个连续空行
    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def retrieve_chunks(
    paper_id: str,
    question: str,
    top_k: int = 8,
) -> List[Dict[str, Any]]:
    """混合检索：TF-IDF (0.3) + 语义嵌入 (0.7)，返回 top_k 相关 chunk"""
    with get_sync_session() as s:
        rows = (
            s.query(PaperChunkRow)
            .filter_by(paper_id=paper_id)
            .order_by(PaperChunkRow.chunk_index)
            .all()
        )

    if not rows:
        return []

    n = len(rows)

    # ---- TF-IDF 检索（归一化到 [0, 1]）----
    if _is_chinese_text(question):
        # 中文问题：避免词表翻译损失语义信息
        # 1) 原始中文直接做 char_wb TF-IDF（中文形态匹配）
        vec_char, matrix_char = _build_tfidf_index(
            rows, analyzer="char_wb", ngram_range=(2, 4)
        )
        q_vec_char = vec_char.transform([question])
        scores_char = cosine_similarity(q_vec_char, matrix_char).flatten()

        # 2) 词表翻译后做英文词级 TF-IDF（覆盖专有名词英译）
        english_q = _translate_question_cn_to_keywords(question)
        vec_word, matrix_word = _build_tfidf_index(rows)
        q_vec_word = vec_word.transform([english_q])
        scores_word = cosine_similarity(q_vec_word, matrix_word).flatten()

        def normalize(arr):
            mn, mx = arr.min(), arr.max()
            if mx - mn < 1e-9:
                return arr
            return (arr - mn) / (mx - mn)

        # 字形 + 译名两条通路，权重对半
        scores_tfidf = 0.5 * normalize(scores_char) + 0.5 * normalize(scores_word)
    else:
        vec, matrix = _build_tfidf_index(rows)
        q_vec = vec.transform([question])
        scores_tfidf = cosine_similarity(q_vec, matrix).flatten()
        mn, mx = scores_tfidf.min(), scores_tfidf.max()
        if mx - mn > 1e-9:
            scores_tfidf = (scores_tfidf - mn) / (mx - mn)
        else:
            scores_tfidf[:] = 0.0

    # ---- 语义嵌入检索 ----
    scores_semantic = np.zeros(n, dtype=np.float32)

    # 优先从 DB 缓存读取 embedding
    cached_vectors = []
    for r in rows:
        if r.embedding_blob:
            try:
                cached_vectors.append(pickle.loads(r.embedding_blob))
            except Exception:
                cached_vectors.append(None)
        else:
            cached_vectors.append(None)

    has_cached = any(v is not None for v in cached_vectors)

    if has_cached:
        # 中文问题：语义检索时用英文译名（MiniLM 在英文上更强）以提升召回
        sem_query = (
            _translate_question_cn_to_keywords(question)
            if _is_chinese_text(question)
            else question
        )
        # 使用缓存向量计算语义相似度
        chunk_vectors = [v for v in cached_vectors if v is not None]
        chunk_indices = [i for i, v in enumerate(cached_vectors) if v is not None]
        chunk_matrix = np.stack(chunk_vectors).astype(np.float32)

        query_vec = _encode_texts([sem_query])
        if query_vec is not None:
            raw_scores = cosine_similarity(query_vec, chunk_matrix).flatten()
            # 归一化
            mn, mx = raw_scores.min(), raw_scores.max()
            if mx - mn > 1e-9:
                norm_scores = (raw_scores - mn) / (mx - mn)
            else:
                norm_scores = raw_scores.copy()

            for idx, score in zip(chunk_indices, norm_scores):
                scores_semantic[idx] = score
    else:
        # 无缓存时实时编码（仅对候选 chunk）
        # 先用 TF-IDF 初筛 top-30 减少编码量（提高覆盖率）
        top_candidates = int(min(30, max(10, n // 2)))
        candidate_indices = np.argsort(scores_tfidf)[::-1][:top_candidates]

        candidate_texts = [rows[i].text for i in candidate_indices]
        candidate_emb = _encode_texts(candidate_texts)
        query_emb = _encode_texts([sem_query])

        if candidate_emb is not None and query_emb is not None:
            raw_scores = cosine_similarity(query_emb, candidate_emb).flatten()
            mn, mx = raw_scores.min(), raw_scores.max()
            if mx - mn > 1e-9:
                norm_scores = (raw_scores - mn) / (mx - mn)
            else:
                norm_scores = raw_scores.copy()

            for ci, idx in enumerate(candidate_indices):
                scores_semantic[idx] = norm_scores[ci]

    # ---- 混合打分：0.2*TF-IDF + 0.8*语义（论文检索更依赖语义匹配）----
    scores_final = 0.2 * scores_tfidf + 0.8 * scores_semantic

    # 取 top_k（不再过滤 score>0，避免归一化后真相关片段被丢掉）
    scored = [(i, float(scores_final[i])) for i in scores_final.argsort()[::-1]]
    scored = scored[:top_k]

    results = []
    for idx, score in scored:
        r = rows[idx]
        results.append({
            "chunk_index": r.chunk_index,
            "page_start": r.page_start,
            "page_end": r.page_end,
            "section": r.section,
            "text": _sanitize_chunk_text(r.text),
            "score": score,
        })
    return results


# ---- 3.5 批注召回（按 session 隔离）----

class _AnnotationLike:
    """轻量包装类，让 _build_tfidf_index 能直接复用（仅用 .text 字段）。"""
    __slots__ = ("__text",)

    def __init__(self, text: str):
        self.__text = text

    @property
    def text(self) -> str:  # 兼容 _build_tfidf_index 的 r.text 访问
        return self.__text


def retrieve_annotations(
    paper_id: str,
    question: str,
    session_id: str = "default",
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """
    混合检索用户批注：TF-IDF + 语义嵌入，返回 top_k 相关批注。

    批注数较少时（< 3 条）直接走全部；多于 top_k 才进入打分排序。
    """
    with get_sync_session() as s:
        rows = (
            s.query(PaperAnnotationRow)
            .filter_by(paper_id=paper_id, session_id=session_id)
            .order_by(PaperAnnotationRow.created_at.desc())
            .all()
        )

    if not rows:
        return []

    # 把每条批注的高亮片段 + 评论 拼成 "text"，统一送入现有检索管线
    docs = [_AnnotationLike(f"{r.highlighted_text}\n{r.comment}") for r in rows]
    texts = [d.text for d in docs]

    n = len(rows)

    # ---- TF-IDF ----
    if _is_chinese_text(question):
        vec_char, matrix_char = _build_tfidf_index(
            docs, analyzer="char_wb", ngram_range=(2, 4)
        )
        q_vec_char = vec_char.transform([question])
        scores_char = cosine_similarity(q_vec_char, matrix_char).flatten()

        english_q = _translate_question_cn_to_keywords(question)
        vec_word, matrix_word = _build_tfidf_index(docs)
        q_vec_word = vec_word.transform([english_q])
        scores_word = cosine_similarity(q_vec_word, matrix_word).flatten()

        def normalize(arr):
            mn, mx = arr.min(), arr.max()
            if mx - mn < 1e-9:
                return arr
            return (arr - mn) / (mx - mn)

        scores_tfidf = 0.5 * normalize(scores_char) + 0.5 * normalize(scores_word)
    else:
        vec, matrix = _build_tfidf_index(docs)
        q_vec = vec.transform([question])
        scores_tfidf = cosine_similarity(q_vec, matrix).flatten()
        mn, mx = scores_tfidf.min(), scores_tfidf.max()
        if mx - mn > 1e-9:
            scores_tfidf = (scores_tfidf - mn) / (mx - mn)
        else:
            scores_tfidf[:] = 0.0

    # ---- 语义嵌入 ----
    scores_semantic = np.zeros(n, dtype=np.float32)
    candidate_emb = _encode_texts(texts)
    query_emb = _encode_texts([question])
    if candidate_emb is not None and query_emb is not None:
        raw = cosine_similarity(query_emb, candidate_emb).flatten()
        mn, mx = raw.min(), raw.max()
        if mx - mn > 1e-9:
            scores_semantic = (raw - mn) / (mx - mn)
        else:
            scores_semantic = raw.copy()

    scores_final = 0.2 * scores_tfidf + 0.8 * scores_semantic

    k = min(top_k, n)
    scored = [(i, float(scores_final[i])) for i in scores_final.argsort()[::-1]]
    scored = scored[:k]

    results = []
    for idx, score in scored:
        r = rows[idx]
        results.append({
            "annotation_id": r.id,
            "page_number": r.page_number,
            "highlighted_text": r.highlighted_text,
            "comment": r.comment,
            "score": score,
        })
    return results


# ---- 4. 主工具：ask_paper ----

def _chat_with_budget_retry(
    llm,
    model_name: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    budgets,
    label: str = "LLM",
) -> str:
    """调用 LLM；若因 max_tokens 被截断（finish_reason=length）则加大预算重试。

    推理型模型（如 deepseek-v4-flash）的 reasoning token 也计入 max_tokens，
    预算不足时会话说到一半就断，表现为"只输出了第 1 点"。
    """
    last = ""
    for budget in budgets:
        resp = llm.chat_completions(
            model=model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=budget,
        )
        choice = resp["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
        usage = resp.get("usage") or {}
        reasoning = (usage.get("completion_tokens_details") or {}).get(
            "reasoning_tokens"
        )
        log.info(
            f"[{label}] finish_reason={choice.get('finish_reason')} "
            f"content_len={len(content)} completion_tokens="
            f"{usage.get('completion_tokens')} reasoning_tokens={reasoning}"
        )
        if choice.get("finish_reason") != "length":
            return content
        last = content
        log.warning(f"[{label}] 回答被 max_tokens={budget} 截断，加大预算重试")
    return last


def ask_paper(
    paper_id: str,
    question: str,
    top_k: int = 8,
    force_reindex: bool = False,
    session_id: str = "default",
    include_annotations: bool = True,
    selected_text: Optional[str] = None,
    selected_page: Optional[int] = None,
) -> Dict[str, Any]:
    """
    基于 PDF 全文回答用户关于该论文的问题。

    参数:
        paper_id: arXiv 论文短 ID（如 "2401.12345"）
        question: 用户问题
        top_k: 检索的段落数量（默认 5）
        force_reindex: 是否强制重新索引（覆盖已有 chunks）
        session_id: 当前会话 ID；用于按 session 检索个人批注
        selected_text: 用户拖选出的原文（最高优先级 context）
        selected_page: 选区所在 PDF 页码
        include_annotations: 是否把相关批注注入到上下文

    返回:
        {
            "answer": str,          # LLM 综合 Top-K 段落后的回答
            "sources": [...],       # 引用的段落列表（标注 kind=chunk/annotation）
            "annotations_used": [...], # 实际注入的高相关批注
            "confidence": str,      # "high" | "medium" | "low"
            "chunk_count": int,    # 该论文的总 chunk 数
            "indexed": bool,        # 是否进行了索引（首次调用时为 True）
        }
    """
    # 1. 检查 PDF 是否存在且已下载
    pdf_asset = store.get_pdf_asset(paper_id)
    if not pdf_asset or pdf_asset.status != "READY":
        return {
            "error": f"论文 {paper_id} 尚未下载 PDF，请先调用 download_arxiv_pdf",
        }
    pdf_path = pdf_asset.local_path
    if not pdf_path or not __import__("os").path.exists(pdf_path):
        return {
            "error": f"PDF 文件不存在: {pdf_path}，请重新下载",
        }

    log.info(
        f"[RAG] ask_paper enter paper={paper_id} "
        f"selected_text_len={len(selected_text) if selected_text else 0} "
        f"selected_page={selected_page}"
    )

    # 2. 增量索引
    indexed = False
    with get_sync_session() as s:
        existing_count = s.query(PaperChunkRow).filter_by(paper_id=paper_id).count()

    if existing_count == 0 or force_reindex:
        if force_reindex:
            # 删除旧 chunks，重新索引
            with get_sync_session() as s:
                s.query(PaperChunkRow).filter_by(paper_id=paper_id).delete()
                s.commit()
        count = index_paper_chunks(paper_id, pdf_path)
        indexed = True
    else:
        count = existing_count

    # 3. 检索 Top-K（若无结果，fallback 到摘要/前言 chunks）
    retrieved = retrieve_chunks(paper_id, question, top_k)
    if not retrieved:
        log.warning(f"[RAG] retrieve_chunks 返回空，尝试 fallback（摘要/前言）")
        with get_sync_session() as s:
            fallback_rows = (
                s.query(PaperChunkRow)
                .filter_by(paper_id=paper_id)
                .order_by(PaperChunkRow.chunk_index)
                .limit(10)
                .all()
            )
        if fallback_rows:
            retrieved = [
                {
                    "chunk_index": r.chunk_index,
                    "page_start": r.page_start,
                    "page_end": r.page_end,
                    "section": r.section,
                    "text": _sanitize_chunk_text(r.text),
                    "score": 0.01,
                }
                for r in fallback_rows
            ]
        else:
            return {
                "answer": "未在论文中找到相关内容，请尝试换一种问法。",
                "sources": [],
                "annotations_used": [],
                "confidence": "low",
                "chunk_count": count,
                "indexed": indexed,
            }

    # 4. 组装 Prompt，调用 LLM
    page_info = "、".join(
        f"第 {r['page_start']} 页" if r['page_start'] == r['page_end']
        else f"第 {r['page_start']}-{r['page_end']} 页"
        for r in retrieved
    )
    # 每个片段送入 prompt 的字符上限从 600 提升到 800，确保长片段不被截断过头
    context = "\n\n---\n\n".join(
        f"[来源：第 {r['page_start']}-{r['page_end']} 页]\n{r['text'][:800]}"
        for r in retrieved
    )

    # 4.0 选区优先注入：用户拖选出的文字必须出现在「可用片段」顶部，
    # 避免因为 TF-IDF 检索把它漏掉，导致 LLM 说"片段未涉及此问题"。
    selected_block = ""
    if selected_text and selected_text.strip():
        sel = selected_text.strip()
        page_tag = f"第 {selected_page} 页" if selected_page else "用户选区"
        # 1) 若选区所在页存在于 chunks，优先用该页的真实 chunk 替换裸文本，
        #    确保页码标注与正文一致。
        page_chunk = None
        if selected_page:
            with get_sync_session() as s:
                page_chunk = (
                    s.query(PaperChunkRow)
                    .filter_by(paper_id=paper_id, page_start=selected_page)
                    .order_by(PaperChunkRow.chunk_index)
                    .first()
                )
        if page_chunk and page_chunk.text and sel[:50] in page_chunk.text:
            selected_block = f"[用户选区 · {page_tag}（来自真实 chunk）]\n{_sanitize_chunk_text(page_chunk.text)[:1500]}"
            log.info(f"[RAG] 选区命中 page={selected_page} 的 chunk，已注入完整 chunk")
        else:
            selected_block = f"[用户选区 · {page_tag}]\n{sel[:1500]}"
            log.info(f"[RAG] 选区未命中 chunk，已注入裸文本（page={selected_page}）")

        # 2) 把 selected_block 注入到 context 顶部（确保 LLM 一定看到）
        if selected_block:
            context = f"{selected_block}\n\n---\n\n{context}" if context else selected_block

    # 4.5 批注召回：与正文 chunks 并行打分，取 top_k//3（最少 1，最多 3）注入 prompt
    annotations_used: List[Dict[str, Any]] = []
    annotation_block = ""
    if include_annotations and session_id:
        try:
            n_annot = max(1, min(3, top_k // 3))
            annotations_used = retrieve_annotations(
                paper_id=paper_id,
                question=question,
                session_id=session_id,
                top_k=n_annot,
            )
        except Exception as e:
            log.warning(f"[RAG] 批注召回失败（不影响主流程）: {e}")
            annotations_used = []

        if annotations_used:
            annotation_block_parts = []
            for a in annotations_used:
                page_tag = (
                    f"第 {a['page_number']} 页"
                    if a.get("page_number") is not None
                    else "未指定页码"
                )
                annotation_block_parts.append(
                    f"[批注 · {page_tag}]\n"
                    f"原文：{a['highlighted_text'][:400]}\n"
                    f"你的评论：{a['comment'][:300]}"
                )
            annotation_block = (
                "=== 我的批注（高相关度，session=" + session_id + "）===\n"
                + "\n\n---\n\n".join(annotation_block_parts)
                + "\n\n"
            )
            log.info(
                f"[RAG] 注入了 {len(annotations_used)} 条批注到上下文 "
                f"(paper={paper_id}, session={session_id})"
            )

    # 防御性检查：context 至少要有实际内容
    if not context or len(context.strip()) < 50:
        log.error(f"[RAG] {paper_id} context 内容过少（{len(context)} bytes），retrieved={len(retrieved)} chunks")
        return {
            "answer": f"⚠️ 检索到的内容过少，可能 PDF 解析失败或 chunk 为空。请确认该论文 PDF 已正确下载（chunk_count={count}）。",
            "sources": [],
            "annotations_used": [],
            "confidence": "low",
            "chunk_count": count,
            "indexed": indexed,
        }

    prompt = (
        "你是一个专业的学术论文审稿人。请基于以下论文片段，用中文回答用户的问题。\n\n"
        "【硬性约束 — 严格遵守】\n"
        "1. 仅使用下方「可用片段」与「我的批注」中的信息作答，绝对不要编造或臆测。\n"
        "2. 引用页码只使用片段头部 [来源：第 X-Y 页] / [批注 · 第 X 页] / [用户选区 · 第 X 页] 中标注的页码，不要自行推断。\n"
        "3. 回答末尾不要追加任何\"免责声明 / 完整性声明 / 片段未覆盖\"之类的元说明。\n"
        "4. 回答正文不要出现\"第X页\"等字面页码引用，需要引用时使用「（来源 1）」或「（批注 1）」这种角标形式，并在末尾用列表统一列出 [来源 1] 第 X-Y 页 / <section>、[批注 1] 第 X 页 / <你的评论摘要>。\n"
        "5. 当上下文包含「[用户选区 · ...]」时：这就是用户拖选并提问的原文，是你回答问题的**第一手资料**，必须直接基于它作答；不要回复\"论文片段未涉及此问题\"。\n\n"
        "【回答格式】\n"
        "- 直接给出结论与要点，不要任何前置铺垫（如\"根据提供的片段...\"）。\n"
        "- 若多个片段或批注涉及同一论点，按逻辑合并叙述。\n"
        "- 若片段与批注信息确实不足，请用一句话直说\"论文片段未涉及此问题\"，然后立即停笔，不要扩展。\n"
        "- 「我的批注」是用户过去阅读时的高亮与评论，请优先把它们作为个人偏好/重点来回答，而不是和正文片段一视同仁。\n\n"
        f"=== 可用片段 ===\n{context}\n\n"
        f"{annotation_block}"
        f"=== 用户问题 ===\n{question}\n\n"
        "=== 回答（中文）==="
    )

    try:
        from utils.llm_client import get_app_llm_client
        from services.app_settings import get_llm_config

        llm = get_app_llm_client()
        user_cfg = get_llm_config()
        model_name = (
            os.getenv("LLM_MODEL")
            or get_llm_config().model
            or settings.models.agent_model
        )
        # 注意：deepseek-v4-flash 这类模型的 reasoning token 也计入 max_tokens。
        # 1200 的预算在思考较长时会把回答截断（例如只输出第 1 个创新点）。
        answer = _chat_with_budget_retry(
            llm,
            model_name=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的学术论文审稿人，擅长从论文片段中提取准确信息并用中文回答问题。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            budgets=(3000, 5000),
            label="RAG",
        )
    except Exception as e:
        log.error(f"[RAG] LLM 调用失败: {e}")
        return {
            "answer": f"LLM 调用失败: {e}",
            "sources": [],
            "annotations_used": [],
            "confidence": "low",
            "chunk_count": count,
            "indexed": indexed,
        }

    confidence = "high" if retrieved[0]["score"] > 0.3 else "medium"

    # 5. 构造 sources：把正文 chunk 与批注分开标注 kind，方便前端渲染
    chunk_sources = [
        {
            "kind": "chunk",
            "page": f"{r['page_start']}-{r['page_end']}",
            "section": r["section"],
            "snippet": r["text"][:200],
            "score": round(r["score"], 4),
            "chunk_index": r["chunk_index"],
        }
        for r in retrieved
    ]
    annotation_sources = [
        {
            "kind": "annotation",
            "annotation_id": a["annotation_id"],
            "page": str(a["page_number"]) if a.get("page_number") is not None else None,
            "snippet": a["highlighted_text"][:200],
            "comment": a["comment"][:200],
            "score": round(a["score"], 4),
        }
        for a in annotations_used
    ]

    return {
        "answer": answer,
        "sources": chunk_sources,
        "annotations_used": [
            {
                "annotation_id": a["annotation_id"],
                "page_number": a.get("page_number"),
                "snippet": a["highlighted_text"][:200],
                "comment": a["comment"][:200],
                "score": round(a["score"], 4),
            }
            for a in annotations_used
        ],
        "confidence": confidence,
        "chunk_count": count,
        "indexed": indexed,
    }


# ---- 5. 工具：summarize_paper ----

def summarize_paper(
    paper_id: str,
    focus: str = "general",
    max_length: int = 500,
) -> Dict[str, Any]:
    """
    对全文做摘要，支持指定关注点。
    参数:
        focus: "general" | "method" | "experiment" | "conclusion" | "contribution"
    """
    pdf_asset = store.get_pdf_asset(paper_id)
    if not pdf_asset or pdf_asset.status != "READY":
        return {"error": f"论文 {paper_id} 尚未下载 PDF"}

    # 确保已索引（用于获取文本）
    pdf_path = pdf_asset.local_path
    with get_sync_session() as s:
        count = s.query(PaperChunkRow).filter_by(paper_id=paper_id).count()
    if count == 0:
        index_paper_chunks(paper_id, pdf_path)

    with get_sync_session() as s:
        rows = (
            s.query(PaperChunkRow)
            .filter_by(paper_id=paper_id)
            .order_by(PaperChunkRow.chunk_index)
            .limit(30)
            .all()
        )
    full_text = "\n\n".join(r.text for r in rows)

    focus_map = {
        "general": "研究背景、主要方法、核心贡献和实验结论",
        "method": "技术方法和模型架构",
        "experiment": "实验设置、数据集和性能对比结果",
        "conclusion": "主要结论和未来工作方向",
        "contribution": "主要创新点和贡献",
    }
    focus_text = focus_map.get(focus, focus)

    prompt = (
        f"请用中文总结以下学术论文的内容，重点关注「{focus_text}」。"
        f"总结不超过 {max_length} 字，简洁专业。\n\n"
        f"=== 论文内容 ===\n{full_text[:10000]}"
    )

    try:
        from utils.llm_client import get_app_llm_client
        from services.app_settings import get_llm_config

        llm = get_app_llm_client()
        user_cfg = get_llm_config()
        model_name = (
            os.getenv("LLM_MODEL")
            or get_llm_config().model
            or settings.models.agent_model
        )
        # 留足 token headroom：max_tokens 要远大于 max_length，
        # 因为 prompt 正文本身占约 2000-3000 tokens，
        # 输出应在剩余 context 窗口内完成。取 *3+500 确保不被截断。
        summary = _chat_with_budget_retry(
            llm,
            model_name=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的学术论文审稿人，擅长简洁准确地总结论文要点。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            budgets=(max_length * 3 + 500, max_length * 5 + 800),
            label="RAG-summary",
        )
        # 后处理：超过 max_length 时在句子边界截断，避免出现不完整句
        if len(summary) > max_length:
            cutoff = summary[:max_length]
            last_punct = max(cutoff.rfind("。"), cutoff.rfind("！"), cutoff.rfind("？"))
            summary = cutoff[:last_punct + 1] if last_punct > max_length * 0.7 else cutoff + "…"
    except Exception as e:
        log.error(f"[RAG] summarize_paper LLM 失败: {e}")
        return {"error": str(e)}

    return {"summary": summary, "focus": focus, "paper_id": paper_id}


# ---- 6. 工具：reindex_paper ----

def reindex_paper(paper_id: str) -> Dict[str, Any]:
    """强制重新索引某篇论文（删除旧 chunks 后重建）"""
    pdf_asset = store.get_pdf_asset(paper_id)
    if not pdf_asset or pdf_asset.status != "READY":
        return {"error": f"论文 {paper_id} 尚未下载 PDF"}

    pdf_path = pdf_asset.local_path
    if not __import__("os").path.exists(pdf_path):
        return {"error": f"PDF 文件不存在: {pdf_path}"}

    # 删除旧 chunks
    with get_sync_session() as s:
        deleted = s.query(PaperChunkRow).filter_by(paper_id=paper_id).delete()
        s.commit()

    count = index_paper_chunks(paper_id, pdf_path)
    return {
        "paper_id": paper_id,
        "chunks_deleted": deleted,
        "chunks_created": count,
        "status": "ok",
    }


# ---- 7. 注册工具 ----

ASK_PAPER_SCHEMA = {
    "type": "object",
    "properties": {
        "paper_id": {
            "type": "string",
            "description": "arXiv 论文短 ID（如 '2401.12345'）",
        },
        "question": {
            "type": "string",
            "description": "用户关于该论文的问题（如'这篇论文用了哪些数据集？'）",
        },
        "top_k": {
            "type": "integer",
            "description": "检索的段落数量（1-10）",
            "default": 5,
            "minimum": 1,
            "maximum": 10,
        },
        "force_reindex": {
            "type": "boolean",
            "description": "是否强制重新索引 PDF",
            "default": False,
        },
    },
    "required": ["paper_id", "question"],
}

SUMMARIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "paper_id": {"type": "string", "description": "arXiv 论文短 ID"},
        "focus": {
            "type": "string",
            "description": "摘要关注点",
            "enum": ["general", "method", "experiment", "conclusion", "contribution"],
            "default": "general",
        },
        "max_length": {
            "type": "integer",
            "description": "摘要最大字数",
            "default": 500,
            "minimum": 100,
            "maximum": 2000,
        },
    },
    "required": ["paper_id"],
}

REINDEX_SCHEMA = {
    "type": "object",
    "properties": {
        "paper_id": {"type": "string", "description": "arXiv 论文短 ID"},
    },
    "required": ["paper_id"],
}

registry.register_tool(
    name="ask_paper",
    description=(
        "基于已下载论文 PDF 全文回答用户问题。"
        "自动处理 PDF 解析、段落检索和 LLM 生成，返回答案 + 引用页码。"
        "首次调用时会自动索引 PDF（只需一次）。"
    ),
    parameter_schema=ASK_PAPER_SCHEMA,
    func=ask_paper,
)

registry.register_tool(
    name="summarize_paper",
    description=(
        "对论文 PDF 进行结构化摘要，支持按关注点聚焦："
        "general(全面)/method(方法)/experiment(实验)/conclusion(结论)/contribution(贡献)。"
    ),
    parameter_schema=SUMMARIZE_SCHEMA,
    func=summarize_paper,
)

registry.register_tool(
    name="reindex_paper",
    description="强制重新索引某篇论文的 PDF（删除旧 chunks 并重建，用于 PDF 内容更新后）",
    parameter_schema=REINDEX_SCHEMA,
    func=reindex_paper,
)
