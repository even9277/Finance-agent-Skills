import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  ReportProgressFrame,
  ReportStageFrameState,
  ReportStageStatus,
  ReportStatusResponse,
  ReportTaskStatus,
} from '@/api'

export type ReportTransportStatus =
  | 'IDLE'
  | 'CONNECTING'
  | 'SSE_ACTIVE'
  | 'FALLBACK_POLLING'
  | 'POLLING_CONFIRMING'
  | 'COMPLETED'
  | 'FAILED'
  | 'OBSERVATION_FAILED'
  | 'STOPPED'

const STAGE_TERMINAL_STATUSES = new Set<ReportStageStatus>([
  'SUCCEEDED', 'FAILED', 'SKIPPED',
])

/**
 * 保存当前报告任务的单一、单调观察状态。
 *
 * SSE 与 polling 都只能通过此 reducer 写入；旧任务、旧 sequence、终态回退
 * 和进度回退会被拒绝，避免 transport 切换时产生两套状态。
 */
export const useReportProgressStore = defineStore('report-progress', () => {
  const taskId = ref<string | null>(null)
  const reportId = ref<string | null>(null)
  const status = ref<ReportTaskStatus>('pending')
  const progress = ref(0)
  const stages = ref<ReportStageFrameState[]>([])
  const lastSequence = ref(0)
  const terminal = ref(false)
  const errorCode = ref<string | null>(null)
  const errorMessage = ref<string | null>(null)
  const transportStatus = ref<ReportTransportStatus>('IDLE')

  function begin(nextTaskId: string, nextReportId: string): void {
    taskId.value = nextTaskId
    reportId.value = nextReportId
    status.value = 'pending'
    progress.value = 0
    stages.value = []
    lastSequence.value = 0
    terminal.value = false
    errorCode.value = null
    errorMessage.value = null
    transportStatus.value = 'CONNECTING'
  }

  function matches(task: string, report?: string): boolean {
    return taskId.value === task && (!report || reportId.value === report)
  }

  function setTransport(task: string, next: ReportTransportStatus): boolean {
    if (!matches(task)) return false
    transportStatus.value = next
    return true
  }

  function mergeStage(next: ReportStageFrameState): void {
    const current = stages.value.find((item) => item.stage === next.stage)
    if (!current) {
      stages.value.push({ ...next })
      return
    }
    if (STAGE_TERMINAL_STATUSES.has(current.status) && current.status !== next.status) return
    if (current.status === 'RUNNING' && next.status === 'RUNNING') return
    current.status = next.status
  }

  function applyFrame(frame: ReportProgressFrame): boolean {
    if (!matches(frame.task_id, frame.report_id)
      || terminal.value
      || frame.sequence <= lastSequence.value) return false

    lastSequence.value = frame.sequence
    progress.value = Math.max(progress.value, frame.progress)

    if (frame.type === 'stream_ready') {
      if (status.value === 'pending' || frame.status !== 'pending') status.value = frame.status
      for (const stage of frame.stages) mergeStage(stage)
      return true
    }

    if (frame.type === 'stage_update') {
      if (status.value === 'pending') status.value = 'running'
      mergeStage({ stage: frame.stage, status: frame.stage_status })
      return true
    }

    status.value = frame.status
    terminal.value = true
    errorCode.value = frame.error_code
    errorMessage.value = frame.message
    transportStatus.value = frame.status === 'completed' ? 'COMPLETED' : 'FAILED'
    return true
  }

  function applyPollingSnapshot(snapshot: ReportStatusResponse): boolean {
    if (!matches(snapshot.task_id, snapshot.report_id) || terminal.value) return false
    progress.value = Math.max(progress.value, snapshot.progress)
    if (snapshot.status === 'completed' || snapshot.status === 'failed') {
      status.value = snapshot.status
      terminal.value = true
      errorCode.value = snapshot.error_code || null
      errorMessage.value = snapshot.error_msg || null
      transportStatus.value = snapshot.status === 'completed' ? 'COMPLETED' : 'FAILED'
      return true
    }
    if (status.value === 'pending' || snapshot.status === 'running') status.value = snapshot.status
    return true
  }

  function selectCompleted(nextTaskId: string, nextReportId: string): void {
    begin(nextTaskId, nextReportId)
    status.value = 'completed'
    progress.value = 100
    terminal.value = true
    transportStatus.value = 'COMPLETED'
  }

  function markStopped(): void {
    if (!terminal.value && taskId.value) transportStatus.value = 'STOPPED'
  }

  function reset(): void {
    taskId.value = null
    reportId.value = null
    status.value = 'pending'
    progress.value = 0
    stages.value = []
    lastSequence.value = 0
    terminal.value = false
    errorCode.value = null
    errorMessage.value = null
    transportStatus.value = 'IDLE'
  }

  return {
    taskId,
    reportId,
    status,
    progress,
    stages,
    lastSequence,
    terminal,
    errorCode,
    errorMessage,
    transportStatus,
    begin,
    setTransport,
    applyFrame,
    applyPollingSnapshot,
    selectCompleted,
    markStopped,
    reset,
  }
})
