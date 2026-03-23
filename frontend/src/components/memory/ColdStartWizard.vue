<script setup lang="ts">
import { ref, computed } from 'vue'
import { useUserStore } from '@/stores/userStore'
import { useRouter, useRoute } from 'vue-router'
import RiskProfileCard from './RiskProfileCard.vue'
import SectorTagSelector from './SectorTagSelector.vue'
import ReturnExpectation from './ReturnExpectation.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const step = ref(1)
const TOTAL_STEPS = 4
const loading = ref(false)

// 收集的偏好数据
const displayName = ref('')
const riskProfile = ref('')
const sectors = ref<string[]>([])
const watchlistInput = ref('')
const watchlist = ref<string[]>([])
const returnExpectation = ref(10)
const investmentHorizon = ref('')

const HORIZON_OPTIONS = [
  { id: 'ultra_short', label: '超短线', desc: '日内 ~ 1周' },
  { id: 'short', label: '短线', desc: '1周 ~ 1月' },
  { id: 'swing', label: '波段', desc: '1~6个月' },
  { id: 'medium_long', label: '中长线', desc: '6个月以上' },
]

const stepTitles = ['基本信息', '风险偏好', '关注板块', '收益与周期']

const canNext = computed(() => {
  if (step.value === 1) return displayName.value.trim().length > 0
  if (step.value === 2) return !!riskProfile.value
  return true
})

function addWatchlist() {
  const code = watchlistInput.value.trim().toUpperCase()
  if (code && !watchlist.value.includes(code)) {
    watchlist.value.push(code)
  }
  watchlistInput.value = ''
}

