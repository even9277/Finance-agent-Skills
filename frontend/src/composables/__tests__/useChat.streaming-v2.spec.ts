import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { listSessionsMock } = vi.hoisted(() => ({
  listSessionsMock: vi.fn(),
}))

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      listSessions: listSessionsMock,
    },
  }
})

vi.mock('@/composables/useMemory', () => ({
  useMemory: () => ({ loadProfile: vi.fn().mockResolvedValue(undefined) }),
}))

import { CHAT_STREAM_PROTOCOL_VERSION } from '@/api'
import { useChat } from '@/composables/useChat'
import { useChatStore } from '@/stores/chatStore'
import { useUserStore } from '@/stores/userStore'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static CLOSING = 2

  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  sent: string[] = []
  closed = false
  readyState = 0

  constructor(public readonly url: string) {
    FakeWebSocket.instances.push(this)
  }

  send(payload: string) {
    this.sent.push(payload)
  }

  emitOpen() {
    this.readyState = 1
    this.onopen?.(new Event('open'))
  }

  emitMessage(frame: object) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(frame) }))
  }

  close(_code?: number, _reason?: string) {
    this.closed = true
    this.readyState = 3
    this.onclose?.(new CloseEvent('close'))
  }
}

function envelope(
  type: string,
  sequence: number,
  extra: Record<string, unknown> = {},
  requestId = 'request-v2',
) {
  return {
    type,
    protocol_version: CHAT_STREAM_PROTOCOL_VERSION,
    request_id: requestId,
    session_id: 'session-v2',
    sequence,
    ...extra,
  }
}

