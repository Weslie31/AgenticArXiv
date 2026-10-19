// src/api/types.ts

export type Role = "user" | "assistant";

// ReAct history step
export interface ReactStep {
  thought: string;
  action: string;
  observation: string;
  [k: string]: any;
}

export interface Paper {
  id: string;
  title: string;
  authors?: string[];
  summary?: string | null;
  published?: string | null;
  updated?: string | null;
  pdf_url?: string | null;
  paper_url?: string | null;  // 论文详情页 URL（doi.org / openalex.org）
  primary_category?: string | null;
  categories?: string[];
  comment?: string | null;
  links?: string[];
  fetched_at?: string | null;  // 本次被检索到/写入 session 的时间（ISO 字符串）
  fetch_type?: "manual" | "subscription";  // manual=手动检索，subscription=定时订阅
  [k: string]: any;
}

export interface PdfAsset {
  paper_id: string;
  pdf_url?: string | null;
  local_path?: string | null;
  status?: string; // READY / DOWNLOADING / FAILED / STALE ...
  size_bytes?: number | null;
  sha256?: string | null;
  downloaded_at?: string | null;
  updated_at?: string | null;
  error?: string | null;
  [k: string]: any;
}

export interface DiscoveredPaper {
  paper_id: string;
  local_path: string;
  size_bytes: number;
  has_translation: boolean;
  translation_path: string | null;
}

export interface TranslateAsset {
  paper_id: string;
  input_pdf_path?: string | null;
  output_mono_path?: string | null;
  output_dual_path?: string | null;
  status?: string; // READY / TRANSLATING / FAILED / STALE ...
  service?: string | null;
  threads?: number | null;
  translated_at?: string | null;
  updated_at?: string | null;
  error?: string | null;
  log_path?: string | null;
  [k: string]: any;
}

// 后端 models.schemas.TranslateTask（按 endpoints.py / translate_runner.py 的字段适配）
export interface TranslateTask {
  task_id: string;
  session_id: string;
  paper_id: string;

  status: string; // PENDING / RUNNING / SUCCEEDED / FAILED ...
  progress?: number; // 0~1

  input_pdf_url?: string | null;
  input_pdf_path?: string | null;
  output_pdf_path?: string | null;

  error?: string | null;
  meta?: Record<string, any>;

  created_at?: string | null;
  updated_at?: string | null;

  [k: string]: any;
}

export type AgentType = "regex" | "mcp" | "skill_cli";

export interface ChatRequest {
  session_id: string;
  message: string;
  agent_model?: string | null;
  agent_type?: AgentType;
}

export interface ChatResponse {
  session_id: string;
  message: string;
  reply: string;
  history: ReactStep[];

  papers: Paper[];
  pdf_assets: PdfAsset[];
  translate_assets: TranslateAsset[];

  // 后端新增 tasks
  tasks?: TranslateTask[];
  agent_type?: AgentType;
}

export interface PdfAssetsResponse {
  assets: PdfAsset[];
}

export interface TranslateAssetsResponse {
  assets: TranslateAsset[];
}

// 删除接口返回
export type DeleteKind = "pdf" | "translate";

export interface DeleteAssetResponse {
  kind: DeleteKind;
  paper_id: string;
  removed_cache: boolean;
  deleted_files: string[];
  warnings: string[];
}

// --- Log types ---

export interface LogSessionSummary {
  session_id: string;
  message_count: number;
  last_active_at: string | null;
}

export interface ChatLogItem {
  msg_id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string | null;
  model: string | null;
  agent_type: string | null;
  created_at: string | null;
}

export interface AgentStepItem {
  step_index: number;
  thought: string | null;
  action_name: string | null;
  action_args: string | null;
  observation: string | null;
  llm_latency_ms: number | null;
  tool_latency_ms: number | null;
  created_at: string | null;
}

// SSE envelope：event_bus.publish 的结构
export interface SseEnvelope {
  type: string; // connected / task_created / task_started / task_succeeded / task_failed / asset_deleted / ...
  session_id?: string;

  kind?: string; // translate / pdf / ...
  task?: TranslateTask;

  // 删除事件（asset_deleted）会用到
  paper_id?: string;
  deleted_files?: string[];
  warnings?: string[];

  message?: string;

  // agent_step 事件
  step?: AgentStepItem;

  [k: string]: any;
}

// Paper Summary types
export interface PaperSummary {
  paper_id: string;
  status: "NOT_SUMMARIZED" | "SUMMARIZING" | "READY" | "FAILED";
  background?: string | null;
  innovation?: string | null;
  summarized_at?: string | null;
  error?: string | null;
}

export interface SummarizeResponse {
  summary: PaperSummary;
  message: string;
}

// ============ Paper Comparison types ============

export type ComparisonStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";

export interface ComparisonDimension {
  name: string;
  paper_values: Record<string, string>;
  ranking: string[];
  summary?: string | null;
}

export interface ComparisonReport {
  comparison_id: string;
  overview?: string | null;
  dimensions: ComparisonDimension[];
  recommendations?: string | null;
  created_at: string;
}

export interface PaperComparison {
  comparison_id: string;
  session_id: string;
  paper_ids: string[];
  status: ComparisonStatus;
  created_at: string;
  updated_at: string;
  error?: string | null;
}

export interface PaperComparisonWithReport {
  comparison: PaperComparison;
  report?: ComparisonReport | null;
  papers: Paper[];
}

export interface CreateComparisonRequest {
  session_id?: string;
  paper_ids: string[];
}

export interface CreateComparisonResponse {
  comparison: PaperComparison;
  papers: Paper[];
}

