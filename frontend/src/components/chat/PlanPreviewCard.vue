<script setup lang="ts">
import type { PlanPreviewItem } from '@/api'

defineProps<{
  items?: PlanPreviewItem[]
}>()

function statusLabel(status?: string) {
  const map: Record<string, string> = {
    planned: '待执行',
    running: '执行中',
    succeeded: '已完成',
    failed: '失败',
    replanned: '已补证',
    skipped: '已跳过',
  }
  return map[status || 'planned'] || status || '待执行'
}

function statusClass(status?: string) {
  if (status === 'succeeded') return 'bg-emerald-500/15 text-emerald-300'
  if (status === 'running') return 'bg-sky-500/15 text-sky-300'
  if (status === 'failed') return 'bg-rose-500/15 text-rose-300'
  if (status === 'skipped') return 'bg-slate-700 text-slate-300'
  return 'bg-amber-500/15 text-amber-300'
}
</script>

<template>
  <div v-if="items?.length" class="mt-2 w-full rounded-lg border border-slate-700/70 bg-slate-900/80 px-3 py-2 text-[11px] text-slate-300">
    <div class="mb-2 flex items-center gap-2 text-slate-400">
      <span class="font-medium text-slate-300">执行计划</span>
      <span class="text-slate-500">{{ items.length }} 步</span>
    </div>
    <div class="space-y-1.5">
      <div
        v-for="item in items"
        :key="item.step_id"
        class="grid grid-cols-[auto,minmax(0,1fr),auto] items-center gap-2"
      >
        <span class="font-mono text-[10px] text-slate-500">{{ item.step_id }}</span>
        <div class="min-w-0">
          <div class="truncate text-slate-200">{{ item.title }}</div>
          <div class="truncate text-[10px] text-slate-500">
            {{ item.description || item.estimated_evidence || 'evidence' }}
            <span v-if="item.required" class="ml-1 text-amber-300">required</span>
          </div>
        </div>
        <span class="rounded-full px-2 py-0.5" :class="statusClass(item.status)">
          {{ statusLabel(item.status) }}
        </span>
      </div>
    </div>
  </div>
</template>