describe('useChat chat-stream-v2 consumption', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    FakeWebSocket.instances = []
    listSessionsMock.mockReset()
    listSessionsMock.mockResolvedValue({ data: [] })
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  it('appends ordered deltas to one message and finishes only on stream_end', async () => {
    const userStore = useUserStore()
    userStore.userId = 'user-v2'
    const store = useChatStore()
    const { sendMessageStream } = useChat()

    const completion = sendMessageStream('请生成足够长的回答')
    const websocket = FakeWebSocket.instances[0]
    websocket.emitOpen()

    const sentPayload = JSON.parse(websocket.sent[0]) as Record<string, unknown>
    expect(sentPayload.request_id).toEqual(expect.any(String))
    const requestId = String(sentPayload.request_id)

    websocket.emitMessage(envelope('stream_start', 1, {}, requestId))
    websocket.emitMessage(envelope('content_delta', 2, {
      chunk_index: 1,
      content: '第一段',
    }, requestId))
    websocket.emitMessage(envelope('content_delta', 3, {
      chunk_index: 2,
      content: '第二段',
    }, requestId))
    websocket.emitMessage(envelope('stream_end', 4, {
      status: 'SUCCEEDED',
      chunk_count: 2,
      content_sha256: 'a'.repeat(64),
    }, requestId))
    await completion

    expect(store.currentSessionId).toBe('session-v2')
    expect(store.messages.filter((item) => item.role === 'assistant')).toHaveLength(1)
    expect(store.messages.at(-1)?.content).toBe('第一段第二段')
    expect(store.isStreaming).toBe(false)
    expect(store.isSending).toBe(false)
  })

  it('rejects a sequence gap and ignores later content', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const userStore = useUserStore()
    userStore.userId = 'user-v2'
    const store = useChatStore()
    const { sendMessageStream } = useChat()

    const completion = sendMessageStream('验证乱序保护')
    const websocket = FakeWebSocket.instances[0]
    websocket.emitOpen()
    const requestId = String(JSON.parse(websocket.sent[0]).request_id)

    websocket.emitMessage(envelope('stream_start', 1, {}, requestId))
    websocket.emitMessage(envelope('content_delta', 3, {
      chunk_index: 1,
      content: '不应追加',
    }, requestId))
    websocket.emitMessage(envelope('content_delta', 2, {
      chunk_index: 1,
      content: '晚到内容',
    }, requestId))
    await completion

    expect(websocket.closed).toBe(true)
    expect(store.messages.at(-1)?.content).toContain('协议错误，请重试')
    expect(store.messages.at(-1)?.content).not.toContain('不应追加')
    expect(store.messages.at(-1)?.content).not.toContain('晚到内容')
    expect(store.isStreaming).toBe(false)
  })

  it('keeps received content and marks a stream_error as failed', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const userStore = useUserStore()
    userStore.userId = 'user-v2'
    const store = useChatStore()
    const { sendMessageStream } = useChat()

    const completion = sendMessageStream('验证流中失败')
    const websocket = FakeWebSocket.instances[0]
    websocket.emitOpen()
    const requestId = String(JSON.parse(websocket.sent[0]).request_id)

    websocket.emitMessage(envelope('stream_start', 1, {}, requestId))
    websocket.emitMessage(envelope('content_delta', 2, {
      chunk_index: 1,
      content: '已展示内容',
    }, requestId))
    websocket.emitMessage(envelope('stream_error', 3, {
      code: 'CHAT_STREAM_FAILED',
      message: '对话处理失败',
      chunk_count: 1,
    }, requestId))
    await completion

    expect(store.messages.at(-1)?.content).toContain('已展示内容')
    expect(store.messages.at(-1)?.content).toContain('错误：对话处理失败')
    expect(store.isStreaming).toBe(false)
    expect(store.isSending).toBe(false)
  })

  it('closes the active socket on page exit and keeps only a local partial', async () => {
    const userStore = useUserStore()
    userStore.userId = 'user-v2'
    const store = useChatStore()
    const { sendMessageStream } = useChat()

    const completion = sendMessageStream('验证页面退出取消')
    const websocket = FakeWebSocket.instances[0]
    websocket.emitOpen()
    const requestId = String(JSON.parse(websocket.sent[0]).request_id)
    websocket.emitMessage(envelope('stream_start', 1, {}, requestId))
    websocket.emitMessage(envelope('content_delta', 2, {
      chunk_index: 1,
      content: '退出前片段',
    }, requestId))

    window.dispatchEvent(new Event('beforeunload'))
    await completion

    expect(websocket.closed).toBe(true)
    expect(store.messages.at(-1)?.content).toContain('退出前片段')
    expect(store.messages.at(-1)?.content).toContain('连接已中断，请重试')
    expect(store.isStreaming).toBe(false)
    expect(store.isSending).toBe(false)
  })

  it('dispatches D04 control frames and closes the execution on stream_end', async () => {
    const userStore = useUserStore()
    userStore.userId = 'user-v2'
    const store = useChatStore()
    const { sendMessageStream } = useChat()

    const completion = sendMessageStream('验证受控执行事件')
    const websocket = FakeWebSocket.instances[0]
    websocket.emitOpen()
    const requestId = String(JSON.parse(websocket.sent[0]).request_id)

    websocket.emitMessage(envelope('stream_start', 1, {}, requestId))
    websocket.emitMessage(envelope('plan_preview', 2, {
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
    }, requestId))
    websocket.emitMessage(envelope('step_status', 3, {
      plan_id: 'plan-d04',
      revision: 1,
      step_id: 'market-step',
      status: 'RUNNING',
    }, requestId))
    websocket.emitMessage(envelope('tool_status', 4, {
      plan_id: 'plan-d04',
      revision: 1,
      tool_call_id: 'call-d04',
      step_id: 'market-step',
      display_name: '行情数据工具',
      status: 'SUCCEEDED',
      attempt: 1,
      elapsed_ms: 12.5,
      parameter_summary: ['标的：600519.SH'],
      result_summary: '已返回 1 条可校验证据',
    }, requestId))
    websocket.emitMessage(envelope('step_status', 5, {
      plan_id: 'plan-d04',
      revision: 1,
      step_id: 'market-step',
      status: 'SUCCEEDED',
      elapsed_ms: 13,
    }, requestId))
    websocket.emitMessage(envelope('verification_summary', 6, {
      plan_id: 'plan-d04',
      revision: 1,
      sufficiency: 'SUFFICIENT',
      claim_level: 'ANALYTICAL',
      accepted_count: 1,
      rejected_count: 0,
      covered_dimensions: ['market_snapshot'],
      missing_dimensions: [],
      limitation: '证据满足当前分析要求。',
    }, requestId))
    websocket.emitMessage(envelope('content_delta', 7, {
      chunk_index: 1,
      content: '最终回答',
    }, requestId))
    websocket.emitMessage(envelope('stream_end', 8, {
      status: 'SUCCEEDED',
      chunk_count: 1,
      content_sha256: 'a'.repeat(64),
    }, requestId))
    await completion

    expect(store.controlledExecution?.requestId).toBe(requestId)
    expect(store.controlledExecution?.status).toBe('SUCCEEDED')
    expect(store.controlledExecution?.steps[0].status).toBe('SUCCEEDED')
    expect(store.controlledExecution?.tools[0].status).toBe('SUCCEEDED')
    expect(store.controlledExecution?.verification?.sufficiency).toBe('SUFFICIENT')
    expect(store.messages.at(-1)?.content).toBe('最终回答')
  })

  it('stops the active request as a user cancellation without error text', async () => {
    const userStore = useUserStore()
    userStore.userId = 'user-v2'
    const store = useChatStore()
    const { sendMessageStream, stopStreaming } = useChat()

    const completion = sendMessageStream('验证用户主动停止')
    const websocket = FakeWebSocket.instances[0]
    websocket.emitOpen()
    const requestId = String(JSON.parse(websocket.sent[0]).request_id)
    websocket.emitMessage(envelope('stream_start', 1, {}, requestId))
    websocket.emitMessage(envelope('plan_preview', 2, {
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
    }, requestId))
    websocket.emitMessage(envelope('step_status', 3, {
      plan_id: 'plan-d04',
      revision: 1,
      step_id: 'market-step',
      status: 'RUNNING',
    }, requestId))
    websocket.emitMessage(envelope('tool_status', 4, {
      plan_id: 'plan-d04',
      revision: 1,
      tool_call_id: 'call-d04',
      step_id: 'market-step',
      display_name: '行情数据工具',
      status: 'STARTED',
      attempt: 1,
      parameter_summary: ['标的：600519.SH'],
    }, requestId))

    stopStreaming()
    await completion

    expect(websocket.closed).toBe(true)
    expect(store.controlledExecution?.status).toBe('CANCELLED')
    expect(store.controlledExecution?.steps[0].status).toBe('CANCELLED')
    expect(store.controlledExecution?.tools[0].status).toBe('CANCELLED')
    expect(store.messages.at(-1)?.content).not.toContain('连接已中断')
    expect(store.messages.at(-1)?.content).not.toContain('错误')
    expect(store.isStreaming).toBe(false)
    expect(store.isSending).toBe(false)
  })

  it('marks control progress unavailable and rejects before-start socket failure for HTTP fallback', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const userStore = useUserStore()
    userStore.userId = 'user-v2'
    const store = useChatStore()
    class ThrowingWebSocket {
      static CLOSING = 2

      constructor() {
        throw new Error('offline websocket unavailable')
      }
    }
    vi.stubGlobal('WebSocket', ThrowingWebSocket)
    const { sendMessageStream } = useChat()

    await expect(sendMessageStream('验证同步降级')).rejects.toThrow('WebSocket unavailable')

    expect(store.controlledExecution?.status).toBe('UNAVAILABLE')
    expect(store.controlledExecution?.steps).toEqual([])
    expect(store.controlledExecution?.tools).toEqual([])
    expect(store.isStreaming).toBe(false)
    expect(store.isSending).toBe(false)
  })
})
