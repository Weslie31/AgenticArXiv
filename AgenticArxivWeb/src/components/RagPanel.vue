<template>
  <div class="rag-page">

    <!-- ========== 左侧：论文选择列表 ========== -->
    <aside class="paper-list">
      <div class="panel-header">
        <div class="panel-title">📚 已下载论文</div>
        <div class="paper-count">{{ pdfPapers.length }} 篇</div>
      </div>

      <div class="paper-search">
        <input
          class="input"
          v-model="searchQ"
          placeholder="搜索标题 / ID..."
        />
      </div>

      <div class="paper-items">
        <!-- 上半：会话论文 -->
        <div v-if="filteredSessionPapers.length > 0" class="paper-group">
          <div class="group-header">
            <span class="group-dot session"></span>
            <span class="group-title">会话论文</span>
            <span class="group-count">{{ filteredSessionPapers.length }}</span>
          </div>
          <div
            v-for="p in filteredSessionPapers"
            :key="`s-${p.paper_id}`"
            class="paper-item"
            :class="{ selected: selectedPaperId === p.paper_id }"
            @click="selectPaper(p.paper_id)"
          >
            <div class="paper-item-title">{{ p.title || p.paper_id }}</div>
            <div class="paper-item-meta">
              <span class="mono">{{ p.paper_id }}</span>
              <span v-if="p.primary_category" class="cat">{{ p.primary_category }}</span>
              <span class="rag-count" v-if="ragHistoryCount(p.paper_id) > 0">
                💬 {{ ragHistoryCount(p.paper_id) }}
              </span>
              <button
                v-if="getPdfUrl(p.paper_id)"
                class="paper-pdf-btn"
                title="打开 PDF 预览"
                @click.stop="openPdf(p.paper_id)"
              >
                📖 PDF
              </button>
            </div>
          </div>
        </div>

        <!-- 下半：订阅论文 -->
        <div v-if="filteredScheduledPapers.length > 0" class="paper-group">
          <div class="group-header">
            <span class="group-dot scheduled"></span>
            <span class="group-title">订阅论文</span>
            <span class="group-count">{{ filteredScheduledPapers.length }}</span>
          </div>
          <div
            v-for="p in filteredScheduledPapers"
            :key="`r-${p.paper_id}`"
            class="paper-item"
            :class="{ selected: selectedPaperId === p.paper_id }"
            @click="selectPaper(p.paper_id)"
          >
            <div class="paper-item-title">{{ p.title || p.paper_id }}</div>
            <div class="paper-item-meta">
              <span class="mono">{{ p.paper_id }}</span>
              <span v-if="p.primary_category" class="cat">{{ p.primary_category }}</span>
              <span class="rag-count" v-if="ragHistoryCount(p.paper_id) > 0">
                💬 {{ ragHistoryCount(p.paper_id) }}
              </span>
              <button
                v-if="getPdfUrl(p.paper_id)"
                class="paper-pdf-btn"
                title="打开 PDF 预览"
                @click.stop="openPdf(p.paper_id)"
              >
                📖 PDF
              </button>
            </div>
          </div>
        </div>

        <div v-if="pdfPapers.length === 0" class="empty-hint">
          <div>暂无已下载论文</div>
          <div class="hint-sub">请先在「论文」页面下载 PDF</div>
        </div>
      </div>
    </aside>

    <!-- ========== 右侧：问答区 ========== -->
    <main class="qa-area">

      <!-- 未选论文时 -->
      <div v-if="!selectedPaperId" class="qa-empty">
        <div class="empty-icon">💬</div>
        <div class="empty-title">选择左侧论文后开始提问</div>
        <div class="empty-sub">
          基于 PDF 全文进行语义问答，支持追问与引用追溯
        </div>
        <div class="empty-tips">
          <div class="tip-title">💡 示例问题</div>
          <div class="tip-item" @click="quickAsk('这篇论文的创新点是什么？')">
            这篇论文的创新点是什么？
          </div>
          <div class="tip-item" @click="quickAsk('实验用了哪些数据集？结果如何？')">
            实验用了哪些数据集？结果如何？
          </div>
          <div class="tip-item" @click="quickAsk('作者的方法和现有方法相比有什么优势？')">
            作者的方法和现有方法相比有什么优势？
          </div>
          <div class="tip-item" @click="quickAsk('论文的局限性有哪些？未来工作是什么？')">
            论文的局限性有哪些？未来工作是什么？
          </div>
        </div>
      </div>

      <!-- 已选论文时 -->
      <template v-else>
        <div class="qa-header">
          <div class="qa-paper-info">
            <div class="qa-paper-title">{{ selectedPaper?.title || selectedPaperId }}</div>
            <div class="qa-paper-meta">
              <span class="mono">{{ selectedPaperId }}</span>
              <span v-if="selectedPaper?.primary_category" class="cat">
                {{ selectedPaper.primary_category }}
              </span>
              <span v-if="selectedPaper?.authors?.length">
                {{ selectedPaper.authors.slice(0, 3).join(", ") }}{{ (selectedPaper.authors?.length || 0) > 3 ? "…" : "" }}
              </span>
            </div>
          </div>
          <div class="qa-header-actions">
            <button class="btn small" @click="doSummarize('general')">📄 摘要</button>
            <button class="btn small" @click="doSummarize('method')">⚙️ 方法</button>
            <button class="btn small" @click="doSummarize('experiment')">📊 实验</button>
          </div>
        </div>

        <!-- tab 切换：问答 / 批注 -->
        <div class="qa-tabs">
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'qa' }"
            @click="activeTab = 'qa'"
          >
            💬 问答
            <span v-if="history.length" class="tab-count">{{ history.length }}</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'annotation' }"
            @click="activeTab = 'annotation'"
          >
            📝 批注
            <span v-if="annotationCount" class="tab-count">{{ annotationCount }}</span>
          </button>
        </div>

        <!-- 提问区 -->
        <div class="qa-input-area">
          <div v-if="pendingSnippet" class="qa-snippet-hint">
            <span class="qa-snippet-icon">📄</span>
            <span class="qa-snippet-text">
              来自 PDF 第 <b>{{ pendingSnippet.page || '?' }}</b> 页选区
            </span>
            <button class="btn small ghost" @click="dismissSnippet">清除</button>
          </div>
          <div class="qa-input-row">
            <input
              ref="questionInput"
              class="input qa-input"
              v-model="questionDraft"
              placeholder="输入问题，例如：本文用了哪些数据集？作者如何处理边界情况？"
              @keyup.enter="submitQuestion"
              :disabled="loading"
            />
            <select class="input qa-focus" v-model="focusDraft">
              <option value="general">general</option>
              <option value="method">method</option>
              <option value="experiment">experiment</option>
              <option value="conclusion">conclusion</option>
              <option value="contribution">contribution</option>
            </select>
            <button
              class="btn primary"
              @click="submitQuestion"
              :disabled="loading || !questionDraft.trim()"
            >
              提问
            </button>
          </div>
        </div>

        <!-- 加载状态 -->
        <div v-if="loading" class="qa-loading">
          <span class="loading-spinner"></span>
          <span v-if="!historyLoaded">正在检索 PDF 全文并生成答案…</span>
          <span v-else>正在生成答案…</span>
          <span class="hint-sub">首次提问约需 3-5 秒建立索引</span>
        </div>

        <!-- 错误提示 -->
        <div v-if="lastError" class="qa-error">
          ❌ {{ lastError }}
          <button class="btn small ghost" @click="lastError = ''">清除</button>
        </div>

        <!-- 问答 tab 内容 -->
        <template v-if="activeTab === 'qa'">
        <!-- 问答历史 -->
        <div v-if="history.length" class="qa-history">
          <div class="qa-history-header">
            <span>💬 问答历史（{{ history.length }} 条）</span>
            <button class="btn small ghost" @click="clearHistory">清空</button>
          </div>

          <div
            v-for="(entry, i) in history"
            :key="i"
            class="qa-entry"
          >
            <div class="qa-q">
              <span class="qa-q-icon">Q</span>
              <span>{{ entry.question }}</span>
            </div>
            <div class="qa-a">
              <span class="qa-a-icon">A</span>
              <span class="qa-a-text">{{ entry.answer }}</span>
            </div>
            <div class="qa-meta">
              <span
                class="conf-tag"
                :class="'conf-' + entry.confidence"
              >
                {{ entry.confidence }}
              </span>
              <span
                v-if="entry.sources?.length"
                class="sources-toggle"
                @click="toggleSources(i)"
              >
                📎 {{ entry.sources.length }} 个引用
                <span>{{ sourcesShown[i] ? "▾" : "▸" }}</span>
              </span>
              <span
                v-if="entry.annotations_used?.length"
                class="annot-toggle"
                @click="toggleAnnots(i)"
              >
                🗒️ 引用了 {{ entry.annotations_used.length }} 条批注
                <span>{{ annotShown[i] ? "▾" : "▸" }}</span>
              </span>
              <span
                class="qa-annot-gen"
                :class="{ disabled: annotSaving[i] }"
                :title="entry.sources?.length ? '把这组问答与引用片段生成批注' : '无引用来源时将以问答作为批注内容'"
                @click="generateAnnotationFromQA(entry, i)"
              >
                <span v-if="annotSaving[i]">⏳ 生成中…</span>
                <span v-else>📌 生成批注</span>
              </span>
              <span class="qa-time">{{ formatTime(entry.asked_at) }}</span>
            </div>

            <!-- 引用来源 -->
            <div v-if="entry.sources?.length && sourcesShown[i]" class="qa-sources">
              <div
                v-for="(src, j) in entry.sources"
                :key="j"
                class="qa-source"
              >
                <div class="qa-source-head">
                  <span class="qa-source-page">
                    第 {{ src.page }} 页
                    <span v-if="src.kind === 'annotation'" class="kind-tag annot">批注</span>
                  </span>
                  <span v-if="src.section" class="qa-source-section">· {{ src.section }}</span>
                  <span class="qa-source-score">score={{ src.score?.toFixed(4) }}</span>
                </div>
                <div class="qa-source-snippet">{{ src.snippet }}</div>
                <div v-if="src.comment" class="qa-source-comment">💬 {{ src.comment }}</div>
              </div>
            </div>

            <!-- 引用的批注（来自 annotations_used） -->
            <div
              v-if="entry.annotations_used?.length && annotShown[i]"
              class="qa-annot-list"
            >
              <div
                v-for="(a, k) in entry.annotations_used"
                :key="k"
                class="qa-annot-card"
              >
                <div class="qa-annot-head">
                  🗒️ 批注 #{{ a.annotation_id }} ·
                  第 {{ a.page_number ?? "?" }} 页 · score={{ a.score?.toFixed(4) }}
                </div>
                <blockquote class="qa-annot-quote">{{ a.snippet }}</blockquote>
                <div class="qa-annot-comment">{{ a.comment }}</div>
              </div>
            </div>
          </div>
        </div>

        <div v-else-if="!loading" class="qa-empty-history">
          <p>输入问题后按回车开始问答。</p>
          <p>同一篇论文可多次追问，历史自动累积。</p>
        </div>
        </template>

        <!-- 批注 tab 内容 -->
        <AnnotationPanel
          v-else-if="activeTab === 'annotation'"
          :paper-id="selectedPaperId"
        />
      </template>

    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useAppStore } from "@/stores/appStore";
