<script setup lang="ts">
import { ref } from 'vue'
import type { ReportListItem } from '@/api'

const props = defineProps<{
  history: ReportListItem[]
  currentId?: string
}>()
const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'delete', id: string): void
}>()

const searchQ = ref('')

const filtered = () =>
  props.history.filter((r) => {
    if (!searchQ.value) return true
    const q = searchQ.value.toLowerCase()
    return (
      r.company_name?.toLowerCase().includes(q) ||
      r.stock_code?.toLowerCase().includes(q)
    )
  })

function formatDate(d: string) {
  return new Date(d).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

const statusColor: Record<string, string> = {
  completed: 'text-green-400',
  running: 'text-amber-400',
  pending: 'text-slate-500',
  failed: 'text-red-400',
}
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="px-3 pt-3 pb-2">
      <input
        v-model="searchQ"
        type="text"
        placeholder="搜索报告..."
        class="w-full bg-slate-800 border border-slate-700 rounded-md px-3 py-1.5 text-xs text-slate-300 placeholder-slate-500 focus:outline-none focus:border-amber-500 transition-colors"
      />
    </div>

    <div class="flex-1 overflow-y-auto">
      <div
        v-for="r in filtered()"
        :key="r.report_id"
        :class="[
          'group flex items-start gap-2 px-3 py-2.5 cursor-pointer transition-colors border-b border-slate-800/50',
          currentId === r.report_id
            ? 'bg-amber-500/10 border-l-2 border-l-amber-500'
            : 'hover:bg-slate-800/50',
        ]"
        @click="emit('select', r.report_id)"
      >
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-1.5 mb-0.5">
            <span class="text-xs font-medium text-slate-200 truncate">
              {{ r.company_name || r.stock_code || '未知标的' }}
            </span>
            <span v-if="r.stock_code" class="text-[10px] text-slate-500 shrink-0">{{ r.stock_code }}</span>
          </div>
          <div class="flex items-center justify-between">
            <span :class="['text-[10px]', statusColor[r.status] || 'text-slate-500']">
              {{ r.status === 'completed' ? '已完成' : r.status === 'running' ? '生成中' : r.status === 'failed' ? '失败' : '等待中' }}
            </span>
            <span class="text-[10px] text-slate-600">{{ formatDate(r.created_at) }}</span>
          </div>
        </div>
        <!-- 删除按钮 -->
        <button
          class="opacity-0 group-hover:opacity-100 p-0.5 text-slate-500 hover:text-red-400 transition-all"
          @click.stop="emit('delete', r.report_id)"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
          </svg>
        </button>
      </div>

      <div v-if="!filtered().length" class="text-center py-8 text-slate-600 text-xs">
        暂无历史报告
      </div>
    </div>
  </div>
</template>
