<script setup lang="ts">
import type { SkillConfirmation } from '@/api'

withDefaults(defineProps<{
  confirmation: SkillConfirmation
  disabled?: boolean
}>(), {
  disabled: false,
})

const emit = defineEmits<{
  (event: 'confirm', skillName: string): void
  (event: 'cancel'): void
}>()

function confidenceLabel(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}
</script>

<template>
  <section
    class="mx-4 mb-3 rounded-xl border border-amber-700/50 bg-amber-950/30 p-3"
    aria-label="Skill 确认"
  >
    <div class="flex items-start justify-between gap-3">
      <div>
        <p class="text-sm font-medium text-amber-200">请选择分析方式</p>
        <p class="mt-1 text-xs text-amber-100/70">{{ confirmation.reason }}</p>
      </div>
      <button
        data-testid="cancel-skill-confirmation"
        type="button"
        class="shrink-0 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
        :disabled="disabled"
        @click="emit('cancel')"
      >
        取消
      </button>
    </div>

    <div class="mt-3 grid gap-2 sm:grid-cols-2">
      <button
        v-for="candidate in confirmation.candidates"
        :key="candidate.skill_name"
        :data-testid="`confirm-${candidate.skill_name}`"
        type="button"
        class="rounded-lg border border-slate-700 bg-slate-900/70 p-3 text-left transition-colors hover:border-amber-500/70 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="disabled"
        @click="emit('confirm', candidate.skill_name)"
      >
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs font-semibold text-slate-100">{{ candidate.skill_name }}</span>
          <span class="text-[10px] text-amber-400">{{ confidenceLabel(candidate.confidence) }}</span>
        </div>
        <p class="mt-1 text-[11px] leading-relaxed text-slate-400">{{ candidate.reason }}</p>
        <p class="mt-1 text-[10px] text-slate-600">版本 {{ candidate.version }}</p>
      </button>
    </div>
  </section>
</template>
