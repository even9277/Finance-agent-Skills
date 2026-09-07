import { afterEach, describe, expect, it, vi } from 'vitest'

import { http, reportApi } from '@/api'

describe('D06 report create API contract', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('sends an explicit idempotency key without adding it to the JSON body', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({
      data: {
        task_id: 'task-d06',
        report_id: 'report-d06',
        status: 'pending',
        idempotency_status: 'CREATED',
        expires_at: '2026-09-07T00:10:00Z',
      },
    })

    await reportApi.generate(
      '分析贵州茅台 600519',
      'user-d06',
      '44444444-4444-4444-8444-444444444444',
    )

    expect(post).toHaveBeenCalledWith(
      '/report/generate',
      { command: '分析贵州茅台 600519', user_id: 'user-d06' },
      { headers: { 'Idempotency-Key': '44444444-4444-4444-8444-444444444444' } },
    )
  })
})
