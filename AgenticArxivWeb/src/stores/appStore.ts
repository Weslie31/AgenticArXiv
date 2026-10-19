// src/stores/appStore.ts
import { defineStore } from "pinia";
import { api, getApiBase } from "@/api/client";
import { openEventsSse } from "@/api/sse";
import type {
  AgentType,
  ChatResponse,
  Paper,
  PdfAsset,
  TranslateAsset,
  Role,
  ReactStep,
  TranslateTask,
  SseEnvelope,
  DeleteAssetResponse,
  PaperSummary,
  PaperComparison,
  ComparisonResultResponse,
  CreateComparisonResponse,
  ComparisonListResponse,
  DiscoveredPaper,
  RagAskRequest,
  RagAskResponse,
  RagSummarizeRequest,
  RagSummarizeResponse,
  RagHistoryEntry,
  Annotation,
  AnnotationCreatePayload,
  AnnotationUpdatePayload,
  AnnotationListResponse,
  PaperTag,
  PaperTagList,
  PaperBookmark,
  PaperBookmarkList,
  PaperBookmarkWithPaper,
  PaperFlagsResponse,
  TagCreatePayload,
  BookmarkCreatePayload,
  BookmarkUpdatePayload,
  BookmarkDeleteResponse,
} from "@/api/types";

export interface ChatMessage {
  role: Role;
  content: string;
  ts: number;
  taskId?: string;
  history?: ReactStep[];
  agentType?: AgentType;
}

export type TranslateService = "deepl" | "google" | "openai" | "azure";

export const TRANSLATE_SERVICES: { value: TranslateService; label: string; needApiKey: boolean }[] = [
  { value: "deepl", label: "DeepL（高质量）", needApiKey: true },
  // pdf2zh 的 GoogleTranslator 走公开接口，不需要 Key
  { value: "google", label: "Google Translate（免 Key）", needApiKey: false },
  { value: "openai", label: "OpenAI GPT", needApiKey: true },
  { value: "azure", label: "Azure Translator", needApiKey: true },
];

function nowTs() {
  return Date.now();
}

let _es: EventSource | null = null;
let _reconnectTimer: number | null = null;
let _reconnectBackoffMs = 1000;

