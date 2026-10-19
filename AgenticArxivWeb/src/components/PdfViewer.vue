<template>
  <Teleport to="body">
    <div class="pdf-viewer-overlay" @click.self="close">
      <div class="pdf-viewer-container" ref="panelRef">
        <header class="toolbar">
          <span class="toolbar-title">{{ title || paperId }}</span>
          <div class="toolbar-controls">
            <button class="btn-icon" @click="page--" :disabled="page <= 1" title="上一页">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="15 18 9 12 15 6"></polyline>
              </svg>
            </button>
            <span class="page-info">{{ page }} / {{ totalPages }}</span>
            <button class="btn-icon" @click="page++" :disabled="page >= totalPages" title="下一页">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </button>
            <span class="divider"></span>
            <button class="btn-icon" @click="zoomOut" title="缩小">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="8" y1="11" x2="14" y2="11"></line>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
            </button>
            <span class="scale-info">{{ renderWidth }}px</span>
            <button class="btn-icon" @click="zoomIn" title="放大">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="8" y1="11" x2="14" y2="11"></line>
                <line x1="11" y1="8" x2="11" y2="14"></line>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
            </button>
            <span class="divider"></span>
            <button
              class="btn-icon"
              @click="fitToWidth"
              title="适合宽度 (Fit)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 8h2V5h3V3H3v5z"></path>
                <path d="M21 8h-2V5h-3V3h5v5z"></path>
                <path d="M3 16h2v3h3v2H3v-5z"></path>
                <path d="M21 16h-2v3h-3v2h5v-5z"></path>
              </svg>
            </button>
            <span class="divider"></span>
            <div
              class="pdf-variant-toggle"
              :class="{ disabled: !hasTranslated || !translatedUrl }"
              :title="hasTranslated && translatedUrl ? '切换原版 / 翻译版 PDF' : '该论文尚未翻译，无法查看翻译版 PDF'"
            >
              <button
                class="pdf-variant-btn"
                :class="{ active: variant === 'original' }"
                :disabled="!hasTranslated && false"
                @click="switchVariant('original')"
              >原版</button>
              <button
                class="pdf-variant-btn"
                :class="{ active: variant === 'translated' }"
                :disabled="!hasTranslated || !translatedUrl"
                @click="switchVariant('translated')"
              >翻译版</button>
            </div>
            <span class="divider"></span>
            <button
              v-if="paperId"
              class="btn-icon btn-rag"
              @click="openInRag()"
              title="到 RAG 问答"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>
              </svg>
            </button>
            <a v-if="downloadUrl" :href="downloadUrl" class="btn-icon" download target="_blank" title="下载">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 3v10"></path>
                <path d="M8 9l4 4 4-4"></path>
                <path d="M4 20h16"></path>
              </svg>
            </a>
            <button class="btn-icon btn-close" @click="close" title="关闭 (Esc)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
        </header>

          <!-- variant 变化时 :key 不同，Vue 彻底销毁并重建整个 vue-pdf-embed 树 -->
          <!-- 翻译版 / 原版都用同一套 vue-pdf-embed，保证 text-layer → RAG 联动 -->
          <div class="pdf-content" ref="containerRef">
            <div class="pdf-embed-wrapper">
              <vue-pdf-embed
                v-if="workerReady"
                :key="`${variant}-${pdfEmbedKey}`"
                :source="currentUrl"
                :page="page"
                :width="renderWidth"
                :text-layer="true"
                @loaded="onLoaded"
                @loading-failed="onError"
                @error="onError"
                class="pdf-embed"
              />

              <div v-if="loading" class="loading">
                <div class="spinner"></div>
                <span>加载中...</span>
              </div>
              <div v-else-if="error" class="error">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"></circle>
                  <line x1="12" y1="8" x2="12" y2="12"></line>
                  <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                <span>{{ error }}</span>
              </div>
            </div>

            <!-- 选中浮窗 -->
            <div
              v-if="selection.visible && selection.text"
              class="selection-popover"
              :style="{ top: selection.top + 'px', left: selection.left + 'px' }"
              @mousedown.prevent
            >
              <div class="selection-popover-meta">
                第 {{ page }} 页 · {{ selection.text.length }} 字符
              </div>
              <button class="selection-popover-btn" @click="askSelection">
                💬 问一下这段
              </button>
              <button class="selection-popover-btn ghost" @click="dismissSelection">
                取消
              </button>
            </div>
          </div>
        </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
  import { ref, computed, onMounted, onUnmounted, reactive, watch, nextTick } from 'vue'
