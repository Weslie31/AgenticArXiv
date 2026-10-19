<template>
  <div class="annotation-panel">
    <div class="ap-toolbar">
      <button class="btn primary small" @click="openCreate">
        ＋ 新建批注
      </button>
      <span class="ap-count">共 {{ items.length }} 条</span>
      <button class="btn ghost small" @click="refresh" :disabled="loading">
        {{ loading ? "刷新中…" : "刷新" }}
      </button>
    </div>

    <div v-if="loading && !items.length" class="ap-loading">加载批注中…</div>

    <div v-else-if="!items.length" class="ap-empty">
      <p>还没有批注</p>
      <p class="hint">
        把论文里有启发的段落记录下来，下次提问时 AI 会优先参考。
      </p>
    </div>

    <ul v-else class="ap-list">
      <li v-for="item in items" :key="item.id" class="ap-card">
        <div class="ap-card-head">
          <span class="ap-page">📄 第 {{ item.page_number ?? "?" }} 页</span>
          <span class="ap-time">{{ formatTime(item.created_at) }}</span>
        </div>
        <blockquote class="ap-quote">{{ item.highlighted_text }}</blockquote>
        <div class="ap-comment">{{ item.comment }}</div>
        <div class="ap-card-actions">
          <button class="btn small ghost" @click="openEdit(item)">编辑</button>
          <button class="btn small ghost danger" @click="onDelete(item)">
            删除
          </button>
        </div>
      </li>
    </ul>

    <!-- 编辑/新建弹窗 -->
    <div v-if="editing" class="ap-modal-mask" @click.self="closeEdit">
      <div class="ap-modal">
        <div class="ap-modal-title">
          {{ editing.id ? "编辑批注" : "新建批注" }}
        </div>
        <label class="ap-field">
          <span>页码（可选）</span>
          <input
            class="input"
            type="number"
            min="1"
            v-model.number="editing.page_number"
            placeholder="例如 5"
          />
        </label>
        <label class="ap-field">
          <span>原文片段 *</span>
          <textarea
            class="input"
            rows="4"
            v-model="editing.highlighted_text"
            placeholder="从论文中复制的关键段落"
          ></textarea>
        </label>
        <label class="ap-field">
          <span>你的评论 *</span>
          <textarea
            class="input"
            rows="3"
            v-model="editing.comment"
            placeholder="写下你的理解、问题或联想"
          ></textarea>
        </label>
        <div v-if="editError" class="ap-edit-error">❌ {{ editError }}</div>
        <div class="ap-modal-actions">
          <button class="btn ghost small" @click="closeEdit">取消</button>
          <button class="btn primary small" @click="saveEdit" :disabled="saving">
            {{ saving ? "保存中…" : "保存" }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useAppStore } from "@/stores/appStore";
import type { Annotation, AnnotationCreatePayload } from "@/api/types";

const props = defineProps<{ paperId: string }>();
const store = useAppStore();

const items = computed<Annotation[]>(() =>
  store.annotationsFor(props.paperId)
);
const loading = computed(() => store.annotationsLoading);
const saving = ref(false);
const editError = ref("");

interface EditingState {
  id: number | null;
  page_number: number | null;
  highlighted_text: string;
  comment: string;
}
const editing = ref<EditingState | null>(null);

async function refresh() {
  if (!props.paperId) return;
  await store.fetchAnnotations(props.paperId);
}

onMounted(refresh);
watch(() => props.paperId, refresh);

function openCreate() {
  editing.value = {
    id: null,
    page_number: null,
    highlighted_text: "",
    comment: "",
  };
  editError.value = "";
}

function openEdit(item: Annotation) {
  editing.value = {
    id: item.id,
    page_number: item.page_number,
    highlighted_text: item.highlighted_text,
    comment: item.comment,
  };
  editError.value = "";
}

function closeEdit() {
  editing.value = null;
  editError.value = "";
}

async function saveEdit() {
  if (!editing.value) return;
  const e = editing.value;
  if (!e.highlighted_text.trim() || !e.comment.trim()) {
    editError.value = "原文片段和评论都不能为空";
    return;
  }
  saving.value = true;
  editError.value = "";
  try {
    if (e.id) {
      await store.updateAnnotation(e.id, {
        page_number: e.page_number ?? null,
        highlighted_text: e.highlighted_text,
        comment: e.comment,
      });
    } else {
      const payload: AnnotationCreatePayload = {
        paper_id: props.paperId,
        session_id: store.sessionId,
        page_number: e.page_number ?? null,
        highlighted_text: e.highlighted_text,
        comment: e.comment,
      };
      await store.createAnnotation(payload);
    }
    editing.value = null;
  } catch (err: any) {
    editError.value = err?.message || String(err);
  } finally {
    saving.value = false;
  }
}

async function onDelete(item: Annotation) {
  if (!confirm(`确认删除第 ${item.page_number ?? "?"} 页的这条批注？`)) return;
  try {
    await store.deleteAnnotation(item.id, item.paper_id);
  } catch (err: any) {
    alert(err?.message || String(err));
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
</script>

<style scoped>
.annotation-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  flex: 1;
}

.ap-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 4px;
}
.ap-count {
  font-size: 12px;
  color: var(--muted, #888);
}

.ap-empty {
  text-align: center;
  padding: 32px 12px;
  color: var(--muted, #888);
}
.ap-empty .hint {
  font-size: 12px;
  margin-top: 4px;
}

.ap-loading {
  text-align: center;
  padding: 24px;
  color: var(--muted, #888);
}

.ap-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.ap-card {
  border: 1px solid var(--border, #2a2a2a);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--card-bg, rgba(255, 255, 255, 0.02));
}
.ap-card-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--muted, #888);
  margin-bottom: 6px;
}
.ap-page {
  font-weight: 600;
  color: var(--fg, #eee);
}
.ap-quote {
  margin: 6px 0;
  padding: 6px 10px;
  border-left: 3px solid var(--accent, #3a8ee6);
  background: rgba(58, 142, 230, 0.06);
  font-style: italic;
  color: var(--fg, #ddd);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
}
.ap-comment {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  color: var(--fg, #ddd);
}
.ap-card-actions {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  justify-content: flex-end;
}
.btn.danger {
  color: #d96a6a;
}

/* Modal */
.ap-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}
.ap-modal {
  width: 480px;
  max-width: 90vw;
  background: var(--modal-bg, #1e1e1e);
  border: 1px solid var(--border, #333);
  border-radius: 8px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}
.ap-modal-title {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 4px;
}
.ap-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted, #aaa);
}
.ap-field .input {
  font-size: 13px;
}
.ap-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
}
.ap-edit-error {
  color: #d96a6a;
  font-size: 12px;
}
</style>