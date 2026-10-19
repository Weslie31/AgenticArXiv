<template>
  <div class="comparison-result-view">
    <!-- 对比状态提示 -->
    <div v-if="comparison?.status !== 'SUCCEEDED'" class="status-banner" :class="comparison?.status?.toLowerCase()">
      <template v-if="comparison?.status === 'RUNNING'">
        <span class="spinner-small"></span>
        对比分析进行中...
      </template>
      <template v-else-if="comparison?.status === 'PENDING'">
        ⏳ 对比任务待执行
      </template>
      <template v-else-if="comparison?.status === 'FAILED'">
        ❌ 对比失败: {{ comparison?.error || '未知错误' }}
      </template>
    </div>

    <!-- 论文列表概览 -->
    <div class="papers-overview">
      <h3>对比论文</h3>
      <div class="papers-grid">
        <div v-for="(paper, idx) in papers" :key="paper.id" class="paper-card">
          <div class="paper-number">{{ idx + 1 }}</div>
          <div class="paper-title">{{ paper.title || '无标题' }}</div>
          <div class="paper-authors" v-if="paper.authors?.length">
            {{ paper.authors.slice(0, 2).join(', ') }}{{ paper.authors.length > 2 ? ' et al.' : '' }}
          </div>
          <div class="paper-category" v-if="paper.primary_category">
            {{ paper.primary_category }}
          </div>
        </div>
      </div>
    </div>

    <!-- 对比报告 -->
    <template v-if="report && comparison?.status === 'SUCCEEDED'">
      <!-- 综合概述 -->
      <div class="report-section overview">
        <h3>📊 综合概述</h3>
        <p class="overview-text">{{ report.overview || '暂无概述' }}</p>
      </div>

      <!-- 维度对比 -->
      <div class="report-section dimensions">
        <h3>🔬 维度对比</h3>
        <div class="dimensions-list">
          <div v-for="dim in report.dimensions" :key="dim.name" class="dimension-card">
            <div class="dimension-header">
              <h4>{{ dim.name }}</h4>
              <div v-if="dim.ranking.length > 0" class="ranking">
                <span class="ranking-label">排名:</span>
                <span 
                  v-for="(pid, rank) in dim.ranking" 
                  :key="pid"
                  class="rank-item"
                  :class="{ 'rank-1': rank === 0, 'rank-2': rank === 1, 'rank-3': rank === 2 }"
                >
                  {{ getPaperTitle(pid) }}
                </span>
              </div>
            </div>

            <div class="dimension-values">
              <div v-for="(paper, idx) in papers" :key="paper.id" class="value-item">
                <div class="value-header">
                  <span class="paper-index">{{ idx + 1 }}</span>
                  <span class="paper-name">{{ paper.title?.slice(0, 40) || '无标题' }}...</span>
                </div>
                <div class="value-content">
                  {{ dim.paper_values[paper.id] || '暂无数据' }}
                </div>
              </div>
            </div>

            <div v-if="dim.summary" class="dimension-summary">
              <strong>总结:</strong> {{ dim.summary }}
            </div>
          </div>
        </div>
      </div>

      <!-- 推荐建议 -->
      <div class="report-section recommendations">
        <h3>💡 推荐建议</h3>
        <p class="recommendations-text">{{ report.recommendations || '暂无推荐' }}</p>
      </div>
    </template>

    <!-- 暂无报告 -->
    <div v-else-if="comparison?.status === 'SUCCEEDED' && !report" class="empty-report">
      <p>报告数据不存在</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Paper, PaperComparison, ComparisonReport } from '@/api/types';

const props = defineProps<{
  comparison?: PaperComparison;
  papers?: Paper[];
  report?: ComparisonReport | null;
}>();

const getPaperTitle = (paperId: string): string => {
  const paper = props.papers?.find(p => p.id === paperId);
  if (!paper) return paperId;
  const title = paper.title || '无标题';
  return title.length > 30 ? title.slice(0, 30) + '...' : title;
};
</script>

<style scoped>
/* === 与 PapersPanel 一致的暗主题变量色系 === */
.comparison-result-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0;
  color: var(--fg);
}

.status-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
  border: 1px solid var(--border);
}

.status-banner.pending {
  background: rgba(255,255,255,0.03);
  color: var(--muted);
}

.status-banner.running {
  background: rgba(246, 193, 119, 0.10);
  color: #f6c177;
  border-color: rgba(246,193,119,0.30);
}

.status-banner.failed {
  background: rgba(255,107,107,0.10);
  color: #ff6b6b;
  border-color: rgba(255,107,107,0.30);
}

.spinner-small {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(246, 193, 119, 0.4);
  border-top-color: #f6c177;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.papers-overview {
  margin-bottom: 18px;
}

.papers-overview h3 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.papers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}

.paper-card {
  padding: 12px;
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--border);
  border-radius: 10px;
  position: relative;
}

.paper-number {
  position: absolute;
  top: -8px;
  left: -8px;
  width: 22px;
  height: 22px;
  background: var(--accent, #79c0ff);
  color: #0b0b10;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
}

.paper-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
  line-height: 1.4;
  color: var(--fg);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.paper-authors {
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 4px;
}

.paper-category {
  font-size: 10px;
  color: var(--accent, #79c0ff);
  background: rgba(121, 192, 255, 0.12);
  padding: 1px 6px;
  border-radius: 4px;
  display: inline-block;
}

.report-section {
  margin-bottom: 18px;
}

.report-section h3 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.overview {
  padding: 14px;
  background: linear-gradient(135deg, rgba(121,192,255,0.08), rgba(121,192,255,0.03));
  border-radius: 10px;
  border: 1px solid rgba(121,192,255,0.25);
}

.overview-text {
  font-size: 13px;
  line-height: 1.7;
  color: var(--fg);
}

.dimensions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dimension-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  background: rgba(255,255,255,0.02);
}

.dimension-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 10px;
  flex-wrap: wrap;
  gap: 8px;
}

.dimension-header h4 {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
  color: var(--fg);
}

.ranking {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.ranking-label {
  color: var(--muted);
}

.rank-item {
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  color: var(--fg);
}

.rank-item.rank-1 {
  background: rgba(255, 215, 0, 0.18);
  color: #ffd966;
  border-color: rgba(255, 217, 102, 0.45);
  font-weight: 700;
}

.rank-item.rank-2 {
  background: rgba(192, 192, 192, 0.18);
  color: #d8d8e0;
  border-color: rgba(216, 216, 224, 0.35);
}

.rank-item.rank-3 {
  background: rgba(205, 127, 50, 0.20);
  color: #d39b6b;
  border-color: rgba(211, 155, 107, 0.40);
}

.dimension-values {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.value-item {
  padding: 10px 12px;
  background: rgba(255,255,255,0.02);
  border-radius: 8px;
  border-left: 3px solid var(--accent, #79c0ff);
}

.value-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.paper-index {
  width: 20px;
  height: 20px;
  background: var(--accent, #79c0ff);
  color: #0b0b10;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.paper-name {
  font-size: 12px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.value-content {
  font-size: 13px;
  line-height: 1.6;
  color: var(--fg);
}

.dimension-summary {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
  font-size: 12px;
  color: var(--muted);
}

.recommendations {
  padding: 14px;
  background: linear-gradient(135deg, rgba(126,226,168,0.10), rgba(121,192,255,0.06));
  border-radius: 10px;
  border: 1px solid rgba(126,226,168,0.30);
}

.recommendations-text {
  font-size: 13px;
  line-height: 1.7;
  color: var(--fg);
}

.empty-report {
  text-align: center;
  padding: 40px;
  color: var(--muted);
}
</style>
