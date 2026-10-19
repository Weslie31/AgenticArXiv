<template>
  <section class="settings-page">
    <div class="settings-card">
      <h2 class="section-title">连接</h2>

      <div class="field">
        <label class="field-label">API 地址</label>
        <div class="field-value mono">{{ store.apiBase }}</div>
      </div>

      <div class="field">
        <label class="field-label">SSE 状态</label>
        <div class="field-row">
          <span class="pill" :class="store.sseStatus">{{ sseLabel }}</span>
          <button class="btn" @click="reconnectSse">重连</button>
        </div>
        <div class="field-hint" v-if="store.sseLastEvent">
          最近事件: {{ store.sseLastEvent }} · {{ fmtTs(store.sseLastEventTs) }}
        </div>
      </div>
    </div>

    <div class="settings-card">
        <h2 class="section-title">LLM 接入</h2>

      <!-- 当前生效配置（脱敏） -->
      <div class="field" v-if="llmLoaded">
        <label class="field-label">当前生效</label>
        <div class="llm-current">
          <div class="llm-current-row">
            <span class="muted-key">模型</span>
            <span class="mono">{{ llmCfg.model || "—" }}</span>
          </div>
          <div class="llm-current-row">
            <span class="muted-key">Base URL</span>
            <span class="mono">{{ llmCfg.base_url || "—" }}</span>
          </div>
          <div class="llm-current-row">
            <span class="muted-key">API Key</span>
            <span class="mono">{{ llmCfg.api_key_masked || "—" }}</span>
          </div>
          <div class="llm-current-row">
            <span class="muted-key">状态</span>
            <span class="pill" :class="llmCfg.is_default ? 'idle' : 'connected'">
            {{ llmCfg.is_default ? "使用系统默认" : "使用自定义配置" }}
            </span>
          </div>
        </div>
        <div
          v-if="llmCfg.warning"
          class="field-hint"
          style="color: #e0a100; margin-top: 6px;"
        >
          ⚠ {{ llmCfg.warning }}
        </div>
      </div>

      <!-- 编辑表单 -->
      <div class="field">
        <label class="field-label">Base URL</label>
        <div class="field-row">
          <input
            class="input"
            type="text"
            v-model="llmForm.base_url"
            placeholder="https://api.openai.com/v1"
            :disabled="llmSaving"
          />
        </div>
        <div class="field-hint">
          OpenAI 兼容接口地址。填 <code>https://api.openai.com</code> 或
          <code>https://api.openai.com/v1</code> 都可以，系统会自动补全
          <code>/v1/chat/completions</code>。
        </div>
      </div>

      <div class="field">
        <label class="field-label">API Key</label>
        <div class="field-row">
          <input
            class="input"
            :type="showKey ? 'text' : 'password'"
            v-model="llmForm.api_key"
            placeholder="留空 = 不修改当前 Key"
            :disabled="llmSaving"
          />
          <button
            type="button"
            class="btn small"
            @click="showKey = !showKey"
            :disabled="llmSaving"
          >
            {{ showKey ? "隐藏" : "显示" }}
          </button>
        </div>
        <div class="field-hint">仅存于服务端数据库，本地浏览器不留明文。</div>
      </div>

      <div class="field">
        <label class="field-label">模型</label>
        <div class="field-row">
          <select class="select" v-model="llmForm.model" :disabled="llmSaving">
            <option value="">— 选择预设 —</option>
            <option v-for="m in llmPresets" :key="m.id" :value="m.id">
              {{ m.label }}（{{ m.provider }}）
            </option>
          </select>
          <input
            class="input"
            type="text"
            v-model="llmForm.model"
            placeholder="或手动输入模型名"
            :disabled="llmSaving"
          />
        </div>
      </div>

      <!-- 操作 -->
      <div class="field" style="margin-top: 12px;">
        <div class="field-row">
          <button class="btn primary" :disabled="llmSaving || llmTesting" @click="saveLlmConfig">
            {{ llmSaving ? "保存中…" : "保存" }}
          </button>
          <button class="btn" :disabled="llmSaving || llmTesting" @click="testLlmConfig">
            {{ llmTesting ? "测试中…" : "测试连接" }}
          </button>
          <button
            class="btn"
            :disabled="llmSaving || llmTesting || (llmCfg.is_default && !llmCfg.warning)"
            @click="resetLlmConfig"
          >
            恢复系统默认
          </button>
          <span class="status" v-if="llmStatus" :class="llmStatusKind">{{ llmStatus }}</span>
        </div>
        <div class="field-hint" v-if="llmTestDetail" style="white-space: pre-wrap; word-break: break-all;">
          {{ llmTestDetail }}
        </div>
      </div>
    </div>

    <div class="settings-card">
      <h2 class="section-title">Agent 架构</h2>

      <div class="field">
        <label class="field-label">工具调用方案</label>
        <div class="field-row">
          <select class="select" v-model="store.agentType" @change="onAgentTypeChange">
            <option value="regex">ReAct + 正则解析</option>
            <option value="mcp">MCP 协议</option>
            <option value="skill_cli">Skill/CLI 命令</option>
          </select>
        </div>
        <div class="field-hint">{{ agentTypeHint }}</div>
      </div>
    </div>

    <div class="settings-card">
      <h2 class="section-title">翻译接入</h2>

      <!-- 当前生效配置（脱敏） -->
      <div class="field" v-if="trLoaded">
        <label class="field-label">当前生效</label>
        <div class="llm-current">
          <div class="llm-current-row">
            <span class="muted-key">引擎</span>
            <span>{{ trCfg.service || "bing" }}</span>
          </div>
          <div class="llm-current-row">
            <span class="muted-key">API Key</span>
            <span class="mono">{{ trCfg.api_key_masked || "（无）" }}</span>
          </div>
          <div class="llm-current-row">
            <span class="muted-key">状态</span>
            <span class="pill" :class="trCfg.is_default ? 'idle' : 'connected'">
            {{ trCfg.is_default ? "使用系统默认" : "使用自定义配置" }}
            </span>
          </div>
        </div>
      </div>

      <!-- 编辑表单 -->
      <div class="field">
        <label class="field-label">翻译引擎</label>
        <div class="field-row">
          <select class="select" v-model="trForm.service" :disabled="trSaving">
            <option v-for="s in translateServices" :key="s.value" :value="s.value">
              {{ s.label }}
            </option>
          </select>
        </div>
      </div>

      <div class="field">
        <label class="field-label">API Key</label>
        <div class="field-row">
          <input
            class="input"
            :type="trShowKey ? 'text' : 'password'"
            v-model="trForm.api_key"
            placeholder="留空 = 不修改当前 Key"
            :disabled="trSaving"
          />
          <button type="button" class="btn small" @click="trShowKey = !trShowKey" :disabled="trSaving">
            {{ trShowKey ? "隐藏" : "显示" }}
          </button>
        </div>
        <div class="field-hint">
          <template v-if="trForm.service === 'deepl'">
            从 <a href="https://www.deepl.com/pro-api" target="_blank">DeepL API</a> 获取
          </template>
          <template v-else-if="trForm.service === 'google'">
            Google 翻译走公开接口，<b>无需 Key</b>；填了 Key 也会优先走 Cloud API。
          </template>
          <template v-else-if="trForm.service === 'azure'">
            从 <a href="https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.CognitiveServices%2Faccounts" target="_blank">Azure Portal</a> 获取
          </template>
          <template v-else-if="trForm.service === 'openai'">
            从 <a href="https://platform.openai.com/api-keys" target="_blank">OpenAI Platform</a> 获取
          </template>
          <template v-else>
            该引擎由 pdf2zh 提供，通常无需 Key
          </template>
          · 仅存于服务端数据库
        </div>
      </div>

      <!-- 操作 -->
      <div class="field" style="margin-top: 12px;">
        <div class="field-row">
          <button class="btn primary" :disabled="trSaving || trTesting" @click="saveTranslateConfig">
            {{ trSaving ? "保存中…" : "保存" }}
          </button>
          <button class="btn" :disabled="trSaving || trTesting" @click="testTranslateConfig">
            {{ trTesting ? "测试中…" : "测试连接" }}
          </button>
          <button class="btn" :disabled="trSaving || trTesting || trCfg.is_default" @click="resetTranslateConfig">
            恢复系统默认
          </button>
          <span class="status" v-if="trStatus" :class="trStatusKind">{{ trStatus }}</span>
        </div>
        <div class="field-hint" v-if="trTestDetail" style="white-space: pre-wrap; word-break: break-all;">
          {{ trTestDetail }}
        </div>
      </div>
    </div>

    <div class="settings-card muted-card">
      <div class="about">AgenticArxiv v0.2.0 · ReAct Agent + arXiv 论文管理</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useAppStore, TRANSLATE_SERVICES } from "@/stores/appStore";
