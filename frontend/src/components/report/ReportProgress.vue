<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  progress: number  // 0-100
  status: string    // pending | running | completed | failed
}>()

const steps = [
  { label: '基本面', icon: '📊', threshold: 20 },
  { label: '技术面', icon: '📈', threshold: 40 },
  { label: '估值', icon: '💰', threshold: 55 },
  { label: '新闻', icon: '📰', threshold: 70 },
  { label: '汇总', icon: '🤖', threshold: 90 },
]

const stepState = computed(() => {
  return steps.map((s, i) => {
    if (props.status === 'completed') return 'done'
    if (props.status === 'failed') return i === 0 ? 'error' : 'idle'
    if (props.progress >= s.threshold) return 'done'
    if (props.progress >= (steps[i - 1]?.threshold ?? 0)) return 'active'
    return 'idle'
  })
})
</script>

<template>
  <div class="w-full py-4 px-2">
    <div class="flex items-center justify-between">
      <template v-for="(step, i) in steps" :key="i">
        <!-- 步骤圆圈 -->
        <div class="flex flex-col items-center gap-1.5">
          <div
            :class="[
              'w-10 h-10 rounded-full flex items-center justify-center text-base border-2 transition-all duration-500',
              stepState[i] === 'done' ? 'bg-amber-500 border-amber-500 text-black' :
              stepState[i] === 'active' ? 'border-amber-400 bg-slate-900 animate-pulse' :
              stepState[i] === 'error' ? 'border-red-500 bg-red-950 text-red-400' :
              'border-slate-700 bg-slate-900 text-slate-500',
            ]"
          >
            <span v-if="stepState[i] === 'done'">✓</span>
            <span v-else-if="stepState[i] === 'active'">{{ step.icon }}</span>
            <span v-else>{{ step.icon }}</span>
          </div>
          <span
            :class="[
              'text-xs whitespace-nowrap',
              stepState[i] === 'done' ? 'text-amber-400' :
              stepState[i] === 'active' ? 'text-slate-200' :
              'text-slate-600',
            ]"
          >{{ step.label }}</span>
        </div>

        <!-- 连接线 -->
        <div
          v-if="i < steps.length - 1"
          :class="[
            'flex-1 h-px mx-1 mb-5 transition-all duration-500',
            stepState[i] === 'done' ? 'bg-amber-500' : 'bg-slate-700',
          ]"
        />
      </template>
    </div>

    <!-- 进度条 -->
    <div class="mt-4 h-1 bg-slate-800 rounded-full overflow-hidden">
      <div
        class="h-full bg-amber-500 rounded-full transition-all duration-500"
        :style="{ width: `${progress}%` }"
      />
    </div>
    <div class="flex justify-between mt-1 text-xs text-slate-500">
      <span>{{ status === 'failed' ? '生成失败' : status === 'completed' ? '已完成' : '分析中...' }}</span>
      <span>{{ progress }}%</span>
    </div>
  </div>
</template>
