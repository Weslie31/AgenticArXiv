<template>
  <div class="papers-page">
    <!-- 顶部 tab：📋 订阅规则 / 📚 订阅论文 -->
    <div class="page-tabs">
      <button
        class="page-tab"
        :class="{ active: activeTab === 'rules' }"
        @click="activeTab = 'rules'"
      >
        📋 订阅规则
        <span v-if="subscriptions?.length" class="tab-badge">{{ subscriptions?.length }}</span>
      </button>
      <button
        class="page-tab"
        :class="{ active: activeTab === 'papers' }"
        @click="activeTab = 'papers'"
      >
        📚 订阅论文
        <span v-if="store.scheduledPapers?.length" class="tab-badge">{{ store.scheduledPapers?.length }}</span>
      </button>
    </div>

    <!-- ============== Tab: 订阅规则 ============== -->
    <section v-show="activeTab === 'rules'" class="rules-section">
      <header class="card-header">
        <div class="title">定时订阅规则</div>
        <div class="row">
          <button class="btn" @click="fetchSubscriptions" :disabled="subsLoading">
            {{ subsLoading ? "刷新中…" : "刷新" }}
          </button>
          <button class="btn primary" @click="openCreate">
            ＋ 新建订阅
          </button>
        </div>
      </header>

      <div v-if="subsError" class="subs-error">❌ {{ subsError }}</div>

      <div v-if="subsLoading && !subscriptions.length" class="muted loading-row">
        加载中…
      </div>

      <div v-else-if="!subscriptions.length" class="muted empty-block">
        <p>还没有定时订阅</p>
        <p class="hint">点击右上角「＋ 新建订阅」开始配置规则，例如每周自动检索某领域的新论文。</p>
      </div>

      <div v-else class="subs-list">
        <div
          v-for="sub in subscriptions"
          :key="sub.id"
          class="subs-card"
          :class="{ disabled: !sub.enabled }"
        >
          <div class="subs-head">
            <label class="switch" :title="sub.enabled ? '点击停用' : '点击启用'">
              <input
                type="checkbox"
                :checked="sub.enabled"
                @change="toggleEnabled(sub)"
              />
              <span class="slider"></span>
            </label>
            <div class="subs-title">
              <span class="subs-name">{{ sub.name }}</span>
              <span class="subs-id mono">{{ sub.id }}</span>
            </div>
            <div class="subs-actions">
              <button
                class="btn small"
                @click="runOne(sub)"
                :disabled="runningId === sub.id"
                :title="`立即执行订阅 ${sub.name}`"
              >
                {{ runningId === sub.id ? "执行中…" : "▶ 立即执行" }}
              </button>
              <button class="btn small ghost" @click="openEdit(sub)">编辑</button>
              <button
                class="btn small ghost danger"
                @click="onDelete(sub)"
                :disabled="deletingId === sub.id"
              >
                {{ deletingId === sub.id ? "删除中…" : "删除" }}
              </button>
            </div>
          </div>

          <div class="subs-body">
            <div class="subs-row">
              <div class="subs-kv">
                <span class="k">分类</span>
                <span class="v">{{ sub.aspects?.length ? sub.aspects.join(", ") : "—" }}</span>
              </div>
              <div class="subs-kv">
                <span class="k">关键词</span>
                <span class="v">
                  <span v-if="sub.match_mode === 'all'" class="tag">全部匹配</span>
                  <span v-for="kw in sub.keywords" :key="kw" class="tag tag-kw">{{ kw }}</span>
                  <span v-if="!sub.keywords?.length">—</span>
                </span>
              </div>
              <div class="subs-kv" v-if="sub.exclude_keywords?.length">
                <span class="k">排除</span>
                <span class="v">
                  <span
                    v-for="kw in sub.exclude_keywords"
                    :key="kw"
                    class="tag tag-ex"
                  >{{ kw }}</span>
                </span>
              </div>
            </div>

            <div class="subs-row meta-row">
              <span class="meta-item">⏱ 区间 {{ sub.days }} 天</span>
              <span class="meta-item">📊 上限 {{ sub.max_results }} 篇</span>
              <span class="meta-item" v-if="sub.interval_minutes">
                🔁 每 {{ formatIntervalDisplay(sub.interval_minutes) }}
              </span>
              <span class="meta-item" v-else>🔁 仅手动触发</span>
              <span class="meta-item">📦 session: <span class="mono">{{ sub.session_id }}</span></span>
              <span class="meta-item" v-if="sub.last_run_at">
                🕒 上次执行 {{ formatTime(sub.last_run_at) }} ·
                新增 <b>{{ sub.last_run_count }}</b>
              </span>
              <span class="meta-item" v-else>🕒 尚未执行</span>
            </div>

            <div v-if="lastResults[sub.id]" class="subs-result">
              <div class="result-head">
                <b>最近一次执行结果</b>
                <span class="muted">
                  {{ formatTime(lastResults[sub.id]?.run_at) }} ·
                  耗时 {{ lastResults[sub.id]?.duration_ms }} ms ·
                  共 {{ lastResults[sub.id]?.papers_count }} 篇 /
                  新增 {{ lastResults[sub.id]?.new_papers_count }} 篇
                </span>
              </div>
              <div
                v-if="lastResults[sub.id]?.errors?.length"
                class="result-errors"
              >
                <div v-for="(err, ei) in lastResults[sub.id]?.errors" :key="ei">
                  ⚠️ {{ err }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 新建/编辑弹窗 -->
      <div
        v-if="editing"
        class="modal-mask"
        @click.self="closeEdit"
      >
        <div class="modal">
          <div class="modal-title">
            {{ editing.id ? "编辑订阅" : "新建订阅" }}
          </div>
          <label class="field">
            <span>订阅名称 *</span>
            <input class="input" v-model="editing.name" placeholder="如：每周 RAG 新论文" />
          </label>
          <label class="field" v-if="!editing.id">
            <span>订阅 ID（可选，留空自动生成）</span>
            <input class="input mono" v-model="editing.id" placeholder="留空自动生成" />
          </label>
          <label class="field">
            <span>分类（逗号分隔，留空不限）</span>
            <input class="input" v-model="editing._aspectsText" placeholder="如：cs.CL, cs.AI" />
          </label>
          <label class="field">
            <span>关键词（逗号分隔）</span>
            <input class="input" v-model="editing._keywordsText" placeholder="如：RAG, retrieval, agent" />
          </label>
          <label class="field">
            <span>关键词匹配模式</span>
            <select class="select" v-model="editing.match_mode">
              <option value="any">任一命中（召回多）</option>
              <option value="all">全部命中（更精确）</option>
            </select>
            <span class="field-hint">
              多个关键词时：任一=命中任意一个即可；全部=每个关键词都要出现（适合同一主题的多个限定词）
            </span>
          </label>
          <label class="field">
            <span>排除关键词（可选）</span>
            <input class="input" v-model="editing._excludeText" placeholder="如：survey, review" />
          </label>
          <div class="field-row">
            <label class="field small">
              <span>检索区间（天）</span>
              <input class="input" type="number" min="1" max="30" v-model.number="editing.days" />
            </label>
            <label class="field small">
              <span>最大结果数</span>
              <input class="input" type="number" min="1" max="100" v-model.number="editing.max_results" />
            </label>
            <label class="field small">
              <span>自动间隔（天，0=仅手动）</span>
              <input
                class="input"
                type="number"
                min="0"
                step="0.5"
                v-model.number="intervalDaysDisplay"
                placeholder="如：3"
              />
            </label>
          </div>
          <label class="field">
            <span>Session ID</span>
            <input class="input mono" v-model="editing.session_id" />
          </label>
          <label class="check-row">
            <input type="checkbox" v-model="editing.enabled" />
            <span>启用此订阅</span>
          </label>
          <div v-if="editError" class="edit-error">❌ {{ editError }}</div>
          <div class="modal-actions">
            <button class="btn ghost" @click="closeEdit">取消</button>
            <button class="btn primary" @click="saveEdit" :disabled="saving">
              {{ saving ? "保存中…" : "保存" }}
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- ============== Tab: 订阅论文（原面板，逻辑不变）============== -->
    <section v-show="activeTab === 'papers'" class="papers-section">
    <header class="card-header">
      <div class="title">定时订阅论文</div>

      <div class="row">
        <input class="input" v-model="q" placeholder="搜索标题/作者/arxiv id…" />
        <button class="btn" @click="store.refreshSnapshot()" :disabled="store.loading">刷新</button>
      </div>

      <!-- 批量操作工具条 -->
      <div class="bulk-bar" v-if="filteredPapers.length">
        <label class="bulk-check" :title="allSubSelected ? '取消全选' : '全选当前列表'">
          <input
            type="checkbox"
            :checked="allSubSelected"
            :indeterminate.prop="someSubSelected && !allSubSelected"
            @change="toggleSubSelectAll"
          />
          <span class="bulk-check-label">
            {{ allSubSelected ? "取消全选" : "全选" }}
          </span>
        </label>
        <span class="bulk-count">
          已选 <b>{{ selectedSub.size }}</b> / {{ filteredPapers.length }} 篇
        </span>
        <button
          class="btn small danger"
          :disabled="!selectedSub.size || bulkSubDeleting"
          @click="confirmBulkSubDelete"
        >
          {{ bulkSubDeleting ? "删除中…" : `🗑 删除选中 (${selectedSub.size})` }}
        </button>
        <button
          v-if="selectedSub.size"
          class="btn small ghost"
          @click="clearSubSelection"
        >清空选择</button>
      </div>

      <p class="muted">
        共 {{ filteredPapers.length }} 篇（定时订阅自动拉取的论文，不占用 session 临时记忆）
      </p>

      <div v-if="downloadFeedback" class="download-feedback" :class="downloadFeedback.ok ? 'ok' : 'err'">
        {{ downloadFeedback.msg }}
      </div>
    </header>

    <!-- 独立滚动区域：只滚表格，不滚整个右侧页面 -->
    <div class="table-scroll" v-if="filteredPapers.length">
      <table class="table">
        <thead>
          <tr>
            <th class="col-idx">#</th>
            <th class="col-check">
              <input
                type="checkbox"
                :checked="allSubSelected"
                :indeterminate.prop="someSubSelected && !allSubSelected"
                @change="toggleSubSelectAll"
                :title="allSubSelected ? '取消全选' : '全选'"
              />
            </th>
            <th>标题</th>
            <th class="col-auth">作者</th>
            <th class="col-time">时间</th>
            <th class="col-flag">下载</th>
            <th class="col-flag">翻译</th>
            <th class="col-flag">总结</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>

        <tbody>
          <template v-for="p in filteredPapers" :key="p.id">
            <tr :class="{ 'row-selected': selectedSub.has(p.id) }">
              <td class="mono col-idx">{{ indexOf(p.id) }}</td>
              <td class="col-check">
                <input
                  type="checkbox"
                  :checked="selectedSub.has(p.id)"
                  @change="toggleSubSelect(p.id)"
                  :title="selectedSub.has(p.id) ? '取消选中' : '选中'"
                />
              </td>

              <td>
                <div class="p-title">
                  {{ p.title }}
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

              <td class="col-op">
                <div class="ops">
                  <!-- 下载 -->
                  <button
                    class="btn icon"
                    :title="pdfReady(p.id) ? '下载 PDF（覆盖/更新缓存）' : '下载 PDF'"
                    aria-label="下载 PDF"
                    @click="handleDownload(p.id)"
                    :disabled="downloadingPaperId === p.id"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <path d="M12 3v10"></path>
                      <path d="M8 9l4 4 4-4"></path>
                      <path d="M4 20h16"></path>
                      <path d="M6 20v-4"></path>
                      <path d="M18 20v-4"></path>
                    </svg>
                  </button>

                  <!-- 翻译 -->
                  <button
                    class="btn primary icon"
                    :title="trReady(p.id) ? '重新翻译（更新翻译缓存）' : '翻译 PDF'"
                    aria-label="翻译 PDF"
                    @click="store.translateById(p.id)"
                    :disabled="store.loading"
                  >
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
                    :disabled="!pdfAccessible(p.id)"
                  >
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
                    @click="toggleSummary(p.id)"
                    :disabled="!pdfReady(p.id) || store.loading"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z"></path>
                      <path d="M5 19l1 2 2-1-1-2-2 1z"></path>
                      <path d="M19 5l1 2 2-1-1-2-2 1z"></path>
                    </svg>
                  </button>

                  <!-- RAG 提问 -->
                  <button
                    class="btn icon"
                    :title="pdfReady(p.id) ? 'RAG 提问（进入论文问答）' : '请先下载 PDF'"
                    aria-label="RAG 提问"
                    @click="store.goToRagPage(p.id)"
                    :disabled="!pdfReady(p.id)"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                      <circle cx="12" cy="12" r="10"></circle>
                      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                      <circle cx="12" cy="17" r="0.5" fill="currentColor"></circle>
                    </svg>
                  </button>

                  <!-- 🗑 单删 -->
                  <button
                    class="btn icon danger"
                    title="从订阅论文列表中删除这篇（不影响缓存/翻译/总结）"
                    aria-label="删除论文"
                    @click="confirmDeleteSubOne(p)"
                    :disabled="deletingSubId === p.id"
                  >
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
                      @click="store.summarizeById(p.id)"
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
      暂无论文（定时订阅尚未拉取到论文，请检查设置中的领域配置）
    </div>

  </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useAppStore } from "@/stores/appStore";
