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
})