import VuePdfEmbed from 'vue-pdf-embed'
import 'vue-pdf-embed/dist/styles/textLayer.css'
import 'vue-pdf-embed/dist/styles/annotationLayer.css'
import { useAppStore } from '@/stores/appStore'

// worker 文件已拷贝到 public/pdf.worker.min.mjs，vite 原样 serve 真实文件。
const PDF_WORKER_URL = '/pdf.worker.min.mjs'

// overridePdfJsWorker 必须在 vue-pdf-embed 加载之后调用，
// 因为 vue-pdf-embed 的 import 才会在 window.pdfjsLib 上设置 GlobalWorkerOptions。
// 在模块顶层（import 尚未解析完成）调用时 target 为 null，override 无效。
function overridePdfJsWorker() {
  const target: any =
    (globalThis as any).pdfjsLib ||
    (typeof window !== 'undefined' ? (window as any).pdfjsLib : null)
  if (target && target.GlobalWorkerOptions) {
    target.GlobalWorkerOptions.workerSrc = PDF_WORKER_URL
    console.debug('[PdfViewer] pdf.worker overridden to', PDF_WORKER_URL)
  } else {
    console.warn('[PdfViewer] pdfjsLib not found yet, worker override skipped')
  }
}

// workerReady = true 时才渲染 vue-pdf-embed，确保 worker override 先完成。
const workerReady = ref(false)

// 组件挂载时调用，此时 vue-pdf-embed 已完成初始化
onMounted(() => {
  overridePdfJsWorker()
  workerReady.value = true
})

