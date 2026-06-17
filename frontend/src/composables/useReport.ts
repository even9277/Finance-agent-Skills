import { ref, computed } from 'vue'
import { saveAs } from 'file-saver'
import {
  buildReportEventUrl,
  reportApi,
  type ReportDetail,
  type ReportListItem,
  type ReportStatusResponse,
} from '@/api'
import { useUserStore } from '@/stores/userStore'

const POLL_INTERVAL = 2000 // ms
const STAGE_FALLBACK_LABEL = '报告生成中'

export function useReport() {
  const userStore = useUserStore()

  const taskId = ref<string | null>(null)
  const reportId = ref<string | null>(null)
  const status = ref<ReportStatusResponse['status']>('pending')
  const progress = ref(0)
  const report = ref<ReportDetail | null>(null)
  const errorMsg = ref<string | null>(null)
  const currentStage = ref<string | null>(null)
  const currentStageLabel = ref<string | null>(null)
  const isGenerating = ref(false)
  const history = ref<ReportListItem[]>([])
  const previewOpen = ref(false)

  let _pollTimer: ReturnType<typeof setInterval> | null = null
  let _eventSource: EventSource | null = null

  const isCompleted = computed(() => status.value === 'completed')
  const isFailed = computed(() => status.value === 'failed')

  async function generateReport(command: string) {
    if (isGenerating.value) return
    isGenerating.value = true
    report.value = null
    errorMsg.value = null
    progress.value = 0
    status.value = 'pending'
    currentStage.value = null
    currentStageLabel.value = null

    try {
      const { data } = await reportApi.generate(command, userStore.userId)
      taskId.value = data.task_id
      reportId.value = data.report_id
      status.value = data.status
      if (data.status === 'completed' && data.report_id) {
        progress.value = 100
        currentStageLabel.value = '生成完成'
        await _fetchReport(data.report_id)
        isGenerating.value = false
        return
      }
      _startSSE(data.task_id)
    } catch (e: unknown) {
      errorMsg.value = e instanceof Error ? e.message : '触发失败'
      isGenerating.value = false
    }
  }

  function _applyStatusPayload(data: ReportStatusResponse) {
    status.value = data.status
    progress.value = data.progress
    errorMsg.value = data.error_msg || null
    currentStage.value = data.current_stage || null
    if (data.status === 'completed') {
      currentStageLabel.value = '生成完成'
    } else if (data.status === 'failed') {
      currentStageLabel.value = '生成失败'
    } else {
      currentStageLabel.value = data.current_stage_label || STAGE_FALLBACK_LABEL
    }
    if (data.report_id) reportId.value = data.report_id
  }

  async function _handleTerminalPayload(data: ReportStatusResponse) {
    _applyStatusPayload(data)
    _stopSSE()
    _stopPolling()
    if (data.status === 'completed' && data.report_id) {
      await _fetchReport(data.report_id)
    }
    isGenerating.value = false
  }

  function _startSSE(id: string) {
    _stopSSE()
    _stopPolling()
    const source = new EventSource(buildReportEventUrl(id))
    _eventSource = source

    source.addEventListener('status', (event) => {
      const data = JSON.parse((event as MessageEvent).data) as ReportStatusResponse
      _applyStatusPayload(data)
    })

    source.addEventListener('completed', (event) => {
      const data = JSON.parse((event as MessageEvent).data) as ReportStatusResponse
      void _handleTerminalPayload({ ...data, status: 'completed', progress: 100 })
    })

    source.addEventListener('failed', (event) => {
      const data = JSON.parse((event as MessageEvent).data) as ReportStatusResponse
      void _handleTerminalPayload({ ...data, status: 'failed' })
    })

    source.onerror = () => {
      _stopSSE()
      if (isGenerating.value && status.value !== 'completed' && status.value !== 'failed') {
        _startPolling()
      }
    }
  }

  function _stopSSE() {
    if (_eventSource) {
      _eventSource.close()
      _eventSource = null
    }
  }

  function _startPolling() {
    _stopPolling()
    const pollOnce = async () => {
      if (!taskId.value) return
      try {
        const { data } = await reportApi.getStatus(taskId.value)
        _applyStatusPayload(data)

        if (data.status === 'completed' && data.report_id) {
          await _handleTerminalPayload(data)
        } else if (data.status === 'failed') {
          await _handleTerminalPayload(data)
        }
      } catch {
        // 轮询偶发失败不终止
      }
    }
    void pollOnce()
    _pollTimer = setInterval(() => {
      void pollOnce()
    }, POLL_INTERVAL)
  }

  function _stopPolling() {
    if (_pollTimer) {
      clearInterval(_pollTimer)
      _pollTimer = null
    }
  }

  async function _fetchReport(id: string) {
    const { data } = await reportApi.getReport(id)
    report.value = data
  }

  async function loadHistory(q?: string) {
    const { data } = await reportApi.listHistory(userStore.userId, q)
    history.value = data
  }

  async function loadReport(id: string) {
    _stopSSE()
    _stopPolling()
    await _fetchReport(id)
    reportId.value = id
    status.value = 'completed'
    progress.value = 100
    currentStage.value = 'completed'
    currentStageLabel.value = '生成完成'
  }

  function downloadMarkdown() {
    if (!report.value?.content) return
    const company = report.value.company_name || report.value.stock_code || 'report'
    const date = new Date(report.value.created_at).toISOString().slice(0, 10).replace(/-/g, '')
    const filename = `${company}_${date}.md`
    const blob = new Blob([report.value.content], { type: 'text/markdown;charset=utf-8' })
    saveAs(blob, filename)
  }

  function openPreview() {
    previewOpen.value = true
  }

  function closePreview() {
    previewOpen.value = false
  }

  async function deleteReport(id: string) {
    await reportApi.deleteReport(id)
    history.value = history.value.filter((r) => r.report_id !== id)
    if (reportId.value === id) {
      _stopSSE()
      _stopPolling()
      report.value = null
      reportId.value = null
      status.value = 'pending'
      currentStage.value = null
      currentStageLabel.value = null
    }
  }

  return {
    taskId,
    reportId,
    status,
    progress,
    report,
    errorMsg,
    currentStage,
    currentStageLabel,
    isGenerating,
    isCompleted,
    isFailed,
    history,
    previewOpen,
    generateReport,
    loadHistory,
    loadReport,
    downloadMarkdown,
    openPreview,
    closePreview,
    deleteReport,
  }
}
