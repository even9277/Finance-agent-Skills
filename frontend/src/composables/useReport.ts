import { computed, getCurrentScope, onScopeDispose, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { saveAs } from 'file-saver'
import {
  ACCESS_TOKEN_KEY,
  ApiRequestError,
  createReportSseParser,
  reportApi,
  type ReportDetail,
  type ReportListItem,
  type ReportProgressFrame,
} from '@/api'
import {
  clearActiveReportTask,
  createReportIdempotencyKey,
  loadActiveReportTask,
  reportRequestFingerprint,
  saveActiveReportTask,
} from '@/composables/reportTaskRecovery'
import { useAuthStore } from '@/stores/authStore'
import { useReportProgressStore } from '@/stores/reportProgressStore'
import { useUserStore } from '@/stores/userStore'

const FIRST_FRAME_TIMEOUT_MS = 5_000
const POLL_INTERVAL_MS = 2_000
const POLL_ERROR_BACKOFF_MS = [2_000, 4_000, 8_000, 15_000] as const
const MAX_CONSECUTIVE_POLL_ERRORS = 5
const OBSERVATION_BUDGET_MS = 15 * 60 * 1_000
const OBSERVATION_FAILED_MESSAGE = '进度查询暂时不可用，请稍后在历史报告中查看结果'
const MAX_CREATE_ATTEMPTS = 2

/** 管理报告创建后的唯一 SSE 观察器及有界 polling 降级链。 */
export function useReport() {
  const userStore = useUserStore()
  const authStore = useAuthStore()
  const progressStore = useReportProgressStore()
  const {
    taskId,
    reportId,
    status,
    progress,
    stages,
    transportStatus,
  } = storeToRefs(progressStore)

  const report = ref<ReportDetail | null>(null)
  const errorMsg = ref<string | null>(null)
  const isGenerating = ref(false)
  const history = ref<ReportListItem[]>([])
  const previewOpen = ref(false)

  let observationEpoch = 0
  let activeController: AbortController | null = null
  let activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null
  let firstFrameTimer: ReturnType<typeof setTimeout> | null = null
  let delayTimer: ReturnType<typeof setTimeout> | null = null
  let unloadRegistered = false
  let activeStorageKey: string | null = null

  const isCompleted = computed(() => status.value === 'completed')
  const isFailed = computed(() => status.value === 'failed')

  function isCurrent(epoch: number, expectedTaskId: string): boolean {
    return observationEpoch === epoch && taskId.value === expectedTaskId
  }

  function clearFirstFrameTimer(): void {
    if (firstFrameTimer !== null) {
      clearTimeout(firstFrameTimer)
      firstFrameTimer = null
    }
  }

  function clearDelayTimer(): void {
    if (delayTimer !== null) {
      clearTimeout(delayTimer)
      delayTimer = null
    }
  }

  function unregisterBeforeUnload(): void {
    if (!unloadRegistered) return
    window.removeEventListener('beforeunload', handleBeforeUnload)
    unloadRegistered = false
  }

  function registerBeforeUnload(): void {
    if (unloadRegistered) return
    window.addEventListener('beforeunload', handleBeforeUnload)
    unloadRegistered = true
  }

  function cancelReader(): void {
    const reader = activeReader
    activeReader = null
    if (reader) void reader.cancel().catch(() => undefined)
  }

  function releaseTransport(): void {
    clearFirstFrameTimer()
    clearDelayTimer()
    cancelReader()
    activeController?.abort()
    activeController = null
    unregisterBeforeUnload()
  }

  /** 终止当前 SSE、轮询请求和等待定时器，所有迟到结果由 epoch 隔离。 */
  function stopObservation(): void {
    observationEpoch += 1
    releaseTransport()
    progressStore.markStopped()
    isGenerating.value = false
  }

  function handleBeforeUnload(): void {
    stopObservation()
  }

  function newController(): AbortController {
    activeController?.abort()
    const controller = new AbortController()
    activeController = controller
    return controller
  }

  function clearActiveReference(): void {
    clearActiveReportTask(activeStorageKey)
    activeStorageKey = null
  }

  function isRetryableCreateError(error: unknown): boolean {
    if (!(error instanceof ApiRequestError) || error.status === undefined) return true
    return error.status === 408
      || error.status === 425
      || error.status === 429
      || error.status >= 500
  }

  async function createWithOneRetry(
    command: string,
    userId: string,
    idempotencyKey: string,
  ) {
    let lastError: unknown
    for (let attempt = 1; attempt <= MAX_CREATE_ATTEMPTS; attempt += 1) {
      try {
        return await reportApi.generate(command, userId, idempotencyKey)
      } catch (error: unknown) {
        lastError = error
        if (attempt === MAX_CREATE_ATTEMPTS || !isRetryableCreateError(error)) throw error
      }
    }
    throw lastError
  }

  async function persistActiveReference(
    userId: string,
    command: string,
    idempotencyKey: string,
    nextTaskId: string,
    nextReportId: string,
  ): Promise<void> {
    const requestFingerprint = await reportRequestFingerprint(command)
    if (!requestFingerprint) return
    activeStorageKey = await saveActiveReportTask(userId, {
      task_id: nextTaskId,
      report_id: nextReportId,
      idempotency_key: idempotencyKey,
      request_fingerprint: requestFingerprint,
    })
  }

  function waitFor(ms: number, signal: AbortSignal): Promise<boolean> {
    return new Promise((resolve) => {
      if (signal.aborted) {
        resolve(false)
        return
      }
      const onAbort = () => {
        clearDelayTimer()
        resolve(false)
      }
      delayTimer = setTimeout(() => {
        delayTimer = null
        signal.removeEventListener('abort', onAbort)
        resolve(true)
      }, ms)
      signal.addEventListener('abort', onAbort, { once: true })
    })
  }

  async function fetchReport(id: string): Promise<void> {
    const { data } = await reportApi.getReport(id)
    report.value = data
  }

  async function finishTerminal(epoch: number, frame: ReportProgressFrame): Promise<void> {
    if (frame.type !== 'task_terminal' || !isCurrent(epoch, frame.task_id)) return
    releaseTransport()
    clearActiveReference()
    errorMsg.value = frame.message
    if (frame.status === 'completed') {
      try {
        await fetchReport(frame.report_id)
      } catch {
        errorMsg.value = '报告已完成，但读取报告内容失败，请从历史报告重试'
      }
    }
    if (isCurrent(epoch, frame.task_id)) isGenerating.value = false
  }

  async function finishPollingTerminal(
    epoch: number,
    expectedTaskId: string,
    expectedReportId: string,
  ): Promise<void> {
    if (!isCurrent(epoch, expectedTaskId)) return
    releaseTransport()
    clearActiveReference()
    errorMsg.value = progressStore.errorMessage
    if (status.value === 'completed') {
      try {
        await fetchReport(expectedReportId)
      } catch {
        errorMsg.value = '报告已完成，但读取报告内容失败，请从历史报告重试'
      }
    }
    if (isCurrent(epoch, expectedTaskId)) isGenerating.value = false
  }

  async function observeSse(
    epoch: number,
    expectedTaskId: string,
    expectedReportId: string,
  ): Promise<boolean> {
    const controller = newController()
    let firstFrameSeen = false
    let firstFrameTimedOut = false
    let protocolInvalid = false
    let terminalFrame: ReportProgressFrame | null = null

    try {
      // 超时预算覆盖连接、响应头和首个业务帧，避免 fetch 本身悬挂时无法降级。
      firstFrameTimer = setTimeout(() => {
        firstFrameTimedOut = true
        controller.abort()
        cancelReader()
      }, FIRST_FRAME_TIMEOUT_MS)
      const token = localStorage.getItem(ACCESS_TOKEN_KEY)
      const headers = new Headers({ Accept: 'text/event-stream' })
      if (token) headers.set('Authorization', `Bearer ${token}`)
      const response = await fetch(`/api/report/events/${encodeURIComponent(expectedTaskId)}`, {
        method: 'GET',
        headers,
        cache: 'no-store',
        signal: controller.signal,
      })
      const contentType = response.headers.get('Content-Type') || ''
      if (!response.ok || !contentType.toLowerCase().startsWith('text/event-stream') || !response.body) {
        throw new Error('REPORT_SSE_UNAVAILABLE')
      }
      if (!isCurrent(epoch, expectedTaskId) || controller.signal.aborted) return false

      const reader = response.body.getReader()
      activeReader = reader

      const parser = createReportSseParser(
        (frame) => {
          if (!isCurrent(epoch, expectedTaskId)
            || frame.task_id !== expectedTaskId
            || frame.report_id !== expectedReportId) return
          if (!firstFrameSeen) {
            if (frame.type !== 'stream_ready') {
              protocolInvalid = true
              controller.abort()
              void reader.cancel().catch(() => undefined)
              return
            }
            firstFrameSeen = true
            clearFirstFrameTimer()
            progressStore.setTransport(expectedTaskId, 'SSE_ACTIVE')
          }
          if (protocolInvalid || !progressStore.applyFrame(frame)) return
          if (frame.type === 'task_terminal') terminalFrame = frame
        },
        () => {
          protocolInvalid = true
          controller.abort()
          void reader.cancel().catch(() => undefined)
        },
      )
      const decoder = new TextDecoder()

      while (isCurrent(epoch, expectedTaskId) && !terminalFrame) {
        const { done, value } = await reader.read()
        if (done) break
        parser.push(decoder.decode(value, { stream: true }))
        if (protocolInvalid) break
      }
      parser.push(decoder.decode())
      parser.finish()

      if (terminalFrame) {
        await finishTerminal(epoch, terminalFrame)
        return true
      }
      if (!isCurrent(epoch, expectedTaskId)) return false
      if (firstFrameTimedOut || protocolInvalid || !firstFrameSeen) {
        throw new Error('REPORT_SSE_PROTOCOL_FAILED')
      }
      throw new Error('REPORT_SSE_ENDED_EARLY')
    } catch {
      if (!isCurrent(epoch, expectedTaskId)) return false
      return false
    } finally {
      clearFirstFrameTimer()
      activeReader = null
      if (activeController === controller) activeController = null
    }
  }

  function failObservation(epoch: number, expectedTaskId: string): void {
    if (!isCurrent(epoch, expectedTaskId)) return
    releaseTransport()
    progressStore.setTransport(expectedTaskId, 'OBSERVATION_FAILED')
    errorMsg.value = OBSERVATION_FAILED_MESSAGE
    isGenerating.value = false
  }

  async function observeByPolling(
    epoch: number,
    expectedTaskId: string,
    expectedReportId: string,
    startedAt: number,
  ): Promise<void> {
    const controller = newController()
    let consecutiveErrors = 0
    progressStore.setTransport(expectedTaskId, 'FALLBACK_POLLING')

    while (isCurrent(epoch, expectedTaskId) && !controller.signal.aborted) {
      if (Date.now() - startedAt >= OBSERVATION_BUDGET_MS) {
        failObservation(epoch, expectedTaskId)
        return
      }
      try {
        const { data } = await reportApi.getStatus(expectedTaskId, controller.signal)
        if (!isCurrent(epoch, expectedTaskId) || controller.signal.aborted) return
        consecutiveErrors = 0
        const applied = progressStore.applyPollingSnapshot(data)
        if (!applied) {
          if (!await waitFor(POLL_INTERVAL_MS, controller.signal)) return
          continue
        }
        if (data.status === 'completed' || data.status === 'failed') {
          await finishPollingTerminal(epoch, expectedTaskId, data.report_id || expectedReportId)
          return
        }
        progressStore.setTransport(expectedTaskId, 'POLLING_CONFIRMING')
        if (!await waitFor(POLL_INTERVAL_MS, controller.signal)) return
      } catch {
        if (!isCurrent(epoch, expectedTaskId) || controller.signal.aborted) return
        consecutiveErrors += 1
        progressStore.setTransport(expectedTaskId, 'FALLBACK_POLLING')
        if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
          failObservation(epoch, expectedTaskId)
          return
        }
        const backoff = POLL_ERROR_BACKOFF_MS[consecutiveErrors - 1]
          ?? POLL_ERROR_BACKOFF_MS[POLL_ERROR_BACKOFF_MS.length - 1]
        if (!await waitFor(backoff, controller.signal)) return
      }
    }
  }

  async function observeTask(
    epoch: number,
    expectedTaskId: string,
    expectedReportId: string,
  ): Promise<void> {
    const startedAt = Date.now()
    const terminalReached = await observeSse(epoch, expectedTaskId, expectedReportId)
    if (terminalReached || !isCurrent(epoch, expectedTaskId)) return

    // SSE controller 已结束后才创建 polling controller，保证同一时刻只有一个 transport。
    cancelReader()
    activeController?.abort()
    activeController = null
    await observeByPolling(epoch, expectedTaskId, expectedReportId, startedAt)
  }

  async function generateReport(command: string): Promise<void> {
    if (isGenerating.value) return
    stopObservation()
    clearActiveReference()
    report.value = null
    errorMsg.value = null
    progressStore.reset()
    isGenerating.value = true
    const requestEpoch = observationEpoch
    const requestUserId = userStore.userId

    try {
      const idempotencyKey = createReportIdempotencyKey()
      const { data } = await createWithOneRetry(command, requestUserId, idempotencyKey)
      // 用户退出、切换历史报告或启动了更新任务后，丢弃迟到的创建响应。
      if (observationEpoch !== requestEpoch) return
      progressStore.begin(data.task_id, data.report_id)
      await persistActiveReference(
        requestUserId,
        command,
        idempotencyKey,
        data.task_id,
        data.report_id,
      )
      if (observationEpoch !== requestEpoch) {
        clearActiveReference()
        return
      }
      registerBeforeUnload()
      void observeTask(requestEpoch, data.task_id, data.report_id)
    } catch (error: unknown) {
      if (observationEpoch !== requestEpoch) return
      errorMsg.value = error instanceof Error ? error.message : '触发失败'
      isGenerating.value = false
    }
  }

  /** 从当前用户的最小标签页记录恢复同一任务，恢复过程绝不重新 POST。 */
  async function restoreActiveTask(): Promise<boolean> {
    if (isGenerating.value || !userStore.userId) return false
    const ownerUserId = userStore.userId
    const lookupEpoch = observationEpoch
    const stored = await loadActiveReportTask(ownerUserId)
    if (!stored) return false
    // Web Crypto/Storage 读取期间可能已经启动新任务；旧恢复不得接管新 epoch。
    if (isGenerating.value
      || observationEpoch !== lookupEpoch
      || userStore.userId !== ownerUserId) return false

    stopObservation()
    report.value = null
    errorMsg.value = null
    progressStore.reset()
    activeStorageKey = stored.storageKey
    isGenerating.value = true
    const restoreEpoch = observationEpoch
    const { reference } = stored

    try {
      // 状态接口先完成认证与所有权校验，浏览器记录本身不授予任务访问权。
      const { data } = await reportApi.getStatus(reference.task_id)
      if (observationEpoch !== restoreEpoch) return false
      if (data.task_id !== reference.task_id
        || (data.report_id && data.report_id !== reference.report_id)) {
        clearActiveReference()
        progressStore.reset()
        isGenerating.value = false
        return false
      }

      progressStore.begin(reference.task_id, reference.report_id)
      progressStore.applyPollingSnapshot(data)
      if (data.status === 'completed' || data.status === 'failed') {
        await finishPollingTerminal(
          restoreEpoch,
          reference.task_id,
          data.report_id || reference.report_id,
        )
        return true
      }

      registerBeforeUnload()
      void observeTask(restoreEpoch, reference.task_id, reference.report_id)
      return true
    } catch (error: unknown) {
      if (error instanceof ApiRequestError
        && (error.status === 401 || error.status === 404)) clearActiveReference()
      progressStore.reset()
      isGenerating.value = false
      errorMsg.value = error instanceof Error ? error.message : '恢复报告任务失败'
      return false
    }
  }

  async function loadHistory(q?: string): Promise<void> {
    const { data } = await reportApi.listHistory(userStore.userId, q)
    history.value = data
  }

  async function loadReport(id: string): Promise<void> {
    stopObservation()
    clearActiveReference()
    errorMsg.value = null
    await fetchReport(id)
    if (report.value) progressStore.selectCompleted(report.value.task_id, id)
    isGenerating.value = false
  }

  function downloadMarkdown(): void {
    if (!report.value?.content) return
    const company = report.value.company_name || report.value.stock_code || 'report'
    const date = new Date(report.value.created_at).toISOString().slice(0, 10).replace(/-/g, '')
    const filename = `${company}_${date}.md`
    const blob = new Blob([report.value.content], { type: 'text/markdown;charset=utf-8' })
    saveAs(blob, filename)
  }

  function openPreview(): void {
    previewOpen.value = true
  }

  function closePreview(): void {
    previewOpen.value = false
  }

  async function deleteReport(id: string): Promise<void> {
    await reportApi.deleteReport(id)
    history.value = history.value.filter((item) => item.report_id !== id)
    if (reportId.value === id) {
      stopObservation()
      clearActiveReference()
      report.value = null
      progressStore.reset()
    }
  }

  if (getCurrentScope()) {
    const stopAuthWatch = watch(
      () => authStore.accessToken,
      (token, previous) => {
        if (previous && !token) {
          stopObservation()
          clearActiveReference()
        }
      },
    )
    onScopeDispose(() => {
      stopAuthWatch()
      stopObservation()
    })
  }

  return {
    taskId,
    reportId,
    status,
    progress,
    stages,
    transportStatus,
    report,
    errorMsg,
    isGenerating,
    isCompleted,
    isFailed,
    history,
    previewOpen,
    generateReport,
    restoreActiveTask,
    stopObservation,
    loadHistory,
    loadReport,
    downloadMarkdown,
    openPreview,
    closePreview,
    deleteReport,
  }
}
