<template>
  <section class="papers">
    <header class="card-header">
      <div class="title">会话论文</div>

      <div class="row">
        <input class="input" v-model="q" placeholder="搜索标题/作者/arxiv id…" />
        <button class="btn" @click="store.refreshSnapshot()" :disabled="store.loading">刷新</button>
      </div>

      <!-- 批量操作工具条：选中后才显示 -->
      <div class="bulk-bar" v-if="filtered.length">
        <label class="bulk-check" :title="allSelected ? '取消全选' : '全选当前列表'">
          <input
            type="checkbox"
            :checked="allSelected"
            :indeterminate.prop="someSelected && !allSelected"
            @change="toggleSelectAll"
          />
          <span class="bulk-check-label">
            {{ allSelected ? "取消全选" : "全选" }}
          </span>
        </label>
        <span class="bulk-count">
          已选 <b>{{ selected.size }}</b> / {{ filtered.length }} 篇
        </span>
        <button
          class="btn small danger"
          :disabled="!selected.size || bulkDeleting"
          @click="confirmBulkDelete"
        >
          {{ bulkDeleting ? "删除中…" : `🗑 删除选中 (${selected.size})` }}
        </button>
        <button
          v-if="selected.size"
          class="btn small ghost"
          @click="clearSelection"
        >清空选择</button>
      </div>

      <p class="muted">
        共 {{ filtered.length }} 篇（显示编号 1..N，便于“下载第2篇/翻译第3篇”）
      </p>
    </header>

    <!-- 独立滚动区域：只滚表格，不滚整个右侧页面 -->
    <div class="table-scroll" v-if="filtered.length">
      <table class="table">
        <thead>
          <tr>
            <th class="col-idx">#</th>
            <th class="col-check">
              <input
                type="checkbox"
                :checked="allSelected"
                :indeterminate.prop="someSelected && !allSelected"
                @change="toggleSelectAll"
                :title="allSelected ? '取消全选' : '全选'"
              />
            </th>
            <th>标题</th>
            <th class="col-auth">作者</th>
            <th class="col-time">时间</th>
            <th class="col-flag">下载</th>
            <th class="col-flag">翻译</th>
            <th class="col-flag">总结</th>
            <th class="col-flag">RAG</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>

        <tbody>
          <template v-for="p in filtered" :key="p.id">
            <tr :class="{ 'row-selected': selected.has(p.id) }">
              <td class="mono col-idx">{{ indexOf(p.id) }}</td>
              <td class="col-check">
                <input
                  type="checkbox"
                  :checked="selected.has(p.id)"
                  @change="toggleSelect(p.id)"
                  :title="selected.has(p.id) ? '取消选中' : '选中'"
                />
              </td>

              <td>
                <div class="p-title">
                  {{ p.title }}
                  <span
                    v-if="p.fetch_type === 'subscription'"
                    class="subs-tag"
                    title="该论文来自定时订阅"
                  >📬 订阅</span>
                  <span
                    v-if="pdfStatusText(p.id) === 'FAILED'"
                    class="download-failed-tag"
                    :title="pdfDownloadError(p.id) || '下载失败，请前往论文详情页手动下载'"
                    @click.stop="copyPaperLink(p)"
                    role="button"
                  >⚠️ 无法下载</span>
                  <span
                    v-else-if="pdfStatusText(p.id) === 'STALE'"
                    class="download-stale-tag"
                    :title="pdfDownloadError(p.id) || '本地 PDF 文件丢失，点击重新下载即可恢复'"
                    role="status"
                  >🟡 本地文件丢失</span>
                </div>
                <div class="sub mono">
                  <a v-if="paperIdHref(p.id)"
                     :href="paperIdHref(p.id)"
                     target="_blank"
                     rel="noreferrer"
                     class="paper-id-link"
                     :title="'打开论文详情页：' + paperIdHref(p.id)">
                    {{ p.id }}
                  </a>
                  <span v-else>{{ p.id }}</span>
                  <span v-if="p.primary_category" class="primary-cat">{{ p.primary_category }}</span>
                  <span
                    v-if="p.categories && p.categories.length > 1"
                    class="all-cats"
                    :title="'所有分类: ' + p.categories.join(', ')"
                  >+{{ p.categories.length - 1 }}</span>
                </div>
                <div class="sub" v-if="p.comment">注释：{{ p.comment }}</div>

                <div class="sub" v-if="p.pdf_url">
                  PDF：
                  <a :href="normalizePdf(p.pdf_url)" target="_blank" rel="noreferrer">
                    {{ normalizePdf(p.pdf_url) }}
                  </a>
                </div>

                <div class="sub" v-if="p.paper_url">
                  <a :href="p.paper_url" target="_blank" rel="noreferrer" class="paper-link" title="打开论文详情页">
                    📄 论文详情页
                  </a>
                </div>

                <!-- ⭐ 收藏 + 🏷️ tag 操作行 -->
                <div class="bk-row">
                  <button
                    class="bk-star-btn"
                    :class="{ active: isBookmarked(p.id) }"
                    :title="isBookmarked(p.id) ? '已收藏（点击取消收藏）' : '收藏到我的收藏夹'"
                    @click="toggleBookmark(p.id)"
                  >{{ isBookmarked(p.id) ? '★' : '☆' }}</button>
                  <button
                    class="bk-tag-btn"
                    :title="paperTags(p.id).length ? '查看/编辑 tag' : '为这篇论文添加 tag'"
                    @click="openTagInput(p.id)"
                  >🏷️ {{ paperTags(p.id).length || '+ tag' }}</button>
                  <span
                    v-for="t in paperTags(p.id).slice(0, 3)"
                    :key="t"
                    class="bk-tag-chip"
                    :title="'#' + t"
                  >#{{ t }}</span>
                  <input
                    v-if="tagInputOpenFor === p.id"
                    :ref="(el) => (tagInputEls[p.id] = el as HTMLInputElement | null)"
                    class="bk-tag-input-inline"
                    v-model="tagDrafts[p.id]"
                    placeholder="新 tag，回车确认"
                    @keydown.enter.prevent="confirmAddTag(p.id)"
                    @keydown.esc="cancelTagInput(p.id)"
                    @blur="confirmAddTag(p.id)"
                  />
                </div>
              </td>

              <td class="col-auth">
                <div class="sub">
                  {{ (p.authors || []).slice(0, 6).join(", ") }}
                  <span v-if="(p.authors || []).length > 6">…</span>
                </div>
              </td>

              <td class="sub col-time">
                <div>pub: {{ p.published || "-" }}</div>
                <div>upd: {{ p.updated || "-" }}</div>
                <div class="fetched-at" :title="p.fetched_at || ''">
                  检索: {{ formatTime(p.fetched_at) || "-" }}
                </div>
              </td>

              <!-- ✅/🟡/❌：READY=✅，STALE=🟡（文件丢失，可重下），其他一律❌ -->
              <td class="col-flag">
                <span
                  class="flag"
                  :class="pdfReady(p.id) ? 'ok' : pdfStatusText(p.id) === 'STALE' ? 'warn' : 'bad'"
                  :title="'PDF: ' + pdfStatusText(p.id)"
                >
                  {{ pdfReady(p.id) ? "✅" : pdfStatusText(p.id) === 'STALE' ? "🟡" : "❌" }}
                </span>
              </td>

              <td class="col-flag">
                <span
                  class="flag"
                  :class="trReady(p.id) ? 'ok' : trStatusText(p.id) === 'STALE' ? 'warn' : 'bad'"
                  :title="'Translate: ' + trStatusText(p.id)"
                >
                  {{ trReady(p.id) ? "✅" : trStatusText(p.id) === 'STALE' ? "🟡" : "❌" }}
                </span>
              </td>

              <td class="col-flag">
                <span
                  class="flag"
                  :class="summaryReady(p.id) ? 'ok' : summaryRunning(p.id) ? 'running' : 'bad'"
                  :title="'Summary: ' + summaryStatusText(p.id)"
                >
                  {{ summaryReady(p.id) ? "✅" : summaryRunning(p.id) ? "..." : "❌" }}
                </span>
              </td>

              <td class="col-flag">
                <span
                  class="flag clickable"
                  :class="ragReady(p.id) ? 'ok' : 'bad'"
                  :title="pdfReady(p.id) ? 'RAG 问答（跳转）' : '请先下载 PDF'"
                  @click="pdfReady(p.id) && store.goToRagPage(p.id)"
                  :style="pdfReady(p.id) ? 'cursor: pointer' : 'cursor: default'"
                >
                  {{ ragReady(p.id) ? "✅" : pdfReady(p.id) ? "❓" : "—" }}
                </span>
              </td>

              <td class="col-op">
                <div class="ops">
                  <!-- 下载 -->
                  <button
                    class="btn icon"
                    :title="pdfReady(p.id) ? '下载 PDF（覆盖/更新缓存）' : '下载 PDF'"
                    aria-label="下载 PDF"
                    @click="store.downloadPaper(indexOf(p.id))"
                    :disabled="store.loading"
                  >
                    <!-- download icon -->
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <path d="M12 3v10"></path>
                      <path d="M8 9l4 4 4-4"></path>
                      <path d="M4 20h16"></path>
                      <path d="M6 20v-4"></path>
                      <path d="M18 20v-4"></path>
                    </svg>
                  </button>

                  <!-- 上传本地 PDF -->
                  <button
                    class="btn icon upload-btn"
                    :title="pdfReady(p.id) ? '上传本地 PDF 覆盖' : '上传本地 PDF'"
                    aria-label="上传本地 PDF"
                    @click="triggerUpload(p.id)"
                    :disabled="store.loading"
                  >
                    <!-- upload icon -->
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                      <polyline points="17 8 12 3 7 8"></polyline>
                      <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                  </button>

                  <!-- 翻译 -->
                  <button
                    class="btn primary icon"
                    :title="trReady(p.id) ? '重新翻译（更新翻译缓存）' : '翻译 PDF'"
                    aria-label="翻译 PDF"
                    @click="store.translatePaper(indexOf(p.id))"
                    :disabled="store.loading"
                  >
                    <!-- translate icon -->
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <path d="M16 4l4 4-4 4"></path>
                      <path d="M20 8H4"></path>
                      <path d="M8 20l-4-4 4-4"></path>
                      <path d="M4 16h16"></path>
                    </svg>
                  </button>

                  <!-- 查看翻译后论文 -->
                  <button
                    class="btn icon"
                    :title="trReady(p.id) ? '查看翻译后论文（新标签页打开）' : '请先翻译 PDF'"
                    aria-label="查看翻译后论文"
                    @click="store.openTranslatedPdf(p.id, 'mono')"
                    :disabled="!trReady(p.id)"
                  >
                    <!-- external-link icon -->
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <path d="M14 4h6v6"></path>
                      <path d="M10 14L20 4"></path>
                      <path d="M19 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h6"></path>
                    </svg>
                  </button>

                  <!-- 预览 -->
                  <button
                    class="btn icon"
                    :title="pdfReady(p.id) ? '预览原文' : pdfAccessible(p.id) ? '本地文件丢失，点击重下并预览' : '请先下载 PDF'"
                    aria-label="预览 PDF"
                    @click="openPreview(p)"
                    :disabled="!pdfAccessible(p.id) && !trAccessible(p.id)"
                  >
                    <!-- eye icon -->
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                      <circle cx="12" cy="12" r="3"></circle>
                    </svg>
                  </button>

                  <!-- 总结 -->
                  <button
                    class="btn icon summary-btn"
                    :title="pdfReady(p.id) ? '总结论文（背景+创新点）' : '请先下载 PDF'"
                    aria-label="总结论文"
                    @click="toggleSummary(indexOf(p.id), p.id)"
                    :disabled="!pdfReady(p.id) || store.loading"
                  >
                    <!-- sparkles icon -->
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z"></path>
                      <path d="M5 19l1 2 2-1-1-2-2 1z"></path>
                      <path d="M19 5l1 2 2-1-1-2-2 1z"></path>
                    </svg>
                  </button>

                  <!-- RAG 提问 -->
                  <button
                    class="btn icon rag-btn"
                    :title="pdfReady(p.id) ? '基于 PDF 全文问答（RAG）' : '请先下载 PDF'"
                    aria-label="RAG 提问"
                    @click="store.goToRagPage(p.id)"
                    :disabled="!pdfReady(p.id)"
                  >
                    <!-- chat-bubble icon -->
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                  </button>

                  <!-- 🗑 单删 -->
                  <button
                    class="btn icon danger"
                    title="从会话论文列表中删除这篇（不影响缓存/翻译/总结）"
                    aria-label="删除论文"
                    @click="confirmDeleteOne(p)"
                    :disabled="deletingId === p.id"
                  >
                    <!-- trash icon -->
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="3 6 5 6 21 6"></polyline>
                      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
                      <path d="M10 11v6"></path>
                      <path d="M14 11v6"></path>
                      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"></path>
                    </svg>
                  </button>
                </div>

                <!-- 隐藏的上传 input（每行一个） -->
                <input
                  type="file"
                  accept="application/pdf,.pdf"
                  :ref="(el) => registerUploadInput(p.id, el)"
                  style="display: none"
                  @change="handleUploadFile(p.id, $event)"
                />

              </td>
            </tr>

            <!-- 总结展示行：仅当展开时显示 -->
            <tr v-if="expandedSummaryIndex === indexOf(p.id)" class="summary-row">
              <td colspan="8" class="summary-cell">
                <div class="summary-card">
                  <div class="summary-header">
                    <strong>📄 论文总结</strong>
                    <button
                      v-if="!summaryRunning(p.id)"
                      class="btn small"
                      @click="store.summarizePaper(indexOf(p.id))"
                      :disabled="store.loading"
                    >
                      {{ summaryReady(p.id) ? '重新总结' : '开始总结' }}
                    </button>
                    <button class="btn small ghost" @click="expandedSummaryIndex = -1">收起</button>
                  </div>

                  <div v-if="summaryRunning(p.id)" class="summary-loading">
                    <span class="loading-spinner"></span>
                    AI 正在分析论文内容，请稍候...
                  </div>

                  <div v-else-if="summaryReady(p.id)" class="summary-content">
                    <div class="summary-section" v-if="summaryFor(p.id)?.background">
                      <div class="summary-label">🔍 研究背景</div>
                      <div class="summary-text">{{ summaryFor(p.id)?.background }}</div>
                    </div>
                    <div class="summary-section" v-if="summaryFor(p.id)?.innovation">
                      <div class="summary-label">💡 主要创新点</div>
                      <div class="summary-text innovation-text">{{ summaryFor(p.id)?.innovation }}</div>
                    </div>
                    <div class="summary-meta" v-if="summaryFor(p.id)?.summarized_at">
                      总结时间：{{ formatTime(summaryFor(p.id)?.summarized_at) }}
                    </div>
                  </div>

                  <div v-else-if="summaryFor(p.id)?.status === 'FAILED'" class="summary-error">
                    ❌ 总结失败：{{ summaryFor(p.id)?.error || '未知错误' }}
                  </div>

                  <div v-else class="summary-empty">
                    <p>点击「开始总结」按钮，AI 将分析论文的背景与创新点</p>
                  </div>
                </div>
              </td>
            </tr>

          </template>
        </tbody>
      </table>
    </div>

    <div class="empty" v-else>
      暂无论文（通过对话检索论文后会在此显示）
    </div>