import type { RagHistoryEntry } from "@/api/types";
import AnnotationPanel from "@/components/AnnotationPanel.vue";

const store = useAppStore();

// ---------- 论文选择 ----------
const searchQ = ref("");
const selectedPaperId = ref<string>("");

// 从 pdfAssets + session papers + scheduled papers 合并已下载论文列表
// 已下载的论文分两个来源：会话论文（手动检索）和订阅论文（订阅自动加入）
const downloadedIds = computed(() => {
  const ids = new Set<string>();
  for (const a of store.pdfAssets || []) {
    if (a.status === "READY" && a.paper_id) ids.add(a.paper_id);
  }
  return ids;
});

// 已下载 + 来自会话的论文（会话论文可能在某些情况下没有 pdfAssets）
const sessionPapers = computed(() => {
  const ids = downloadedIds.value;
  const seen = new Set<string>();
  const out: any[] = [];
  // 优先用 pdfAssets（已下载的）但仅当它也属于 session.papers
  const sessionIds = new Set((store.papers || []).map((p) => p.id));
  for (const a of store.pdfAssets || []) {
    if (a.status !== "READY" || !a.paper_id) continue;
    if (!sessionIds.has(a.paper_id)) continue;
    seen.add(a.paper_id);
    const meta = (store.papers || []).find((p) => p.id === a.paper_id);
    out.push({
      paper_id: a.paper_id,
      title: meta?.title || a.paper_id,
      primary_category: meta?.primary_category || null,
      authors: meta?.authors || null,
    });
  }
  // 再补上 session papers 中已下载但不在 pdfAssets 中的
  for (const p of store.papers || []) {
    if (seen.has(p.id)) continue;
    if (!ids.has(p.id)) continue; // 只显示已下载的
    seen.add(p.id);
    out.push({
      paper_id: p.id,
      title: p.title || p.id,
      primary_category: p.primary_category || null,
      authors: p.authors || null,
    });
  }
  return out;
});