import type { TranslateService } from "@/stores/appStore";
import { api } from "@/api/client";

const store = useAppStore();

const translateServices = TRANSLATE_SERVICES;

onMounted(loadLlmConfig);
onMounted(loadTranslateConfig);

    // ---------- 翻译服务配置 ----------
interface TranslateConfig {
  service: string;
  api_key_masked: string;
  is_default: boolean;
}

const trLoaded = ref(false);
const trCfg = ref<TranslateConfig>({ service: "bing", api_key_masked: "", is_default: true });
const trForm = ref({ service: "bing", api_key: "" });
const trSaving = ref(false);
const trTesting = ref(false);
const trShowKey = ref(false);
const trStatus = ref("");
const trStatusKind = ref<"ok" | "err" | "">("");
const trTestDetail = ref("");

function setTrStatus(text: string, kind: "ok" | "err" | "" = "") {
  trStatus.value = text;
  trStatusKind.value = kind;
  if (kind === "ok") {
    setTimeout(() => {
      if (trStatus.value === text) { trStatus.value = ""; trStatusKind.value = ""; }
    }, 2500);
  }
}

async function loadTranslateConfig() {
  try {
    const resp = await api.get<TranslateConfig>("/translate/config");
    trCfg.value = resp.data;
    trForm.value.service = resp.data.service || "bing";
    trForm.value.api_key = ""; // 不回填明文
    trLoaded.value = true;
  } catch (e: any) {
    setTrStatus(
      "加载翻译配置失败: " + (e?.response?.data?.detail || e?.message || String(e)),
      "err",
    );
  }
}