</section>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onMounted, ref, watch } from "vue";
import { useAppStore } from "@/stores/appStore";

const store = useAppStore();
const q = ref("");
// 当前展开的总结索引（-1 表示无）
const expandedSummaryIndex = ref<number>(-1);

// ========== 单删 / 批量删除 ==========
const selected = ref<Set<string>>(new Set());
const deletingId = ref<string | null>(null);
const bulkDeleting = ref(false);

const allSelected = computed(
  () => !!filtered.value.length && selected.value.size === filtered.value.length
);
const someSelected = computed(
  () => selected.value.size > 0 && selected.value.size < filtered.value.length
);

function toggleSelect(paperId: string) {
  const next = new Set(selected.value);
  if (next.has(paperId)) next.delete(paperId);
  else next.add(paperId);
  selected.value = next;
}

function toggleSelectAll() {
  if (allSelected.value) {
    selected.value = new Set();
  } else {
    selected.value = new Set(filtered.value.map((p) => p.id));
  }
}

function clearSelection() {
  selected.value = new Set();
}

function shortTitle(p: any, max = 32): string {
  const t = (p?.title || "").replace(/\s+/g, " ").trim();
  return t.length > max ? t.slice(0, max) + "…" : t;
}

async function confirmDeleteOne(p: any) {
  const ok = confirm(
    `确认从「会话论文」中删除？\n\n` +
    `  标题：${shortTitle(p, 50)}\n` +
    `  ID：${p.id}\n\n` +
    `（仅从列表移除，不影响已下载的 PDF / 翻译 / 总结缓存）`
  );
  if (!ok) return;
  deletingId.value = p.id;
  try {
    await store.removeSessionPapers([p.id]);
    // 同步清掉本行选中态
    if (selected.value.has(p.id)) {
      const next = new Set(selected.value);
      next.delete(p.id);
      selected.value = next;
    }
  } catch (e) {
    console.warn("[PapersPanel] delete failed", e);
  } finally {
    deletingId.value = null;
  }
}

