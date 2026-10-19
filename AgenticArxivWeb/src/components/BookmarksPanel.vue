<template>
  <section class="bookmarks">
    <header class="card-header">
      <div class="title">⭐ 我的收藏夹</div>

      <div class="row">
        <input
          class="input"
          v-model="searchKw"
          placeholder="搜索标题/作者/arxiv id/note…"
        />
        <select class="input select" v-model="filterTag" @change="onFilterTag">
          <option value="">全部 tag</option>
          <option v-for="t in store.allTags" :key="t" :value="t">
            # {{ t }}
          </option>
        </select>
        <button class="btn" @click="refresh" :disabled="store.bookmarksLoading">
          {{ store.bookmarksLoading ? "刷新中…" : "刷新" }}
        </button>
      </div>

      <p class="muted">
        共 <b>{{ store.bookmarkListTotal }}</b> 篇收藏 ·
        {{ store.allTags.length }} 个 tag ·
        跨 session/订阅 自动汇总
      </p>
    </header>

    <div v-if="store.lastError" class="bk-error">❌ {{ store.lastError }}</div>

    <div
      v-if="store.bookmarksLoading && !store.bookmarkList.length"
      class="bk-loading"
    >
      加载收藏夹…
    </div>

    <div
      v-else-if="!filteredItems.length"
      class="bk-empty"
    >
      <p v-if="filterTag">该 tag 下还没有收藏</p>
      <p v-else>
        收藏夹还是空的 —— 去「论文」或「订阅」面板，点击 ⭐ 把感兴趣的论文加进来。
      </p>
    </div>

    <div v-else class="bk-table-scroll">
      <table class="bk-table">
        <thead>
          <tr>
            <th class="bk-col-idx">#</th>
            <th>论文</th>
            <th class="bk-col-tags">Tags</th>
            <th class="bk-col-note">备注</th>
            <th class="bk-col-time">收藏时间</th>
            <th class="bk-col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, i) in filteredItems" :key="item.bookmark.id">
            <td class="mono bk-col-idx">{{ i + 1 }}</td>

            <td>
              <div class="bk-title" v-if="item.paper">
                {{ item.paper.title }}
                <span
                  v-if="pdfStatusText(item.bookmark.paper_id) === 'FAILED'"
                  class="download-failed-tag"
                  :title="pdfDownloadError(item.bookmark.paper_id) || '下载失败，请前往论文详情页手动下载'"
                  @click.stop="copyPaperLink(item.paper)"
                  role="button"
                >⚠️ 无法下载</span>
                <span
                  v-else-if="pdfStatusText(item.bookmark.paper_id) === 'STALE'"
                  class="download-stale-tag"
                  :title="pdfDownloadError(item.bookmark.paper_id) || '本地 PDF 文件丢失，点击重新下载即可恢复'"
                  role="status"
                >🟡 本地文件丢失</span>
              </div>
              <div class="bk-title bk-title-missing" v-else>
                (论文元数据已不可用)
              </div>
              <div class="bk-sub mono">
                <a v-if="paperIdHref(item.bookmark.paper_id)"
                   :href="paperIdHref(item.bookmark.paper_id)"
                   target="_blank"
                   rel="noreferrer"
                   class="bk-paper-id-link"
                   :title="'打开论文详情页：' + paperIdHref(item.bookmark.paper_id)">
                  {{ item.bookmark.paper_id }}
                </a>
                <span v-else>{{ item.bookmark.paper_id }}</span>
                <span
                  v-if="item.paper?.primary_category"
                  class="bk-cat"
                >{{ item.paper.primary_category }}</span>
              </div>
              <div
                class="bk-sub"
                v-if="item.paper?.authors?.length"
              >
                {{ item.paper.authors.slice(0, 4).join(", ")
                }}<span v-if="item.paper.authors.length > 4">…</span>
              </div>
              <div class="bk-sub" v-if="item.paper?.pdf_url">
                PDF：
                <a
                  :href="normalizePdf(item.paper.pdf_url)"
                  target="_blank"
                  rel="noreferrer"
                >{{ normalizePdf(item.paper.pdf_url) }}</a>
              </div>
              <div class="bk-sub" v-if="item.paper?.paper_url">
                <a
                  :href="item.paper.paper_url"
                  target="_blank"
                  rel="noreferrer"
                  class="paper-link"
                  title="打开论文详情页"
                >📄 论文详情页</a>
              </div>
            </td>

            <td class="bk-col-tags">
              <div class="bk-tags">
                <span
                  v-for="t in item.tags"
                  :key="t"
                  class="bk-tag"
                  @click="filterTag = t; refresh()"
                  title="按此 tag 筛选"
                >
                  #{{ t }}
                  <button
                    class="bk-tag-x"
                    title="删除这个 tag"
                    @click.stop="removeTagFromItem(item, t)"
                  >×</button>
                </span>
                <button
                  v-if="!tagAdding[item.bookmark.paper_id]"
                  class="bk-tag-add"
                  @click="openTagInput(item)"
                  title="给这篇论文加 tag"
                >+ tag</button>
                <input
                  v-else
                  class="bk-tag-input"
                  :ref="(el) => (tagInputEls[item.bookmark.paper_id] = el as HTMLInputElement | null)"
                  v-model="tagDraft[item.bookmark.paper_id]"
                  placeholder="新 tag，回车确认"
                  @keydown.enter.prevent="confirmAddTag(item)"
                  @keydown.esc="cancelTagInput(item)"
                  @blur="confirmAddTag(item)"
                />
              </div>
            </td>

            <td class="bk-col-note">
              <div v-if="editingNoteId === item.bookmark.paper_id" class="bk-note-edit">
                <textarea
                  class="input"
                  rows="2"
                  v-model="noteDraft"
                  placeholder="写点备注，帮助未来检索…"
                ></textarea>
                <div class="bk-note-actions">
                  <button class="btn small ghost" @click="cancelNoteEdit">取消</button>
                  <button
                    class="btn small primary"
                    @click="saveNote(item)"
                    :disabled="noteSaving"
                  >{{ noteSaving ? "保存中…" : "保存" }}</button>
                </div>
              </div>
              <div v-else class="bk-note" @click="openNoteEdit(item)">
                <template v-if="item.bookmark.note">
                  {{ item.bookmark.note }}
                </template>
                <span v-else class="bk-note-empty">(无备注，点击编辑)</span>
              </div>
            </td>

            <td class="bk-col-time">
              <div class="bk-sub">{{ formatTime(item.bookmark.created_at) }}</div>
              <div
                v-if="item.bookmark.updated_at !== item.bookmark.created_at"
                class="bk-sub"
                :title="'最近更新: ' + formatTime(item.bookmark.updated_at)"
              >最近更新：{{ formatTime(item.bookmark.updated_at) }}</div>
            </td>

            <td class="bk-col-op">
              <div class="bk-ops">
                <button
                  class="btn icon"
                  :title="pdfAccessible(item.bookmark.paper_id) ? (pdfReady(item.bookmark.paper_id) ? '预览原文' : '本地文件丢失，点击重下并预览') : '请先下载 PDF'"
                  :disabled="!item.paper || !pdfAccessible(item.bookmark.paper_id)"
                  @click="store.openRawPdf(item.bookmark.paper_id)"
                >
                  <!-- eye -->
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                  </svg>
                </button>
                <button
                  class="btn icon"
                  :title="pdfReady(item.bookmark.paper_id) ? 'RAG 问答' : '请先下载 PDF'"
                  :disabled="!item.paper || !pdfReady(item.bookmark.paper_id)"
                  @click="store.goToRagPage(item.bookmark.paper_id)"
                >
                  <!-- chat-bubble -->
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                  </svg>
                </button>
                <button
                  class="btn icon bk-danger"
                  title="取消收藏（同时清理该论文的全部 tag）"
                  @click="onUnbookmark(item)"
                >
                  <!-- trash -->
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"></path>
                    <path d="M10 11v6M14 11v6"></path>
                  </svg>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onMounted, ref } from "vue";