async function saveTranslateConfig() {
  trSaving.value = true;
  trTestDetail.value = "";
  try {
    const payload: Record<string, string | null> = {};
    if (trForm.value.service !== trCfg.value.service) {
      payload.service = trForm.value.service;
    }
    if (trForm.value.api_key) {
      payload.api_key = trForm.value.api_key;
    }
    if (Object.keys(payload).length === 0) {
      setTrStatus("没有变更需要保存", "");
      return;
    }
    const resp = await api.put<TranslateConfig>("/translate/config", payload);
    trCfg.value = resp.data;
    store.translateService = resp.data.service as any; // 同步前端下拉
    trForm.value.api_key = "";
    setTrStatus("已保存", "ok");
  } catch (e: any) {
    setTrStatus(
      "保存失败: " + (e?.response?.data?.detail || e?.message || String(e)),
      "err",
    );
  } finally {
    trSaving.value = false;
  }
}

async function testTranslateConfig() {
  trTesting.value = true;
  trTestDetail.value = "";
  try {
    const payload: Record<string, string | null> = {
      service: trForm.value.service || null,
      api_key: trForm.value.api_key || null,
    };
    const resp = await api.post<{ ok: boolean; message: string; detail?: string }>(
      "/translate/test",
      payload,
    );
    if (resp.data.ok) {
      setTrStatus("✓ " + resp.data.message, "ok");
    } else {
      setTrStatus("✗ " + resp.data.message, "err");
    }
    if (resp.data.detail) trTestDetail.value = resp.data.detail;
  } catch (e: any) {
    setTrStatus(
      "测试失败: " + (e?.response?.data?.detail || e?.message || String(e)),
      "err",
    );
  } finally {
    trTesting.value = false;
  }
}

async function resetTranslateConfig() {
    if (!confirm("确认恢复为系统默认翻译配置？已保存的配置将被清空。")) return;
  trSaving.value = true;
  try {
    await api.delete("/translate/config");
    await loadTranslateConfig();
    trForm.value.api_key = "";
    setTrStatus("已恢复系统默认", "ok");
  } catch (e: any) {
    setTrStatus(
      "重置失败: " + (e?.response?.data?.detail || e?.message || String(e)),
      "err",
    );
  } finally {
    trSaving.value = false;
  }
}

    // ---------- LLM 接入 ----------