async function confirmBulkDelete() {
  const ids = Array.from(selected.value);
  if (!ids.length) return;
  const ok = confirm(
    `确认删除选中的 ${ids.length} 篇会话论文？\n\n` +
    `（仅从列表移除，不影响已下载的 PDF / 翻译 / 总结缓存）`
  );
  if (!ok) return;
  bulkDeleting.value = true;
  try {
    await store.removeSessionPapers(ids);
    selected.value = new Set();
  } catch (e) {
    console.warn("[PapersPanel] bulk delete failed", e);
  } finally {
    bulkDeleting.value = false;
  }
}

// ========== 收藏 / Tag 内联编辑 ==========
const tagInputOpenFor = ref<string | null>(null);
const tagDrafts = ref<Record<string, string>>({});
const tagInputEls = ref<Record<string, HTMLInputElement | null>>({});

function isBookmarked(paperId: string) {
  return store.isBookmarked(paperId);
}
function paperTags(paperId: string) {
  return store.tagsFor(paperId);
}

async function toggleBookmark(paperId: string) {
  try {
    if (isBookmarked(paperId)) {
      await store.unbookmarkPaper(paperId);
    } else {
      await store.bookmarkPaper(paperId);
    }
  } catch (e) {
    console.warn("[Bookmark] toggle failed", e);
  }
}