// 已下载 + 来自订阅的论文
const scheduledPapers = computed(() => {
  const ids = downloadedIds.value;
  const out: any[] = [];
  for (const p of store.scheduledPapers || []) {
    if (!ids.has(p.id)) continue;
    out.push({
      paper_id: p.id,
      title: p.title || p.id,
      primary_category: p.primary_category || null,
      authors: p.authors || null,
    });
  }
  return out;
});

// 兼容旧字段：总已下载论文（用于搜索时跨段匹配）
const pdfPapers = computed(() => [
  ...sessionPapers.value,
  ...scheduledPapers.value,
]);

const filteredSessionPapers = computed(() => filterPapers(sessionPapers.value));
const filteredScheduledPapers = computed(() => filterPapers(scheduledPapers.value));

function filterPapers(papers: any[]) {
  const kw = searchQ.value.trim().toLowerCase();
  if (!kw) return papers;
  return papers.filter((p) => {
    return (
      p.paper_id.toLowerCase().includes(kw) ||
      (p.title || "").toLowerCase().includes(kw)
    );
  });
}

const filteredPdfPapers = computed(() => [
  ...filteredSessionPapers.value,
  ...filteredScheduledPapers.value,
]);

const selectedPaper = computed(() =>
  store.papers.find((p) => p.id === selectedPaperId.value) || null
);