import { useAppStore } from "@/stores/appStore";
import type { PaperBookmarkWithPaper } from "@/api/types";

const store = useAppStore();

const searchKw = ref("");
const filterTag = ref("");
const editingNoteId = ref<string | null>(null);
const noteDraft = ref("");
const noteSaving = ref(false);
const tagDraft = ref<Record<string, string>>({});
const tagAdding = ref<Record<string, boolean>>({});
const tagInputEls = ref<Record<string, HTMLInputElement | null>>({});

const filteredItems = computed(() => {
  const items = store.bookmarkList || [];
  const kw = searchKw.value.trim().toLowerCase();
  if (!kw) return items;
  return items.filter((it) => {
    const p = it.paper;
    const hay = [
      it.bookmark.paper_id,
      p?.title || "",
      (p?.authors || []).join(" "),
      p?.primary_category || "",
      it.bookmark.note || "",
      ...(it.tags || []),
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(kw);
  });
});

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
  if (id.startsWith("10.") && id.includes("/")) return `https://doi.org/${id}`;
  if (id.startsWith("W") && /^\d+$/.test(id.slice(1))) return `https://openalex.org/${id}`;
  if (/^\d{4}\.\d{4,5}(v\d+)?$/.test(id)) return `https://arxiv.org/abs/${id}`;
  return "";
}