async function openTagInput(paperId: string) {
  // 确保本地 cache 里有当前 tag（避免 UI 出现 "0" 然后突然变成 "2"）
  await store.fetchPaperTags(paperId);
  tagInputOpenFor.value = paperId;
  tagDrafts.value = { ...tagDrafts.value, [paperId]: "" };
  await nextTick();
  const el = tagInputEls.value[paperId];
  if (el) el.focus();
}

function cancelTagInput(paperId: string) {
  if (tagInputOpenFor.value === paperId) tagInputOpenFor.value = null;
  const next = { ...tagDrafts.value };
  delete next[paperId];
  tagDrafts.value = next;
}

async function confirmAddTag(paperId: string) {
  const raw = (tagDrafts.value[paperId] || "").trim();
  if (!raw) {
    cancelTagInput(paperId);
    return;
  }
  try {
    await store.addPaperTag(paperId, raw);
    cancelTagInput(paperId);
  } catch (e) {
    console.warn("[Tag] add failed", e);
  }
}

// 进入论文界面时主动拉一次快照，确保已有总结能直接显示（不重新总结）
async function refreshForPapersPanel() {
  if (!store.paperSummaries || store.paperSummaries.length === 0) {
    await store.refreshSnapshot();
  }
  // 顺手拉一次收藏/标签 flags（用于行内 ⭐ / 🏷️ 渲染）
  if (store.papers && store.papers.length) {
    await store.fetchPaperFlags(store.papers.map((p) => p.id));
  }
}
onMounted(refreshForPapersPanel);
onActivated(refreshForPapersPanel);

