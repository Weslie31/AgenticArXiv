<template>
  <div class="comparison-panel">
    <div class="panel-header">
      <h2>论文对比</h2>
      <button class="btn-close" @click="$emit('close')">×</button>
    </div>

    <!-- Tab: 选择论文 / 查看结果 -->
    <div class="tabs">
      <button 
        :class="{ active: activeTab === 'select' }" 
        @click="activeTab = 'select'"
      >
        选择论文
      </button>
      <button 
        :class="{ active: activeTab === 'result' }" 
        @click="switchToResultTab"
      >
        查看结果
        <span v-if="store.comparisons.length" class="badge">{{ store.comparisons.length }}</span>
      </button>
      <button 
        :class="{ active: activeTab === 'history' }" 
        @click="activeTab = 'history'"
      >
        历史记录
      </button>
    </div>

    <!-- Tab: 选择论文 -->
    <div v-show="activeTab === 'select'" class="tab-content">
      <div class="selection-info">
        <span>已选择: {{ store.selectedPaperIds.length }} 篇论文</span>
        <span class="hint">(2-10 篇)</span>
        <button
          v-if="store.selectedPaperIds.length > 0"
          class="btn-clear"
          @click="store.clearPaperSelection()"
        >
          清空
        </button>
      </div>

      <div v-if="displayedPapers.length === 0" class="empty-state">
        <p>暂无论文，请先搜索或订阅论文</p>
      </div>

      <div v-else class="paper-groups">
        <!-- 会话论文分组：独立滚动条 -->
        <div v-if="sessionPapers.length" class="paper-group">
          <div class="group-header">
            <span class="group-title">会话论文</span>
            <span class="group-count">{{ sessionPapers.length }}</span>
          </div>
          <div class="paper-scroll">
            <div
              v-for="(paper, index) in sessionPapers"
              :key="paper.id"
              :class="['paper-item', { selected: isSelected(paper.id) }]"
              @click="store.togglePaperSelection(paper.id)"
            >
              <div class="paper-checkbox">
                <input
                  type="checkbox"
                  :checked="isSelected(paper.id)"
                  @click.stop="store.togglePaperSelection(paper.id)"
                />
              </div>
              <div class="paper-info">
                <div class="paper-title">{{ index + 1 }}. {{ paper.title || '无标题' }}</div>
                <div class="paper-meta">
                  <span v-if="paper.authors?.length">
                    {{ paper.authors.slice(0, 2).join(', ') }}{{ paper.authors.length > 2 ? ' et al.' : '' }}
                  </span>
                  <span v-if="paper.primary_category">{{ paper.primary_category }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 定时获取论文分组：独立滚动条 -->
        <div v-if="scheduledForCompare.length" class="paper-group">
          <div class="group-header">
            <span class="group-title">定时获取论文</span>
            <span class="group-count">{{ scheduledForCompare.length }}</span>
          </div>
          <div class="paper-scroll">
            <div
              v-for="(paper, index) in scheduledForCompare"
              :key="paper.id"
              :class="['paper-item', { selected: isSelected(paper.id) }]"
              @click="store.togglePaperSelection(paper.id)"
            >
              <div class="paper-checkbox">
                <input
                  type="checkbox"
                  :checked="isSelected(paper.id)"
                  @click.stop="store.togglePaperSelection(paper.id)"
                />
              </div>
              <div class="paper-info">
                <div class="paper-title">
                  {{ sessionPapers.length + index + 1 }}. {{ paper.title || '无标题' }}
                  <span class="source-tag scheduled">定时</span>
                </div>
                <div class="paper-meta">
                  <span v-if="paper.authors?.length">
                    {{ paper.authors.slice(0, 2).join(', ') }}{{ paper.authors.length > 2 ? ' et al.' : '' }}
                  </span>
                  <span v-if="paper.primary_category">{{ paper.primary_category }}</span>
                  <span v-if="paper.fetched_at" class="fetched-time">
                    检索: {{ formatFetched(paper.fetched_at) }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 已下载论文分组：不在当前会话/定时中但 PDF 已下载到本地的论文 -->
        <div v-if="downloadedForCompare.length" class="paper-group">
          <div class="group-header">
            <span class="group-title">已下载论文</span>
            <span class="group-count">{{ downloadedForCompare.length }}</span>
          </div>
          <div class="paper-scroll">
            <div
              v-for="(paper, index) in downloadedForCompare"
              :key="paper.id"
              :class="['paper-item', { selected: isSelected(paper.id) }]"
              @click="store.togglePaperSelection(paper.id)"
            >
              <div class="paper-checkbox">
                <input
                  type="checkbox"
                  :checked="isSelected(paper.id)"
                  @click.stop="store.togglePaperSelection(paper.id)"
                />
              </div>
              <div class="paper-info">
                <div class="paper-title">
                  {{ sessionPapers.length + scheduledForCompare.length + index + 1 }}. {{ paper.title || '无标题' }}
                  <span class="source-tag downloaded">已下载</span>
                </div>
                <div class="paper-meta">
                  <span v-if="paper.authors?.length">
                    {{ paper.authors.slice(0, 2).join(', ') }}{{ paper.authors.length > 2 ? ' et al.' : '' }}
                  </span>
                  <span v-if="paper.primary_category">{{ paper.primary_category }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 固定在底部的操作栏（不受 tab 滚动影响） -->
    <div v-show="activeTab === 'select'" class="action-bar">
      <button
        class="btn-primary"
        :disabled="store.selectedPaperIds.length < 2 || store.comparisonLoading"
        @click="handleCreateComparison"
      >
        {{ store.comparisonLoading ? '创建中...' : '开始对比' }}
      </button>
    </div>

    <!-- Tab: 查看结果 -->
    <div v-show="activeTab === 'result'" class="tab-content scrollable">
      <div v-if="!store.currentComparisonResult" class="empty-state">
        <p>请先创建对比或从历史记录中选择</p>
        <button class="btn-secondary" @click="activeTab = 'history'">查看历史</button>
      </div>
      <div v-else class="result-view">
        <ComparisonResultView
          :comparison="store.currentComparisonResult?.comparison"
          :papers="store.currentComparisonResult?.papers || []"
          :report="store.currentComparisonResult?.report"
        />
      </div>
    </div>

    <!-- Tab: 历史记录 -->
    <div v-show="activeTab === 'history'" class="tab-content">
      <div v-if="store.comparisons.length === 0" class="empty-state">
        <p>暂无对比历史</p>
      </div>
      <div v-else class="comparison-list">
        <div 
          v-for="cmp in store.comparisons" 
          :key="cmp.comparison_id"
          class="comparison-item"
          :class="{ active: store.currentComparisonId === cmp.comparison_id }"
          @click="handleSelectComparison(cmp.comparison_id)"
        >
          <div class="comparison-header">
            <span class="comparison-id">{{ cmp.comparison_id.slice(0, 12) }}...</span>
            <span :class="['status', cmp.status.toLowerCase()]">{{ cmp.status }}</span>
          </div>
          <div class="comparison-meta">
            <span>{{ cmp.paper_ids.length }} 篇论文</span>
            <span>{{ formatDate(cmp.created_at) }}</span>
          </div>
          <div class="comparison-actions">
            <button 
              v-if="cmp.status === 'PENDING' || cmp.status === 'FAILED'"
              class="btn-small"
              @click.stop="handleExecuteComparison(cmp.comparison_id)"
            >
              执行对比
            </button>
            <button 
              v-if="cmp.status === 'SUCCEEDED'"
              class="btn-small"
              @click.stop="handleViewResult(cmp.comparison_id)"
            >
              查看结果
            </button>
            <button 
              class="btn-small danger"
              @click.stop="handleDeleteComparison(cmp.comparison_id)"
            >
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Loading Overlay -->
    <div v-if="store.comparisonLoading" class="loading-overlay">
      <div class="spinner"></div>
      <p>{{ loadingMessage }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue';
import { useAppStore } from '@/stores/appStore';
import ComparisonResultView from './ComparisonResultView.vue';

const store = useAppStore();

const emit = defineEmits(['close']);

const activeTab = ref<'select' | 'result' | 'history'>('select');
const loadingMessage = ref('处理中...');

const isSelected = (paperId: string) => store.selectedPaperIds.includes(paperId);

const formatDate = (dateStr?: string) => {
  if (!dateStr) return '';
  try {
    return new Date(dateStr).toLocaleDateString('zh-CN');
  } catch {
    return dateStr;
  }
};

const formatFetched = (dateStr?: string) => {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    if (Number.isNaN(d.getTime())) return dateStr;
    const now = Date.now();
    const diffMin = Math.floor((now - d.getTime()) / 60000);
    if (diffMin < 1) return '刚刚';
    if (diffMin < 60) return `${diffMin}分钟前`;
    if (diffMin < 60 * 24) return `${Math.floor(diffMin / 60)}小时前`;
    return d.toLocaleDateString('zh-CN');
  } catch {
    return dateStr;
  }
};

const sessionPapers = computed(() => store.papers || []);

// 定时获取的论文：去重（与 sessionPapers 重叠的不重复展示）
const scheduledForCompare = computed(() => {
  const sessionIds = new Set(sessionPapers.value.map((p: any) => p.id));
  return (store.scheduledPapers || []).filter((p: any) => !sessionIds.has(p.id));
});

// 已下载论文：直接用后端 /pdf/discovered 扫描本地文件
const downloadedForCompare = computed(() => {
  if (!store.discoveredPapers?.length) return [];
  const discoveredIds = new Set(store.discoveredPapers.map((d: any) => d.paper_id));
  const sessionIds = new Set(sessionPapers.value.map((p: any) => p.id));
  const scheduledIds = new Set(scheduledForCompare.value.map((p: any) => p.id));

  const all = [...sessionPapers.value, ...scheduledForCompare.value];
  const allIds = new Set(all.map((p: any) => p.id));

  const result: any[] = [];
  for (const p of all) {
    if (discoveredIds.has(p.id)) {
      result.push(p);
    }
  }
  // 额外补入：有本地 PDF 但元数据不在 session/scheduled 的论文
  for (const dp of store.discoveredPapers) {
    if (!allIds.has(dp.paper_id)) {
      result.push({
        id: dp.paper_id,
        title: dp.paper_id, // 元数据不全时用 id 兜底
        authors: [],
        primary_category: null,
        _discovered: dp,
      });
    }
  }
  return result;
});

const displayedPapers = computed(() => [
  ...sessionPapers.value,
  ...scheduledForCompare.value,
  ...downloadedForCompare.value,
]);

const switchToResultTab = () => {
  activeTab.value = 'result';
};

// 每次切换到选择论文 tab 都刷新（确保拿到最新下载记录）
watch(activeTab, async (tab) => {
  if (tab === 'select') {
    await store.fetchDiscoveredPapers();
  }
  if (tab === 'history') {
    await store.fetchComparisons();
  }
});

const handleCreateComparison = async () => {
  const cmp = await store.createComparison();
  if (cmp) {
    loadingMessage.value = '正在启动对比分析...';
    await store.executeComparison(cmp.comparison_id);
    await store.pollComparisonStatus(cmp.comparison_id);
    activeTab.value = 'result';
  }
};

const handleSelectComparison = async (comparisonId: string) => {
  await store.loadComparisonResult(comparisonId);
  activeTab.value = 'result';
};

const handleExecuteComparison = async (comparisonId: string) => {
  loadingMessage.value = '正在执行对比分析...';
  store.comparisonLoading = true;
  try {
    await store.executeComparison(comparisonId);
    await store.pollComparisonStatus(comparisonId);
    await store.loadComparisonResult(comparisonId);
  } finally {
    store.comparisonLoading = false;
  }
};

const handleViewResult = async (comparisonId: string) => {
  await store.loadComparisonResult(comparisonId);
  activeTab.value = 'result';
};

const handleDeleteComparison = async (comparisonId: string) => {
  if (confirm('确定要删除这个对比记录吗？')) {
    await store.deleteComparison(comparisonId);
  }
};

onMounted(async () => {
  await Promise.all([store.fetchComparisons(), store.fetchDiscoveredPapers()]);
});
</script>

<style scoped>
/* === 与 PapersPanel 一致的暗主题变量色系 === */
.comparison-panel {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 36px);
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: rgba(255,255,255,0.02);
  overflow: hidden;
  color: var(--fg);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 12px 10px;
  border-bottom: 1px solid var(--border);
}

.panel-header h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
}

.btn-close {
  background: none;
  border: none;
  font-size: 22px;
  cursor: pointer;
  color: var(--muted);
  padding: 0 8px;
  line-height: 1;
}

.btn-close:hover {
  color: var(--fg);
}

.tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  background: rgba(255,255,255,0.02);
}

