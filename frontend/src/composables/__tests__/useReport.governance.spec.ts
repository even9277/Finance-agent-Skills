import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { effectScope, nextTick } from 'vue'

const mocks = vi.hoisted(() => ({
  generate: vi.fn(),
  getStatus: vi.fn(),
  getReport: vi.fn(),
  listHistory: vi.fn(),
  deleteReport: vi.fn(),
}))

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    reportApi: { ...mocks },
  }
})

import { useReport } from '@/composables/useReport'
import { reportTaskStorageKey } from '@/composables/reportTaskRecovery'
import { ApiRequestError } from '@/api'
import { useAuthStore } from '@/stores/authStore'
import { useUserStore } from '@/stores/userStore'

async function flushMicrotasks(): Promise<void> {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
}

function pendingStream(): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({ start() {} })
}

async function seedActiveReference(reference: Record<string, string>): Promise<void> {
  const storageKey = await reportTaskStorageKey('user-d06')
  expect(storageKey).not.toBeNull()
  sessionStorage.setItem(storageKey as string, JSON.stringify(reference))
}

describe('D06 report task governance lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    useUserStore().userId = 'user-d06'
    mocks.generate.mockReset().mockResolvedValue({
      data: {
        task_id: 'task-d06',
        report_id: 'report-d06',
        status: 'pending',
        idempotency_status: 'CREATED',
        expires_at: '2026-09-05T00:10:00Z',
      },
    })
    mocks.getStatus.mockReset()
    mocks.getReport.mockReset().mockResolvedValue({
      data: {
        task_id: 'task-d06',
        report_id: 'report-d06',
        status: 'completed',
        progress: 100,
        content: '# fixture',
        created_at: '2026-09-05T00:00:00Z',
      },
    })
    mocks.listHistory.mockReset().mockResolvedValue({ data: [] })
    mocks.deleteReport.mockReset()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(pendingStream(), {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })))
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    localStorage.clear()
    sessionStorage.clear()
  })

  it('creates one explicit key and stores only a minimal active-task reference', async () => {
    const controller = useReport()

    await controller.generateReport('分析贵州茅台 600519')
    await flushMicrotasks()

    expect(mocks.generate).toHaveBeenCalledTimes(1)
    const [command, userId, idempotencyKey] = mocks.generate.mock.calls[0] as string[]
    expect(command).toBe('分析贵州茅台 600519')
    expect(userId).toBe('user-d06')
    expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/)
    const entries = Object.entries(sessionStorage)
    expect(entries).toHaveLength(1)
    const serialized = entries[0]?.[1] ?? ''
    const activity = JSON.parse(serialized) as Record<string, unknown>
    expect(activity.task_id).toBe('task-d06')
    expect(activity.report_id).toBe('report-d06')
    expect(activity.idempotency_key).toBe(idempotencyKey)
    expect(serialized).not.toContain('分析贵州茅台')
    expect(serialized).not.toContain('user-d06')
    controller.stopObservation()
  })

  it('restores the same task after refresh without calling generate', async () => {
    await seedActiveReference({
      task_id: 'task-d06',
      report_id: 'report-d06',
      idempotency_key: '11111111-1111-4111-8111-111111111111',
      request_fingerprint: 'a'.repeat(64),
    })
    mocks.getStatus.mockResolvedValue({
      data: { task_id: 'task-d06', report_id: 'report-d06', status: 'running', progress: 65 },
    })
    const controller = useReport() as ReturnType<typeof useReport> & {
      restoreActiveTask: () => Promise<boolean>
    }

    expect(typeof controller.restoreActiveTask).toBe('function')
    expect(await controller.restoreActiveTask()).toBe(true)
    await flushMicrotasks()

    expect(mocks.generate).not.toHaveBeenCalled()
    expect(controller.taskId.value).toBe('task-d06')
    expect(fetch).toHaveBeenCalledWith(
      '/api/report/events/task-d06',
      expect.objectContaining({ method: 'GET' }),
    )
    controller.stopObservation()
  })

  it('does not let a delayed refresh recovery replace a newly created task', async () => {
    await seedActiveReference({
      task_id: 'stale-task',
      report_id: 'stale-report',
      idempotency_key: '55555555-5555-4555-8555-555555555555',
      request_fingerprint: 'e'.repeat(64),
    })
    const originalDigest = globalThis.crypto.subtle.digest.bind(globalThis.crypto.subtle)
    let releaseLookup: (() => void) | undefined
    vi.spyOn(globalThis.crypto.subtle, 'digest').mockImplementationOnce(
      async (algorithm, data) => {
        await new Promise<void>((resolve) => {
          releaseLookup = resolve
        })
        return originalDigest(algorithm, data)
      },
    )
    mocks.generate.mockResolvedValueOnce({
      data: { task_id: 'fresh-task', report_id: 'fresh-report', status: 'pending' },
    })
    const controller = useReport()

    const restore = controller.restoreActiveTask()
    await flushMicrotasks()
    const generate = controller.generateReport('分析新的报告意图')
    await flushMicrotasks()
    releaseLookup?.()
    await Promise.all([restore, generate])
    await flushMicrotasks()

    expect(await restore).toBe(false)
    expect(mocks.getStatus).not.toHaveBeenCalled()
    expect(controller.taskId.value).toBe('fresh-task')
    controller.stopObservation()
  })

  it('clears the active reference on terminal completion', async () => {
    await seedActiveReference({
      task_id: 'stale-task',
      report_id: 'stale-report',
      idempotency_key: '22222222-2222-4222-8222-222222222222',
      request_fingerprint: 'b'.repeat(64),
    })
    const stream = [
      'event: stream_ready',
      'data: {"protocol_version":"report-progress-v1","task_id":"task-d06","report_id":"report-d06","sequence":7,"emitted_at":"2026-09-05T00:00:00Z","type":"stream_ready","status":"running","progress":65,"stages":[]}',
      '',
      'event: task_terminal',
      'data: {"protocol_version":"report-progress-v1","task_id":"task-d06","report_id":"report-d06","sequence":8,"emitted_at":"2026-09-05T00:01:00Z","type":"task_terminal","status":"completed","progress":100,"error_code":null,"message":null}',
      '',
    ].join('\n')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })))
    const controller = useReport()

    await controller.generateReport('分析贵州茅台 600519')
    await flushMicrotasks()

    expect(controller.status.value).toBe('completed')
    expect(sessionStorage.length).toBe(0)
    expect(mocks.generate).toHaveBeenCalledTimes(1)
  })

  it('retries one transient create failure with the identical key', async () => {
    mocks.generate.mockRejectedValueOnce(new ApiRequestError('temporary network failure'))
    const controller = useReport()

    await controller.generateReport('分析贵州茅台 600519')
    await flushMicrotasks()

    expect(mocks.generate).toHaveBeenCalledTimes(2)
    const firstKey = mocks.generate.mock.calls[0]?.[2] as string
    const secondKey = mocks.generate.mock.calls[1]?.[2] as string
    expect(firstKey).toBe(secondKey)
    expect(sessionStorage.length).toBe(1)
    controller.stopObservation()
  })

  it('does not retry a stable idempotency conflict', async () => {
    mocks.generate.mockRejectedValueOnce(new ApiRequestError(
      '同一幂等键不能绑定不同请求',
      409,
      'IDEMPOTENCY_KEY_CONFLICT',
    ))
    const controller = useReport()

    await controller.generateReport('分析贵州茅台 600519')

    expect(mocks.generate).toHaveBeenCalledTimes(1)
    expect(controller.errorMsg.value).toContain('不能绑定不同请求')
    expect(controller.isGenerating.value).toBe(false)
    expect(sessionStorage.length).toBe(0)
  })

  it('isolates recovery records by authenticated user digest', async () => {
    const otherStorageKey = await reportTaskStorageKey('other-user')
    expect(otherStorageKey).not.toBeNull()
    sessionStorage.setItem(otherStorageKey as string, JSON.stringify({
      task_id: 'other-task',
      report_id: 'other-report',
      idempotency_key: '33333333-3333-4333-8333-333333333333',
      request_fingerprint: 'c'.repeat(64),
    }))
    const controller = useReport()

    expect(await controller.restoreActiveTask()).toBe(false)

    expect(mocks.getStatus).not.toHaveBeenCalled()
    expect(controller.taskId.value).toBeNull()
    expect(sessionStorage.getItem(otherStorageKey as string)).not.toBeNull()
  })

  it('deletes only the current malformed recovery record', async () => {
    const storageKey = await reportTaskStorageKey('user-d06')
    expect(storageKey).not.toBeNull()
    sessionStorage.setItem(storageKey as string, JSON.stringify({
      task_id: 'task-d06',
      report_id: 'report-d06',
      idempotency_key: 'not-a-valid-key',
      request_fingerprint: 'd'.repeat(64),
    }))
    sessionStorage.setItem('unrelated-ui-state', 'keep-me')
    const controller = useReport()

    expect(await controller.restoreActiveTask()).toBe(false)

    expect(sessionStorage.getItem(storageKey as string)).toBeNull()
    expect(sessionStorage.getItem('unrelated-ui-state')).toBe('keep-me')
  })

  it('clears the active reference when the mounted report scope logs out', async () => {
    const authStore = useAuthStore()
    authStore.accessToken = 'fixture-token'
    const scope = effectScope()
    const controller = scope.run(() => useReport())
    expect(controller).toBeDefined()

    await controller?.generateReport('分析贵州茅台 600519')
    await flushMicrotasks()
    expect(sessionStorage.length).toBe(1)

    authStore.clearAuth()
    await nextTick()

    expect(sessionStorage.length).toBe(0)
    expect(controller?.isGenerating.value).toBe(false)
    scope.stop()
  })

  it('uses a fresh explicit key for a later deliberate generation', async () => {
    mocks.generate
      .mockResolvedValueOnce({
        data: { task_id: 'task-one', report_id: 'report-one', status: 'pending' },
      })
      .mockResolvedValueOnce({
        data: { task_id: 'task-two', report_id: 'report-two', status: 'pending' },
      })
    const controller = useReport()

    await controller.generateReport('分析贵州茅台 600519')
    await flushMicrotasks()
    controller.stopObservation()
    await controller.generateReport('再次分析贵州茅台 600519')
    await flushMicrotasks()

    const firstKey = mocks.generate.mock.calls[0]?.[2] as string
    const secondKey = mocks.generate.mock.calls[1]?.[2] as string
    expect(firstKey).not.toBe(secondKey)
    expect(controller.taskId.value).toBe('task-two')
    expect(sessionStorage.length).toBe(1)
    controller.stopObservation()
  })
})