// ---------- 问答 ----------
const questionDraft = ref("");
const focusDraft = ref<"general" | "method" | "experiment" | "conclusion" | "contribution">("general");
const loading = ref(false);
const lastError = ref("");
const sourcesShown = ref<Record<number, boolean>>({});
const annotShown = ref<Record<number, boolean>>({});
const annotSaving = ref<Record<number, boolean>>({});
const annotCreated = ref<Record<number, number>>({});
const historyLoaded = ref(false);
const activeTab = ref<"qa" | "annotation">("qa");
const questionInput = ref<HTMLInputElement | null>(null);

// 来自 PDF 选区的元信息（页码 + 片段），用作提示
const pendingSnippet = ref<{ page?: number; snippet?: string } | null>(null);

watch(
  () => (store as any)._ragPendingQuestionMeta as { page?: number; snippet?: string } | null,
  (meta) => {
    pendingSnippet.value = meta ? { ...meta } : null;
  }
);

function dismissSnippet() {
  pendingSnippet.value = null;
  (store as any)._ragPendingQuestionMeta = null;
}

const history = computed((): RagHistoryEntry[] =>
  selectedPaperId.value ? store.ragHistoryFor(selectedPaperId.value) : []
);

const annotationCount = computed(() =>
  selectedPaperId.value ? store.annotationsFor(selectedPaperId.value).length : 0
);

function ragHistoryCount(paperId: string) {
  return store.ragHistoryFor(paperId).length;
}

function getPdfUrl(paperId: string): string | null {
  const asset = store.pdfMap?.get?.(paperId);
  // 优先用本地代理：避免走 arxiv.org 远端（速度慢、可能失败）
  // 后端 /api/pdf/view/raw 会自动选用本地原始 PDF；STALE 时会 on-demand 重下
  if (asset && (asset.status === "READY" || asset.status === "STALE")) {
    return `/api/pdf/view/raw/${encodeURIComponent(paperId)}`;
  }
  // 退而求其次：如果论文 meta 上有 pdf_url（远端），仅作兜底
  const meta = (store.papers || []).find((p) => p.id === paperId);
  return meta?.pdf_url || null;
}

function openPdf(paperId: string) {
  const url = getPdfUrl(paperId);
  if (!url) return;
  const meta = (store.papers || []).find((p) => p.id === paperId);
  // 把翻译 PDF URL 与"是否已翻译"透传给 viewer：未翻译时 viewer 自动隐藏切换控件
  const translateAsset = store.translateMap?.get?.(paperId);
  const hasTranslated =
    !!translateAsset &&
    (translateAsset.status || "").toUpperCase() === "READY" &&
    !!(translateAsset.output_mono_path || translateAsset.output_dual_path);
  const translatedUrl = hasTranslated
    ? store.getTranslatedPdfViewUrl(paperId, "mono")
    : undefined;
  store.openPdfViewer({
    paperId,
    url,
    title: meta?.title || paperId,
    translatedUrl,
    hasTranslated,
  });
}

