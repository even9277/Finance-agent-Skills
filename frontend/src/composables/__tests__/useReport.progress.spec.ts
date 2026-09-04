import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

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
    reportApi: {
      generate: mocks.generate,
      getStatus: mocks.getStatus,
      getReport: mocks.getReport,
      listHistory: mocks.listHistory,
      deleteReport: mocks.deleteReport,
    },
  }
})

import { ACCESS_TOKEN_KEY } from '@/api'
import { useReport } from '@/composables/useReport'
import { useUserStore } from '@/stores/userStore'

async function flushMicrotasks() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
}

function pendingStream(): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start() {
      // 首帧超时和 lifecycle 测试需要保持连接打开。
    },
  })
}

describe('useReport SSE observation and fallback lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    localStorage.clear()
    mocks.generate.mockReset().mockResolvedValue({
      data: { task_id: 'task-d05', report_id: 'report-d05', status: 'pending' },
    })
    mocks.getStatus.mockReset()
    mocks.getReport.mockReset().mockResolvedValue({
      data: {
        report_id: 'report-d05',
        task_id: 'task-d05',
        status: 'completed',
        progress: 100,
        content: '# 离线报告',
        created_at: '2026-09-04T12:00:00Z',
      },
    })
    mocks.listHistory.mockReset().mockResolvedValue({ data: [] })
    mocks.deleteReport.mockReset().mockResolvedValue({ data: { message: '已删除' } })
    useUserStore().userId = 'user-d05'
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('opens fetch SSE with the bearer token and completes without polling', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'fixture-token')
    const stream = [
      'event: stream_ready',
      'data: {"protocol_version":"report-progress-v1","task_id":"task-d05","report_id":"report-d05","sequence":1,"emitted_at":"2026-09-04T12:00:00Z","type":"stream_ready","status":"running","progress":20,"stages":[]}',
      '',
      'event: task_terminal',
      'data: {"protocol_version":"report-progress-v1","task_id":"task-d05","report_id":"report-d05","sequence":2,"emitted_at":"2026-09-04T12:01:00Z","type":"task_terminal","status":"completed","progress":100,"error_code":null,"message":null}',
      '',
    ].join('\n')
    const fetchMock = vi.fn().mockResolvedValue(new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = useReport()

    await controller.generateReport('分析茅台 600519')
    await flushMicrotasks()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/report/events/task-d05')
    expect(new Headers(options.headers).get('Authorization')).toBe('Bearer fixture-token')
    expect(options.signal).toBeInstanceOf(AbortSignal)
    expect(controller.transportStatus.value).toBe('COMPLETED')
    expect(mocks.getReport).toHaveBeenCalledWith('report-d05')
    expect(mocks.getStatus).not.toHaveBeenCalled()
    expect(mocks.generate).toHaveBeenCalledTimes(1)
  })

  it('falls back on first-frame timeout and keeps polling serial', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(
      pendingStream(),
      {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      },
    )))
    vi.stubGlobal('fetch', fetchMock)
    let resolveStatus: ((value: object) => void) | undefined
    mocks.getStatus.mockReturnValue(new Promise((resolve) => {
      resolveStatus = resolve
    }))
    const controller = useReport()

    await controller.generateReport('分析茅台 600519')
    await flushMicrotasks()
    await vi.advanceTimersByTimeAsync(5000)
    await flushMicrotasks()
    await vi.advanceTimersByTimeAsync(15000)

    expect(controller.transportStatus.value).toBe('FALLBACK_POLLING')
    expect(mocks.getStatus).toHaveBeenCalledTimes(1)
    expect(mocks.generate).toHaveBeenCalledTimes(1)

    resolveStatus?.({ data: { task_id: 'task-d05', status: 'running', progress: 35 } })
    await flushMicrotasks()
    await vi.advanceTimersByTimeAsync(1999)
    expect(mocks.getStatus).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(mocks.getStatus).toHaveBeenCalledTimes(2)
    controller.stopObservation()
  })

  it('starts fallback when the SSE response headers never arrive', async () => {
    const fetchMock = vi.fn().mockImplementation((_url: string, options: RequestInit) => (
      new Promise((_resolve, reject) => {
        options.signal?.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'))
        }, { once: true })
      })
    ))
    vi.stubGlobal('fetch', fetchMock)
    mocks.getStatus.mockResolvedValue({
      data: { task_id: 'task-d05', status: 'completed', progress: 100, report_id: 'report-d05' },
    })
    const controller = useReport()

    await controller.generateReport('分析茅台 600519')
    await flushMicrotasks()
    const signal = (fetchMock.mock.calls[0]?.[1] as RequestInit).signal as AbortSignal
    await vi.advanceTimersByTimeAsync(5000)
    await flushMicrotasks()

    expect(signal.aborted).toBe(true)
    expect(mocks.getStatus).toHaveBeenCalledTimes(1)
    expect(controller.transportStatus.value).toBe('COMPLETED')
    expect(mocks.getReport).toHaveBeenCalledWith('report-d05')
  })

  it('falls back on malformed data or a stream that ends before terminal', async () => {
    const malformed = 'data: {bad-json}\n\n'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(malformed, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })))
    mocks.getStatus.mockResolvedValue({
      data: { task_id: 'task-d05', status: 'failed', progress: 35, error_msg: '生成失败' },
    })
    const controller = useReport()

    await controller.generateReport('分析茅台 600519')
    await flushMicrotasks()

    expect(mocks.getStatus).toHaveBeenCalledTimes(1)
    expect(controller.status.value).toBe('failed')
    expect(controller.errorMsg.value).toBe('生成失败')
    expect(controller.transportStatus.value).toBe('FAILED')
  })

  it('falls back when an established SSE stream ends before terminal', async () => {
    const readyOnly = [
      'event: stream_ready',
      'data: {"protocol_version":"report-progress-v1","task_id":"task-d05","report_id":"report-d05","sequence":1,"emitted_at":"2026-09-04T12:00:00Z","type":"stream_ready","status":"running","progress":20,"stages":[]}',
      '',
    ].join('\n')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(readyOnly, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })))
    mocks.getStatus.mockResolvedValue({
      data: { task_id: 'task-d05', status: 'completed', progress: 100, report_id: 'report-d05' },
    })
    const controller = useReport()

    await controller.generateReport('分析茅台 600519')
    await flushMicrotasks()

    expect(mocks.getStatus).toHaveBeenCalledTimes(1)
    expect(controller.transportStatus.value).toBe('COMPLETED')
    expect(mocks.getReport).toHaveBeenCalledWith('report-d05')
  })

  it('uses bounded error backoff and stops after five polling errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('SSE unavailable')))
    mocks.getStatus.mockRejectedValue(new Error('temporary polling error'))
    const controller = useReport()

    await controller.generateReport('分析茅台 600519')
    await flushMicrotasks()
    expect(mocks.getStatus).toHaveBeenCalledTimes(1)

    for (const expectedDelay of [2000, 4000, 8000, 15000]) {
      await vi.advanceTimersByTimeAsync(expectedDelay)
      await flushMicrotasks()
    }

    expect(mocks.getStatus).toHaveBeenCalledTimes(5)
    expect(controller.transportStatus.value).toBe('OBSERVATION_FAILED')
    expect(controller.status.value).toBe('pending')
    expect(controller.errorMsg.value).toContain('进度查询暂时不可用')
    expect(controller.isGenerating.value).toBe(false)
  })

  it('stops a healthy polling fallback at the total observation budget', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('SSE unavailable')))
    mocks.getStatus.mockResolvedValue({
      data: { task_id: 'task-d05', status: 'running', progress: 35 },
    })
    const controller = useReport()

    await controller.generateReport('分析茅台 600519')
    await flushMicrotasks()
    await vi.advanceTimersByTimeAsync(15 * 60 * 1000)
    await flushMicrotasks()

    expect(mocks.getStatus.mock.calls.length).toBeGreaterThan(1)
    expect(mocks.getStatus.mock.calls.length).toBeLessThanOrEqual(450)
    expect(controller.transportStatus.value).toBe('OBSERVATION_FAILED')
    expect(controller.isGenerating.value).toBe(false)
  })

  it('aborts the active stream on history switch and component-scope disposal', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(
      pendingStream(),
      {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      },
    )))
    vi.stubGlobal('fetch', fetchMock)
    const scope = effectScope()
    const controller = scope.run(() => useReport())
    expect(controller).toBeDefined()

    await controller?.generateReport('分析茅台 600519')
    await flushMicrotasks()
    const firstSignal = (fetchMock.mock.calls[0]?.[1] as RequestInit).signal as AbortSignal
    await controller?.loadReport('historical-report')
    expect(firstSignal.aborted).toBe(true)
    expect(controller?.transportStatus.value).toBe('COMPLETED')

    mocks.generate.mockResolvedValueOnce({
      data: { task_id: 'task-next', report_id: 'report-next', status: 'pending' },
    })
    await controller?.generateReport('分析宁德时代 300750')
    await flushMicrotasks()
    const secondSignal = (fetchMock.mock.calls[1]?.[1] as RequestInit).signal as AbortSignal
    scope.stop()
    expect(secondSignal.aborted).toBe(true)
  })

  it('ignores a delayed create response after observation was stopped', async () => {
    let resolveGenerate: ((value: object) => void) | undefined
    mocks.generate.mockReturnValueOnce(new Promise((resolve) => {
      resolveGenerate = resolve
    }))
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const controller = useReport()

    const pendingGenerate = controller.generateReport('分析茅台 600519')
    await flushMicrotasks()
    controller.stopObservation()
    resolveGenerate?.({
      data: { task_id: 'stale-task', report_id: 'stale-report', status: 'pending' },
    })
    await pendingGenerate
    await flushMicrotasks()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(controller.taskId.value).toBeNull()
    expect(controller.reportId.value).toBeNull()
    expect(controller.isGenerating.value).toBe(false)
  })
})