export interface ComparisonResultResponse {
  comparison: PaperComparison;
  papers: Paper[];
  report?: ComparisonReport | null;
  message: string;
}

export interface ComparisonListResponse {
  comparisons: PaperComparison[];
  total: number;
}

export interface ExecuteComparisonRequest {
  dimensions?: string[] | null;
  async_mode?: boolean;
}

export interface ExecuteComparisonResponse {
  message: string;
  comparison_id: string;
  status: ComparisonStatus;
  result?: {
    comparison: PaperComparison;
    papers: Paper[];
    report?: ComparisonReport | null;
  } | null;
}

// ============ RAG Paper QA types ============

export interface RagSource {
  kind?: "chunk" | "annotation";   // 后端标注；旧数据无此字段时默认 "chunk"
  page: string;
  section: string | null;
  snippet: string;
  score: number;
  // chunk 来源才有的字段
  chunk_index?: number;
  // annotation 来源才有的字段
  annotation_id?: number;
  comment?: string;
}

export interface RagAskRequest {
  session_id?: string;
  paper_id: string;
  question: string;
  top_k?: number;
  force_reindex?: boolean;
  include_annotations?: boolean;   // 默认 true，按 session 召回个人批注
  selected_text?: string;          // 用户在 PDF 中拖选出的文字（最高优先级 context）
  selected_page?: number;          // 选中片段所在的页码
}

export interface RagAskResponse {
  answer: string;
  sources: RagSource[];
  annotations_used: AnnotationCite[];  // 实际注入上下文的高相关批注
  confidence: "high" | "medium" | "low";
  chunk_count: number;
  indexed: boolean;
}

export interface RagIndexRequest {
  paper_id: string;
  force?: boolean;
}

export interface RagIndexResponse {
  paper_id: string;
  chunk_count: number;
  status: string;
}

export interface RagSummarizeRequest {
  paper_id: string;
  focus?: "general" | "method" | "experiment" | "conclusion" | "contribution";
  max_length?: number;
}

export interface RagSummarizeResponse {
  paper_id: string;
  summary: string;
  focus: string;
}

// ============ 定时订阅 ============

export interface Subscription {
  id: string;
  name: string;
  aspects: string[];
  keywords: string[];
  exclude_keywords: string[];
  days: number;
  max_results: number;
  enabled: boolean;
  session_id: string;
  match_mode: "any" | "all";
  interval_minutes: number | null;
  last_run_at: string | null;
  last_run_count: number;
  created_at: string;
}

export interface SubscriptionCreatePayload {
  id?: string | null;
  name: string;
  aspects?: string[];
  keywords?: string[];
  exclude_keywords?: string[];
  days?: number;
  max_results?: number;
  enabled?: boolean;
  session_id?: string;
  match_mode?: "any" | "all";
  interval_minutes?: number | null;
}

export interface SubscriptionUpdatePayload {
  name?: string;
  aspects?: string[];
  keywords?: string[];
  exclude_keywords?: string[];
  days?: number;
  max_results?: number;
  enabled?: boolean;
  match_mode?: "any" | "all";
  interval_minutes?: number | null;
}

export interface SubscriptionResult {
  subscription_id: string;
  subscription_name: string;
  papers_count: number;
  new_papers_count: number;
  duration_ms: number;
  errors: string[];
  run_at: string | null;
}

// ============ 论文批注 ============

export interface Annotation {
  id: number;
  paper_id: string;
  session_id: string;
  chunk_index: number | null;
  page_number: number | null;
  highlighted_text: string;
  comment: string;
  created_at: string;  // ISO
  updated_at: string;  // ISO
}

export interface AnnotationCreatePayload {
  paper_id: string;
  session_id?: string;
  page_number?: number | null;
  highlighted_text: string;
  comment: string;
  chunk_index?: number | null;
}

export interface AnnotationUpdatePayload {
  page_number?: number | null;
  highlighted_text?: string;
  comment?: string;
}

export interface AnnotationListResponse {
  paper_id: string;
  session_id: string;
  items: Annotation[];
}

/** RAG 答案里引用的批注（精简版） */
export interface AnnotationCite {
  annotation_id: number;
  page_number: number | null;
  snippet: string;
  comment: string;
  score: number;
}

// 本地前端缓存：每篇论文的历史问答
export interface RagHistoryEntry {
  question: string;
  answer: string;
  confidence: string;
  sources: RagSource[];
  annotations_used?: AnnotationCite[];
  asked_at: string; // ISO
}

// ============ 论文收藏 / 标签（跨会话个人兴趣库） ============

export interface PaperTag {
  id: number;
  paper_id: string;
  tag: string;
  created_at: string;
}

export interface PaperTagList {
  paper_id: string;
  tags: string[];           // 平铺字符串数组
  items: PaperTag[];        // 完整对象（含 created_at）
}

export interface PaperBookmark {
  id: number;
  paper_id: string;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaperBookmarkWithPaper {
  bookmark: PaperBookmark;
  paper: Paper | null;      // 论文可能已被清理：null 时仅展示 paper_id
  tags: string[];
}

export interface PaperBookmarkList {
  items: PaperBookmarkWithPaper[];
  total: number;
  all_tags: string[];
}

/** 批量 flags 查询响应：用于论文列表行内 ⭐/🏷️ 渲染 */
export interface PaperFlagsResponse {
  bookmarked: string[];
  tags_map: Record<string, string[]>;
}

export interface TagCreatePayload {
  tag: string;
}

export interface BookmarkCreatePayload {
  note?: string | null;
}

export interface BookmarkUpdatePayload {
  note?: string | null;
}

export interface BookmarkDeleteResponse {
  paper_id: string;
  removed: boolean;
  removed_tag_count: number;
}

