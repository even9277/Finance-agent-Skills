import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useMemoryStore } from '@/stores/memoryStore'

describe('memoryStore M7 command state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('stores pending confirmation without exposing extra payload', () => {
    const store = useMemoryStore()
    store.setCommandResult({
      status: 'CONFIRMATION_REQUIRED',
      command_kind: 'FORGET',
      command_ref: 'mcmd_fixture',
      affected_count: 2,
      affected_record_ids: ['record-a', 'record-b'],
      consistency_status: 'CONSISTENT',
      pending_confirmation_id: 'pending-fixture',
      user_message: '将删除 2 条文本记忆，请回复确认。',
      preview_items: [],
    })

    expect(store.lastCommand?.status).toBe('CONFIRMATION_REQUIRED')
    expect(store.lastCommand?.pending_confirmation_id).toBe('pending-fixture')
    expect(store.lastCommand).not.toHaveProperty('raw_message')
  })

  it('clears command state when the user resets the memory view', () => {
    const store = useMemoryStore()
    store.setCommandResult({
      status: 'FAILED',
      affected_count: 0,
      affected_record_ids: [],
      consistency_status: 'DEGRADED',
      user_message: '失败',
      preview_items: [],
    })

    store.resetProfile()

    expect(store.lastCommand).toBeNull()
  })
})