function selectPaper(paperId: string) {
  selectedPaperId.value = paperId;
  questionDraft.value = "";
  lastError.value = "";
  historyLoaded.value = history.value.length > 0;
  activeTab.value = "qa";
  nextTick(() => questionInput.value?.focus());
}

function toggleSources(idx: number) {
  sourcesShown.value[idx] = !sourcesShown.value[idx];
}

function toggleAnnots(idx: number) {
  annotShown.value[idx] = !annotShown.value[idx];
}

function clearHistory() {
  if (selectedPaperId.value) {
    store.clearRagHistory(selectedPaperId.value);
  }
}

/**
 * 把后端 rag 来源里的 page 字段规整成「整数 | null」。
 * 支持：number、string number、"9-9"（取首位）、null/undefined → null。
 * 不可解析时返回 null 而不抛错，避免触发 pydantic 422。
 */
function parsePageNumber(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return Math.trunc(raw);
  }
  if (typeof raw === "string") {
    // 形如 "9-9"、"9-10"：取首位整数
    const m = raw.match(/(\d+)/);
    const numStr = m?.[1];
    if (numStr) {
      const n = parseInt(numStr, 10);
      return Number.isFinite(n) ? n : null;
    }
  }
  return null;
}

/**
 * 把当前问答条目生成一条批注，写入后端数据库，并自动切到批注 tab 让用户看到。
 *
 * 字段映射规则：
 *  - highlighted_text（原文片段）：优先取 sources 中分数最高的非批注来源的前 400 字；
 *    若没有任何来源，则用 question 本身兜底；
 *    若是"摘要"类型（question 以 [摘要 开头）则用 answer 的前 400 字。
 *  - comment（评论）：使用 answer，并在开头拼接 question 作为上下文；
 *    截断到 4000 字避免超出后端 max_length 限制。
 *  - page_number：取第一个来源的页码；无来源时为 null。
 */
async function generateAnnotationFromQA(entry: RagHistoryEntry, idx: number) {
  if (!selectedPaperId.value) return;
  if (annotSaving.value[idx]) return; // 防止重复点击
  annotSaving.value[idx] = true;
  try {
    const question = entry.question || "";
    const answer = entry.answer || "";
    const sources = entry.sources || [];

    let highlighted = "";
    let page: number | null = null;
    if (sources.length > 0) {
      // 找第一条"有用的"原文片段：跳过参考文献条目（常见特征：带编号 "12. " 开头、
      // "et al."、"——" 等明显是引用而非正文），改用下一条更相关的正文来源。
      for (const src of sources) {
        const snip = (src.snippet || "").trim();
        if (
          // 参考文献编号开头，如 "12. Jha" / "[1] Smith"
          /^\[?\d+[\].]?\s+[A-Z]/.test(snip) ||
          // 作者列表含 "et al." 格式
          /\bet al\b/i.test(snip) ||
          // 年份格式 (2021) 或 (2020) 在段首
          /^\s*\(?\d{4}\)?\s/.test(snip)
        ) {
          continue; // 跳过参考文献条目，找下一条
        }
        // 找到第一段正文片段
        page = parsePageNumber(src.page);
        highlighted = snip;
        break;
      }
    }
    if (!highlighted) {
      // 兜底：摘要类条目没有 sources，直接用答案前 400 字
      highlighted = question.startsWith("[摘要")
        ? answer.slice(0, 400)
        : question.slice(0, 400);
    }
    highlighted = highlighted.slice(0, 800);

    // 评论：带上"Q/A"上下文
    const comment = `Q: ${question}\n\nA: ${answer}`.slice(0, 4000);

    const created = await store.createAnnotation({
      paper_id: selectedPaperId.value,
      session_id: store.sessionId,
      page_number: page,
      highlighted_text: highlighted,
      comment,
    });

    annotCreated.value[idx] = created.id;
    // 自动切到批注 tab，让用户立刻看到这条新批注
    activeTab.value = "annotation";
    // 兜底刷新一次（store.createAnnotation 内部通常已写本地缓存，这里保险）
    if (typeof store.fetchAnnotations === "function") {
      try { await store.fetchAnnotations(selectedPaperId.value); } catch { /* 忽略 */ }
    }
  } catch (e: any) {
    // 防御式：store 可能抛出 Error 实例、AxiosError、字符串、对象；统一序列化
    console.error("[generateAnnotation] failed:", e);
    let msg = "";
    if (typeof e === "string") {
      msg = e;
    } else if (e?.response?.data?.detail) {
      msg = typeof e.response.data.detail === "string"
        ? e.response.data.detail
        : JSON.stringify(e.response.data.detail);
    } else if (e?.message) {
      msg = e.message;
    } else {
      try { msg = JSON.stringify(e); } catch { msg = String(e); }
    }
    lastError.value = `生成批注失败: ${msg || "未知错误"}`;
  } finally {
    annotSaving.value[idx] = false;
  }
}