.tabs button {
  flex: 1;
  padding: 10px 14px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 13px;
  color: var(--muted);
  position: relative;
  transition: color 0.15s;
}

.tabs button:hover {
  color: var(--fg);
}

.tabs button.active {
  color: var(--accent, #79c0ff);
  font-weight: 600;
}

.tabs button.active::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--accent, #79c0ff);
}

.badge {
  display: inline-block;
  background: var(--accent, #79c0ff);
  color: #0b0b10;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 999px;
  margin-left: 6px;
}

.tab-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 12px;
}

.selection-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--muted);
  flex-shrink: 0;
}

.hint {
  color: var(--muted);
  opacity: 0.7;
}

.btn-clear {
  background: var(--bg2, rgba(255,255,255,0.03));
  border: 1px solid var(--border);
  padding: 4px 12px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  color: var(--fg);
  transition: background 0.15s;
}

.btn-clear:hover {
  background: var(--hover-bg, rgba(255,255,255,0.06));
}

.paper-groups {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: hidden;
}

.paper-group {
  flex: 1 1 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: rgba(255,255,255,0.02);
  overflow: hidden;
}

.paper-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: rgba(255,255,255,0.02);
  flex-shrink: 0;
}

.group-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.group-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 18px;
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(121, 192, 255, 0.14);
  color: var(--accent, #79c0ff);
  font-size: 10px;
  font-weight: 700;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.source-tag {
  display: inline-flex;
  align-items: center;
  margin-left: 8px;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.3px;
  vertical-align: middle;
}

.source-tag.scheduled {
  background: rgba(246, 193, 119, 0.15);
  color: #f6c177;
  border: 1px solid rgba(246, 193, 119, 0.30);
}

.source-tag.downloaded {
  background: rgba(126, 226, 168, 0.15);
  color: #7ee2a8;
  border: 1px solid rgba(126, 226, 168, 0.30);
}

.fetched-time {
  color: var(--accent, #79c0ff);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
}

.paper-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(255,255,255,0.02);
  cursor: pointer;
  transition: all 0.15s;
}

.paper-item:hover {
  border-color: rgba(121, 192, 255, 0.35);
  background: rgba(121, 192, 255, 0.06);
}

.paper-item.selected {
  border-color: rgba(121, 192, 255, 0.45);
  background: rgba(121, 192, 255, 0.10);
}

.paper-checkbox {
  padding-top: 2px;
  color: var(--muted);
}

.paper-info {
  flex: 1;
  min-width: 0;
}

.paper-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--fg);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.paper-meta {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  gap: 8px;
}