import { api } from "@/api/client";
import type {
  Subscription,
  SubscriptionCreatePayload,
  SubscriptionResult,
} from "@/api/types";

const store = useAppStore();

// ========== 订阅论文：单删 / 批量删除 ==========
const selectedSub = ref<Set<string>>(new Set());
const deletingSubId = ref<string | null>(null);
const bulkSubDeleting = ref(false);

const allSubSelected = computed(
  () =>
    !!filteredPapers.value.length &&
    selectedSub.value.size === filteredPapers.value.length
);
const someSubSelected = computed(
  () =>
    selectedSub.value.size > 0 &&
    selectedSub.value.size < filteredPapers.value.length
);

function toggleSubSelect(paperId: string) {
  const next = new Set(selectedSub.value);
  if (next.has(paperId)) next.delete(paperId);
  else next.add(paperId);
  selectedSub.value = next;
}

function toggleSubSelectAll() {
  if (allSubSelected.value) selectedSub.value = new Set();
  else selectedSub.value = new Set(filteredPapers.value.map((p) => p.id));
}

function clearSubSelection() {
  selectedSub.value = new Set();
}

function shortSubTitle(p: any, max = 32): string {
  const t = (p?.title || "").replace(/\s+/g, " ").trim();
  return t.length > max ? t.slice(0, max) + "…" : t;
}

