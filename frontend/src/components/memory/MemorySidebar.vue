<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useMemoryStore } from '@/stores/memoryStore'
import { useMemory } from '@/composables/useMemory'
import { useRouter } from 'vue-router'
import RiskProfileCard from './RiskProfileCard.vue'
import SectorTagSelector from './SectorTagSelector.vue'
import ReturnExpectation from './ReturnExpectation.vue'
import WatchlistPanel from './WatchlistPanel.vue'

const router = useRouter()
const memoryStore = useMemoryStore()
const { loadProfile, updateRisk, updateSectors, updateReturn, clearAllMemories, loadMemoryItems } = useMemory()

const activeTab = ref<'overview' | 'items'>('overview')
const showClearConfirm = ref(false)
const clearing = ref(false)
const loadingItems = ref(false)

onMounted(async () => {
  // Phase 3: 只在全局 store 尚未加载时才触发加载（正常情况下 App.vue 已加载）
  if (!memoryStore.loaded) {
    await loadProfile()
  }
})

async function switchTab(tab: 'overview' | 'items') {
  activeTab.value = tab
  // 每次进入「记忆条目」都重新拉取，避免 itemsLoaded 一直为 true 导致列表不刷新
  if (tab === 'items') {
    loadingItems.value = true
    try {
      await loadMemoryItems(1)
    } finally {
      loadingItems.value = false
    }
  }
}

function handleGenerateReport(code: string) {
  router.push({ name: 'Report', query: { q: code } })
}

async function doClearAll() {
  clearing.value = true
  try {
    await clearAllMemories()
    showClearConfirm.value = false
    await loadProfile()
    memoryStore.clearItems()
  } finally {
    clearing.value = false
  }
}

// 来源颜色
function sourceColor(source: string): string {
  const map: Record<string, string> = {
    ui: 'text-amber-400 bg-amber-400/10',
    cold_start: 'text-blue-400 bg-blue-400/10',
    chat_inferred: 'text-slate-400 bg-slate-400/10',
    report_inferred: 'text-slate-400 bg-slate-400/10',
    explicit_correction: 'text-emerald-400 bg-emerald-400/10',
  }
  return map[source] || 'text-slate-500 bg-slate-500/10'
}

function sourceLabel(source: string): string {
  const map: Record<string, string> = {
    ui: 'UI设置', cold_start: '冷启动',
    chat_inferred: '对话推断', report_inferred: '报告推断',
    explicit_correction: '主动纠正',
  }
  return map[source] || source
}

/** 展示创建时间（API 保证有 created_at 字段，可能为空串） */
function formatCreatedAt(iso: string | undefined): string {
  const s = (iso ?? '').trim()
  if (!s) return '时间未知'
  try {
    const d = new Date(s)
    if (Number.isNaN(d.getTime())) return s
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return s
  }
}

const stats = computed(() => memoryStore.stats)
const commandNotice = computed(() => memoryStore.lastCommand)
const hasProfile = computed(() => {
  const p = memoryStore.profile
  return !!(p.risk_profile || p.sectors.length || p.return_expectation || p.investment_horizon)
})
</script>