// 论文列表变化时也补一次 flags（覆盖用户通过对话检索新增论文的场景）
watch(
  () => store.papers.map((p) => p.id).join(","),
  async () => {
    if (store.papers && store.papers.length) {
      await store.fetchPaperFlags(store.papers.map((p) => p.id));
    }
  },
);

const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase();
  if (!kw) return store.papers;
  return store.papers.filter((p) => {
    const hay = [
      p.id,
      p.title,
      (p.authors || []).join(" "),
      p.primary_category || "",
      (p.categories || []).join(" "),
      p.comment || "",
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(kw);
  });
});

// 论文在 session 里的顺序就是“第N篇”
function indexOf(paperId: string): number {
  const i = store.papers.findIndex((p) => p.id === paperId);
  return i >= 0 ? i + 1 : -1;
}

// 列表 / 搜索结果变化时，丢弃已不存在的 paper_id
watch(
  () => filtered.value.map((p) => p.id).join(","),
  () => {
    const validIds = new Set(filtered.value.map((p) => p.id));
    let changed = false;
    const next = new Set<string>();
    for (const id of selected.value) {
      if (validIds.has(id)) next.add(id);
      else changed = true;
    }
    if (changed) selected.value = next;
  }
);

function normalizePdf(url: string) {
  return url.endsWith(".pdf") ? url : `${url}.pdf`;
}

/**
 * 把 paper.id 渲染成可点击的"论文详情页 URL"。
 * - DOI（10.x/y）→ https://doi.org/...
 * - arXiv ID（YYMM.NNNNN）→ https://arxiv.org/abs/...
 * - OpenAlex W... → https://openalex.org/...
 * - 其他（含完整 URL）→ 原样
 */
