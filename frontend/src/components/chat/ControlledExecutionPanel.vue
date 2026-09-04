<script setup lang="ts">
import { computed } from 'vue'
import type {
  ControlledExecutionState,
  ControlledExecutionStep,
  ControlledExecutionTool,
} from '@/stores/chatStore'

const props = defineProps<{
  execution: ControlledExecutionState | null
}>()

const hasVisibleExecution = computed(() => {
  const execution = props.execution
  if (!execution) return false
  return execution.status === 'UNAVAILABLE'
    || execution.traces.length > 0
    || execution.planHistory.length > 0
    || execution.steps.length > 0
    || execution.tools.length > 0
    || execution.verification !== null
})

const stepStatusLabels: Record<ControlledExecutionStep['status'], string> = {
  PLANNED: '待执行',
  RUNNING: '执行中',
  SUCCEEDED: '已完成',
  FAILED: '失败',
  SKIPPED: '已跳过',
  REPLANNED: '已被补证计划替代',
  CANCELLED: '已取消',
}

const toolStatusLabels: Record<ControlledExecutionTool['status'], string> = {
  STARTED: '调用中',
  SUCCEEDED: '调用完成',
  FAILED: '调用失败',
  SKIPPED: '未调用',
  CANCELLED: '已取消',
}

const sufficiencyLabels = {
  SUFFICIENT: '证据充分',
  PARTIAL: '证据部分充分',
  INSUFFICIENT: '证据不足',
} as const
</script>

<template>
  <section
    v-if="execution && hasVisibleExecution"
    class="mx-4 mb-3 max-h-[38vh] overflow-y-auto rounded-xl border border-slate-700/70 bg-slate-900/70 p-3"
    aria-label="受控执行状态"
  >
    <div class="flex items-center justify-between gap-3">
      <div>
        <p class="text-sm font-semibold text-slate-100">
          {{ execution.status === 'UNAVAILABLE' ? '执行进度不可用' : '已校验计划' }}
        </p>
        <p class="mt-0.5 text-[10px] text-slate-500">仅展示受控摘要，不包含原始参数与模型思考</p>
      </div>
      <span class="rounded-full bg-slate-800 px-2 py-1 text-[10px] text-amber-300">
        {{ execution.status }}
      </span>
    </div>

    <div v-if="execution.planHistory.length" class="mt-3 space-y-2">
      <div
        v-for="plan in execution.planHistory"
        :key="`${plan.plan_id}:${plan.revision}`"
        class="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2"
      >
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-slate-200">第 {{ plan.revision }} 版</span>
          <span class="text-[10px] text-emerald-400">已校验</span>
        </div>
        <p v-if="plan.replan_reason" class="mt-1 text-[11px] text-amber-300/80">
          {{ plan.replan_reason }}
        </p>
      </div>
    </div>

    <div v-if="execution.steps.length" class="mt-3 space-y-2">
      <article
        v-for="step in execution.steps"
        :key="`${step.plan_id}:${step.step_id}`"
        class="rounded-lg border border-slate-800 px-3 py-2"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-xs font-medium text-slate-100">{{ step.title }}</p>
            <p class="mt-0.5 text-[10px] text-slate-500">
              {{ step.subject_summary }} · {{ step.purpose }}
            </p>
          </div>
          <span class="shrink-0 text-[10px] text-amber-300">
            {{ stepStatusLabels[step.status] }}
          </span>
        </div>
        <p v-if="step.error_code" class="mt-1 text-[10px] text-red-300">
          {{ step.error_code }}
        </p>
      </article>
    </div>

    <div v-if="execution.tools.length" class="mt-3 border-t border-slate-800 pt-3">
      <p class="text-[10px] font-medium uppercase tracking-wide text-slate-500">工具调用</p>
      <div
        v-for="tool in execution.tools"
        :key="tool.tool_call_id"
        class="mt-2 rounded-lg bg-slate-950/60 px-3 py-2"
      >
        <div class="flex items-center justify-between gap-3">
          <span class="text-xs text-slate-200">{{ tool.display_name }}</span>
          <span class="text-[10px] text-slate-400">{{ toolStatusLabels[tool.status] }}</span>
        </div>
        <p v-if="tool.parameter_summary.length" class="mt-1 text-[10px] text-slate-500">
          {{ tool.parameter_summary.join(' · ') }}
        </p>
        <p v-if="tool.result_summary" class="mt-1 text-[10px] text-slate-300">
          {{ tool.result_summary }}
        </p>
      </div>
    </div>

    <div
      v-if="execution.verification"
      class="mt-3 rounded-lg border border-amber-800/50 bg-amber-950/20 px-3 py-2"
    >
      <div class="flex items-center justify-between gap-3">
        <span class="text-xs font-medium text-amber-200">
          {{ sufficiencyLabels[execution.verification.sufficiency] }}
        </span>
        <span class="text-[10px] text-slate-500">
          {{ execution.verification.claim_level }}
        </span>
      </div>
      <p v-if="execution.verification.missing_dimensions.length" class="mt-1 text-[10px] text-red-300">
        缺失：{{ execution.verification.missing_dimensions.join('、') }}
      </p>
      <p class="mt-1 text-[11px] leading-relaxed text-slate-300">
        {{ execution.verification.limitation }}
      </p>
    </div>
  </section>
</template>
