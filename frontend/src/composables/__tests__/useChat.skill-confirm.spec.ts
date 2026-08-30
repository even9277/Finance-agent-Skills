import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { sendMessageMock, listSessionsMock } = vi.hoisted(() => ({
  sendMessageMock: vi.fn(),
  listSessionsMock: vi.fn(),
}))

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      sendMessage: sendMessageMock,
      listSessions: listSessionsMock,
    },
  }
})

vi.mock('@/composables/useMemory', () => ({
  useMemory: () => ({ loadProfile: vi.fn() }),
}))

import { useChat } from '@/composables/useChat'
import { useChatStore } from '@/stores/chatStore'
import { useUserStore } from '@/stores/userStore'

const confirmation = {
  reason: '需要确认分析任务',
  registry_snapshot_hash: 'a'.repeat(64),
  candidates: [
    {
      skill_name: 'fund-compare',
      confidence: 0.72,
      version: '1.1.0',
      reason: '匹配基金比较',
    },
  ],
}

describe('useChat Skill confirmation closure', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sendMessageMock.mockReset()
    listSessionsMock.mockReset()
    sendMessageMock.mockResolvedValue({
      data: {
        reply: '已按基金比较执行。',
        session_id: 'session-1',
        context_window: null,
      },
    })
    listSessionsMock.mockResolvedValue({ data: [] })
  })

  it('resubmits the original query on the same session without duplicating user text', async () => {
    const userStore = useUserStore()
    userStore.userId = 'user-1'
    const store = useChatStore()
    store.setCurrentSession('session-1')
    store.appendMessage({
      id: 1,
      session_id: 'session-1',
      role: 'user',
      content: '比较两只黄金基金',
      is_compressed: false,
      created_at: new Date().toISOString(),
    })
    store.setSkillConfirmation({
      originalMessage: '比较两只黄金基金',
      sessionId: 'session-1',
      confirmation,
    })
    const { confirmSkill } = useChat()

    await confirmSkill('fund-compare')

    expect(sendMessageMock).toHaveBeenCalledWith(
      'user-1',
      '比较两只黄金基金',
      'session-1',
      'fund-compare',
    )
    expect(store.messages.filter((item) => item.role === 'user')).toHaveLength(1)
    expect(store.pendingSkillConfirmation).toBeNull()
  })

  it('cancels locally without sending a request', () => {
    const store = useChatStore()
    store.setSkillConfirmation({
      originalMessage: '比较两只黄金基金',
      sessionId: 'session-1',
      confirmation,
    })
    const { cancelSkillConfirmation } = useChat()

    cancelSkillConfirmation()

    expect(store.pendingSkillConfirmation).toBeNull()
    expect(sendMessageMock).not.toHaveBeenCalled()
  })
})