function paperIdHref(id: string | null | undefined): string {
  if (!id) return "";
  if (id.startsWith("http://") || id.startsWith("https://")) return id;
  // DOI
  if (id.startsWith("10.") && id.includes("/")) return `https://doi.org/${id}`;
  // OpenAlex W...
  if (id.startsWith("W") && /^\d+$/.test(id.slice(1))) return `https://openalex.org/${id}`;
  // arXiv 风格 ID
  if (/^\d{4}\.\d{4,5}(v\d+)?$/.test(id)) return `https://arxiv.org/abs/${id}`;
  return "";
}

function pdfStatusText(paperId: string) {
  const a = store.pdfMap.get(paperId);
  return a ? a.status : "NOT_DOWNLOADED";
}
function trStatusText(paperId: string) {
  const a = store.translateMap.get(paperId);
  return a ? a.status : "NOT_TRANSLATED";
}

function pdfReady(paperId: string) {
  return pdfStatusText(paperId) === "READY";
}
function trReady(paperId: string) {
  return trStatusText(paperId) === "READY";
}
// STALE（本地文件丢失）允许预览按钮（后端 on-demand 会重下）
function pdfAccessible(paperId: string) {
  const s = pdfStatusText(paperId);
  return s === "READY" || s === "STALE";
}
function trAccessible(paperId: string) {
  const s = trStatusText(paperId);
  return s === "READY" || s === "STALE";
}

// 获取下载失败的错误原因（asset.error 字段）
function pdfDownloadError(paperId: string): string {
  const a = store.pdfMap.get(paperId);
  return a?.error || "";
}

// 复制论文详情页链接（DOI/OpenAlex/arXiv）到剪贴板,方便用户手动下载
async function copyPaperLink(p: any) {
  const url = paperIdHref(p.id) || p.paper_url || p.pdf_url || "";
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    store.pushAssistant?.(`已复制链接: ${url}`);
  } catch {
    // 退化: 提示用户手动复制
    store.pushAssistant?.(`请手动复制: ${url}`);
  }
}

// ========== Summary helpers ==========
function summaryFor(paperId: string) {
  return store.paperSummaryMap.get(paperId);
}

function summaryStatus(paperId: string): string {
  return summaryFor(paperId)?.status || "NOT_SUMMARIZED";
}

function summaryReady(paperId: string) {
  return summaryStatus(paperId) === "READY";
}

function summaryRunning(paperId: string) {
  return summaryStatus(paperId) === "SUMMARIZING";
}

function summaryStatusText(paperId: string) {
  const status = summaryStatus(paperId);
  if (status === "NOT_SUMMARIZED") return "未总结";
  if (status === "SUMMARIZING") return "总结中...";
  if (status === "READY") return "已总结";
  if (status === "FAILED") return "总结失败";
  return status;
}

async function toggleSummary(refIndex: number, paperId: string) {
  // 展开面板
  expandedSummaryIndex.value = refIndex;

  // 如果还没生成总结，且 PDF 已下载，则自动触发一次
  // （summary 数据已在 store.refreshSnapshot 中一次性加载）
  const status = summaryStatus(paperId);
  if (status === "NOT_SUMMARIZED") {
    await store.summarizePaper(refIndex);
  }
}

function ragReady(paperId: string) {
  // 仅有 history 即代表至少成功索引过一次
  return (store.ragHistoryFor(paperId) || []).length > 0;
}

function formatTime(iso?: string | null) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function openPreview(paper: any) {
  // 预览按钮始终展示原文（眼睛图标 = 预览原始 PDF）。
  // 翻译版通过独立的"查看翻译后论文"按钮（external-link 图标）打开。
  if (pdfAccessible(paper.id)) {
    store.openRawPdf(paper.id);
  }
}

function shouldWarnTranslate(paperId: string) {
  const a = store.pdfMap.get(paperId);
  return !a || a.status !== "READY";
}

// ---- 上传本地 PDF ----
const uploadFileInputs = ref<Map<string, HTMLInputElement>>(new Map());

function registerUploadInput(paperId: string, el: any) {
  if (!el) return;
  uploadFileInputs.value.set(paperId, el as HTMLInputElement);
}

function triggerUpload(paperId: string) {
  const el = uploadFileInputs.value.get(paperId);
  if (el) el.click();
}

