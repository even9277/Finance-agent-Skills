import { describe, expect, it, vi } from 'vitest'
import { CHAT_STREAM_PROTOCOL_VERSION, chatApi, http, parseWsFrame } from '@/api'

describe('public chat Skill contract', () => {
  it('sends optional explicit_skill without changing old call arguments', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: {} })

    await chatApi.sendMessage('user-1', '比较两只基金', 'session-1', 'fund-compare')
    expect(post).toHaveBeenCalledWith('/chat/message', {
      user_id: 'user-1',
      message: '比较两只基金',
      session_id: 'session-1',
      explicit_skill: 'fund-compare',
    })

    await chatApi.sendMessage('user-1', '旧客户端请求')
    expect(post).toHaveBeenLastCalledWith('/chat/message', {
      user_id: 'user-1',
      message: '旧客户端请求',
      session_id: undefined,
      explicit_skill: undefined,
    })
  })

  it('parses the typed skill_confirm WebSocket frame', () => {
    const frame = parseWsFrame(JSON.stringify({
      type: 'skill_confirm',
      protocol_version: CHAT_STREAM_PROTOCOL_VERSION,
      request_id: 'request-skill-confirm',
      session_id: 'session-1',
      sequence: 3,
      confirmation: {
        reason: '需要确认',
        registry_snapshot_hash: 'a'.repeat(64),
        candidates: [
          {
            skill_name: 'fund-compare',
            confidence: 0.72,
            version: '1.1.0',
            reason: '匹配基金比较',
          },
        ],
      },
    }))

    expect(frame?.type).toBe('skill_confirm')
    if (frame?.type === 'skill_confirm') {
      expect(frame.confirmation.candidates[0].skill_name).toBe('fund-compare')
    }
  })
})