.action-bar {
  flex-shrink: 0;
  padding: 12px;
  border-top: 1px solid var(--border);
  background: rgba(255,255,255,0.02);
}

.btn-primary {
  width: 100%;
  height: 36px;
  padding: 0 14px;
  background: rgba(89, 153, 255, 0.18);
  color: var(--accent, #79c0ff);
  border: 1px solid rgba(121, 192, 255, 0.35);
  border-radius: 10px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: background 0.15s;
}

.btn-primary:hover:not(:disabled) {
  background: rgba(89, 153, 255, 0.28);
}

.btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-secondary {
  padding: 6px 14px;
  background: var(--bg2, rgba(255,255,255,0.03));
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
  color: var(--fg);
  font-size: 12px;
  transition: background 0.15s;
}

.btn-secondary:hover {
  background: var(--hover-bg, rgba(255,255,255,0.06));
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--muted);
}

.comparison-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
}

.comparison-item {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(255,255,255,0.02);
  cursor: pointer;
  transition: all 0.15s;
}

.comparison-item:hover {
  border-color: rgba(121, 192, 255, 0.35);
}

.comparison-item.active {
  border-color: rgba(121, 192, 255, 0.45);
  background: rgba(121, 192, 255, 0.10);
}

.comparison-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.comparison-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  color: var(--accent, #79c0ff);
}