async function handleUploadFile(paperId: string, ev: Event) {
  const target = ev.target as HTMLInputElement;
  const file = target.files?.[0];
  target.value = "";  // 重置以便重复选择同一文件
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    store.pushAssistant?.(`仅支持 .pdf 文件（当前: ${file.name}）`);
    return;
  }
  try {
    await store.uploadPaperById(paperId, file);
    // 上传成功后直接打开预览（新标签页）
    setTimeout(() => store.openRawPdf(paperId), 300);
  } catch {
    /* store.uploadPaperById 已显示错误 */
  }
}
</script>

<style scoped>
.papers {
  height: calc(100vh - 36px);
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: rgba(255,255,255,0.02);
  overflow: hidden;
}

.card-header {
  padding: 12px 12px 10px;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.title { font-weight: 700; margin-bottom: 6px; }
.row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.input {
  flex:1;
  min-width: 240px;
  height: 32px;
  padding: 0 10px;
  border:1px solid var(--border);
  border-radius: 8px;
  background: var(--bg2);
  color: var(--fg);
}
.muted { color: var(--muted); margin: 8px 0 0; }

.table-scroll {
  /* 关键：独立滚动条只出现在这里 */
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}

.table {
  width: 100%;
  border-collapse: collapse;
}

thead th {
  position: sticky;   /* 表头固定，滚动时更好用 */
  top: 0;
  z-index: 1;
  background: rgba(10, 10, 12, 0.92);
  backdrop-filter: blur(8px);
}

th, td {
  border-bottom: 1px solid var(--border);
  padding: 10px;
  vertical-align: top;
}

th { text-align:left; color: var(--muted); font-weight: 600; }

.p-title { font-weight: 700; margin-bottom: 4px; }
.upload-btn {
  position: relative;
  background: linear-gradient(135deg, rgba(110, 193, 228, 0.12), rgba(110, 193, 228, 0.04));
  border-color: rgba(110, 193, 228, 0.35);
}
.upload-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(110, 193, 228, 0.25), rgba(110, 193, 228, 0.08));
  border-color: rgba(110, 193, 228, 0.6);
  transform: translateY(-1px);
}
.upload-btn svg {
  color: #6ec1e4;
}
.subs-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #4d8be8, #2f64c0);
  cursor: default;
  user-select: none;
  white-space: nowrap;
}

.download-failed-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #e85d5d, #c63838);
  cursor: pointer;
  user-select: none;
  vertical-align: middle;
  box-shadow: 0 1px 3px rgba(200, 56, 56, 0.3);
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.download-failed-tag:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(200, 56, 56, 0.5);
}
.download-failed-tag:active {
  transform: translateY(0);
}
.download-stale-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #e0a83a, #b8821f);
  cursor: default;
  user-select: none;
  vertical-align: middle;
  box-shadow: 0 1px 3px rgba(184, 130, 31, 0.3);
}
.sub { color: var(--muted); font-size: 12px; line-height: 1.4; margin-top: 2px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }

.paper-id-link {
  color: var(--accent, #79c0ff);
  text-decoration: underline dotted;
  text-underline-offset: 2px;
}
.paper-id-link:hover { text-decoration: underline; }

.primary-cat {
  color: var(--accent, #79c0ff);
  margin-left: 6px;
}

.all-cats {
  display: inline-flex;
  align-items: center;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(121, 192, 255, 0.15);
  color: var(--accent, #79c0ff);
  font-size: 11px;
  cursor: help;
  transition: background 0.2s;
}

.all-cats:hover {
  background: rgba(121, 192, 255, 0.3);
}

/* ✅/❌ 小圆角胶囊，带 title 可看真实状态 */
.flag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,0.02);
  user-select: none;
}
.flag.ok { border-color: rgba(0,255,153,.35); }
.flag.bad { border-color: rgba(255,107,107,.35); }
.flag.running { border-color: rgba(255,200,0,.35); animation: pulse 1.6s ease-in-out infinite; }
.flag.warn { border-color: rgba(255,200,0,.45); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}

/* Summary expansion row */
.summary-row td.summary-cell {
  padding: 0;
  background: rgba(255, 255, 255, 0.02);
}

.summary-card {
  padding: 14px 16px 16px;
  border-top: 1px dashed rgba(121, 192, 255, 0.25);
}

.summary-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.summary-header strong {
  flex: 1;
  font-size: 13px;
  color: var(--accent, #79c0ff);
}

.summary-section {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
}

.summary-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent, #79c0ff);
  margin-bottom: 6px;
}

.summary-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--fg);
  white-space: pre-wrap;
  word-break: break-word;
}

