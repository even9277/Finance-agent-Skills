<script setup lang="ts">
import type { SkillConfirmPayload } from '@/api'

defineProps<{
  payload: SkillConfirmPayload
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'choose', key: string): void
}>()
</script>

<template>
  <div
    class="mx-4 mb-3 rounded-xl border border-amber-600/50 bg-amber-950/40 px-4 py-3 text-sm text-slate-200 shadow-lg"
    role="region"
    aria-label="路由确认"
  >
    <div class="flex items-start gap-2">
      <span class="text-amber-400 shrink-0" aria-hidden="true">⚠️</span>
      <div class="min-w-0 flex-1">
        <p class="text-xs font-medium text-amber-200/95">系统对本轮问题路由把握不足，请确认处理方式</p>
        <p v-if="payload.resolved_query" class="mt-1 text-[11px] text-slate-400 truncate" :title="payload.resolved_query">
          理解查询：{{ payload.resolved_query }}
        </p>
        <p v-if="payload.reasoning" class="mt-1 text-[11px] text-slate-500 leading-relaxed">
          {{ payload.reasoning }}
        </p>
        <p class="mt-0.5 text-[10px] text-slate-600">置信度 {{ (payload.confidence * 100).toFixed(0) }}%</p>
      </div>
    </div>
    <div class="mt-3 flex flex-wrap gap-2">
      <button
        v-for="opt in payload.options"
        :key="opt.key"
        type="button"
        :disabled="disabled"
        class="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50"
        :class="
          opt.recommended
            ? 'bg-sky-600 text-white hover:bg-sky-500'
            : 'bg-slate-700 text-slate-200 hover:bg-slate-600'
        "
        @click="emit('choose', opt.key)"
      >
        {{ opt.label }}
      </button>
    </div>
  </div>
</template>