.status {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 999px;
  text-transform: uppercase;
  border: 1px solid var(--border);
  font-weight: 600;
  letter-spacing: 0.3px;
}

.status.pending  { background: rgba(255,255,255,0.04); color: var(--muted); }
.status.running  { background: rgba(255, 200, 0, 0.15); color: #f6c177; border-color: rgba(246,193,119,0.35); }
.status.succeeded{ background: rgba(0, 255, 153, 0.15); color: #7ee2a8; border-color: rgba(126,226,168,0.35); }
.status.failed   { background: rgba(255,107,107,0.15); color: #ff6b6b; border-color: rgba(255,107,107,0.35); }

.comparison-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 8px;
}

.comparison-actions {
  display: flex;
  gap: 6px;
}

.btn-small {
  height: 28px;
  padding: 0 12px;
  font-size: 12px;
  background: var(--bg2, rgba(255,255,255,0.03));
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  color: var(--fg);
  transition: background 0.15s;
}

.btn-small:hover {
  background: var(--hover-bg, rgba(255,255,255,0.06));
}

.btn-small.danger {
  color: #ff6b6b;
  border-color: rgba(255,107,107,0.40);
  background: rgba(255,107,107,0.08);
}

.btn-small.danger:hover {
  background: rgba(255,107,107,0.16);
}

.loading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(11, 11, 16, 0.78);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--muted);
}

.spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--border);
  border-top-color: var(--accent, #79c0ff);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.result-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
