<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  watchlist: string[]
  readonly?: boolean
}>()
const emit = defineEmits<{
  (e: 'remove', code: string): void
  (e: 'generateReport', code: string): void
  (e: 'add', code: string): void
}>()

const newCode = ref('')
const adding = ref(false)

function addStock() {
  const code = newCode.value.trim().toUpperCase()
  if (!code) return
  emit('add', code)
  newCode.value = ''
  adding.value = false
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-3">
      <p class="text-xs text-slate-500">自选股</p>
      <button
        v-if="!readonly && !adding"
        class="text-[10px] text-amber-400 hover:text-amber-300 transition-colors"
        @click="adding = true"
      >+ 添加</button>
    </div>

    <!-- 添加输入框 -->
    <div v-if="adding" class="flex gap-1.5 mb-2">
      <input
        v-model="newCode"
        type="text"
        placeholder="股票代码/名称"
        class="flex-1 bg-slate-800/80 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-amber-500"
        @keydown.enter="addStock"
        @keydown.esc="adding = false"
      />
      <button
        class="px-2 py-1 bg-amber-500/20 text-amber-400 text-[10px] rounded hover:bg-amber-500/30 transition-colors"
        @click="addStock"
      >确定</button>
      <button
        class="px-2 py-1 text-slate-500 text-[10px] hover:text-slate-300 transition-colors"
        @click="adding = false"
      >取消</button>
    </div>

    <div v-if="watchlist.length" class="space-y-1.5">
      <div
        v-for="code in watchlist"
        :key="code"
        class="group flex items-center justify-between px-2.5 py-1.5 bg-slate-900/50 border border-slate-800 rounded-lg hover:border-slate-700 transition-colors"
      >
        <span class="text-xs text-slate-300 font-mono">{{ code }}</span>
        <div class="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            class="text-[10px] text-amber-400 hover:text-amber-300 transition-colors font-medium"
            title="生成投研报告"
            @click="emit('generateReport', code)"
          >报告</button>
          <button
            v-if="!readonly"
            class="text-slate-600 hover:text-red-400 transition-colors"
            title="删除"
            @click="emit('remove', code)"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <div v-else class="text-center py-4 text-slate-600 text-xs">
      <p>暂无自选股</p>
      <p class="text-[10px] mt-0.5 text-slate-700">
        {{ readonly ? '冷启动时可添加' : '点击"+ 添加"录入股票代码' }}
      </p>
    </div>
  </div>
</template>
