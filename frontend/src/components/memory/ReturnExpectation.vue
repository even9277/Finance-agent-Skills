<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{ value?: number; riskProfile?: string; readonly?: boolean }>()
const emit = defineEmits<{ (e: 'update', val: number): void }>()

const PRESETS = [
  { label: '保本', range: '0-5%', value: 3 },
  { label: '跑赢通胀', range: '5-10%', value: 8 },
  { label: '积极增长', range: '10-20%', value: 15 },
  { label: '高收益', range: '20%+', value: 25 },
]

const localVal = ref(props.value ?? 10)

watch(() => props.value, (v) => { if (v !== undefined) localVal.value = v })

function handleInput(e: Event) {
  localVal.value = Number((e.target as HTMLInputElement).value)
  emit('update', localVal.value)
}

function setPreset(val: number) {
  if (props.readonly) return
  localVal.value = val
  emit('update', val)
}

// 风险/收益冲突检测
const hasConflict = computed(() => {
  if (!props.riskProfile) return false
  return props.riskProfile === 'conservative' && localVal.value >= 20
})
</script>

<template>
  <div>
    <p class="text-xs text-slate-500 mb-3">期望年化收益</p>

    <!-- 滑块 -->
    <div class="mb-3">
      <div class="flex justify-between text-xs text-slate-400 mb-1.5">
        <span>0%</span>
        <span class="text-amber-400 font-semibold">{{ localVal }}%</span>
        <span>50%</span>
      </div>
      <input
        type="range"
        :value="localVal"
        min="0"
        max="50"
        step="5"
        :disabled="readonly"
        class="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-amber-500 disabled:cursor-default"
        @input="handleInput"
      />
    </div>

    <!-- 快捷选项 -->
    <div class="grid grid-cols-2 gap-1.5 mb-3">
      <button
        v-for="p in PRESETS"
        :key="p.label"
        :disabled="readonly"
        :class="[
          'text-left px-2.5 py-1.5 rounded-md border text-[11px] transition-all',
          localVal === p.value
            ? 'border-amber-500 bg-amber-500/10 text-amber-300'
            : 'border-slate-700 text-slate-500 hover:border-slate-600 hover:text-slate-300',
          readonly ? 'cursor-default' : 'cursor-pointer',
        ]"
        @click="setPreset(p.value)"
      >
        <div class="font-medium">{{ p.label }}</div>
        <div class="opacity-70">{{ p.range }}</div>
      </button>
    </div>

    <!-- 冲突警告 -->
    <div
      v-if="hasConflict"
      class="flex items-start gap-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs"
    >
      <span class="shrink-0 mt-0.5">⚠️</span>
      <span>注意：收益目标与风险偏好"保守"可能存在冲突</span>
    </div>
  </div>
</template>
