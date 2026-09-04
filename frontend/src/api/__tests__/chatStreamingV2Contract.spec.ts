import { describe, expect, it } from 'vitest'
import {
  CHAT_STREAM_PROTOCOL_VERSION,
  parseWsFrame,
  type WsStreamV2Frame,
} from '@/api'

describe('WebSocket chat-stream-v2 protocol contract', () => {
  it('parses a typed content delta with the complete correlation envelope', () => {
    const expected: WsStreamV2Frame = {
      type: 'content_delta',
      protocol_version: CHAT_STREAM_PROTOCOL_VERSION,
      request_id: 'request-v2',
      session_id: 'session-v2',
      sequence: 2,
      chunk_index: 1,
      content: '第一段',
    }

    const frame = parseWsFrame(JSON.stringify(expected))

    expect(frame).toEqual(expected)
  })

  it('rejects legacy terminal and unknown JSON frames instead of keeping a dual protocol', () => {
    expect(parseWsFrame(JSON.stringify({ type: 'done', session_id: 'legacy' }))).toBeNull()
    expect(parseWsFrame(JSON.stringify({ type: 'provider_private_delta', token: 'x' })))
      .toBeNull()
    expect(parseWsFrame('legacy raw token')).toBeNull()
  })

  it('parses all D04 controlled interaction frames with the v2 envelope', () => {
    const common = {
      protocol_version: CHAT_STREAM_PROTOCOL_VERSION,
      request_id: 'request-d04',
      session_id: 'session-d04',
    }
    const frames = [
      {
        ...common,
        type: 'trace_summary',
        sequence: 2,
        stage: 'validate',
        status: 'SUCCEEDED',
        elapsed_ms: 1.5,
        summary: '执行计划已通过校验',
      },
      {
        ...common,
        type: 'plan_preview',
        sequence: 3,
        plan_id: 'plan-d04',
        revision: 1,
        validated: true,
        steps: [{
          step_id: 'market-step',
          title: '获取行情数据',
          purpose: '补充行情证据',
          required: true,
          status: 'PLANNED',
          depends_on: [],
          subject_summary: '贵州茅台（600519.SH）',
        }],
      },
      {
        ...common,
        type: 'step_status',
        sequence: 4,
        plan_id: 'plan-d04',
        revision: 1,
        step_id: 'market-step',
        status: 'RUNNING',
      },
      {
        ...common,
        type: 'tool_status',
        sequence: 5,
        plan_id: 'plan-d04',
        revision: 1,
        tool_call_id: 'call-d04',
        step_id: 'market-step',
        display_name: '行情数据工具',
        status: 'STARTED',
        attempt: 1,
        parameter_summary: ['标的：600519.SH'],
      },
      {
        ...common,
        type: 'verification_summary',
        sequence: 6,
        plan_id: 'plan-d04',
        revision: 1,
        sufficiency: 'PARTIAL',
        claim_level: 'DESCRIPTIVE',
        accepted_count: 1,
        rejected_count: 0,
        covered_dimensions: ['market_snapshot'],
        missing_dimensions: ['financial_indicator'],
        limitation: '部分关键证据缺失，结论仅作描述性参考。',
      },
    ]

    expect(frames.map((frame) => parseWsFrame(JSON.stringify(frame))))
      .toEqual(frames)
  })

  it('rejects malformed lifecycles and forbidden raw tool payloads', () => {
    const toolFrame = {
      protocol_version: CHAT_STREAM_PROTOCOL_VERSION,
      request_id: 'request-d04',
      session_id: 'session-d04',
      sequence: 5,
      type: 'tool_status',
      plan_id: 'plan-d04',
      revision: 1,
      tool_call_id: 'call-d04',
      step_id: 'market-step',
      display_name: '行情数据工具',
      status: 'STARTED',
      attempt: 1,
      parameter_summary: ['标的：600519.SH'],
    }

    expect(parseWsFrame(JSON.stringify({ ...toolFrame, status: 'RUNNING' }))).toBeNull()
    expect(parseWsFrame(JSON.stringify({
      ...toolFrame,
      arguments: { token: 'SECRET_TOKEN' },
    }))).toBeNull()
    expect(parseWsFrame(JSON.stringify({
      ...toolFrame,
      sequence: 0,
    }))).toBeNull()
  })
})
