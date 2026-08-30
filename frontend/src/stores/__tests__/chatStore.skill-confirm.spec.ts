import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useChatStore } from '@/stores/chatStore'

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

describe('chatStore Skill confirmation state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('stores only the original query, session and typed confirmation', () => {
    const store = useChatStore()
    store.setSkillConfirmation({
      originalMessage: '比较两只黄金基金',
      sessionId: 'session-1',
      confirmation,
    })

    expect(store.pendingSkillConfirmation?.sessionId).toBe('session-1')
    expect(store.pendingSkillConfirmation?.confirmation.candidates[0].skill_name)
      .toBe('fund-compare')
  })

  it('clears confirmation on cancel and reset', () => {
    const store = useChatStore()
    store.setSkillConfirmation({
      originalMessage: '比较两只黄金基金',
      sessionId: 'session-1',
      confirmation,
    })
    store.clearSkillConfirmation()
    expect(store.pendingSkillConfirmation).toBeNull()

    store.setSkillConfirmation({
      originalMessage: '比较两只黄金基金',
      sessionId: 'session-1',
      confirmation,
    })
    store.reset()
    expect(store.pendingSkillConfirmation).toBeNull()
  })
})