async function confirmDeleteSubOne(p: any) {
  const ok = confirm(
    `确认从「订阅论文」中删除？\n\n` +
    `  标题：${shortSubTitle(p, 50)}\n` +
    `  ID：${p.id}\n\n` +
    `（仅从列表移除，不影响已下载的 PDF / 翻译 / 总结缓存）`
  );
  if (!ok) return;
  deletingSubId.value = p.id;
  try {
    await store.removeScheduledPapers([p.id]);
    if (selectedSub.value.has(p.id)) {
      const next = new Set(selectedSub.value);
      next.delete(p.id);
      selectedSub.value = next;
    }
  } catch (e) {
    console.warn("[SubscriptionsPanel] delete failed", e);
  } finally {
    deletingSubId.value = null;
  }
}

async function confirmBulkSubDelete() {
  const ids = Array.from(selectedSub.value);
  if (!ids.length) return;
  const ok = confirm(
    `确认删除选中的 ${ids.length} 篇订阅论文？\n\n` +
    `（仅从列表移除，不影响已下载的 PDF / 翻译 / 总结缓存）`
  );
  if (!ok) return;
  bulkSubDeleting.value = true;
  try {
    await store.removeScheduledPapers(ids);
    selectedSub.value = new Set();
  } catch (e) {
    console.warn("[SubscriptionsPanel] bulk delete failed", e);
  } finally {
    bulkSubDeleting.value = false;
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

// ========== Tab 切换 ==========
const activeTab = ref<"rules" | "papers">("rules");

// ========== 订阅规则 state ==========
const subscriptions = ref<Subscription[]>([]);
const subsLoading = ref(false);
const subsError = ref("");
const runningId = ref<string | null>(null);
const deletingId = ref<string | null>(null);
const lastResults = ref<Record<string, SubscriptionResult | null>>({});
const saving = ref(false);
const editError = ref("");

interface EditingState {
  id: string;
  name: string;
  _aspectsText: string;
  _keywordsText: string;
  _excludeText: string;
  days: number;
  max_results: number;
  enabled: boolean;
  session_id: string;
  match_mode: "any" | "all";
  interval_minutes: number | null;
}
// minutes <-> days display conversion
const intervalOptions = [
  { label: "5 分钟", value: 5 },
  { label: "6 小时", value: 360 },
  { label: "1 天", value: 1440 },
  { label: "3 天", value: 4320 },
  { label: "7 天", value: 10080 },
];
const intervalDaysDisplay = computed({
  get: () => {
    const v = editing.value?.interval_minutes;
    if (!v) return null;
    const days = v / 1440;
    return Number(days.toFixed(2));
  },
  set: (days: number | null) => {
    if (!editing.value) return;
    if (days === null) {
      editing.value.interval_minutes = null;
    } else {
      editing.value.interval_minutes = Math.round(days * 1440);
    }
  },
});

function formatIntervalDisplay(minutes: number | null | undefined): string {
  if (!minutes) return "仅手动";
  const days = minutes / 1440;
  if (days >= 1) return `${days} 天`;
  const hours = minutes / 60;
  if (hours >= 1) return `${hours} 小时`;
  return `${minutes} 分钟`;
}

const editing = ref<EditingState | null>(null);
const q = ref("");
const expandedSummaryIndex = ref<number>(-1);
const downloadingPaperId = ref<string | null>(null);
const downloadFeedback = ref<{ id: string; msg: string; ok: boolean } | null>(null);

async function handleDownload(paperId: string) {
  if (downloadingPaperId.value) return;
  downloadingPaperId.value = paperId;
  downloadFeedback.value = null;
  store.loading = true;
  try {
    const res = await api.post("/pdf/download", {
      session_id: store.sessionId,
      paper_id: paperId,
      force: false,
    });
    downloadFeedback.value = {
      id: paperId,
      msg: `下载完成：${(res.data?.size_bytes / 1024).toFixed(0)} KB`,
      ok: true,
    };
    await store.refreshSnapshot();
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || String(e);
    downloadFeedback.value = {
      id: paperId,
      msg: `下载失败：${msg}`,
      ok: false,
    };
  } finally {
    downloadingPaperId.value = null;
    store.loading = false;
    setTimeout(() => (downloadFeedback.value = null), 4000);
  }
}

const filteredPapers = computed(() => {
  const kw = q.value.trim().toLowerCase();
  if (!kw) return store.scheduledPapers;
  return store.scheduledPapers.filter((p) => {
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

function indexOf(paperId: string): number {
  const i = store.scheduledPapers.findIndex((p) => p.id === paperId);
  return i >= 0 ? i + 1 : -1;
}

// 过滤结果变化时清理无效选中
watch(
  () => filteredPapers.value.map((p) => p.id).join(","),
  () => {
    const validIds = new Set(filteredPapers.value.map((p) => p.id));
    let changed = false;
    const next = new Set<string>();
    for (const id of selectedSub.value) {
      if (validIds.has(id)) next.add(id);
      else changed = true;
    }
    if (changed) selectedSub.value = next;
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
  if (id.startsWith("10.") && id.includes("/")) return `https://doi.org/${id}`;
  if (id.startsWith("W") && /^\d+$/.test(id.slice(1))) return `https://openalex.org/${id}`;
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

function pdfDownloadError(paperId: string): string {
  const a = store.pdfMap.get(paperId);
  return a?.error || "";
}

async function copyPaperLink(p: any) {
  const url = paperIdHref(p.id) || p.paper_url || p.pdf_url || "";
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    store.pushAssistant?.(`已复制链接: ${url}`);
  } catch {
    store.pushAssistant?.(`请手动复制: ${url}`);
  }
}

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

async function toggleSummary(paperId: string) {
  expandedSummaryIndex.value = store.scheduledPapers.findIndex((p) => p.id === paperId) + 1;
  const status = summaryStatus(paperId);
  if (status === "NOT_SUMMARIZED") {
    await store.summarizeById(paperId);
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

function openPreview(paper: any) {
  // 预览按钮始终展示原文（眼睛图标 = 预览原始 PDF）。
  // 翻译版通过订阅行的"查看翻译后论文"按钮（external-link 图标）打开。
  if (pdfAccessible(paper.id)) {
    store.openRawPdf(paper.id);
  }
}

// ========== 订阅规则：CRUD + 启停 + 立即执行 ==========

async function fetchSubscriptions() {
  subsLoading.value = true;
  subsError.value = "";
  try {
    const resp = await api.get<Subscription[]>("/subscriptions");
    subscriptions.value = resp.data || [];
    // 后台并行拉取每个订阅的最近一次结果（不影响主流程）
    for (const sub of subscriptions.value) {
      if (sub.last_run_at) {
        fetchResult(sub.id, false).catch(() => {});
      }
    }
  } catch (e: any) {
    subsError.value = e?.response?.data?.detail || e?.message || String(e);
  } finally {
    subsLoading.value = false;
  }
}

async function fetchResult(subId: string, showError = false) {
  try {
    const resp = await api.get<SubscriptionResult>(
      `/subscriptions/${encodeURIComponent(subId)}/result`,
    );
    lastResults.value[subId] = resp.data;
  } catch (e: any) {
    if (showError) {
      console.warn(`[Sub] fetch result failed for ${subId}:`, e);
    }
    if (e?.response?.status === 404) {
      lastResults.value[subId] = null;
    }
  }
}

function splitText(s: string): string[] {
  return s
    .split(/[,，]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function openCreate() {
  editing.value = {
    id: "",
    name: "",
    _aspectsText: "",
    _keywordsText: "",
    _excludeText: "",
    days: 7,
    max_results: 15,
    enabled: true,
    session_id: store.sessionId,
    match_mode: "any",
    interval_minutes: null,
  };
  editError.value = "";
}

function openEdit(sub: Subscription) {
  editing.value = {
    id: sub.id,
    name: sub.name,
    _aspectsText: (sub.aspects || []).join(", "),
    _keywordsText: (sub.keywords || []).join(", "),
    _excludeText: (sub.exclude_keywords || []).join(", "),
    days: sub.days,
    max_results: sub.max_results,
    enabled: sub.enabled,
    session_id: sub.session_id,
    match_mode: sub.match_mode || "any",
    interval_minutes: sub.interval_minutes,
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
  if (!e.name.trim()) {
    editError.value = "订阅名称不能为空";
    return;
  }
  saving.value = true;
  editError.value = "";
  try {
    if (!e.id || !e.id.trim()) {
      const payload: SubscriptionCreatePayload = {
        name: e.name.trim(),
        aspects: splitText(e._aspectsText),
        keywords: splitText(e._keywordsText),
        exclude_keywords: splitText(e._excludeText),
        days: e.days,
        max_results: e.max_results,
        enabled: e.enabled,
        session_id: e.session_id || "default",
        match_mode: e.match_mode,
        interval_minutes: e.interval_minutes || null,
      };
      await api.post("/subscriptions", payload);
    } else {
      const payload = {
        name: e.name.trim(),
        aspects: splitText(e._aspectsText),
        keywords: splitText(e._keywordsText),
        exclude_keywords: splitText(e._excludeText),
        days: e.days,
        max_results: e.max_results,
        enabled: e.enabled,
        match_mode: e.match_mode,
        interval_minutes: e.interval_minutes || null,
      };
      await api.patch(
        `/subscriptions/${encodeURIComponent(e.id)}`,
        payload,
      );
    }
    editing.value = null;
    await fetchSubscriptions();
  } catch (err: any) {
    editError.value = err?.response?.data?.detail || err?.message || String(err);
  } finally {
    saving.value = false;
  }
}

async function onDelete(sub: Subscription) {
  if (!confirm(`确认删除订阅「${sub.name}」？该操作不可撤销。`)) return;
  deletingId.value = sub.id;
  try {
    await api.delete(`/subscriptions/${encodeURIComponent(sub.id)}`);
    await fetchSubscriptions();
  } catch (err: any) {
    subsError.value = err?.response?.data?.detail || err?.message || String(err);
  } finally {
    deletingId.value = null;
  }
}

async function toggleEnabled(sub: Subscription) {
  try {
    await api.patch(`/subscriptions/${encodeURIComponent(sub.id)}`, {
      enabled: !sub.enabled,
    });
    sub.enabled = !sub.enabled;
  } catch (err: any) {
    subsError.value = err?.response?.data?.detail || err?.message || String(err);
  }
}

async function runOne(sub: Subscription) {
  runningId.value = sub.id;
  subsError.value = "";
  try {
    const resp = await api.post<SubscriptionResult>(
      `/subscriptions/${encodeURIComponent(sub.id)}/run`,
    );
    lastResults.value[sub.id] = resp.data;
    sub.last_run_count = resp.data.new_papers_count;
    sub.last_run_at = resp.data.run_at;
    await store.refreshSnapshot();
  } catch (err: any) {
    subsError.value = err?.response?.data?.detail || err?.message || String(err);
  } finally {
    runningId.value = null;
  }
}

onMounted(async () => {
  fetchSubscriptions();
  // 总是刷新订阅论文，确保拿到定时任务最新拉到的论文
  await store.refreshSnapshot();
  // 顺手拉一次收藏/标签 flags（用于行内 ⭐ / 🏷️ 渲染）
  if (store.scheduledPapers && store.scheduledPapers.length) {
    await store.fetchPaperFlags(store.scheduledPapers.map((p) => p.id));
  }
});

// 订阅论文列表变化时也补一次 flags
watch(
  () => store.scheduledPapers.map((p) => p.id).join(","),
  async () => {
    if (store.scheduledPapers && store.scheduledPapers.length) {
      await store.fetchPaperFlags(store.scheduledPapers.map((p) => p.id));
    }
  },
);
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

.download-feedback {
  margin-top: 8px;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
}
.download-feedback.ok { background: rgba(0,200,100,.15); color: #4caf50; }
.download-feedback.err { background: rgba(200,50,50,.15); color: #f44336; }

.table-scroll {
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
  position: sticky;
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

.btn.small {
  height: 26px;
  font-size: 12px;
  padding: 0 10px;
  border-radius: 6px;
}
.btn.ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  cursor: pointer;
}
.btn.ghost:hover { background: rgba(255,255,255,0.05); }

/* 操作列 */
.ops { display:flex; gap:4px; align-items:center; flex-wrap:nowrap; }

.col-idx { width: 40px; text-align:center; color: var(--muted); font-size: 12px; }
.col-auth { max-width: 200px; }
.col-time { max-width: 160px; font-size: 11px; white-space: nowrap; }
.col-flag { width: 60px; text-align:center; }
.col-op { width: 170px; }

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
  flex-shrink: 0;
}
.btn.icon svg {
  width: 14px;
  height: 14px;
}
.btn.icon:hover { background: rgba(255,255,255,0.08); }
.btn.icon:disabled { opacity: 0.4; cursor: not-allowed; }
.btn.icon.primary { background: rgba(121,192,255,0.12); border-color: rgba(121,192,255,0.3); }
.btn.icon.primary:hover { background: rgba(121,192,255,0.22); }
.btn { height: 30px; font-size: 13px; padding: 0 12px; border-radius: 6px; cursor: pointer; transition: background 0.15s; }
.btn:not(.icon):hover { filter: brightness(1.15); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; filter: none; }
.btn.primary { background: rgba(121,192,255,0.15); border: 1px solid rgba(121,192,255,0.3); color: var(--accent,#79c0ff); }

.empty {
  padding: 40px;
  text-align: center;
  color: var(--muted);
  font-size: 14px;
  flex: 1;
}

.fetched-at { margin-top: 2px; color: var(--accent,#79c0ff); }

/* ========== 订阅页面 tab + 订阅规则 UI ========== */

.papers-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.page-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border);
}
.page-tab {
  background: transparent;
  border: none;
  color: var(--muted);
  padding: 8px 14px;
  cursor: pointer;
  font-size: 13px;
  border-bottom: 2px solid transparent;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.page-tab.active {
  color: var(--fg);
  border-bottom-color: var(--accent);
}
.tab-badge {
  background: rgba(58, 142, 230, 0.2);
  color: var(--accent);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
}

.rules-section,
.papers-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.loading-row,
.empty-block {
  padding: 24px 12px;
  text-align: center;
}
.empty-block .hint {
  font-size: 12px;
  margin-top: 4px;
  color: var(--muted);
}

.subs-error {
  background: rgba(217, 106, 106, 0.12);
  color: #d96a6a;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
}

.subs-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.subs-card {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--card-bg, rgba(255, 255, 255, 0.02));
  padding: 12px 14px;
  transition: opacity 0.2s;
}
.subs-card.disabled {
  opacity: 0.55;
}

.subs-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.subs-title {
  flex: 1;
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.subs-name {
  font-weight: 600;
  font-size: 14px;
}
.subs-id {
  font-size: 11px;
  color: var(--muted);
}
.subs-actions {
  display: flex;
  gap: 6px;
}

.subs-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.subs-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: var(--muted);
}
.meta-row {
  border-top: 1px dashed var(--border);
  padding-top: 6px;
}
.meta-item {
  white-space: nowrap;
}
.subs-kv {
  display: inline-flex;
  gap: 6px;
  align-items: baseline;
}
.subs-kv .k {
  color: var(--muted);
}
.subs-kv .v {
  color: var(--fg);
}

.tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 8px;
  font-size: 11px;
  margin-right: 4px;
  margin-bottom: 2px;
}
.tag-kw {
  background: rgba(58, 142, 230, 0.18);
  color: var(--accent);
}
.tag-ex {
  background: rgba(217, 106, 106, 0.18);
  color: #d96a6a;
}

.subs-result {
  margin-top: 8px;
  padding: 8px 10px;
  border: 1px solid rgba(58, 142, 230, 0.3);
  background: rgba(58, 142, 230, 0.05);
  border-radius: 4px;
  font-size: 12px;
}
.result-head {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--fg);
}
.result-errors {
  margin-top: 6px;
  color: #d96a6a;
}

/* iOS 风格开关 */
.switch {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
}
.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}
.slider {
  position: absolute;
  inset: 0;
  background: #4a4a4a;
  border-radius: 20px;
  cursor: pointer;
  transition: background 0.2s;
}
.slider::before {
  content: "";
  position: absolute;
  width: 14px;
  height: 14px;
  left: 3px;
  top: 3px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
}
.switch input:checked + .slider {
  background: var(--accent, #3a8ee6);
}
.switch input:checked + .slider::before {
  transform: translateX(16px);
}

/* 编辑/新建弹窗 */
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}
.modal {
  width: 540px;
  max-width: 92vw;
  max-height: 90vh;
  overflow-y: auto;
  background: var(--modal-bg, #1e1e1e);
  border: 1px solid var(--border, #333);
  border-radius: 8px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}
.modal-title {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 4px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted, #aaa);
}
.field.small {
  flex: 1;
}
.field-row {
  display: flex;
  gap: 10px;
}
.check-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
}
.edit-error {
  color: #d96a6a;
  font-size: 12px;
}

.btn.danger {
  color: #d96a6a;
}
.btn.danger:hover:not(:disabled) {
  background: rgba(217, 106, 106, 0.12);
}

/* ============ 收藏 / Tag 行内样式（与 PapersPanel 保持一致） ============ */
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

/* ============ 订阅论文：单删 / 批量选择样式 ============ */
.col-check { width: 36px; text-align: center; }
.col-check input[type="checkbox"] {
  cursor: pointer;
  width: 14px;
  height: 14px;
  accent-color: var(--accent, #79c0ff);
}

tr.row-selected {
  background: rgba(121, 192, 255, 0.06);
}

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
.bulk-count { font-size: 12px; color: var(--muted); }

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
</style>
