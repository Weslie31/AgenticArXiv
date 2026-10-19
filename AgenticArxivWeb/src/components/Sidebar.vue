<template>
  <nav class="sidebar">
    <div class="brand-icon" title="CS 分类参考" @click="showCategories = true">A</div>

    <div class="nav-items">
      <button
        v-for="item in navItems"
        :key="item.key"
        class="nav-btn"
        :class="{ active: currentPage === item.key }"
        :title="item.label"
        @click="$emit('update:currentPage', item.key)"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path v-if="item.key === 'chat'" d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
          <template v-if="item.key === 'papers'">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </template>
          <template v-if="item.key === 'subscriptions'">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </template>
          <template v-if="item.key === 'bookmarks'">
            <!-- ⭐ star icon -->
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </template>
          <template v-if="item.key === 'assets'">
            <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
            <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
            <line x1="12" y1="22.08" x2="12" y2="12" />
          </template>
          <template v-if="item.key === 'comparison'">
            <rect x="3" y="3" width="7" height="7" />
            <rect x="14" y="3" width="7" height="7" />
            <rect x="14" y="14" width="7" height="7" />
            <rect x="3" y="14" width="7" height="7" />
          </template>
          <template v-if="item.key === 'rag'">
            <!-- chat-bubble icon -->
            <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
            <line x1="9" y1="9" x2="15" y2="9" />
            <line x1="9" y1="13" x2="12" y2="13" />
          </template>
          <template v-if="item.key === 'logs'">
            <line x1="17" y1="10" x2="3" y2="10" />
            <line x1="21" y1="6" x2="3" y2="6" />
            <line x1="21" y1="14" x2="3" y2="14" />
            <line x1="17" y1="18" x2="3" y2="18" />
          </template>
          <template v-if="item.key === 'settings'">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
          </template>
        </svg>
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </div>

    <button class="nav-btn theme-btn" :title="isDark ? '切换亮色' : '切换暗色'" @click="toggleTheme">
      <svg v-if="isDark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="5" />
        <line x1="12" y1="1" x2="12" y2="3" />
        <line x1="12" y1="21" x2="12" y2="23" />
        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
        <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
        <line x1="1" y1="12" x2="3" y2="12" />
        <line x1="21" y1="12" x2="23" y2="12" />
        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
        <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
      </svg>
      <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
      </svg>
      <span class="nav-label">{{ isDark ? '亮色' : '暗色' }}</span>
    </button>

    <Modal :open="showCategories" title="arXiv CS 分类参考" @close="showCategories = false">
      <table class="cat-table">
        <thead>
          <tr><th>代码</th><th>名称</th></tr>
        </thead>
        <tbody>
          <tr v-for="[code, enName, zhName] in categories" :key="code">
            <td class="cat-code">cs.{{ code }}</td>
            <td>{{ enName }} <span class="cat-zh">{{ zhName }}</span></td>
          </tr>
        </tbody>
      </table>
      <template #footer>
        <div class="cat-footer">
          <span class="cat-hint">示例：获取最近7天内AI(cs.AI)方向论文，最多5篇</span>
          <button class="btn primary" @click="showCategories = false">关闭</button>
        </div>
      </template>
    </Modal>
  </nav>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import Modal from "@/components/Modal.vue";

defineProps<{ currentPage: string }>();
defineEmits<{ (e: "update:currentPage", val: string): void }>();

const navItems = [
  { key: "chat", label: "对话" },
  { key: "papers", label: "论文" },
  { key: "comparison", label: "对比" },
  { key: "rag", label: "RAG" },
  { key: "subscriptions", label: "订阅" },
  { key: "bookmarks", label: "收藏" },
  { key: "assets", label: "缓存" },
  { key: "logs", label: "日志" },
  { key: "settings", label: "设置" },
];

const showCategories = ref(false);