function pdfReady(paperId: string) {
  return (store.pdfMap.get(paperId)?.status || "") === "READY";
}
// STALE（本地文件丢失）允许预览/下载入口，调用时由后端 on-demand 重下
function pdfAccessible(paperId: string) {
  const s = store.pdfMap.get(paperId)?.status || "";
  return s === "READY" || s === "STALE";
}
function pdfStatusText(paperId: string) {
  const a = store.pdfMap.get(paperId);
  return a ? a.status : "NOT_DOWNLOADED";
}
function pdfDownloadError(paperId: string): string {
  return store.pdfMap.get(paperId)?.error || "";
}
async function copyPaperLink(p: any) {
  const url = paperIdHref(p.id) || p.paper_url || p.pdf_url || "";
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    // ignore
  }
}

function formatTime(iso?: string | null) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

async function refresh() {
  await store.fetchBookmarkList(filterTag.value || null);
}

function onFilterTag() {
  refresh();
}

// ---- Note 编辑 ----
function openNoteEdit(item: PaperBookmarkWithPaper) {
  editingNoteId.value = item.bookmark.paper_id;
  noteDraft.value = item.bookmark.note || "";
}

function cancelNoteEdit() {
  editingNoteId.value = null;
  noteDraft.value = "";
}

async function saveNote(item: PaperBookmarkWithPaper) {
  if (noteSaving.value) return;
  noteSaving.value = true;
  try {
    await store.updateBookmarkNote(item.bookmark.paper_id, noteDraft.value || null);
    editingNoteId.value = null;
    noteDraft.value = "";
  } catch (e) {
    console.warn("[Bookmark] save note failed", e);
  } finally {
    noteSaving.value = false;
  }
}

// ---- Tag 操作 ----
async function openTagInput(item: PaperBookmarkWithPaper) {
  const pid = item.bookmark.paper_id;
  tagAdding.value = { ...tagAdding.value, [pid]: true };
  tagDraft.value = { ...tagDraft.value, [pid]: "" };
  await nextTick();
  const el = tagInputEls.value[pid];
  if (el) el.focus();
}

function cancelTagInput(item: PaperBookmarkWithPaper) {
  const pid = item.bookmark.paper_id;
  const next = { ...tagAdding.value };
  delete next[pid];
  tagAdding.value = next;
  const nextDraft = { ...tagDraft.value };
  delete nextDraft[pid];
  tagDraft.value = nextDraft;
}

async function confirmAddTag(item: PaperBookmarkWithPaper) {
  const pid = item.bookmark.paper_id;
  const raw = (tagDraft.value[pid] || "").trim();
  if (!raw) {
    cancelTagInput(item);
    return;
  }
  try {
    await store.addPaperTag(pid, raw);
    // 顺手刷新列表，让 tag 顺序按字母排序
    await refresh();
  } catch (e) {
    console.warn("[Bookmark] add tag failed", e);
  } finally {
    cancelTagInput(item);
  }
}

async function removeTagFromItem(item: PaperBookmarkWithPaper, tag: string) {
  if (!confirm(`删除论文 ${item.bookmark.paper_id} 的 tag #${tag}？`)) return;
  try {
    await store.removePaperTag(item.bookmark.paper_id, tag);
    await refresh();
  } catch (e) {
    console.warn("[Bookmark] remove tag failed", e);
  }
}

async function onUnbookmark(item: PaperBookmarkWithPaper) {
  if (!confirm(`取消收藏 ${item.bookmark.paper_id}？\n同时会清理掉这篇论文的所有 tag。`)) return;
  try {
    await store.unbookmarkPaper(item.bookmark.paper_id);
    await refresh();
  } catch (e) {
    console.warn("[Bookmark] unbookmark failed", e);
  }
}

onMounted(refresh);
onActivated(refresh);
</script>

<style scoped>
.bookmarks {
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
  border-bottom: 1px solid var(--border);
}

.title { font-weight: 700; margin-bottom: 6px; }
.row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }

.input {
  height: 32px;
  padding: 0 10px;
  border:1px solid var(--border);
  border-radius: 8px;
  background: var(--bg2);
  color: var(--fg);
  font-family: inherit;
  font-size: 13px;
}
.input:focus { outline: none; border-color: var(--accent); }
.input.select { min-width: 160px; height: 32px; }

.muted { color: var(--muted); margin: 8px 0 0; font-size: 12px; }