interface LlmConfig {
  base_url: string;
  api_key_masked: string;
  model: string;
  is_default: boolean;
  warning?: string | null;
}
interface LlmPreset {
  id: string;
  label: string;
  provider: string;
}

const llmLoaded = ref(false);
const llmCfg = ref<LlmConfig>({ base_url: "", api_key_masked: "", model: "", is_default: true });
const llmForm = ref({ base_url: "", api_key: "", model: "" });
const llmPresets = ref<LlmPreset[]>([]);
const llmSaving = ref(false);
const llmTesting = ref(false);
const showKey = ref(false);
const llmStatus = ref("");
const llmStatusKind = ref<"ok" | "err" | "">("");
const llmTestDetail = ref("");

function setLlmStatus(text: string, kind: "ok" | "err" | "" = "") {
  llmStatus.value = text;
  llmStatusKind.value = kind;
  if (kind === "ok") {
    setTimeout(() => {
      if (llmStatus.value === text) {
        llmStatus.value = "";
        llmStatusKind.value = "";
      }
    }, 2500);
  }
}

async function loadLlmConfig() {
  try {
    const [cfgResp, presetsResp] = await Promise.all([
      api.get<LlmConfig>("/llm/config"),
      api.get<LlmPreset[]>("/llm/models"),
    ]);
    llmCfg.value = cfgResp.data;
    llmForm.value.base_url = cfgResp.data.base_url || "";
    llmForm.value.api_key = ""; // 不回填 Key（后端只返脱敏）
    llmForm.value.model = cfgResp.data.model || "";
    llmPresets.value = presetsResp.data || [];
    llmLoaded.value = true;
  } catch (e: any) {
    setLlmStatus(
      "加载 LLM 配置失败: " + (e?.response?.data?.detail || e?.message || String(e)),
      "err",
    );
  }
}

async function saveLlmConfig() {
  llmSaving.value = true;
  llmTestDetail.value = "";
  try {
    // 区分"未填"和"清空"：空字符串不发送，避免误清
    const payload: Record<string, string | null> = {};
    if (llmForm.value.base_url !== llmCfg.value.base_url) {
      payload.base_url = llmForm.value.base_url || null;
    }
    if (llmForm.value.api_key) {
      payload.api_key = llmForm.value.api_key;
    }
    if (llmForm.value.model !== llmCfg.value.model) {
      payload.model = llmForm.value.model || null;
    }
    if (Object.keys(payload).length === 0) {
      setLlmStatus("没有变更需要保存", "");
      return;
    }
    const resp = await api.put<LlmConfig>("/llm/config", payload);
    llmCfg.value = resp.data;
    llmForm.value.api_key = ""; // 保存后立即清空表单中的 Key
    setLlmStatus("已保存", "ok");
  } catch (e: any) {
    setLlmStatus(
      "保存失败: " + (e?.response?.data?.detail || e?.message || String(e)),
      "err",
    );
  } finally {
    llmSaving.value = false;
  }
}

async function testLlmConfig() {
  llmTesting.value = true;
  llmTestDetail.value = "";
  try {
      // 测试时若表单没填 Key，就用已保存的
    const payload: Record<string, string | null> = {
      base_url: llmForm.value.base_url || null,
      api_key: llmForm.value.api_key || null,
      model: llmForm.value.model || null,
    };
    const resp = await api.post<{ ok: boolean; message: string; detail?: string }>(
      "/llm/test",
      payload,
    );
    if (resp.data.ok) {
      setLlmStatus("✓ " + resp.data.message, "ok");
    } else {
      setLlmStatus("✗ " + resp.data.message, "err");
    }
    if (resp.data.detail) llmTestDetail.value = resp.data.detail;
  } catch (e: any) {
    setLlmStatus(
      "测试失败: " + (e?.response?.data?.detail || e?.message || String(e)),
      "err",
    );
  } finally {
    llmTesting.value = false;
  }
}