const categories: [string, string, string][] = [
  ["*", "All Computer Science", "全部计算机科学"],
  ["AI", "Artificial Intelligence", "人工智能"],
  ["AR", "Hardware Architecture", "硬件架构"],
  ["CC", "Computational Complexity", "计算复杂度"],
  ["CE", "Computational Engineering, Finance, and Science", "计算工程、金融与科学"],
  ["CG", "Computational Geometry", "计算几何"],
  ["CL", "Computation and Language", "计算语言学"],
  ["CR", "Cryptography and Security", "密码学与安全"],
  ["CV", "Computer Vision and Pattern Recognition", "计算机视觉与模式识别"],
  ["CY", "Computers and Society", "计算与社会"],
  ["DB", "Databases", "数据库"],
  ["DC", "Distributed, Parallel, and Cluster Computing", "分布式、并行与集群计算"],
  ["DL", "Digital Libraries", "数字图书馆"],
  ["DM", "Discrete Mathematics", "离散数学"],
  ["DS", "Data Structures and Algorithms", "数据结构与算法"],
  ["ET", "Emerging Technologies", "新兴技术"],
  ["FL", "Formal Languages and Automata Theory", "形式语言与自动机理论"],
  ["GL", "General Literature", "通用文献"],
  ["GR", "Graphics", "图形学"],
  ["GT", "Computer Science and Game Theory", "计算机科学与博弈论"],
  ["HC", "Human-Computer Interaction", "人机交互"],
  ["IR", "Information Retrieval", "信息检索"],
  ["IT", "Information Theory", "信息论"],
  ["LG", "Machine Learning", "机器学习"],
  ["LO", "Logic in Computer Science", "计算机科学逻辑"],
  ["MA", "Multiagent Systems", "多智能体系统"],
  ["MM", "Multimedia", "多媒体"],
  ["MS", "Mathematical Software", "数学软件"],
  ["NA", "Numerical Analysis", "数值分析"],
  ["NE", "Neural and Evolutionary Computing", "神经与进化计算"],
  ["NI", "Networking and Internet Architecture", "网络与互联网架构"],
  ["OH", "Other Computer Science", "其他计算机科学"],
  ["OS", "Operating Systems", "操作系统"],
  ["PF", "Performance", "性能"],
  ["PL", "Programming Languages", "编程语言"],
  ["RO", "Robotics", "机器人学"],
  ["SC", "Symbolic Computation", "符号计算"],
  ["SD", "Sound", "声音"],
  ["SE", "Software Engineering", "软件工程"],
  ["SI", "Social and Information Networks", "社会与信息网络"],
  ["SY", "Systems and Control", "系统与控制"],
];

const isDark = ref(true);

function applyTheme(dark: boolean) {
  isDark.value = dark;
  if (dark) {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", "light");
  }
  localStorage.setItem("theme", dark ? "dark" : "light");
}

function toggleTheme() {
  applyTheme(!isDark.value);
}

onMounted(() => {
  const saved = localStorage.getItem("theme");
  if (saved === "light") {
    applyTheme(false);
  }
});
</script>

<style scoped>
.sidebar {
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  width: 60px;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0;
  z-index: 20;
}

.brand-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(89,153,255,0.15);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 900;
  font-size: 16px;
  margin-bottom: 16px;
  flex-shrink: 0;
  cursor: pointer;
  transition: background 0.15s;
}
.brand-icon:hover {
  background: rgba(89,153,255,0.25);
}

.nav-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.nav-btn {
  width: 44px;
  height: 44px;
  border: none;
  border-radius: 12px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  position: relative;
  transition: background 0.15s, color 0.15s;
}

.nav-btn svg {
  width: 20px;
  height: 20px;
}

.nav-label {
  font-size: 9px;
  line-height: 1;
}

.nav-btn:hover {
  background: var(--hover-bg);
  color: var(--fg);
}

.nav-btn.active {
  background: rgba(89,153,255,0.12);
  color: var(--accent);
}

.nav-btn.active::before {
  content: "";
  position: absolute;
  left: -8px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  border-radius: 0 3px 3px 0;
  background: var(--accent);
}

.theme-btn {
  margin-bottom: 4px;
  flex-shrink: 0;
}

/* Categories table */
.cat-table {
  width: 100%;
  border-collapse: collapse;
}
.cat-table th, .cat-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  font-size: 13px;
}
.cat-table th {
  color: var(--muted);
  font-weight: 600;
  position: sticky;
  top: 0;
  background: var(--modal-bg);
}
.cat-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-weight: 600;
  color: var(--accent);
  white-space: nowrap;
}
.cat-zh {
  color: var(--muted);
  font-size: 12px;
  margin-left: 4px;
}
.cat-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.cat-hint {
  color: var(--muted);
  font-size: 12px;
}

@media (max-width: 768px) {
  .sidebar {
    width: 100%;
    height: 52px;
    top: auto;
    bottom: 0;
    left: 0;
    flex-direction: row;
    justify-content: space-around;
    padding: 0 8px;
    border-right: none;
    border-top: 1px solid var(--border);
  }
  .brand-icon { display: none; }
  .nav-items { flex-direction: row; gap: 0; }
  .nav-btn { width: 52px; height: 44px; }
  .theme-btn { display: none; }
  .nav-btn.active::before {
    left: 50%;
    top: -1px;
    transform: translateX(-50%);
    width: 20px;
    height: 3px;
    border-radius: 0 0 3px 3px;
  }
}
</style>