async function submitQuestion() {
  const q = questionDraft.value.trim();
  if (!q || !selectedPaperId.value) return;
  lastError.value = "";
  historyLoaded.value = history.value.length > 0;
  loading.value = true;
  // 若问题来自 PDF 选区，把选中文本与页码作为顶级 context 一起发给后端
  const meta = pendingSnippet.value;
  const extra = meta && meta.snippet
    ? { selectedText: meta.snippet, selectedPage: meta.page }
    : undefined;
  try {
    await store.ragAsk(selectedPaperId.value, q, 8, extra);
    questionDraft.value = "";
    pendingSnippet.value = null;
    (store as any)._ragPendingQuestionMeta = null;
    historyLoaded.value = true;
  } catch (e: any) {
    lastError.value = e?.message || String(e);
  } finally {
    loading.value = false;
  }
}

async function doSummarize(focus: string) {
  if (!selectedPaperId.value) return;
  lastError.value = "";
  loading.value = true;
  try {
    const resp = await store.ragSummarize(
      selectedPaperId.value,
      focus as "general" | "method" | "experiment" | "conclusion" | "contribution",
      1000,
    );
    // 把摘要追加到历史
    const summaryEntry: RagHistoryEntry = {
      question: `[摘要 · focus=${resp.focus}]`,
      answer: resp.summary,
      confidence: "high",
      sources: [],
      asked_at: new Date().toISOString(),
    };
    if (!store.ragHistoryByPaper[selectedPaperId.value]) {
      store.ragHistoryByPaper[selectedPaperId.value] = [];
    }
    store.ragHistoryByPaper[selectedPaperId.value]!.unshift(summaryEntry);
  } catch (e: any) {
    lastError.value = e?.message || String(e);
  } finally {
    loading.value = false;
  }
}

function quickAsk(q: string) {
  if (!selectedPaperId.value) {
    // 提示用户先选论文
    lastError.value = "请先在左侧选择一篇论文";
    return;
  }
  questionDraft.value = q;
  submitQuestion();
}

function formatTime(iso?: string | null) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// 外部可通过 store.goToRagPage(paperId) 自动跳转并选中论文
// KeepAlive 保持组件存活，所以用 watch 而非 onMounted
watch(
  () => (store as any)._ragPendingPaperId as string | null,
  (newId) => {
    if (newId) {
      selectPaper(newId);
      (store as any)._ragPendingPaperId = null;
    }
  }
);

// 从 PDF 选区带入的初始问题：自动填入并提交
watch(
  () => (store as any)._ragPendingQuestion as string | null,
  async (newQ) => {
    if (!newQ) return;
    if (!selectedPaperId.value) {
      // 理论上 _ragPendingPaperId 已经先触发了 selectPaper；保险起见再等一拍
      await nextTick();
    }
    questionDraft.value = newQ;
    store.clearRagPendingQuestion();
    // 等待 vue 完成渲染再提交，避免拿到旧 selectedPaperId
    await nextTick();
    submitQuestion();
  }
);
</script>

<style scoped>
.rag-page {
  display: flex;
  height: calc(100vh - 36px);
  gap: 12px;
  min-height: 0;
}

/* ===== 左侧论文列表 ===== */
.paper-list {
  width: 300px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: rgba(255,255,255,0.02);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 8px;
  border-bottom: 1px solid var(--border);
}

.panel-title {
  font-weight: 700;
  font-size: 14px;
}

.paper-count {
  font-size: 12px;
  color: var(--muted);
  background: rgba(255,255,255,0.05);
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
}

.paper-search {
  padding: 8px 10px;
}

.paper-items {
  flex: 1;
  overflow-y: auto;
  padding: 4px 6px 8px;
}

.paper-group {
  margin-bottom: 10px;
}

.paper-group:last-child {
  margin-bottom: 0;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px 4px;
  font-size: 11px;
  color: var(--muted);
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
}

.group-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.group-dot.session {
  background: #599fff;
  box-shadow: 0 0 6px rgba(89, 153, 255, 0.5);
}

