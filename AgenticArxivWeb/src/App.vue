<template>
  <div class="app">
    <Sidebar :currentPage="currentPage" @update:currentPage="currentPage = $event" />

    <main class="main-content">
      <KeepAlive>
        <component :is="pageComponent" />
      </KeepAlive>
    </main>

    <!-- 全局 PDF Viewer：监听 store._pdfViewerRequest -->
    <PdfViewer
      v-if="pdfRequest"
      :key="pdfRequest.paperId + ':' + (pdfRequest.initialPage || 1)"
      :url="pdfRequest.url"
      :paper-id="pdfRequest.paperId"
      :title="pdfRequest.title"
      :download-url="pdfRequest.downloadUrl"
      :initial-page="pdfRequest.initialPage"
      :translated-url="pdfRequest.translatedUrl"
      :has-translated="pdfRequest.hasTranslated"
      @close="onPdfClose"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
// App 启动时预热 pdf.js worker：避免用户首次打开 PDF 时下载 worker 卡顿。
// worker 文件已拷贝到 public/pdf.worker.min.mjs，vite 原样 serve 真实文件（不是 wrapper）。
import ChatPanel from "@/components/ChatPanel.vue";
import Sidebar from "@/components/Sidebar.vue";
import PapersPanel from "@/components/PapersPanel.vue";
import PapersComparisonPanel from "@/components/PapersComparisonPanel.vue";
import SubscriptionsPanel from "@/components/SubscriptionsPanel.vue";
import BookmarksPanel from "@/components/BookmarksPanel.vue";
import AssetsPanel from "@/components/AssetsPanel.vue";
import LogsPanel from "@/components/LogsPanel.vue";
import SettingsPanel from "@/components/SettingsPanel.vue";
import RagPanel from "@/components/RagPanel.vue";
import PdfViewer from "@/components/PdfViewer.vue";
import { useAppStore } from "@/stores/appStore";

// pdf.js worker 文件路径（public 目录，vite 直接 serve）
const PDF_WORKER_URL = "/pdf.worker.min.mjs";

const currentPage = ref("chat");

const pageMap: Record<string, any> = {
  chat: ChatPanel,
  papers: PapersPanel,
  comparison: PapersComparisonPanel,
  subscriptions: SubscriptionsPanel,
  bookmarks: BookmarksPanel,
  assets: AssetsPanel,
  logs: LogsPanel,
  settings: SettingsPanel,
  rag: RagPanel,
};

const store = useAppStore();

// 监听 PapersPanel / RagPanel 通过 store 触发的「跳转到 RAG 页面」指令
watch(
  () => (store as any)._ragTargetPage,
  (newPage) => {
    if (newPage && newPage !== currentPage.value) {
      currentPage.value = newPage;
      (store as any)._ragTargetPage = null;
    }
  }
);

const pdfRequest = computed(() => (store as any)._pdfViewerRequest as null | {
  paperId: string;
  url: string;
  title?: string;
  downloadUrl?: string;
  initialPage?: number;
  translatedUrl?: string;
  hasTranslated?: boolean;
});

function onPdfClose() {
  store.closePdfViewer();
}

const pageComponent = computed(() => pageMap[currentPage.value] || ChatPanel);

// 应用启动时静默预热 pdf.js worker 文件（6MB+），让用户首次打开 PDF 也能"秒开"。
onMounted(() => {
  try {
    const warm = () => {
      // prefetch：让浏览器空闲时把 worker 文件加载到 HTTP cache
      const link = document.createElement('link')
      link.rel = 'prefetch'
      link.as = 'script'
      link.href = PDF_WORKER_URL
      document.head.appendChild(link)
      // 兜底：直接 fetch（强制 cache）
      fetch(PDF_WORKER_URL, { cache: 'force-cache', mode: 'no-cors' }).catch(() => {})
    }
    if ('requestIdleCallback' in window) {
      (window as any).requestIdleCallback(warm, { timeout: 3000 })
    } else {
      setTimeout(warm, 1500)
    }
  } catch { /* ignore */ }
})
</script>

<style scoped>
.app {
  min-height: 100vh;
  background: var(--bg);
  color: var(--fg);
}

.main-content {
  margin-left: 60px;
  padding: 14px 18px;
  min-height: 100vh;
}

@media (max-width: 768px) {
  .main-content {
    margin-left: 0;
    margin-bottom: 52px;
    padding: 10px;
  }
}

</style>