.bk-error {
  margin: 10px 12px 0;
  background: rgba(217, 106, 106, 0.12);
  color: #d96a6a;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
}

.bk-loading,
.bk-empty {
  padding: 40px 12px;
  text-align: center;
  color: var(--muted);
  flex: 1;
  font-size: 14px;
}
.bk-empty p { margin: 4px 0; }
.bk-empty p.hint { font-size: 12px; opacity: 0.7; }

.bk-table-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.bk-table {
  width: 100%;
  border-collapse: collapse;
}

.bk-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: rgba(10, 10, 12, 0.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border);
  padding: 10px;
  text-align: left;
  color: var(--muted);
  font-weight: 600;
}

.bk-table tbody td {
  border-bottom: 1px solid var(--border);
  padding: 10px;
  vertical-align: top;
}

.bk-col-idx { width: 40px; text-align: center; color: var(--muted); font-size: 12px; }
.bk-col-tags { width: 220px; }
.bk-col-note { width: 260px; }
.bk-col-time { width: 150px; font-size: 12px; }
.bk-col-op { width: 140px; }

.bk-title { font-weight: 700; margin-bottom: 4px; }
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
.bk-title-missing { color: var(--muted); font-style: italic; }
.bk-sub { color: var(--muted); font-size: 12px; line-height: 1.4; margin-top: 2px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }

.bk-paper-id-link {
  color: var(--accent, #79c0ff);
  text-decoration: underline dotted;
  text-underline-offset: 2px;
}
.bk-paper-id-link:hover { text-decoration: underline; }
.bk-cat {
  color: var(--accent);
  margin-left: 6px;
}

/* ===== Tags 列 ===== */
.bk-tags { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.bk-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(121, 192, 255, 0.15);
  color: var(--accent);
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s;
}
.bk-tag:hover { background: rgba(121, 192, 255, 0.3); }
.bk-tag-x {
  background: transparent;
  border: none;
  color: inherit;
  font-size: 12px;
  line-height: 1;
  padding: 0 0 0 2px;
  cursor: pointer;
  opacity: 0.6;
}
.bk-tag-x:hover { opacity: 1; }

.bk-tag-add {
  background: transparent;
  border: 1px dashed var(--border);
  color: var(--muted);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  cursor: pointer;
}
.bk-tag-add:hover { color: var(--accent); border-color: var(--accent); }

.bk-tag-input {
  height: 24px;
  font-size: 11px;
  padding: 0 6px;
  border-radius: 6px;
  border: 1px solid var(--accent);
  background: var(--bg2);
  color: var(--fg);
  min-width: 140px;
}

/* ===== Note 列 ===== */
.bk-note {
  font-size: 12px;
  color: var(--fg);
  white-space: pre-wrap;
  word-break: break-word;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  min-height: 24px;
}
.bk-note:hover { background: rgba(255,255,255,0.04); }
.bk-note-empty { color: var(--muted); font-style: italic; }
.bk-note-edit { display: flex; flex-direction: column; gap: 6px; }
.bk-note-edit textarea { resize: vertical; min-height: 48px; font-family: inherit; font-size: 12px; padding: 6px 8px; }
.bk-note-actions { display: flex; gap: 6px; justify-content: flex-end; }

/* ===== 操作列 ===== */
.bk-ops { display: flex; gap: 6px; }
.btn.icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,0.03);
  cursor: pointer;
  transition: background 0.15s;
}
.btn.icon svg { width: 14px; height: 14px; }
.btn.icon:hover { background: rgba(255,255,255,0.08); }
.btn.icon:disabled { opacity: 0.4; cursor: not-allowed; }
.btn.icon.bk-danger:hover { background: rgba(217, 106, 106, 0.15); color: #d96a6a; }

.btn { height: 28px; font-size: 12px; padding: 0 10px; border-radius: 6px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); color: var(--fg); cursor: pointer; }
.btn:hover:not(:disabled) { background: rgba(255,255,255,0.08); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.primary { background: rgba(121, 192, 255, 0.18); border-color: rgba(121, 192, 255, 0.4); color: var(--accent); }
.btn.primary:hover:not(:disabled) { background: rgba(121, 192, 255, 0.28); }
.btn.ghost { background: transparent; }
.btn.small { height: 26px; font-size: 12px; padding: 0 10px; }

/* 小屏适配 */
@media (max-width: 900px) {
  .bk-col-time { display: none; }
  td.bk-col-time { display: none; }
}
@media (max-width: 700px) {
  .bk-col-tags { display: none; }
  td.bk-col-tags { display: none; }
}
</style>