.group-dot.scheduled {
  background: #50dcc8;
  box-shadow: 0 0 6px rgba(80, 220, 200, 0.5);
}

.group-title {
  flex: 1;
  font-size: 11px;
}

.group-count {
  font-size: 10px;
  color: var(--muted);
  background: rgba(255,255,255,0.04);
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid var(--border);
  font-weight: 500;
}

.paper-item {
  padding: 8px 10px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
  margin-bottom: 4px;
}

.paper-item:hover {
  background: rgba(255,255,255,0.04);
}

.paper-item.selected {
  background: rgba(80, 220, 200, 0.1);
  border-color: rgba(80, 220, 200, 0.35);
}

.paper-item-title {
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
  margin-bottom: 3px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.paper-item-meta {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--muted);
}

.paper-item-meta .mono { font-size: 10px; }

.cat {
  color: var(--accent, #79c0ff);
  font-size: 10px;
}

.rag-count {
  color: #50dcc8;
  font-size: 10px;
  font-weight: 600;
}

.paper-pdf-btn {
  appearance: none;
  border: 1px solid var(--border);
  background: rgba(89, 153, 255, 0.12);
  color: #599fff;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  margin-left: auto;
}

.paper-pdf-btn:hover {
  background: rgba(89, 153, 255, 0.22);
  border-color: rgba(89, 153, 255, 0.5);
}

.empty-hint {
  padding: 20px 12px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
}

.hint-sub {
  font-size: 11px;
  margin-top: 4px;
  opacity: 0.7;
}

/* ===== 右侧问答区 ===== */
.qa-area {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: rgba(255,255,255,0.02);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.qa-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
}

.empty-icon { font-size: 48px; }
.empty-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--fg);
}
.empty-sub {
  font-size: 13px;
  color: var(--muted);
  text-align: center;
  max-width: 400px;
}

.empty-tips {
  margin-top: 20px;
  width: 100%;
  max-width: 520px;
}
.tip-title {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 8px;
  font-weight: 600;
}
.tip-item {
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  background: rgba(255,255,255,0.02);
  color: var(--fg);
}
.tip-item:hover {
  background: rgba(80, 220, 200, 0.1);
  border-color: rgba(80, 220, 200, 0.4);
  color: #50dcc8;
}

.qa-header {
  padding: 12px 16px 10px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.qa-paper-info { flex: 1; min-width: 0; }

.qa-paper-title {
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 4px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.qa-paper-meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--muted);
  flex-wrap: wrap;
  align-items: center;
}

.qa-paper-meta .mono { font-size: 10px; }
.qa-paper-meta .cat {
  color: var(--accent, #79c0ff);
  font-size: 10px;
}

.qa-header-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.qa-input-area {
  padding: 12px 14px 8px;
  border-bottom: 1px solid var(--border);
}

.qa-snippet-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  margin-bottom: 8px;
  background: rgba(80, 220, 200, 0.08);
  border: 1px solid rgba(80, 220, 200, 0.3);
  border-radius: 8px;
  font-size: 12px;
  color: var(--fg, #ccc);
}

.qa-snippet-icon { font-size: 13px; }
.qa-snippet-text { flex: 1; }

.qa-input-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.qa-input {
  flex: 1;
  min-width: 260px;
  height: 36px;
}

.qa-focus {
  width: 130px;
  height: 36px;
}

.qa-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 13px;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}

.qa-error {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  font-size: 13px;
  color: #ff6b6b;
  background: rgba(255,107,107,0.08);
  border-bottom: 1px solid rgba(255,107,107,0.2);
}

.qa-history {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
}

.qa-history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--muted);
}

.qa-entry {
  background: rgba(255,255,255,0.025);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
  margin-bottom: 14px;
}

.qa-q {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.qa-q-icon {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(80, 220, 200, 0.2);
  color: #50dcc8;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.qa-a {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 13px;
  line-height: 1.7;
  margin-bottom: 8px;
}

.qa-a-icon {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(89, 153, 255, 0.2);
  color: #599fff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.qa-a-text {
  white-space: pre-wrap;
  word-break: break-word;
  flex: 1;
}

.qa-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 11px;
  color: var(--muted);
  flex-wrap: wrap;
}