const props = defineProps<{
  url: string
  paperId?: string
  title?: string
  downloadUrl?: string
  initialPage?: number
  // 翻译 PDF 可选：未提供 / 论文未翻译时只显示原版
  translatedUrl?: string
  hasTranslated?: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const store = useAppStore()

const page = ref(props.initialPage && props.initialPage > 0 ? props.initialPage : 1)
const totalPages = ref(0)
// PDF 页面渲染目标宽度（CSS px），传给 vue-pdf-embed 的 :width。
// 直接给像素宽度比 scale 倍数更可控，vue-pdf-embed 会按 PDF 原始比例算出对应 height。
const renderWidth = ref(1200)
const minWidth = 400
const maxWidth = 3200
const loading = ref(true)
const error = ref<string | null>(null)
// 外层容器 ref（不收缩，反映真实可用宽度）
const panelRef = ref<HTMLElement | null>(null)
// pdf-content ref（仍用于定位 selection 浮窗）
const containerRef = ref<HTMLElement | null>(null)

// 按面板容器可用宽度算出合适的 renderWidth（让 PDF 几乎填满面板）。
// 注意：不能读 containerRef.clientWidth（flex+center 会收缩到 pdf 宽度，导致一直算成当前宽度）
function autoFitWidth() {
  const panel = panelRef.value || containerRef.value
  if (!panel) return
  // 留 40px 边距（pdf-content padding: 20px 左右），并预留 4px 给阴影
  const avail = panel.clientWidth - 44
  if (avail <= 0) return
  const target = Math.max(minWidth, Math.min(maxWidth, avail))
  // 仅当差异明显时（≥20px）才更新，避免抖动
  if (Math.abs(target - renderWidth.value) >= 20) {
    renderWidth.value = target
  }
}

// 用户手动调过缩放后，短时间内不自动覆盖
let userAdjustUntil = 0
function markUserAdjust() {
  userAdjustUntil = Date.now() + 1500
}

// 多帧 fit：等 vue-pdf-embed 重渲染稳定后再算最终 width
let rafId: number | null = null
let resizeObserver: ResizeObserver | null = null
function scheduleFit() {
  if (Date.now() < userAdjustUntil) return
  if (rafId !== null) cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(() => {
    rafId = null
    if (Date.now() < userAdjustUntil) return
    autoFitWidth()
    requestAnimationFrame(() => {
      if (Date.now() < userAdjustUntil) return
      autoFitWidth()
      requestAnimationFrame(autoFitWidth)
    })
  })
}

function zoomIn() {
  markUserAdjust()
  renderWidth.value = Math.min(maxWidth, renderWidth.value + 80)
}
function zoomOut() {
  markUserAdjust()
  renderWidth.value = Math.max(minWidth, renderWidth.value - 80)
}
function fitToWidth() {
  markUserAdjust()
  renderWidth.value = 1200
  scheduleFit()
}

// 文字选中浮窗
const selection = reactive({
  visible: false,
  text: '',
  top: 0,
  left: 0,
})

// === PDF 加载配置（含 CMap 路径，用于中文等非拉丁字符）===
const PDF_CMAP_URL = '/cmaps/'
function buildPdfSource(url: string) {
  return { url, withCredentials: true, cMapUrl: PDF_CMAP_URL, cMapPacked: true }
}

const variant = ref<'original' | 'translated'>('original')
// 存储完整的 pdf.js source config 对象，而非纯 URL
const currentUrl = ref<ReturnType<typeof buildPdfSource>>(
  buildPdfSource(props.url || '')
)
// 给 vue-pdf-embed 一个 key：URL 变化时强制重建组件（确保切换时一定会重新加载）
const pdfEmbedKey = ref(`0:${Date.now()}`)

// 翻译 URL 或论文未翻译时，永远停在原版
const canShowTranslated = computed(
  () => !!props.translatedUrl && !!props.hasTranslated
)

// 切换 variant：靠 :key 变化触发 vue-pdf-embed 完整销毁/重建，确保 pdfjs 彻底重新加载
async function switchVariant(v: 'original' | 'translated') {
  if (v === 'translated' && !canShowTranslated.value) return
  if (variant.value === v) return
  variant.value = v
  let newUrl = v === 'translated' && props.translatedUrl
    ? props.translatedUrl
    : props.url
  // 翻译版追加 cache buster，强制 pdfjs worker 重新下载 PDF
  if (v === 'translated') {
    const sep = newUrl.includes('?') ? '&' : '?'
    newUrl = `${newUrl}${sep}_nocache=${Date.now()}`
  }
  // 先清空 URL，等 vue-pdf-embed 销毁 → 再给新 URL → 触发完整重建
  currentUrl.value = buildPdfSource('')
  loading.value = true
  error.value = null
  page.value = 1
  totalPages.value = 0
  dismissSelection()
  await nextTick()
  // 组件销毁后（因为 key 会变），给新 URL
  currentUrl.value = buildPdfSource(newUrl)
  // key 依赖 currentUrl，变化时强制 vue-pdf-embed 销毁旧树并重建
  pdfEmbedKey.value = `${variant.value}:${Date.now()}`
  console.log('[PdfViewer] switchVariant ->', v, newUrl)
}

// 当父组件传入新 URL 时（比如重新打开 viewer），重置状态
watch(
  () => [props.url, props.translatedUrl, props.hasTranslated] as const,
  ([u, tu, ht]) => {
    if (!u) return
    // 默认优先展示翻译版（如果有），否则原版
    const wantTranslated = !!tu && !!ht
    const nextUrl = wantTranslated ? (tu as string) : u
    variant.value = wantTranslated ? 'translated' : 'original'
    currentUrl.value = buildPdfSource(nextUrl)
    pdfEmbedKey.value = `${variant.value}:${Date.now()}`
    page.value = props.initialPage && props.initialPage > 0 ? props.initialPage : 1
    totalPages.value = 0
    loading.value = true
    error.value = null
    console.log(
      '[PdfViewer] watch reset ->',
      variant.value,
      nextUrl,
      'hasTranslated=', ht,
      'wantTranslated=', wantTranslated,
    )
  },
  { immediate: true }
)

function onLoaded(pdf: { numPages: number }) {
  loading.value = false
  totalPages.value = pdf.numPages
  error.value = null
  console.log('[PdfViewer] onLoaded', {
    variant: variant.value,
    sourceUrl: currentUrl.value.url,
    propsUrl: props.url,
    propsTranslatedUrl: props.translatedUrl,
    propsHasTranslated: props.hasTranslated,
    totalPages: pdf.numPages,
  })
  // 多帧 fit，等 vue-pdf-embed 重渲染稳定后再算最终 scale
  scheduleFit()
}

function onError(err: Error) {
  loading.value = false
  error.value = err.message || 'PDF 加载失败'
  console.error('[PdfViewer] onError', {
    variant: variant.value,
    sourceUrl: currentUrl.value,
    propsUrl: props.url,
    propsTranslatedUrl: props.translatedUrl,
    propsHasTranslated: props.hasTranslated,
    error: err.message,
  })
}

function close() {
  emit('close')
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (selection.visible) {
      dismissSelection()
    } else {
      close()
    }
  } else if (e.key === 'ArrowLeft') {
    page.value = Math.max(1, page.value - 1)
    dismissSelection()
  } else if (e.key === 'ArrowRight') {
    page.value = Math.min(totalPages.value, page.value + 1)
    dismissSelection()
  }
}