<template>
  <div class="flex flex-col h-full text-sm">
    <!-- 标题 -->
    <div class="px-3 py-3 border-b border-slate-800">
      <h3 class="text-xs font-semibold text-slate-300 font-serif">记忆画像</h3>
      <p class="text-[10px] text-slate-600 mt-0.5">跨会话个性化投研偏好</p>
    </div>

    <!-- 标签页 -->
    <div class="flex border-b border-slate-800">
      <button
        v-for="tab in [{ id: 'overview', label: '画像总览' }, { id: 'items', label: '记忆条目' }]"
        :key="tab.id"
        :class="[
          'flex-1 py-1.5 text-xs transition-colors',
          activeTab === tab.id
            ? 'text-amber-400 border-b-2 border-amber-500'
            : 'text-slate-500 hover:text-slate-300',
        ]"
        @click="switchTab(tab.id as 'overview' | 'items')"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 画像总览 -->
    <div v-if="activeTab === 'overview'" class="flex-1 overflow-y-auto p-3 space-y-5">

      <!-- 无画像引导 -->
      <div v-if="!hasProfile && !memoryStore.loaded" class="text-center py-6">
        <div class="text-2xl mb-2">⏳</div>
        <p class="text-xs text-slate-500">加载中...</p>
      </div>

      <template v-else>
        <RiskProfileCard
          :value="memoryStore.profile.risk_profile ?? undefined"
          @update="updateRisk"
        />
        <SectorTagSelector
          :selected="memoryStore.profile.sectors"
          @update="updateSectors"
        />
        <ReturnExpectation
          :value="memoryStore.profile.return_expectation ?? undefined"
          :risk-profile="memoryStore.profile.risk_profile ?? undefined"
          @update="updateReturn"
        />
        <WatchlistPanel
          :watchlist="memoryStore.profile.watchlist"
          @generate-report="handleGenerateReport"
        />
      </template>

      <!-- 清除按钮 -->
      <div class="pt-2 border-t border-slate-800">
        <div v-if="commandNotice" class="mb-2 text-[10px] text-amber-400" role="status">
          {{ commandNotice.user_message }}
          <span v-if="commandNotice.pending_confirmation_id">请回到对话中回复“确认”或“取消”。</span>
        </div>
        <button
          v-if="!showClearConfirm"
          class="w-full text-[10px] text-slate-600 hover:text-red-400 transition-colors py-1"
          @click="showClearConfirm = true"
        >
          请求清理文本记忆
        </button>
        <div v-else class="space-y-1.5">
          <p class="text-[10px] text-red-400 text-center">将先生成预览，不会直接删除。</p>
          <div class="flex gap-2">
            <button
              class="flex-1 text-[10px] py-1 bg-red-900/40 text-red-400 rounded hover:bg-red-900/60 transition-colors"
              :disabled="clearing"
              @click="doClearAll"
            >{{ clearing ? '生成预览中...' : '生成清理预览' }}</button>
            <button
              class="flex-1 text-[10px] py-1 border border-slate-700 text-slate-500 rounded hover:text-slate-300 transition-colors"
              @click="showClearConfirm = false"
            >取消</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 记忆条目（Phase 3 Mem0 数据） -->
    <div v-else class="flex-1 overflow-y-auto p-3">
      <div v-if="loadingItems" class="text-center py-8">
        <div class="text-2xl mb-2 animate-pulse">🧠</div>
        <p class="text-xs text-slate-500">加载记忆条目中...</p>
      </div>

      <div v-else-if="memoryStore.memoryItems.length === 0" class="text-center py-8 text-slate-600">
        <div class="text-2xl mb-2">🧠</div>
        <p class="text-xs">暂无记忆条目</p>
        <p class="text-[10px] mt-1 text-slate-700">对话或完成冷启动后将自动生成</p>
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="item in memoryStore.memoryItems"
          :key="item.id"
          class="p-2 rounded-lg bg-slate-900/60 border border-slate-800/60"
        >
          <p class="text-[11px] text-slate-300 leading-relaxed">{{ item.content }}</p>
          <p class="text-[9px] text-slate-600 mt-1">创建：{{ formatCreatedAt(item.created_at) }}</p>
          <div class="flex items-center gap-1.5 mt-1.5">
            <span
              v-if="item.category"
              class="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-500"
            >{{ item.category }}</span>
            <span
              v-if="item.source"
              :class="['text-[9px] px-1.5 py-0.5 rounded', sourceColor(item.source)]"
            >{{ sourceLabel(item.source) }}</span>
            <span
              v-if="item.confidence && item.confidence < 0.9"
              class="text-[9px] text-slate-600 ml-auto"
            >置信度 {{ Math.round(item.confidence * 100) }}%</span>
          </div>
        </div>

        <!-- 分页加载更多 -->
        <div v-if="memoryStore.hasMoreItems" class="text-center pt-2">
          <button
            class="text-[10px] text-slate-500 hover:text-amber-400 transition-colors"
            @click="loadMemoryItems(memoryStore.currentPage + 1)"
          >加载更多</button>
        </div>
      </div>
    </div>

    <!-- 底部统计 -->
    <div class="border-t border-slate-800 px-3 py-2 text-[10px] text-slate-600">
      <div class="flex justify-between items-center">
        <span>
          来自
          <span class="text-slate-500">{{ stats.from_conversations }}</span> 次对话 +
          <span class="text-slate-500">{{ stats.from_manual }}</span> 次手动设置
        </span>
        <span class="text-slate-700">Phase 3</span>
      </div>
    </div>
  </div>
</template>
