<script setup lang="ts">
/**
 * 自选股行情同步（Phase 1 预留占位，Phase 4 完整实现）
 */
defineProps<{ lastSyncAt?: string | null }>()
</script>

<template>
  <div class="flex items-center justify-between px-4 py-2.5 bg-slate-900/50 border border-slate-800 rounded-lg">
    <div>
      <span class="text-xs text-slate-400">行情同步</span>
      <span v-if="lastSyncAt" class="text-[10px] text-slate-600 ml-2">
        上次：{{ new Date(lastSyncAt).toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}
      </span>
    </div>
    <button
      class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-400 text-xs rounded-md transition-colors cursor-not-allowed opacity-60"
      disabled
      title="Phase 4 实现"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="23 4 23 10 17 10" />
        <polyline points="1 20 1 14 7 14" />
        <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
      </svg>
      同步行情
    </button>
  </div>
</template>
