import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  REPORT_PROGRESS_PROTOCOL_VERSION,
  type ReportProgressFrame,
} from '@/api'
import { useReportProgressStore } from '@/stores/reportProgressStore'

const common = {
  protocol_version: REPORT_PROGRESS_PROTOCOL_VERSION,
  task_id: 'task-d05',
  report_id: 'report-d05',
  emitted_at: '2026-09-04T12:00:00Z',
}

function readyFrame(): ReportProgressFrame {
  return {
    ...common,
    sequence: 1,
    type: 'stream_ready',
    status: 'running',
    progress: 20,
    stages: [{ stage: 'PREPARING', status: 'SUCCEEDED' }],
  }
}

function stageFrame(
  sequence: number,
  stageStatus: 'RUNNING' | 'SUCCEEDED',
  progress: number,
): ReportProgressFrame {
  return {
    ...common,
    sequence,
    type: 'stage_update',
    stage: 'FUNDAMENTAL_ANALYSIS',
    stage_status: stageStatus,
    progress,
  }
}

describe('report progress task-scoped reducer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('isolates task/sequence, keeps progress monotonic and locks terminal stages', () => {
    const store = useReportProgressStore()
    store.begin('task-d05', 'report-d05')
    expect(store.applyFrame(readyFrame())).toBe(true)
    expect(store.applyFrame(stageFrame(2, 'RUNNING', 50))).toBe(true)
    expect(store.applyFrame(stageFrame(3, 'SUCCEEDED', 35))).toBe(true)
    expect(store.applyFrame(stageFrame(4, 'RUNNING', 65))).toBe(true)
    expect(store.applyFrame({ ...stageFrame(5, 'SUCCEEDED', 80), task_id: 'stale-task' }))
      .toBe(false)
    expect(store.applyFrame(stageFrame(3, 'SUCCEEDED', 80))).toBe(false)

    expect(store.progress).toBe(65)
    expect(store.stages.find((item) => item.stage === 'FUNDAMENTAL_ANALYSIS')?.status)
      .toBe('SUCCEEDED')
  })

  it('locks a task terminal against late SSE and polling responses', () => {
    const store = useReportProgressStore()
    store.begin('task-d05', 'report-d05')
    expect(store.applyPollingSnapshot({
      task_id: 'task-d05',
      status: 'completed',
      progress: 100,
      report_id: 'another-report',
    })).toBe(false)
    store.applyFrame(readyFrame())
    store.applyFrame({
      ...common,
      sequence: 2,
      type: 'task_terminal',
      status: 'completed',
      progress: 100,
      error_code: null,
      message: null,
    })

    expect(store.applyFrame(stageFrame(3, 'RUNNING', 20))).toBe(false)
    expect(store.applyPollingSnapshot({
      task_id: 'task-d05',
      status: 'running',
      progress: 35,
      report_id: 'report-d05',
    })).toBe(false)
    expect(store.status).toBe('completed')
    expect(store.progress).toBe(100)
    expect(store.terminal).toBe(true)
  })
})