async function resetLlmConfig() {
  if (!confirm("确认恢复为系统默认 LLM 配置？你的自配项将被清空。")) return;
  llmSaving.value = true;
  try {
    await api.delete("/llm/config");
    await loadLlmConfig(); // 重新拉一遍
    llmForm.value.api_key = "";
    setLlmStatus("已恢复系统默认", "ok");
  } catch (e: any) {
    setLlmStatus(
      "重置失败: " + (e?.response?.data?.detail || e?.message || String(e)),
      "err",
    );
  } finally {
    llmSaving.value = false;
  }
}

const currentServiceLabel = computed(() => {
      // 优先用后端配置；前端下拉只是编辑时用的临时值
  if (trLoaded.value && trCfg.value.service) return trCfg.value.service;
  const s = translateServices.find((x) => x.value === store.translateService);
  return s ? s.label : store.translateService;
});

const sseLabelMap: Record<string, string> = {
  idle: "未连接",
  connecting: "连接中…",
  connected: "已连接",
  error: "连接失败",
};

const sseLabel = computed(() => sseLabelMap[store.sseStatus] || store.sseStatus);

const agentTypeHintMap: Record<string, string> = {
  regex: "ReAct prompt + 正则提取 JSON Action + 进程内直接函数调用",
  mcp: "ReAct prompt + 正则解析 + MCP JSON-RPC 跨进程工具调用",
  skill_cli: "Skill 文档 + LLM 生成 CLI 命令 + subprocess 执行",
};

const agentTypeHint = computed(() => agentTypeHintMap[store.agentType] || "");

function onAgentTypeChange() {
  localStorage.setItem("agent_type", store.agentType);
}

function reconnectSse() {
  store.closeSse();
  store.ensureSse();
}

function fmtTs(ts: number) {
  if (!ts) return "-";
  return new Date(ts).toLocaleString();
}
</script>

<style scoped>
.settings-page {
  padding: 20px;
  max-width: 640px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: calc(100vh - 36px);
  overflow: auto;
}

.settings-card {
  border: 1px solid var(--border);
  border-radius: 16px;
  background: rgba(255,255,255,0.02);
  padding: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 14px 0;
}

.field {
  margin-bottom: 16px;
}
.field:last-child { margin-bottom: 0; }

.field-label {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
  font-weight: 600;
}

.field-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.field-value {
  font-size: 13px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg2);
}

.field-hint {
  color: var(--muted);
  font-size: 11px;
  margin-top: 4px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
}

/* LLM config card */
.llm-current {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg2);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.llm-current-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.llm-current-row .muted-key {
  width: 70px;
  color: var(--muted);
  flex-shrink: 0;
}
.llm-current-row .mono {
  word-break: break-all;
  font-size: 12px;
}

.btn.small {
  font-size: 12px;
  padding: 4px 10px;
  height: 28px;
}
.status.ok { color: #00cc88; }
.status.err { color: #ff6b6b; }

code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: var(--bg2);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 11px;
}

/* Pill */
.pill {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  font-size: 12px;
}
.pill.idle { opacity: .7; }
.pill.connecting { border-color: rgba(255,200,0,.35); }
.pill.connected { border-color: rgba(0,255,153,.35); }
.pill.error { border-color: rgba(255,107,107,.35); }

/* Select */
.select {
  font-size: 13px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg, #0b0b10);
  color: var(--fg);
  outline: none;
  min-width: 200px;
  cursor: pointer;
}
.select option {
  background: var(--bg, #0b0b10);
  color: var(--fg);
}
.select:focus {
  border-color: var(--accent, #646cff);
}

/* Input */
.input {
  font-size: 13px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg, #0b0b10);
  color: var(--fg);
  outline: none;
  min-width: 280px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.input:focus {
  border-color: var(--accent, #646cff);
}
.input::placeholder {
  color: var(--muted);
}

.muted-card {
  background: transparent;
  border-color: transparent;
}
.about {
  text-align: center;
  color: var(--muted);
  font-size: 12px;
}

/* Link */
.field-hint a {
  color: var(--accent, #646cff);
  text-decoration: none;
}
.field-hint a:hover {
  text-decoration: underline;
}
</style>