.conf-tag {
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid var(--border);
}
.conf-high   { color: #5be7a4; border-color: rgba(91,231,164,.5); }
.conf-medium { color: #f0c674; border-color: rgba(240,198,116,.5); }
.conf-low    { color: #ff8a8a; border-color: rgba(255,138,138,.5); }

.sources-toggle {
  cursor: pointer;
  user-select: none;
}
.sources-toggle:hover { color: #50dcc8; }

.qa-time { margin-left: auto; }

.qa-sources {
  margin-top: 10px;
  border-left: 2px solid rgba(80, 220, 200, 0.4);
  padding-left: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.qa-source {
  background: rgba(0,0,0,0.2);
  border-radius: 8px;
  padding: 7px 10px;
}

.qa-source-head {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 4px;
  align-items: center;
}

.qa-source-page { color: #50dcc8; font-weight: 700; }
.qa-source-score { margin-left: auto; opacity: 0.7; }

.qa-source-snippet {
  font-size: 12px;
  line-height: 1.5;
  color: var(--fg);
  opacity: 0.88;
  white-space: pre-wrap;
  word-break: break-word;
}

.qa-empty-history {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--muted);
  font-size: 13px;
}

.loading-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(80, 220, 200, 0.3);
  border-top-color: #50dcc8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ===== 通用 ===== */
.input {
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg2);
  color: var(--fg);
  font-size: 13px;
}

.btn {
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,0.04);
  color: var(--fg);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
  white-space: nowrap;
}

.btn:hover:not(:disabled) {
  background: rgba(255,255,255,0.08);
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn.primary {
  background: rgba(80, 220, 200, 0.15);
  border-color: rgba(80, 220, 200, 0.5);
  color: #50dcc8;
}

.btn.primary:hover:not(:disabled) {
  background: rgba(80, 220, 200, 0.25);
}

.btn.small {
  height: 26px;
  padding: 0 10px;
  font-size: 12px;
}

.btn.ghost {
  background: transparent;
}

.btn.ghost:hover:not(:disabled) {
  background: rgba(255,255,255,0.06);
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

/* ===== tab 切换 ===== */
.qa-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border, #2a2a2a);
  padding: 0 4px;
}
.tab-btn {
  background: transparent;
  border: none;
  color: var(--muted, #888);
  padding: 8px 14px;
  cursor: pointer;
  font-size: 13px;
  border-bottom: 2px solid transparent;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.tab-btn.active {
  color: var(--fg, #eee);
  border-bottom-color: var(--accent, #3a8ee6);
}
.tab-count {
  background: rgba(58, 142, 230, 0.2);
  color: var(--accent, #3a8ee6);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
}

/* ===== entry 内 annotation 引用块 ===== */
.annot-toggle {
  cursor: pointer;
  color: var(--accent, #3a8ee6);
  font-size: 12px;
  user-select: none;
}

.qa-annot-gen {
  cursor: pointer;
  color: #50dcc8;
  font-size: 12px;
  user-select: none;
  padding: 1px 6px;
  border-radius: 6px;
  border: 1px solid rgba(80, 220, 200, 0.35);
  background: rgba(80, 220, 200, 0.08);
  transition: all 0.15s;
}
.qa-annot-gen:hover:not(.disabled) {
  background: rgba(80, 220, 200, 0.18);
  border-color: rgba(80, 220, 200, 0.6);
}
.qa-annot-gen.disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.qa-annot-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.qa-annot-card {
  border: 1px solid rgba(58, 142, 230, 0.4);
  background: rgba(58, 142, 230, 0.05);
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
}
.qa-annot-head {
  color: var(--accent, #3a8ee6);
  font-weight: 600;
  margin-bottom: 4px;
}
.qa-annot-quote {
  margin: 4px 0;
  padding: 4px 8px;
  border-left: 2px solid var(--accent, #3a8ee6);
  font-style: italic;
  color: var(--fg, #ddd);
  white-space: pre-wrap;
  word-break: break-word;
}
.qa-annot-comment {
  color: var(--fg, #ddd);
  white-space: pre-wrap;
  word-break: break-word;
}
.qa-source-comment {
  margin-top: 4px;
  color: var(--muted, #aaa);
  font-size: 12px;
}
.kind-tag {
  margin-left: 6px;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(255,255,255,0.08);
  color: var(--muted, #aaa);
}
.kind-tag.annot {
  background: rgba(58, 142, 230, 0.2);
  color: var(--accent, #3a8ee6);
}

@media (max-width: 768px) {
  .rag-page { flex-direction: column; }
  .paper-list { width: 100%; height: 200px; }
  .qa-area { flex: 1; }
}
</style>
