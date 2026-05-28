<script setup lang="ts">
import type { StepStatusItem, VerificationSummary } from '@/api'

defineProps<{
  steps?: StepStatusItem[]
  verification?: VerificationSummary | null
}>()

function statusLabel(status?: string) {
  const map: Record<string, string> = {
    running: '执行中',
    succeeded: '已完成',
    failed: '失败',
    skipped: '已跳过',
  }
  return map[status || ''] || status || '待执行'
}

function statusClass(status?: string) {
  if (status === 'succeeded') return 'text-emerald-300'
  if (status === 'running') return 'text-sky-300'
  if (status === 'failed') return 'text-rose-300'
  return 'text-slate-400'
}
</script>

<template>
  <div v-if="steps?.length || verification" class="mt-2 w-full rounded-lg border border-slate-700/70 bg-slate-950/60 px-3 py-2 text-[11px] text-slate-300">
    <div v-if="steps?.length" class="flex flex-wrap gap-2">
      <span
        v-for="step in steps"
        :key="step.step_id"
        class="rounded-full bg-slate-800 px-2 py-0.5"
        :class="statusClass(step.status)"
      >
        {{ step.step_id }} {{ statusLabel(step.status) }}
      </span>
    </div>
    <div v-if="verification" class="mt-2 flex flex-wrap items-center gap-2 text-slate-400">
      <span>证据校验</span>
      <span class="rounded-full bg-slate-800 px-2 py-0.5 text-slate-200">{{ verification.status || 'unknown' }}</span>
      <span v-if="typeof verification.evidence_score === 'number'">score {{ verification.evidence_score }}</span>
      <span v-if="verification.allowed_claim_level">claim {{ verification.allowed_claim_level }}</span>
      <span v-if="verification.missing_dimensions?.length" class="text-amber-300">
        缺失 {{ verification.missing_dimensions.join('、') }}
      </span>
    </div>
  </div>
</template>
