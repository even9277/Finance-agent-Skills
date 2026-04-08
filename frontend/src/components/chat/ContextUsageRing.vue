<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  percent: number
  title?: string
  status?: string
}>()

const normalizedPercent = computed(() => Math.max(0, Math.min(100, props.percent || 0)))
const radius = 15
const circumference = 2 * Math.PI * radius
const dashOffset = computed(() => circumference * (1 - normalizedPercent.value / 100))

const strokeColor = computed(() => {
  if (normalizedPercent.value >= 85 || props.status === 'failed') return '#f87171'
  if (normalizedPercent.value >= 70 || props.status === 'queued' || props.status === 'running') return '#f59e0b'
  return '#38bdf8'
})
</script>

<template>
  <div
    class="relative h-9 w-9 shrink-0"
    :title="title || `Context ${normalizedPercent}%`"
  >
    <svg class="h-9 w-9 -rotate-90" viewBox="0 0 36 36">
      <circle
        cx="18"
        cy="18"
        :r="radius"
        fill="none"
        stroke="rgba(51,65,85,0.8)"
        stroke-width="3"
      />
      <circle
        cx="18"
        cy="18"
        :r="radius"
        fill="none"
        :stroke="strokeColor"
        stroke-width="3"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="dashOffset"
        class="transition-all duration-300"
      />
    </svg>
    <span class="absolute inset-0 flex items-center justify-center text-[9px] font-semibold text-slate-300">
      {{ normalizedPercent }}%
    </span>
  </div>
</template>
