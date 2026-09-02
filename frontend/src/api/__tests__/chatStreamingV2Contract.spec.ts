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
})
