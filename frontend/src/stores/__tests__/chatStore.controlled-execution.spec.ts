import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { CHAT_STREAM_PROTOCOL_VERSION } from '@/api'
import type { ChatPlanPreviewFrame } from '@/api'
import { useChatStore } from '@/stores/chatStore'

const common = {
  protocol_version: CHAT_STREAM_PROTOCOL_VERSION,
  request_id: 'request-d04-a',
  session_id: 'session-d04-a',
}

function planFrame(revision = 1): ChatPlanPreviewFrame {
  return {
    ...common,
    type: 'plan_preview' as const,
    sequence: revision + 1,
    plan_id: `plan-d04-${revision}`,
    revision,
    validated: true,
    replan_reason: revision > 1 ? '补充缺失的财务证据' : undefined,
    steps: revision === 1
      ? [
          {
            step_id: 'market-step',
            title: '获取行情数据',
            purpose: '补充行情证据',
            required: true,
            status: 'PLANNED' as const,
            depends_on: [],
            subject_summary: '贵州茅台（600519.SH）',
          },
          {
            step_id: 'financial-step',
            title: '获取财务指标',
            purpose: '补充财务证据',
            required: true,
            status: 'PLANNED' as const,
            depends_on: [],
            subject_summary: '贵州茅台（600519.SH）',
          },
        ]
      : [{
          step_id: 'replacement-step',
          title: '补充财务指标',
          purpose: '修复证据缺口',
          required: true,
          status: 'PLANNED' as const,
          depends_on: [],
          subject_summary: '贵州茅台（600519.SH）',
        }],
  }
}

function stepFrame(
  stepId: string,
  status: 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'SKIPPED' | 'REPLANNED' | 'CANCELLED',
  revision = 1,
) {
  return {
    ...common,
    type: 'step_status' as const,
    sequence: 10 + revision,
    plan_id: `plan-d04-${revision}`,
    revision,
    step_id: stepId,
    status,
  }
}

function toolFrame(status: 'STARTED' | 'SUCCEEDED' | 'FAILED' | 'SKIPPED' | 'CANCELLED') {
  return {
    ...common,
    type: 'tool_status' as const,
    sequence: status === 'STARTED' ? 20 : 21,
    plan_id: 'plan-d04-1',
    revision: 1,
    tool_call_id: 'tool-call-d04',
    step_id: 'market-step',
    display_name: '行情数据工具',
    status,
    attempt: 1,
    parameter_summary: ['标的：600519.SH'],
  }
}

describe('chatStore controlled execution reducer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('updates parallel steps by stable id and ignores duplicate terminal regression', () => {
    const store = useChatStore()
    store.beginControlledExecution({ requestId: common.request_id, sessionId: common.session_id })
    store.applyControlledFrame(planFrame())
    store.applyControlledFrame(stepFrame('financial-step', 'RUNNING'))
    store.applyControlledFrame(stepFrame('market-step', 'RUNNING'))
    store.applyControlledFrame(stepFrame('market-step', 'SUCCEEDED'))
    store.applyControlledFrame(stepFrame('market-step', 'SUCCEEDED'))
    store.applyControlledFrame(stepFrame('market-step', 'RUNNING'))

    expect(store.controlledExecution?.steps.map((step) => [step.step_id, step.status]))
      .toEqual([
        ['market-step', 'SUCCEEDED'],
        ['financial-step', 'RUNNING'],
      ])
  })

  it('retains completed history and appends a validated replan revision', () => {
    const store = useChatStore()
    store.beginControlledExecution({ requestId: common.request_id, sessionId: common.session_id })
    store.applyControlledFrame(planFrame())
    store.applyControlledFrame(stepFrame('market-step', 'RUNNING'))
    store.applyControlledFrame(stepFrame('market-step', 'SUCCEEDED'))
    store.applyControlledFrame(stepFrame('financial-step', 'REPLANNED'))
    store.applyControlledFrame(planFrame(2))

    expect(store.controlledExecution?.activeRevision).toBe(2)
    expect(store.controlledExecution?.planHistory).toHaveLength(2)
    expect(store.controlledExecution?.steps.find((step) => step.step_id === 'market-step')?.status)
      .toBe('SUCCEEDED')
    expect(store.controlledExecution?.steps.find((step) => step.step_id === 'financial-step')?.status)
      .toBe('REPLANNED')
    expect(store.controlledExecution?.steps.find((step) => step.step_id === 'replacement-step')?.status)
      .toBe('PLANNED')
  })

  it('isolates a new request from stale frames of the previous request', () => {
    const store = useChatStore()
    store.beginControlledExecution({ requestId: common.request_id, sessionId: common.session_id })
    store.applyControlledFrame(planFrame())
    store.beginControlledExecution({ requestId: 'request-d04-b', sessionId: 'session-d04-b' })
    store.applyControlledFrame(stepFrame('market-step', 'SUCCEEDED'))

    expect(store.controlledExecution?.requestId).toBe('request-d04-b')
    expect(store.controlledExecution?.sessionId).toBe('session-d04-b')
    expect(store.controlledExecution?.steps).toEqual([])
  })

  it('closes running work on user cancellation without rewriting success', () => {
    const store = useChatStore()
    store.beginControlledExecution({ requestId: common.request_id, sessionId: common.session_id })
    store.applyControlledFrame(planFrame())
    store.applyControlledFrame(stepFrame('market-step', 'RUNNING'))
    store.applyControlledFrame(toolFrame('STARTED'))
    store.applyControlledFrame(stepFrame('financial-step', 'SUCCEEDED'))

    store.cancelControlledExecution()

    expect(store.controlledExecution?.status).toBe('CANCELLED')
    expect(store.controlledExecution?.steps.find((step) => step.step_id === 'market-step')?.status)
      .toBe('CANCELLED')
    expect(store.controlledExecution?.steps.find((step) => step.step_id === 'financial-step')?.status)
      .toBe('SUCCEEDED')
    expect(store.controlledExecution?.tools[0].status).toBe('CANCELLED')
  })
})
