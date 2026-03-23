import { ref, computed } from 'vue'
import { saveAs } from 'file-saver'
import { reportApi, type ReportDetail, type ReportListItem, type ReportStatusResponse } from '@/api'
import { useUserStore } from '@/stores/userStore'

const POLL_INTERVAL = 2000 // ms

export function useReport() {
  const userStore = useUserStore()

  const taskId = ref<string | null>(null)
  const reportId = ref<string | null>(null)
  const status = ref<ReportStatusResponse['status']>('pending')
  const progress = ref(0)
  const report = ref<ReportDetail | null>(null)
  const errorMsg = ref<string | null>(null)
  const isGenerating = ref(false)
  const history = ref<ReportListItem[]>([])
  const previewOpen = ref(false)

  let _pollTimer: ReturnType<typeof setInterval> | null = null

  const isCompleted = computed(() => status.value === 'completed')
  const isFailed = computed(() => status.value === 'failed')

  async function generateReport(command: string) {
    if (isGenerating.value) return
    isGenerating.value = true
    report.value = null
    errorMsg.value = null
    progress.value = 0
    status.value = 'pending'

    try {
      const { data } = await reportApi.generate(command, userStore.userId)
      taskId.value = data.task_id
      reportId.value = data.report_id
      status.value = 'pending'
      _startPolling()
    } catch (e: unknown) {
      errorMsg.value = e instanceof Error ? e.message : '触发失败'
      isGenerating.value = false
    }
  }

  function _startPolling() {
    _stopPolling()
    _pollTimer = setInterval(async () => {
      if (!taskId.value) return
      try {
        const { data } = await reportApi.getStatus(taskId.value)
        status.value = data.status
        progress.value = data.progress
        errorMsg.value = data.error_msg || null

        if (data.status === 'completed' && data.report_id) {
          _stopPolling()
          await _fetchReport(data.report_id)
          isGenerating.value = false
        } else if (data.status === 'failed') {
          _stopPolling()
          isGenerating.value = false
        }
      } catch {
        // 轮询偶发失败不终止
      }
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
    await _fetchReport(id)
    reportId.value = id
    status.value = 'completed'
    progress.value = 100
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
      report.value = null
      reportId.value = null
      status.value = 'pending'
    }
  }

  return {
    taskId,
    reportId,
    status,
    progress,
    report,
    errorMsg,
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