async function finish() {
  loading.value = true
  try {
    const preferences = {
      risk_profile: riskProfile.value || undefined,
      sectors: sectors.value.length ? sectors.value : undefined,
      return_expectation: returnExpectation.value,
      investment_horizon: investmentHorizon.value || undefined,
      watchlist: watchlist.value.length ? watchlist.value : undefined,
    }
    await userStore.completeColdStart(displayName.value, preferences)
    const redirect = route.query.redirect as string || '/chat'
    router.push(redirect)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-[#0F172A] flex items-center justify-center p-4">
    <div class="w-full max-w-lg">
      <!-- 标题 -->
      <div class="text-center mb-8">
        <div class="w-14 h-14 bg-amber-500 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
            <polyline points="16 7 22 7 22 13" />
          </svg>
        </div>
        <h1 class="text-2xl font-bold text-slate-100 font-serif">欢迎使用智投助手</h1>
        <p class="text-slate-500 text-sm mt-1.5">用两分钟完成画像设置，获得个性化投研体验</p>
      </div>

      <!-- 步骤指示器 -->
      <div class="flex items-center justify-center mb-8 gap-2">
        <div
          v-for="i in TOTAL_STEPS"
          :key="i"
          :class="[
            'transition-all duration-300 rounded-full',
            i === step ? 'w-6 h-2 bg-amber-500' :
            i < step ? 'w-2 h-2 bg-amber-500/50' :
            'w-2 h-2 bg-slate-700',
          ]"
        />
      </div>

      <!-- 步骤卡片 -->
      <div class="bg-[#1E293B] border border-slate-700 rounded-2xl p-6 shadow-xl">
        <h2 class="text-base font-semibold text-slate-200 font-serif mb-4">
          第 {{ step }} 步：{{ stepTitles[step - 1] }}
        </h2>

        <!-- Step 1：基本信息 -->
        <div v-if="step === 1" class="space-y-4">
          <div>
            <label class="text-xs text-slate-400 block mb-1.5">您的昵称</label>
            <input
              v-model="displayName"
              type="text"
              placeholder="例如：价值投资者"
              maxlength="20"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-amber-500/60 transition-colors"
            />
          </div>
        </div>

        <!-- Step 2：风险偏好 -->
        <div v-else-if="step === 2">
          <RiskProfileCard :value="riskProfile || undefined" @update="riskProfile = $event" />
        </div>

        <!-- Step 3：关注板块 + 自选股 -->
        <div v-else-if="step === 3" class="space-y-4">
          <SectorTagSelector :selected="sectors" @update="sectors = $event" />

          <div class="pt-2 border-t border-slate-700">
            <p class="text-xs text-slate-500 mb-2">自选股（可选，输入股票代码）</p>
            <div class="flex gap-2 mb-2">
              <input
                v-model="watchlistInput"
                type="text"
                placeholder="如: 600519"
                class="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-amber-500/60"
                @keyup.enter="addWatchlist"
              />
              <button
                class="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded-lg transition-colors"
                @click="addWatchlist"
              >添加</button>
            </div>
            <div v-if="watchlist.length" class="flex flex-wrap gap-1.5">
              <span
                v-for="code in watchlist"
                :key="code"
                class="flex items-center gap-1 text-xs px-2 py-1 bg-slate-800 border border-slate-700 rounded-md text-slate-300"
              >
                {{ code }}
                <button class="text-slate-500 hover:text-red-400" @click="watchlist = watchlist.filter(c => c !== code)">✕</button>
              </span>
            </div>
          </div>
        </div>

        <!-- Step 4：期望收益 + 投资周期 -->
        <div v-else-if="step === 4" class="space-y-5">
          <ReturnExpectation
            :value="returnExpectation"
            :risk-profile="riskProfile"
            @update="returnExpectation = $event"
          />

          <div class="pt-3 border-t border-slate-700">
            <p class="text-xs text-slate-500 mb-2">投资周期</p>
            <div class="grid grid-cols-2 gap-2">
              <button
                v-for="h in HORIZON_OPTIONS"
                :key="h.id"
                :class="[
                  'px-3 py-2 rounded-lg border text-left transition-all',
                  investmentHorizon === h.id
                    ? 'border-amber-500 bg-amber-500/10 text-amber-300'
                    : 'border-slate-700 text-slate-400 hover:border-slate-600 hover:text-slate-300',
                ]"
                @click="investmentHorizon = h.id"
              >
                <div class="text-xs font-medium">{{ h.label }}</div>
                <div class="text-[10px] opacity-70">{{ h.desc }}</div>
              </button>
            </div>
          </div>
        </div>

        <!-- 导航按钮 -->
        <div class="flex justify-between mt-6 pt-4 border-t border-slate-700">
          <button
            v-if="step > 1"
            class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors"
            @click="step--"
          >← 上一步</button>
          <div v-else class="flex-1" />

          <div class="flex gap-2">
            <button
              v-if="step < TOTAL_STEPS"
              class="px-2 py-2 text-xs text-slate-500 hover:text-slate-300 transition-colors"
              @click="step++"
            >跳过</button>
            <button
              v-if="step < TOTAL_STEPS"
              :disabled="!canNext"
              :class="[
                'px-5 py-2 rounded-lg text-xs font-semibold transition-all',
                canNext
                  ? 'bg-amber-500 hover:bg-amber-400 text-black'
                  : 'bg-slate-700 text-slate-500 cursor-not-allowed',
              ]"
              @click="step++"
            >
              下一步 →
            </button>
            <button
              v-else
              :disabled="loading"
              class="flex items-center gap-2 px-5 py-2 bg-amber-500 hover:bg-amber-400 text-black text-xs font-semibold rounded-lg transition-all disabled:opacity-60"
              @click="finish"
            >
              <svg v-if="loading" class="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-dasharray="30 60" />
              </svg>
              {{ loading ? '正在保存...' : '完成设置 ✓' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 底部跳过 -->
      <p class="text-center mt-4">
        <button
          class="text-xs text-slate-600 hover:text-slate-400 transition-colors"
          @click="router.push('/chat')"
        >
          稍后再说，直接进入 →
        </button>
      </p>
    </div>
  </div>
</template>
