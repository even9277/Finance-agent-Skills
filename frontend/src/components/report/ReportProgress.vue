<script setup lang="ts">
import { computed } from 'vue'
import type {
  ReportStage,
  ReportStageFrameState,
  ReportStageStatus,
  ReportTaskStatus,
} from '@/api'
import type { ReportTransportStatus } from '@/stores/reportProgressStore'

const props = defineProps<{
  progress: number
  status: ReportTaskStatus
  transportStatus: ReportTransportStatus
  stages: ReportStageFrameState[]
}>()

interface DisplayStep {
  stage: ReportStage
  label: string
  icon: string
}

const steps: readonly DisplayStep[] = [
  { stage: 'PREPARING', label: '准备', icon: '⚙' },
  { stage: 'FUNDAMENTAL_ANALYSIS', label: '基本面', icon: '📊' },
  { stage: 'TECHNICAL_ANALYSIS', label: '技术面', icon: '📈' },
  { stage: 'VALUATION_ANALYSIS', label: '估值', icon: '💰' },
  { stage: 'NEWS_ANALYSIS', label: '新闻', icon: '📰' },
  { stage: 'PERSONALIZATION', label: '个性化', icon: '👤' },
  { stage: 'SYNTHESIZING', label: '汇总生成', icon: '🤖' },
]

const stageByName = computed(() => new Map(
  props.stages.map((item) => [item.stage, item.status] as const),
))

const transportLabel = computed(() => {
  const labels: Record<ReportTransportStatus, string> = {
    IDLE: '',
    CONNECTING: '正在连接实时进度',
    SSE_ACTIVE: '实时更新中',
    FALLBACK_POLLING: '实时连接中断，已降级为轮询',
    POLLING_CONFIRMING: '轮询确认中',
    COMPLETED: '报告已完成',
    FAILED: '报告生成失败',
    OBSERVATION_FAILED: '进度跟踪已停止',
    STOPPED: '进度观察已停止',
  }
  return labels[props.transportStatus]
})

function stageStatus(stage: ReportStage): ReportStageStatus | 'IDLE' {
  return stageByName.value.get(stage) || 'IDLE'
}

function stageClass(stage: ReportStage): string {
  switch (stageStatus(stage)) {
    case 'SUCCEEDED': return 'bg-amber-500 border-amber-500 text-black'
    case 'RUNNING': return 'border-amber-400 bg-slate-900 animate-pulse'
    case 'FAILED': return 'border-red-500 bg-red-950 text-red-400'
    case 'SKIPPED': return 'border-slate-600 bg-slate-900 text-slate-500'
    default: return 'border-slate-700 bg-slate-900 text-slate-500'
  }
}

function stageLabelClass(stage: ReportStage): string {
  switch (stageStatus(stage)) {
    case 'SUCCEEDED': return 'text-amber-400'
    case 'RUNNING': return 'text-slate-200'
    case 'FAILED': return 'text-red-400'
    default: return 'text-slate-600'
  }
}
</script>

<template>
  <div class="w-full py-4 px-2">
    <div v-if="transportLabel" class="mb-3 text-center text-xs text-slate-400">
      {{ transportLabel }}
    </div>

    <div class="flex items-start justify-between">
      <template v-for="(step, index) in steps" :key="step.stage">
        <div class="flex min-w-0 flex-col items-center gap-1.5">
          <div
            :class="[
              'w-9 h-9 rounded-full flex items-center justify-center text-sm border-2 transition-all duration-300',
              stageClass(step.stage),
            ]"
          >
            <span v-if="stageStatus(step.stage) === 'SUCCEEDED'">✓</span>
            <span v-else-if="stageStatus(step.stage) === 'SKIPPED'">−</span>
            <span v-else-if="stageStatus(step.stage) === 'FAILED'">!</span>
            <span v-else>{{ step.icon }}</span>
          </div>
          <span :class="['text-[11px] whitespace-nowrap', stageLabelClass(step.stage)]">
            {{ step.label }}
          </span>
          <span
            v-if="stageStatus(step.stage) === 'SKIPPED'"
            class="text-[10px] whitespace-nowrap text-slate-600"
          >已跳过</span>
        </div>

        <div
          v-if="index < steps.length - 1"
          :class="[
            'flex-1 h-px mx-1 mt-4 transition-all duration-300',
            stageStatus(step.stage) === 'SUCCEEDED' ? 'bg-amber-500' : 'bg-slate-700',
          ]"
        />
      </template>
    </div>

    <div class="mt-4 h-1 bg-slate-800 rounded-full overflow-hidden">
      <div
        class="h-full bg-amber-500 rounded-full transition-all duration-300"
        :style="{ width: `${progress}%` }"
      />
    </div>
    <div class="flex justify-between mt-1 text-xs text-slate-500">
      <span>{{ status === 'failed' ? '生成失败' : status === 'completed' ? '已完成' : '分析中...' }}</span>
      <span>{{ progress }}%</span>
    </div>
  </div>
</template>