function getSelectionInViewer(): { text: string; rect: DOMRect | null } {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return { text: '', rect: null }
  const text = sel.toString().trim()
  if (!text || text.length < 2) return { text: '', rect: null }
  const range = sel.getRangeAt(0)
  // 限定必须在 pdf-content 范围内，避免工具栏等误触
  if (!containerRef.value) return { text: '', rect: null }
  if (!containerRef.value.contains(range.commonAncestorContainer)) {
    return { text: '', rect: null }
  }
  const rect = range.getBoundingClientRect()
  return { text, rect }
}

function positionPopoverFromRect(rect: DOMRect) {
  if (!containerRef.value) {
    selection.top = rect.bottom + window.scrollY + 6
    selection.left = rect.left + window.scrollX
    return
  }
  const containerRect = containerRef.value.getBoundingClientRect()
  // 让浮窗相对 container 定位（container 自身是 absolute 子元素时也正常）
  selection.top = rect.bottom - containerRect.top + containerRef.value.scrollTop + 6
  selection.left = Math.max(
    8,
    rect.left - containerRect.left + containerRef.value.scrollLeft,
  )
  // 防止右侧溢出
  const popWidth = 240
  const maxLeft = containerRef.value.clientWidth - popWidth - 8
  if (selection.left > maxLeft) selection.left = maxLeft
}

function onMouseUp() {
  // 延迟一帧以确保 selection 已稳定
  setTimeout(() => {
    console.log('[PdfViewer] mouseup fired, getSelection:', window.getSelection()?.toString()?.slice(0, 50))
    const { text, rect } = getSelectionInViewer()
    console.log('[PdfViewer] getSelectionInViewer ->', { textLen: text.length, rect })
    if (!text || !rect) {
      selection.visible = false
      selection.text = ''
      return
    }
    // 截断过长文本，避免请求体过大
    const trimmed = text.length > 500 ? text.slice(0, 500) + '…' : text
    selection.text = trimmed
    positionPopoverFromRect(rect)
    selection.visible = true
  }, 0)
}

function dismissSelection() {
  selection.visible = false
  selection.text = ''
  const sel = window.getSelection()
  sel?.removeAllRanges()
}

function buildQuestionFromSelection(text: string): string {
  // 简单模板：让 RAG 基于这段文字回答
  const snippet = text.length > 200 ? text.slice(0, 200) + '…' : text
  return `请基于以下论文片段回答："${snippet}"。请解释其含义并补充相关上下文。`
}

function askSelection() {
  const text = selection.text
  if (!text) return
  const question = buildQuestionFromSelection(text)
  const meta = { page: page.value, snippet: text }
  selection.visible = false
  selection.text = ''
  if (props.paperId) {
    store.goToRagWithSelection(props.paperId, question, meta)
    close()
  } else {
    console.warn('[PdfViewer] paperId is missing, cannot jump to RAG')
  }
}

function openInRag() {
  if (!props.paperId) return
  const question = '请对这篇论文做一个总体概述。'
  store.goToRagWithSelection(props.paperId, question, { page: page.value })
  close()
}

watch(page, () => {
  // 翻页时清掉旧的选中
  dismissSelection()
})

// 监听面板容器尺寸变化，浏览器窗口 resize / 侧栏切换等情况都能自动重 fit
onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
  document.addEventListener('mouseup', onMouseUp)
  document.body.style.overflow = 'hidden'
  // 首屏先按当前面板宽度预 fit 一次，避免看到默认 1.0 的小图
  nextTick(() => scheduleFit())
  if (panelRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => scheduleFit())
    resizeObserver.observe(panelRef.value)
  }
  window.addEventListener('resize', scheduleFit)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  document.removeEventListener('mouseup', onMouseUp)
  document.body.style.overflow = ''
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
  window.removeEventListener('resize', scheduleFit)
})
</script>