.innovation-text {
  border-left: 3px solid rgba(255, 200, 0, 0.45);
  padding-left: 10px;
}

.summary-meta {
  margin-top: 10px;
  font-size: 11px;
  color: var(--muted);
  text-align: right;
}

.summary-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--muted);
  padding: 6px 0;
}

.loading-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(121, 192, 255, 0.3);
  border-top-color: var(--accent, #79c0ff);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.summary-empty {
  font-size: 12px;
  color: var(--muted);
  padding: 6px 0;
}
.summary-empty p { margin: 0; }

.summary-error {
  font-size: 12px;
  color: #ff6b6b;
  padding: 6px 0;
}

/* ===== clickable flag styles ===== */
.flag.clickable:hover { opacity: 0.8; }

.btn.small {
  height: 26px;
  font-size: 12px;
  padding: 0 10px;
  border-radius: 6px;
}
.btn.ghost {
  background: transparent;
}

.ops { display:flex; gap:6px; flex-wrap:nowrap; }
.col-op { width: 200px; }
.hint { margin-top: 6px; color: #f6c177; font-size: 12px; }
.empty { padding: 12px; color: var(--muted); }

/* 列宽更稳定（桌面端） */
.col-idx { width: 56px; }
.col-check { width: 36px; text-align: center; }
.col-auth { width: 220px; }
.col-time { width: 150px; }
.col-flag { width: 72px; }
.col-op { width: 200px; }

/* 行内 checkbox */
.col-check input[type="checkbox"] {
  cursor: pointer;
  width: 14px;
  height: 14px;
  accent-color: var(--accent, #79c0ff);
}

/* 选中行高亮 */
tr.row-selected {
  background: rgba(121, 192, 255, 0.06);
}

/* 批量操作工具条 */
.bulk-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(121, 192, 255, 0.06);
  border: 1px dashed rgba(121, 192, 255, 0.3);
}

.bulk-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--fg);
}

.bulk-check input[type="checkbox"] {
  width: 14px;
  height: 14px;
  cursor: pointer;
  accent-color: var(--accent, #79c0ff);
}

.bulk-count {
  font-size: 12px;
  color: var(--muted);
}

/* 危险按钮（删除） */
.btn.danger {
  color: #d96a6a;
  border-color: rgba(217, 106, 106, 0.4);
}
.btn.danger:hover:not(:disabled) {
  background: rgba(217, 106, 106, 0.12);
  color: #ff8585;
}
.btn.icon.danger {
  color: #d96a6a;
}
.btn.icon.danger:hover:not(:disabled) {
  background: rgba(217, 106, 106, 0.12);
  border-color: rgba(217, 106, 106, 0.5);
}

.col-time .fetched-at {
  color: #6366f1;
  font-weight: 500;
}

/* 小屏优化：隐藏作者/时间列，减少横向滚动 */
@media (max-width: 768px) {
  .col-auth, .col-time { display: none; }
  td.col-auth, td.col-time { display: none; }
}

/* ============ 收藏 / Tag 行内样式 ============ */
.bk-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-top: 6px;
}

.bk-star-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 16px;
  line-height: 1;
  width: 28px;
  height: 24px;
  border-radius: 6px;
  cursor: pointer;
  padding: 0;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}
.bk-star-btn:hover {
  color: #f6c177;
  border-color: rgba(246, 193, 119, 0.5);
  background: rgba(246, 193, 119, 0.08);
}
.bk-star-btn.active {
  color: #f6c177;
  border-color: rgba(246, 193, 119, 0.6);
  background: rgba(246, 193, 119, 0.15);
}

.bk-tag-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 12px;
  padding: 2px 8px;
  height: 24px;
  border-radius: 6px;
  cursor: pointer;
}
.bk-tag-btn:hover {
  color: var(--accent);
  border-color: rgba(121, 192, 255, 0.4);
  background: rgba(121, 192, 255, 0.08);
}

.bk-tag-chip {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(121, 192, 255, 0.15);
  color: var(--accent);
}

.bk-tag-input-inline {
  height: 24px;
  font-size: 11px;
  padding: 0 6px;
  border-radius: 6px;
  border: 1px solid var(--accent);
  background: var(--bg2);
  color: var(--fg);
  min-width: 160px;
}
</style>