function clearReconnectTimer() {
  if (_reconnectTimer != null) {
    window.clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
}

export const useAppStore = defineStore("app", {
  state: () => ({
    apiBase: getApiBase(),
    sessionId: (localStorage.getItem("session_id") || "demo1") as string,

    loading: false,
    lastError: "" as string,

    // messages 初始化从 localStorage 读取（按 sessionId 隔离）
    messages: (() => {
      const sid = (localStorage.getItem("session_id") || "demo1") as string;
      try {
        const raw = localStorage.getItem(`chat_messages:${sid}`);
        if (raw) {
          const arr = JSON.parse(raw);
          if (Array.isArray(arr)) return arr as ChatMessage[];
        }
      } catch { /* ignore */ }
      return [] as ChatMessage[];
    })(),

    papers: [] as Paper[],
    scheduledPapers: [] as Paper[],
    pdfAssets: [] as PdfAsset[],
    translateAssets: [] as TranslateAsset[],
    paperSummaries: [] as PaperSummary[],

    tasks: [] as TranslateTask[],
    lastHistory: [] as ReactStep[],

    // RAG: 每篇论文的历史问答（key = paper_id），从 localStorage 读取
    ragHistoryByPaper: (() => {
      try {
        const raw = localStorage.getItem("rag_history_by_paper");
        if (raw) {
          const obj = JSON.parse(raw);
          if (obj && typeof obj === "object") return obj as Record<string, RagHistoryEntry[]>;
        }
      } catch { /* ignore */ }
      return {} as Record<string, RagHistoryEntry[]>;
    })(),
    ragLoading: false,
    // 跨页面跳转指令（App.vue watch）
    _ragTargetPage: null as string | null,
    _ragPendingPaperId: null as string | null,
    // 从 PDF 选择带入 RAG 问答的初始问题
    _ragPendingQuestion: null as string | null,
    _ragPendingQuestionMeta: null as { page?: number; snippet?: string } | null,

    // 全局 PDF Viewer 触发器（任意页面都可调用 store.openPdfViewer()）
    _pdfViewerRequest: null as null | {
      paperId: string;
      url: string;
      title?: string;
      downloadUrl?: string;
      initialPage?: number;
      translatedUrl?: string;
      hasTranslated?: boolean;
    },

    // 论文批注：key = `${sessionId}:${paperId}`，避免跨 session 串数据
    annotationsByPaper: {} as Record<string, Annotation[]>,
    annotationsLoading: false,

    preferAgent: true,
    agentType: (localStorage.getItem("agent_type") || "regex") as AgentType,

    // Translation settings
    translateService: (localStorage.getItem("translate_service") || "openai") as TranslateService,

    thinkingSteps: [] as any[],
    isThinking: false,

    // Track task_ids created via SSE during the current sendChat() call
    _newTaskIds: new Set<string>() as Set<string>,
    // TaskId created during thinking phase (for showing progress in thinking card)
    thinkingTaskId: "" as string,
    // Latest detail line per task (e.g. " 83% 20/24 [01:16<00:17]")
    taskDetailLine: {} as Record<string, string>,

    sseStatus: "idle" as "idle" | "connecting" | "connected" | "error",
    sseLastEvent: "" as string,
    sseLastEventTs: 0 as number,

    // Paper Comparison state
    comparisons: [] as PaperComparison[],
    currentComparisonId: "" as string,
    currentComparisonResult: null as ComparisonResultResponse | null,
    comparisonLoading: false as boolean,
    selectedPaperIds: [] as string[],  // 用于论文选择
    discoveredPapers: [] as DiscoveredPaper[],  // 扫描后端目录发现的论文

    // ============ Paper Bookmarks & Tags 状态（跨会话个人兴趣库） ============
    /** 每篇论文的 tags（key = paper_id）；按需懒加载，避免一次拉太多 */
    tagsByPaper: {} as Record<string, string[]>,
    /** 被收藏的 paper_id 集合（Set 在 Pinia 里用数组更安全） */
    bookmarkedIds: [] as string[],
    /** 收藏夹面板的完整列表（含 paper 元数据 + tags） */
    bookmarkList: [] as PaperBookmarkWithPaper[],
    bookmarkListTotal: 0 as number,
    /** 系统中所有出现过的 tag，供收藏夹面板做筛选下拉 */
    allTags: [] as string[],
    bookmarksLoading: false as boolean,
  }),

  getters: {
    pdfMap(state) {
      const m = new Map<string, PdfAsset>();
      (state.pdfAssets || []).forEach((a) => m.set(a.paper_id, a));
      return m;
    },
    translateMap(state) {
      const m = new Map<string, TranslateAsset>();
      (state.translateAssets || []).forEach((a) => m.set(a.paper_id, a));
      return m;
    },
    paperSummaryMap(state) {
      const m = new Map<string, PaperSummary>();
      (state.paperSummaries || []).forEach((s) => m.set(s.paper_id, s));
      return m;
    },
    /** Set 化的被收藏 paper_id（O(1) 查询） */
    bookmarkedIdSet(state): Set<string> {
      return new Set(state.bookmarkedIds || []);
    },
    /** paper_id -> tags[] 映射（O(1) 查询） */
    tagsMap(state): Record<string, string[]> {
      return state.tagsByPaper || {};
    },
  },

  actions: {
    // -------- localStorage 持久化 --------
    persistMessages() {
      try {
        localStorage.setItem(
          `chat_messages:${this.sessionId}`,
          JSON.stringify(this.messages || [])
        );
      } catch (e) {
        console.warn("[appStore] persistMessages failed", e);
      }
    },
    persistRagHistory() {
      try {
        localStorage.setItem(
          "rag_history_by_paper",
          JSON.stringify(this.ragHistoryByPaper || {})
        );
      } catch (e) {
        console.warn("[appStore] persistRagHistory failed", e);
      }
    },
    loadMessagesForSession(sid: string) {
      try {
        const raw = localStorage.getItem(`chat_messages:${sid}`);
        if (raw) {
          const arr = JSON.parse(raw);
          if (Array.isArray(arr)) {
            this.messages = arr as ChatMessage[];
            return;
          }
        }
      } catch { /* ignore */ }
      this.messages = [];
    },

    // -------- URL helpers --------
    _joinApi(path: string) {
      const b = (this.apiBase || "").replace(/\/+$/, "");
      const p = path.startsWith("/") ? path : `/${path}`;
      return `${b}${p}`;
    },

    getRawPdfViewUrl(paperId: string) {
      const pid = encodeURIComponent((paperId || "").trim());
      const sid = encodeURIComponent(this.sessionId || "default");
      return this._joinApi(`/pdf/view/raw/${pid}?session_id=${sid}`);
    },

    getTranslatedPdfViewUrl(paperId: string, variant: "mono" | "dual" = "mono") {
      const pid = encodeURIComponent((paperId || "").trim());
      const sid = encodeURIComponent(this.sessionId || "default");
      const v = encodeURIComponent(variant);
      return this._joinApi(`/pdf/view/translated/${pid}?variant=${v}&session_id=${sid}`);
    },

    _openNewTab(url: string) {
      if (typeof window === "undefined") return;
      window.open(url, "_blank", "noopener,noreferrer");
    },

    openRawPdf(paperId: string) {
      this._openNewTab(this.getRawPdfViewUrl(paperId));
    },

    openTranslatedPdf(paperId: string, variant: "mono" | "dual" = "mono") {
      this._openNewTab(this.getTranslatedPdfViewUrl(paperId, variant));
    },

    // -------- original logic --------
    setSessionId(id: string) {
      const next = (id || "default").trim() || "default";
      if (next === this.sessionId) {
        // 即使 session 没变，也尝试加载（应对初次加载时序问题）
        this.loadMessagesForSession(next);
        return;
      }

      this.sessionId = next;
      localStorage.setItem("session_id", this.sessionId);

      // 加载新 session 的对话历史
      this.loadMessagesForSession(next);
      this.lastHistory = [];
      this.lastError = "";

      this.tasks = [];
      this.papers = [];
      this.closeSse();
      this.ensureSse();
    },

    newSession() {
      const id = "session-" + crypto.randomUUID().slice(0, 8);
      this.clearChat();
      this.papers = [];
      this.pdfAssets = [];
      this.translateAssets = [];
      this.tasks = [];
      this.setSessionId(id);
      this.refreshSnapshot();
    },

    pushUser(content: string) {
      this.messages.push({ role: "user", content, ts: nowTs() });
      this.persistMessages();
    },
    pushAssistant(content: string, opts?: { taskId?: string; history?: ReactStep[]; agentType?: AgentType }) {
      this.messages.push({ role: "assistant", content, ts: nowTs(), ...opts });
      this.persistMessages();
    },

    ensureSse() {
      if (typeof window === "undefined") return;
      const sid = this.sessionId || "default";
      if (_es) return;

      clearReconnectTimer();
      this.sseStatus = "connecting";

      _es = openEventsSse(this.apiBase, sid, {
        onOpen: () => {
          this.sseStatus = "connected";
          this.sseLastEvent = "open";
          this.sseLastEventTs = nowTs();
          _reconnectBackoffMs = 1000;
        },
        onError: () => {
          this.sseStatus = "error";
          this.sseLastEvent = "error";
          this.sseLastEventTs = nowTs();

          const readyState = _es?.readyState;
          if (readyState === 2) {
            this.closeSse();
            this._scheduleReconnect();
          }
        },
        onEvent: (evt) => this._handleSseEvent(evt),
      });
    },

    closeSse() {
      clearReconnectTimer();
      if (_es) {
        try {
          _es.close();
        } catch { }
      }
      _es = null;
      this.sseStatus = "idle";
    },

    _scheduleReconnect() {
      if (typeof window === "undefined") return;
      if (_reconnectTimer != null) return;

      const delay = Math.min(_reconnectBackoffMs, 15000);
      _reconnectBackoffMs = Math.min(_reconnectBackoffMs * 2, 15000);

      _reconnectTimer = window.setTimeout(() => {
        _reconnectTimer = null;
        this.closeSse();
        this.ensureSse();
      }, delay);
    },

    _upsertTask(t: TranslateTask) {
      const id = t?.task_id;
      if (!id) return;

      const idx = this.tasks.findIndex((x) => x.task_id === id);
      if (idx >= 0) this.tasks[idx] = { ...this.tasks[idx], ...t };
      else this.tasks.unshift(t);

      if (this.tasks.length > 50) this.tasks.length = 50;
    },

    _removePdfAssetLocal(paperId: string) {
      this.pdfAssets = (this.pdfAssets || []).filter((x) => x.paper_id !== paperId);
    },
    _removeTranslateAssetLocal(paperId: string) {
      this.translateAssets = (this.translateAssets || []).filter((x) => x.paper_id !== paperId);
    },

    async _handleSseEvent(evt: SseEnvelope) {
      if (!evt || typeof evt !== "object") return;

      this.sseLastEvent = evt.type || "message";
      this.sseLastEventTs = nowTs();

      if (evt.type === "connected") {
        this.sseStatus = "connected";
        return;
      }

      if (evt.type === "agent_step" && evt.step) {
        this.thinkingSteps.push(evt.step);
        return;
      }

      if (evt.type === "asset_deleted" && evt.paper_id) {
        const kind = String(evt.kind || "").toLowerCase();
        if (kind === "pdf") this._removePdfAssetLocal(evt.paper_id);
        if (kind === "translate") this._removeTranslateAssetLocal(evt.paper_id);
        return;
      }

      if (evt.kind === "translate" && evt.task) {
        this._upsertTask(evt.task);
        // Store detail line for debugging (e.g. " 83% 20/24 [01:16<00:17]")
        const line = evt.detail?.line;
        if (line && evt.task.task_id) {
          this.taskDetailLine[evt.task.task_id] = String(line).trim();
        }
      }

      // Track new tasks created during sendChat (for Issue 1 & 2)
      if (evt.type === "task_created" && evt.kind === "translate" && evt.task?.task_id) {
        if (this.loading) {
          this._newTaskIds.add(evt.task.task_id);
          this.thinkingTaskId = evt.task.task_id;
        }
      }

      if ((evt.type === "task_created" || evt.type === "task_started") && evt.kind === "translate") {
        await Promise.allSettled([this.fetchTranslateAssets(), this.fetchPdfAssets()]);
      }

      if (evt.type === "task_succeeded" && evt.kind === "translate") {
        await Promise.allSettled([this.fetchTranslateAssets(), this.fetchPdfAssets()]);
      }

      if (evt.type === "task_failed" && evt.kind === "translate") {
        const msg = evt.task?.error || evt.message || "翻译任务失败";
        this.lastError = msg;
      }

      // 订阅拉取完成：刷新当前 session 的论文列表
      if (evt.type === "subscription_update") {
        this.lastError = "";
        try {
          await this.refreshSnapshot();
        } catch (e: any) {
          this.lastError = e?.message || String(e);
        }
      }
    },

    async refreshSnapshot() {
      try {
        this.ensureSse();

        const [papersRes, subPapersRes, pdfRes, trRes, summaryRes] = await Promise.all([
          api.get(`/sessions/${encodeURIComponent(this.sessionId)}/papers`),
          api.get(`/papers/subscription`),
          api.get(`/pdf/assets`),
          api.get(`/translate/assets`),
          api.get(`/summary/assets`),
        ]);

        // 当前 session 论文
        this.papers = papersRes.data?.papers || [];
        // 所有定时订阅论文
        this.scheduledPapers = subPapersRes.data?.papers || [];
        this.pdfAssets = pdfRes.data?.assets || [];
        this.translateAssets = trRes.data?.assets || [];
        this.paperSummaries = Array.isArray(summaryRes.data) ? summaryRes.data : [];
      } catch (e: any) {
        this.lastError = e?.response?.data?.detail || e?.message || String(e);
      }
    },

    /**
     * 删除"会话论文"中指定的 paper_id（支持单/批量）。
     * 后端调用后本地立即从 store.papers 中剔除，避免刷新前的 UI 抖动。
     */
    async removeSessionPapers(paperIds: string[]) {
      const ids = Array.from(
        new Set((paperIds || []).filter((x) => !!x))
      );
      if (!ids.length) return { removed_count: 0 };
      try {
        const resp = await api.delete(
          `/sessions/${encodeURIComponent(this.sessionId)}/papers`,
          {
            params: {
              paper_ids: ids,
              fetch_type: "manual",
            },
            paramsSerializer: {
              indexes: null,  // axios <1.x: 允许重复 key；这里 1.x 默认行为已 OK
            },
          }
        );
        // 乐观更新本地缓存
        const removed = new Set(ids);
        this.papers = this.papers.filter((p) => !removed.has(p.id));
        // 同步清掉 PDF / 翻译 / 总结缓存的对应项
        if (this.pdfAssets) this.pdfAssets = this.pdfAssets.filter((a) => !removed.has(a.paper_id));
        if (this.translateAssets) this.translateAssets = this.translateAssets.filter((a) => !removed.has(a.paper_id));
        if (this.paperSummaries) this.paperSummaries = this.paperSummaries.filter((s) => !removed.has(s.paper_id));
        return resp.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    /**
     * 删除"订阅论文"中指定的 paper_id（支持单/批量）。
     */
    async removeScheduledPapers(paperIds: string[]) {
      const ids = Array.from(
        new Set((paperIds || []).filter((x) => !!x))
      );
      if (!ids.length) return { removed_count: 0 };
      try {
        const resp = await api.delete(
          `/sessions/${encodeURIComponent(this.sessionId)}/papers`,
          {
            params: {
              paper_ids: ids,
              fetch_type: "subscription",
            },
          }
        );
        const removed = new Set(ids);
        this.scheduledPapers = this.scheduledPapers.filter(
          (p) => !removed.has(p.id)
        );
        if (this.pdfAssets) this.pdfAssets = this.pdfAssets.filter((a) => !removed.has(a.paper_id));
        if (this.translateAssets) this.translateAssets = this.translateAssets.filter((a) => !removed.has(a.paper_id));
        if (this.paperSummaries) this.paperSummaries = this.paperSummaries.filter((s) => !removed.has(s.paper_id));
        return resp.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    async sendChat(message: string) {
      const text = (message || "").trim();
      if (!text) return;

      this.ensureSse();

      this.loading = true;
      this.isThinking = true;
      this.thinkingSteps = [];
      this._newTaskIds = new Set();
      this.thinkingTaskId = "";
      this.lastError = "";
      this.pushUser(text);

      try {
        const res = await api.post<ChatResponse>("/chat", {
          session_id: this.sessionId,
          message: text,
          agent_type: this.agentType,
        });

        const data = res.data;
        const history = data.history || [];
        // Only assign taskId if a new task was created during THIS chat interaction
        const taskId = Array.isArray(data.tasks)
          ? data.tasks.find((t) => this._newTaskIds.has(t.task_id))?.task_id
          : undefined;
        const agentType = (data.agent_type || this.agentType) as AgentType;
        this.pushAssistant(data.reply || "(空回复)", { history, taskId, agentType });
        this.lastHistory = history;

        // 合并新论文和现有论文，避免重复
        const existingIds = new Set(this.papers.map((p) => p.id));
        const newPapers = (data.papers || []).filter((p) => !existingIds.has(p.id));
        this.papers = [...this.papers, ...newPapers];
        this.pdfAssets = data.pdf_assets || [];
        this.translateAssets = data.translate_assets || [];

        if (Array.isArray(data.tasks)) {
          for (const t of data.tasks) this._upsertTask(t);
        }
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        this.pushAssistant(`请求失败：${msg}`);
      } finally {
        this.loading = false;
        this.isThinking = false;
        this.thinkingSteps = [];
        this._newTaskIds = new Set();
        this.thinkingTaskId = "";
      }
    },

    async fetchPdfAssets() {
      try {
        const resp = await api.get<{ assets: PdfAsset[] }>("/pdf/assets");
        this.pdfAssets = resp.data?.assets || [];
      } catch { }
    },

    async fetchDiscoveredPapers() {
      try {
        const resp = await api.get<{ papers: DiscoveredPaper[] }>("/pdf/discovered");
        this.discoveredPapers = resp.data?.papers || [];
      } catch { }
    },

    async fetchTranslateAssets() {
      try {
        const resp = await api.get<{ assets: TranslateAsset[] }>("/translate/assets");
        this.translateAssets = resp.data?.assets || [];
      } catch { }
    },

    async deletePdfAsset(paperId: string) {
      const pid = (paperId || "").trim();
      if (!pid) return;

      this.lastError = "";
      try {
        const resp = await api.delete<DeleteAssetResponse>(`/pdf/assets/${encodeURIComponent(pid)}`, {
          params: { session_id: this.sessionId },
        });
        this._removePdfAssetLocal(pid);
        await this.fetchPdfAssets();
        return resp.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    async deleteTranslateAsset(paperId: string) {
      const pid = (paperId || "").trim();
      if (!pid) return;

      this.lastError = "";
      try {
        const resp = await api.delete<DeleteAssetResponse>(
          `/translate/assets/${encodeURIComponent(pid)}`,
          { params: { session_id: this.sessionId } }
        );
        this._removeTranslateAssetLocal(pid);
        await this.fetchTranslateAssets();
        return resp.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    async downloadPaper(refIndex1based: number) {
      if (this.preferAgent) {
        await this.sendChat(`下载第${refIndex1based}篇论文PDF`);
        return;
      }

      this.loading = true;
      this.lastError = "";
      try {
        const res = await api.post("/pdf/download", {
          session_id: this.sessionId,
          ref: refIndex1based,
          force: false,
        });
        this.pushAssistant(`下载结果：${JSON.stringify(res.data)}`);
        await this.refreshSnapshot();
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        this.pushAssistant(`下载失败：${msg}`);
      } finally {
        this.loading = false;
      }
    },

    async downloadById(paperId: string) {
      this.loading = true;
      this.lastError = "";
      try {
        const res = await api.post("/pdf/download", {
          session_id: this.sessionId,
          paper_id: paperId,
          force: false,
        });
        this.pushAssistant(`下载结果：${JSON.stringify(res.data)}`);
        await this.refreshSnapshot();
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        this.pushAssistant(`下载失败：${msg}`);
      } finally {
        this.loading = false;
      }
    },

    async uploadPaperById(paperId: string, file: File) {
      this.loading = true;
      this.lastError = "";
      try {
        const form = new FormData();
        form.append("file", file, file.name);
        const res = await api.post(
          `/pdf/upload?paper_id=${encodeURIComponent(paperId)}&session_id=${encodeURIComponent(this.sessionId || "default")}`,
          form,
          { headers: { "Content-Type": "multipart/form-data" } },
        );
        this.pushAssistant(`上传成功: ${file.name} (${(file.size / 1024).toFixed(1)} KB) → ${paperId}`);
        await this.refreshSnapshot();
        return res.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        this.pushAssistant(`上传失败：${msg}`);
        throw e;
      } finally {
        this.loading = false;
      }
    },

    async translateById(paperId: string) {
      this.ensureSse();
      this.loading = true;
      this.lastError = "";
      try {
        const payload: Record<string, any> = {
          session_id: this.sessionId,
          paper_id: paperId,
          force: false,
          service: this.translateService,
          threads: 4,
          keep_dual: false,
        };
    // api_key 改为不传 → 后端自动解析（优先级：系统配置 > 环境变量）
        const resp = await api.post<{ task: TranslateTask }>("/pdf/translate/async", payload);
        const task = resp.data?.task;
        if (task?.task_id) {
          this._upsertTask(task);
          this.pushAssistant(`已创建翻译任务：task_id=${task.task_id}（等待 SSE 推送完成）`);
        }
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        this.pushAssistant(`翻译失败：${msg}`);
      } finally {
        this.loading = false;
      }
    },

    async summarizeById(paperId: string) {
      this.loading = true;
      this.lastError = "";
      try {
        const resp = await api.post<{ summary: PaperSummary; message: string }>(
          "/pdf/summarize",
          { session_id: this.sessionId, paper_id: paperId, force: false }
        );
        const { summary } = resp.data || {};
        if (summary) {
          const idx = this.paperSummaries.findIndex((s) => s.paper_id === summary.paper_id);
          if (idx >= 0) {
            this.paperSummaries[idx] = summary;
          } else {
            this.paperSummaries.push(summary);
          }
        }
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
      } finally {
        this.loading = false;
      }
    },

    async translatePaper(refIndex1based: number) {
      const tip = `准备翻译第${refIndex1based}篇论文（若未下载将自动先下载再翻译）`;

      if (this.preferAgent) {
        await this.sendChat(`${tip}。请开始翻译并输出中文PDF。`);
        return;
      }

      this.ensureSse();

      this.loading = true;
      this.lastError = "";
      try {
        this.pushAssistant(tip);
        const payload: Record<string, any> = {
          session_id: this.sessionId,
          ref: refIndex1based,
          force: false,
          service: this.translateService,
          threads: 4,
          keep_dual: false,
        };
    // api_key 不传 → 后端自动解析系统配置

        const resp = await api.post<{ task: TranslateTask }>("/pdf/translate/async", payload);

        const task = resp.data?.task;
        if (task?.task_id) {
          this._upsertTask(task);
          this.pushAssistant(`已创建翻译任务：task_id=${task.task_id}（等待 SSE 推送完成）`);
        } else {
          this.pushAssistant(`已发起翻译任务（等待 SSE 推送完成）`);
        }
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        this.pushAssistant(`翻译失败：${msg}`);
      } finally {
        this.loading = false;
      }
    },

    async summarizePaper(refIndex1based: number) {
      const tip = `准备总结第${refIndex1based}篇论文的背景与创新点`;

      // 始终走专用总结端点（不依赖 agent 模式）
      this.loading = true;
      this.lastError = "";
      try {
        this.pushAssistant(tip);

        const resp = await api.post<{ summary: PaperSummary; message: string }>(
          "/pdf/summarize",
          {
            session_id: this.sessionId,
            ref: refIndex1based,
            force: false,
          }
        );

        const { summary, message } = resp.data || {};

        if (summary) {
          // Update store
          const idx = this.paperSummaries.findIndex(
            (s) => s.paper_id === summary.paper_id
          );
          if (idx >= 0) {
            this.paperSummaries[idx] = summary;
          } else {
            this.paperSummaries.push(summary);
          }

          if (summary.status === "READY") {
            const msg = [
              `✅ 总结完成：第${refIndex1based}篇`,
              summary.background ? `\n**🔍 研究背景**\n${summary.background}` : "",
              summary.innovation ? `\n**💡 主要创新点**\n${summary.innovation}` : "",
            ].filter(Boolean).join("\n");
            this.pushAssistant(msg);
          } else if (summary.status === "FAILED") {
            this.pushAssistant(`❌ 总结失败：${summary.error || "未知错误"}`);
          } else {
            this.pushAssistant(message || `总结状态：${summary.status}`);
          }
        } else {
          this.pushAssistant(message || "总结失败：未返回数据");
        }
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        this.pushAssistant(`总结失败：${msg}`);
      } finally {
        this.loading = false;
      }
    },

    clearChat() {
      this.messages = [];
      this.lastHistory = [];
      this.lastError = "";
      try {
        localStorage.removeItem(`chat_messages:${this.sessionId}`);
      } catch { /* ignore */ }
    },

    // ============ RAG Paper QA Actions ============

    async ragAsk(
      paperId: string,
      question: string,
      topK = 8,
      extra?: { selectedText?: string; selectedPage?: number },
    ) {
      this.ragLoading = true;
      this.lastError = "";
      console.log(`[RAG] ragAsk start: paper=${paperId} q="${question.slice(0, 40)}" topK=${topK}`);
      try {
        const req: RagAskRequest = {
          session_id: this.sessionId,
          paper_id: paperId,
          question,
          top_k: topK,
          force_reindex: false,
          selected_text: extra?.selectedText,
          selected_page: extra?.selectedPage,
        };
        const resp = await api.post<RagAskResponse>("/rag/ask", req);
        const data = resp.data;
        console.log(`[RAG] ragAsk success: answer_len=${data.answer?.length} sources=${data.sources?.length}`);

        // 写本地历史
        const entry: RagHistoryEntry = {
          question,
          answer: data.answer,
          confidence: data.confidence,
          sources: data.sources,
          annotations_used: data.annotations_used ?? [],
          asked_at: new Date().toISOString(),
        };
        if (!this.ragHistoryByPaper[paperId]) {
          this.ragHistoryByPaper[paperId] = [];
        }
        this.ragHistoryByPaper[paperId].unshift(entry);
        console.log(`[RAG] history for ${paperId}: now ${this.ragHistoryByPaper[paperId].length} entries`);
        this.persistRagHistory();

        return data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        console.error(`[RAG] ragAsk failed:`, e);
        this.lastError = msg;
        throw new Error(msg);
      } finally {
        this.ragLoading = false;
      }
    },

    async ragSummarize(
      paperId: string,
      focus: "general" | "method" | "experiment" | "conclusion" | "contribution" = "general",
      maxLength = 500,
    ) {
      this.ragLoading = true;
      this.lastError = "";
      try {
        const req: RagSummarizeRequest = {
          paper_id: paperId,
          focus,
          max_length: maxLength,
        };
        const resp = await api.post<RagSummarizeResponse>("/rag/summarize", req);
        return resp.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      } finally {
        this.ragLoading = false;
      }
    },

    ragHistoryFor(paperId: string): RagHistoryEntry[] {
      return this.ragHistoryByPaper[paperId] || [];
    },
    clearRagHistory(paperId?: string) {
      if (paperId) {
        delete this.ragHistoryByPaper[paperId];
      } else {
        this.ragHistoryByPaper = {};
      }
      this.persistRagHistory();
    },

    // ============ Paper Annotation Actions ============
    _annotationKey(paperId: string): string {
      return `${this.sessionId}:${paperId}`;
    },

    async fetchAnnotations(paperId: string) {
      const key = this._annotationKey(paperId);
      this.annotationsLoading = true;
      this.lastError = "";
      try {
        const resp = await api.get<AnnotationListResponse>(
          `/annotations/${encodeURIComponent(paperId)}`,
          { params: { session_id: this.sessionId } },
        );
        this.annotationsByPaper[key] = resp.data.items || [];
        console.log(`[Annotation] fetch ${paperId}: ${this.annotationsByPaper[key].length} items`);
        return this.annotationsByPaper[key];
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        console.warn(`[Annotation] fetch failed:`, msg);
        this.lastError = msg;
        // 失败时不覆盖已有缓存，保持可读
        return this.annotationsByPaper[key] || [];
      } finally {
        this.annotationsLoading = false;
      }
    },

    async createAnnotation(payload: AnnotationCreatePayload) {
      try {
        const resp = await api.post<Annotation>("/annotations", {
          ...payload,
          session_id: payload.session_id || this.sessionId,
        });
        const created = resp.data;
        const key = this._annotationKey(created.paper_id);
        if (!this.annotationsByPaper[key]) this.annotationsByPaper[key] = [];
        this.annotationsByPaper[key].unshift(created);
        console.log(`[Annotation] created id=${created.id} paper=${created.paper_id}`);
        return created;
      } catch (e: any) {
        // ⚠️ FastAPI/HTTPException 的 detail 可能是 string、list[dict]（ValidationError）、或 dict；
        // 全部统一序列化为字符串，避免传到前端后变 "[object Object]"
        let msg = "";
        const detail = e?.response?.data?.detail;
        if (typeof detail === "string") {
          msg = detail;
        } else if (Array.isArray(detail) || (detail && typeof detail === "object")) {
          try { msg = JSON.stringify(detail); } catch { msg = String(detail); }
        } else if (e?.message) {
          msg = e.message;
        } else {
          try { msg = JSON.stringify(e); } catch { msg = String(e); }
        }
        console.error(`[Annotation] create failed:`, e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    async updateAnnotation(annotationId: number, payload: AnnotationUpdatePayload) {
      try {
        const resp = await api.put<Annotation>(
          `/annotations/${annotationId}`,
          payload,
        );
        const updated = resp.data;
        const key = this._annotationKey(updated.paper_id);
        const arr = this.annotationsByPaper[key] || [];
        const idx = arr.findIndex((a) => a.id === annotationId);
        if (idx >= 0) arr[idx] = updated;
        return updated;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        console.error(`[Annotation] update failed:`, msg);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    async deleteAnnotation(annotationId: number, paperId: string) {
      try {
        await api.delete(`/annotations/${annotationId}`);
        const key = this._annotationKey(paperId);
        const arr = this.annotationsByPaper[key] || [];
        this.annotationsByPaper[key] = arr.filter((a) => a.id !== annotationId);
        console.log(`[Annotation] deleted id=${annotationId}`);
        return true;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        console.error(`[Annotation] delete failed:`, msg);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    annotationsFor(paperId: string): Annotation[] {
      return this.annotationsByPaper[this._annotationKey(paperId)] || [];
    },

    // ============ Paper Comparison Actions ============

    togglePaperSelection(paperId: string) {
      const idx = this.selectedPaperIds.indexOf(paperId);
      if (idx >= 0) {
        this.selectedPaperIds.splice(idx, 1);
      } else {
        if (this.selectedPaperIds.length >= 10) {
          this.lastError = "最多选择 10 篇论文进行对比";
          return;
        }
        this.selectedPaperIds.push(paperId);
      }
    },

    clearPaperSelection() {
      this.selectedPaperIds = [];
    },

    async createComparison() {
      if (this.selectedPaperIds.length < 2) {
        this.lastError = "请至少选择 2 篇论文";
        return null;
      }

      this.comparisonLoading = true;
      this.lastError = "";
      try {
        const resp = await api.post<CreateComparisonResponse>("/comparison/create", {
          session_id: this.sessionId,
          paper_ids: this.selectedPaperIds,
        });
        const comparison = resp.data?.comparison;
        if (comparison) {
          this.comparisons.unshift(comparison);
          this.currentComparisonId = comparison.comparison_id;
          this.clearPaperSelection();
          return comparison;
        }
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
      } finally {
        this.comparisonLoading = false;
      }
      return null;
    },

    async loadComparisonResult(comparisonId: string) {
      this.comparisonLoading = true;
      this.lastError = "";
      try {
        const resp = await api.get<ComparisonResultResponse>(`/comparison/${comparisonId}`);
        this.currentComparisonId = comparisonId;
        this.currentComparisonResult = resp.data;
        return resp.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        return null;
      } finally {
        this.comparisonLoading = false;
      }
    },

    async executeComparison(comparisonId: string, dimensions?: string[]) {
      this.comparisonLoading = true;
      this.lastError = "";
      try {
        const resp = await api.post<{ message: string; status: string }>(`/comparison/${comparisonId}/execute`, {
          dimensions,
          async_mode: true,
        });
        const result = resp.data;
        if (result?.status === "RUNNING") {
          this.pushAssistant("🔄 论文对比已启动，请稍候...");
        }
        return result;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        return null;
      } finally {
        this.comparisonLoading = false;
      }
    },

    async fetchComparisons() {
      try {
        const resp = await api.get<ComparisonListResponse>("/comparisons", {
          params: { session_id: this.sessionId },
        });
        this.comparisons = resp.data?.comparisons || [];
      } catch (e: any) {
        console.error("fetchComparisons failed:", e);
      }
    },

    async deleteComparison(comparisonId: string) {
      this.lastError = "";
      try {
        await api.delete(`/comparison/${comparisonId}`);
        this.comparisons = this.comparisons.filter(c => c.comparison_id !== comparisonId);
        if (this.currentComparisonId === comparisonId) {
          this.currentComparisonId = "";
          this.currentComparisonResult = null;
        }
        return true;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        return false;
      }
    },

    async pollComparisonStatus(comparisonId: string, intervalMs = 2000, maxAttempts = 30) {
      let attempts = 0;
      return new Promise<ComparisonResultResponse | null>((resolve) => {
        const poll = async () => {
          if (attempts >= maxAttempts) {
            resolve(null);
            return;
          }
          attempts++;
          const result = await this.loadComparisonResult(comparisonId);
          if (result?.comparison?.status === "SUCCEEDED" || result?.comparison?.status === "FAILED") {
            resolve(result);
          } else {
            setTimeout(poll, intervalMs);
          }
        };
        poll();
      });
    },

    // ============ Paper Bookmarks & Tags Actions ============

    /**
     * 批量加载一批论文的收藏/标签信息（论文列表行内 ⭐/🏷️ 渲染）。
     * 调用后会把结果合并进本地缓存，避免每行重复请求。
     */
    async fetchPaperFlags(paperIds: string[]) {
      const ids = Array.from(new Set((paperIds || []).filter(Boolean)));
      if (!ids.length) return;
      try {
        const resp = await api.post<PaperFlagsResponse>("/papers/flags", {
          paper_ids: ids,
        });
        // 合并 bookmarked（去重）
        const merged = new Set<string>([...(this.bookmarkedIds || [])]);
        for (const pid of resp.data?.bookmarked || []) merged.add(pid);
        this.bookmarkedIds = Array.from(merged);
        // 合并 tags
        const cur = { ...(this.tagsByPaper || {}) };
        for (const [pid, tags] of Object.entries(resp.data?.tags_map || {})) {
          cur[pid] = Array.from(new Set([...(cur[pid] || []), ...tags]));
        }
        this.tagsByPaper = cur;
      } catch (e: any) {
        console.warn(`[Bookmark] fetchPaperFlags failed:`, e?.message || e);
      }
    },

    /** 单篇论文的 tag 列表（懒加载 + 写缓存） */
    async fetchPaperTags(paperId: string): Promise<string[]> {
      const pid = (paperId || "").trim();
      if (!pid) return [];
      try {
        const resp = await api.get<PaperTagList>(
          `/papers/${encodeURIComponent(pid)}/tags`,
        );
        const tags = resp.data?.tags || [];
        this.tagsByPaper = { ...(this.tagsByPaper || {}), [pid]: tags };
        return tags;
      } catch (e: any) {
        console.warn(`[Tag] fetch ${pid} failed:`, e?.message || e);
        return this.tagsByPaper[pid] || [];
      }
    },

    /** 加一个 tag（成功后会更新本地缓存 + allTags） */
    async addPaperTag(paperId: string, tag: string): Promise<string[]> {
      const pid = (paperId || "").trim();
      const norm = (tag || "").trim();
      if (!pid || !norm) return this.tagsByPaper[pid] || [];
      try {
        const resp = await api.post<PaperTagList>(
          `/papers/${encodeURIComponent(pid)}/tags`,
          { tag: norm } as TagCreatePayload,
        );
        const tags = resp.data?.tags || [];
        this.tagsByPaper = { ...(this.tagsByPaper || {}), [pid]: tags };
        // 同步 allTags
        const all = new Set<string>(this.allTags || []);
        tags.forEach((t) => all.add(t));
        this.allTags = Array.from(all).sort();
        return tags;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    /** 删一个 tag */
    async removePaperTag(paperId: string, tag: string): Promise<string[]> {
      const pid = (paperId || "").trim();
      if (!pid || !tag) return this.tagsByPaper[pid] || [];
      try {
        const resp = await api.delete<PaperTagList>(
          `/papers/${encodeURIComponent(pid)}/tags/${encodeURIComponent(tag)}`,
        );
        const tags = resp.data?.tags || [];
        this.tagsByPaper = { ...(this.tagsByPaper || {}), [pid]: tags };
        return tags;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    /** 收藏一篇论文（幂等：后端已收藏则视为更新 note） */
    async bookmarkPaper(paperId: string, note?: string | null) {
      const pid = (paperId || "").trim();
      if (!pid) return null;
      try {
        const payload: BookmarkCreatePayload = {};
        if (note !== undefined) payload.note = note;
        const resp = await api.post<PaperBookmark>(
          `/papers/${encodeURIComponent(pid)}/bookmark`,
          payload,
        );
        // 同步本地状态
        if (!this.bookmarkedIds.includes(pid)) {
          this.bookmarkedIds = [...this.bookmarkedIds, pid];
        }
        // 收藏夹面板如果已打开，顺手刷新该条
        const idx = this.bookmarkList.findIndex((x) => x.bookmark.paper_id === pid);
        if (idx >= 0) {
          // 不直接改 paper 元数据，下次 fetch 即可
          this.bookmarkList[idx] = {
            ...this.bookmarkList[idx],
            bookmark: resp.data,
            paper: this.bookmarkList[idx]?.paper ?? null,
            tags: this.bookmarkList[idx]?.tags ?? [],
          };
        }
        return resp.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    /** 更新收藏的 note */
    async updateBookmarkNote(paperId: string, note: string | null) {
      const pid = (paperId || "").trim();
      if (!pid) return null;
      try {
        const resp = await api.put<PaperBookmark>(
          `/papers/${encodeURIComponent(pid)}/bookmark`,
          { note } as BookmarkUpdatePayload,
        );
        // 同步本地
        const idx = this.bookmarkList.findIndex((x) => x.bookmark.paper_id === pid);
        if (idx >= 0) {
          this.bookmarkList[idx] = {
            ...this.bookmarkList[idx],
            bookmark: resp.data,
            paper: this.bookmarkList[idx]?.paper ?? null,
            tags: this.bookmarkList[idx]?.tags ?? [],
          };
        }
        return resp.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    /** 取消收藏（后端会顺带清理该论文的 tags） */
    async unbookmarkPaper(paperId: string) {
      const pid = (paperId || "").trim();
      if (!pid) return null;
      try {
        const resp = await api.delete<BookmarkDeleteResponse>(
          `/papers/${encodeURIComponent(pid)}/bookmark`,
        );
        // 同步本地：去掉 bookmarkedIds
        this.bookmarkedIds = this.bookmarkedIds.filter((x) => x !== pid);
        // 清掉 tagsByPaper
        if (this.tagsByPaper && this.tagsByPaper[pid]) {
          const next = { ...this.tagsByPaper };
          delete next[pid];
          this.tagsByPaper = next;
        }
        // 收藏夹面板里也删掉
        this.bookmarkList = this.bookmarkList.filter(
          (x) => x.bookmark.paper_id !== pid,
        );
        this.bookmarkListTotal = Math.max(0, this.bookmarkListTotal - 1);
        return resp.data;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        throw new Error(msg);
      }
    },

    /** 加载收藏夹列表（可按 tag 筛选） */
    async fetchBookmarkList(tag: string | null = null) {
      this.bookmarksLoading = true;
      this.lastError = "";
      try {
        const resp = await api.get<PaperBookmarkList>("/papers/bookmarks", {
          params: tag ? { tag } : {},
        });
        this.bookmarkList = resp.data?.items || [];
        this.bookmarkListTotal = resp.data?.total || 0;
        this.allTags = resp.data?.all_tags || [];
        // 同步 bookmarkedIds（保证列表里的论文都标记为已收藏）
        const ids = this.bookmarkList.map((x) => x.bookmark.paper_id);
        const merged = new Set<string>([...(this.bookmarkedIds || []), ...ids]);
        this.bookmarkedIds = Array.from(merged);
        // 同步 tagsByPaper
        const cur = { ...(this.tagsByPaper || {}) };
        for (const item of this.bookmarkList) {
          cur[item.bookmark.paper_id] = item.tags || [];
        }
        this.tagsByPaper = cur;
        return this.bookmarkList;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || String(e);
        this.lastError = msg;
        return [];
      } finally {
        this.bookmarksLoading = false;
      }
    },

    /** 查询某篇论文是否已收藏（O(1) from bookmarkedIdSet） */
    isBookmarked(paperId: string): boolean {
      return this.bookmarkedIdSet.has(paperId);
    },

    /** 查询某篇论文的 tags（O(1) from tagsMap） */
    tagsFor(paperId: string): string[] {
      return this.tagsMap[paperId] || [];
    },

    // ============ RAG 页面跳转 ============

    /**
     * 跳转到 RAG 页面并自动选中指定论文
     */
    goToRagPage(paperId: string) {
      this._ragPendingPaperId = paperId;
      this._ragTargetPage = "rag";
    },

    /**
     * 从 PDF 预览里把选中的文字带入 RAG 问答：
     *   - 切换到 rag 页面
     *   - 自动选中目标 paper
     *   - 自动填入 questionDraft 并提交
     */
    goToRagWithSelection(
      paperId: string,
      question: string,
      meta: { page?: number; snippet?: string } | null = null,
    ) {
      const q = (question || "").trim();
      if (!paperId || !q) return;
      this._ragPendingPaperId = paperId;
      this._ragPendingQuestion = q;
      this._ragPendingQuestionMeta = meta
        ? {
            page: typeof meta.page === "number" ? meta.page : undefined,
            snippet: meta.snippet || q,
          }
        : null;
      this._ragTargetPage = "rag";
    },

    /** 清空由 PDF 选区带入的问题（消费完调用） */
    clearRagPendingQuestion() {
      this._ragPendingQuestion = null;
      this._ragPendingQuestionMeta = null;
    },

    /**
     * 触发全局 PDF Viewer（任何页面都可调用）。
     *  由 App.vue 监听 _pdfViewerRequest 渲染 PdfViewer。
     */
    openPdfViewer(req: {
      paperId: string;
      url: string;
      title?: string;
      downloadUrl?: string;
      initialPage?: number;
      // 翻译 PDF 可选：若提供，viewer 顶部会出现「原版 / 翻译版」切换按钮
      translatedUrl?: string;
      hasTranslated?: boolean;
    }) {
      if (!req || !req.paperId || !req.url) return;
      this._pdfViewerRequest = {
        paperId: req.paperId,
        url: req.url,
        title: req.title,
        downloadUrl: req.downloadUrl,
        initialPage: req.initialPage && req.initialPage > 0 ? req.initialPage : 1,
        translatedUrl: req.translatedUrl,
        hasTranslated: !!req.hasTranslated,
      };
    },

    closePdfViewer() {
      this._pdfViewerRequest = null;
    },
  },
});