<style scoped>
.pdf-viewer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}

.pdf-viewer-container {
  width: 96vw;
  height: 95vh;
  max-width: 1800px;
  background: #1a1a1a;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  /* overflow: hidden 会阻止 flex 子元素撑开容器（当子元素是 position:absolute 时），
     改为只在内容区自己处理溢出 */
  overflow: visible;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #2a2a2a;
  border-bottom: 1px solid #3a3a3a;
  gap: 16px;
}

.toolbar-title {
  font-weight: 600;
  color: #e0e0e0;
  font-size: 14px;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toolbar-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: #a0a0a0;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  text-decoration: none;
}

.btn-icon:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.btn-icon:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.btn-icon svg {
  width: 18px;
  height: 18px;
}

.btn-close:hover {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.btn-rag {
  color: #50dcc8;
}
.btn-rag:hover {
  background: rgba(80, 220, 200, 0.18);
  color: #50dcc8;
}

.page-info,
.scale-info {
  color: #808080;
  font-size: 13px;
  min-width: 60px;
  text-align: center;
}

.divider {
  width: 1px;
  height: 20px;
  background: #3a3a3a;
  margin: 0 4px;
}

/* 原版 / 翻译版 toggle */
.pdf-variant-toggle {
  display: inline-flex;
  align-items: center;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  overflow: hidden;
  background: transparent;
}
.pdf-variant-toggle.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.pdf-variant-btn {
  appearance: none;
  background: transparent;
  border: 0;
  color: #cccccc;
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
  line-height: 18px;
  transition: background 0.12s ease, color 0.12s ease;
}
.pdf-variant-btn + .pdf-variant-btn {
  border-left: 1px solid #3a3a3a;
}
.pdf-variant-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
  color: #ffffff;
}
.pdf-variant-btn.active {
  background: #4a90e2;
  color: #ffffff;
}
.pdf-variant-btn:disabled {
  cursor: not-allowed;
  color: #666666;
}

.pdf-content {
  flex: 1;
  overflow: auto;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 20px;
  background: #0d0d0d;
  position: relative;
  /* flex:1 的元素在 flex 父容器里需要 min-height:0 才能被 overflow:auto 约束 */
  min-height: 0;
}

/* vue-pdf-embed 渲染出的 .page div 是 position:absolute，由 pdfjs 自己管理尺寸。
   这里给外层 div 一个最小宽度，确保 PDF 能撑开可见。 */
.pdf-embed-wrapper {
  /* 最小宽度 = PDF 渲染宽度，防止 pdf 内容不可见 */
  width: v-bind("renderWidth + 'px'");
  min-width: v-bind("renderWidth + 'px'");
  /* 不限制高度，让 pdf 自身内容撑开 */
  height: auto;
}

.loading,
.error {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #808080;
  padding: 40px;
  z-index: 2;
  background: rgba(13, 13, 13, 0.5);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #3a3a3a;
  border-top-color: #79c0ff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.error svg {
  width: 40px;
  height: 40px;
  color: #ef4444;
}

/* ===== 选中浮窗 ===== */
.selection-popover {
  position: absolute;
  z-index: 5;
  background: #1f2937;
  color: #e5e7eb;
  border: 1px solid rgba(80, 220, 200, 0.35);
  border-radius: 10px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6);
  width: 240px;
  animation: pop-in 0.12s ease-out;
}

@keyframes pop-in {
  from {
    opacity: 0;
    transform: translateY(-4px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.selection-popover-meta {
  font-size: 11px;
  color: #9ca3af;
  padding: 0 2px;
}

.selection-popover-btn {
  appearance: none;
  border: none;
  background: rgba(80, 220, 200, 0.18);
  color: #50dcc8;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  text-align: left;
}

.selection-popover-btn:hover {
  background: rgba(80, 220, 200, 0.3);
}

.selection-popover-btn.ghost {
  background: transparent;
  color: #9ca3af;
  font-weight: 500;
  text-align: center;
}

.selection-popover-btn.ghost:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #e5e7eb;
}
</style>
