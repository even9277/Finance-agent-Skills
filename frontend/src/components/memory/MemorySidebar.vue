<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMemoryStore } from '@/stores/memoryStore'
import { useMemory } from '@/composables/useMemory'
import RiskProfileCard from './RiskProfileCard.vue'
import SectorTagSelector from './SectorTagSelector.vue'
import ReturnExpectation from './ReturnExpectation.vue'
import WatchlistPanel from './WatchlistPanel.vue'

const router = useRouter()
const memoryStore = useMemoryStore()
const {
  loadProfile,
  updateRisk,
  updateSectors,
  updateReturn,
  clearAllMemories,
} = useMemory()

const showClearConfirm = ref(false)
const clearing = ref(false)

onMounted(async () => {
  if (!memoryStore.loaded) {
    await loadProfile()
  }
})

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

const stats = computed(() => memoryStore.stats)
const hasProfile = computed(() => {
  const p = memoryStore.profile
  return !!(p.risk_profile || p.sectors.length || p.return_expectation || p.investment_horizon)
})
</script>

<template>
  <div class="flex flex-col h-full text-sm">
    <div class="px-3 py-3 border-b border-slate-800">
      <h3 class="text-xs font-semibold text-slate-300 font-serif">记忆画像</h3>
      <p class="text-[10px] text-slate-600 mt-0.5">跨会话个性化投研偏好</p>
    </div>

    <div class="flex-1 overflow-y-auto p-3 space-y-5">
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

      <div class="pt-2 border-t border-slate-800">
        <button
          v-if="!showClearConfirm"
          class="w-full text-[10px] text-slate-600 hover:text-red-400 transition-colors py-1"
          @click="showClearConfirm = true"
        >
          清除所有记忆与画像
        </button>
        <div v-else class="space-y-1.5">
          <p class="text-[10px] text-red-400 text-center">⚠ 此操作不可撤销，确认清除？</p>
          <div class="flex gap-2">
            <button
              class="flex-1 text-[10px] py-1 bg-red-900/40 text-red-400 rounded hover:bg-red-900/60 transition-colors"
              :disabled="clearing"
              @click="doClearAll"
            >{{ clearing ? '清除中...' : '确认清除' }}</button>
            <button
              class="flex-1 text-[10px] py-1 border border-slate-700 text-slate-500 rounded hover:text-slate-300 transition-colors"
              @click="showClearConfirm = false"
            >取消</button>
          </div>
        </div>
      </div>
    </div>

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
