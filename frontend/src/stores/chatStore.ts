import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type {
  ChatContextWindow,
  ChatMessage,
  PlanPreviewItem,
  ChatRouteSummary,
  ChatSession,
  SkillConfirmPayload,
  StepStatusItem,
  VerificationSummary,
} from '@/api'

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const isSending = ref(false)

  const isStreaming = ref(false)
  const currentRunningSummary = ref<string | null>(null)
  const currentRunningSummaryMode = ref<string | null>(null)
  const currentContextWindow = ref<ChatContextWindow | null>(null)
  const streamingMessageId = ref<number | null>(null)

  const taskStatus = ref<'idle' | 'queued' | 'running' | 'done' | 'failed'>('idle')
  const taskKind = ref<string>('')
  const isPreCompacting = ref(false)
  const preCompactionMessage = ref('')
  const preCompactionShownCount = ref(0)
  const preCompactionTotalDurationMs = ref(0)
  const preCompactionLastDurationMs = ref<number | null>(null)
  const preCompactionStartedAt = ref<number | null>(null)
  const preCompactionAverageDurationMs = computed(() => {
    if (preCompactionShownCount.value <= 0) return 0
    return Math.round(preCompactionTotalDurationMs.value / preCompactionShownCount.value)
  })

  const pendingSkillConfirm = ref<SkillConfirmPayload | null>(null)

  function setCurrentSession(sessionId: string | null) {
    currentSessionId.value = sessionId
    if (!sessionId) {
      messages.value = []
      currentRunningSummary.value = null
      currentRunningSummaryMode.value = null
      currentContextWindow.value = null
      pendingSkillConfirm.value = null
    }
  }

  function setSessions(list: ChatSession[]) {
    sessions.value = list
  }

  function setMessages(list: ChatMessage[]) {
    messages.value = list
  }

  function appendMessage(msg: ChatMessage) {
    messages.value.push(msg)
  }

  function removeMessageById(messageId: number) {
    messages.value = messages.value.filter((msg) => msg.id !== messageId)
  }

  function updateMessageRouteSummary(messageId: number, routeSummary: ChatRouteSummary | null | undefined) {
    const target = messages.value.find((msg) => msg.id === messageId)
    if (target) {
      target.route_summary = routeSummary || null
    }
  }

  function updateMessagePlanPreview(messageId: number, items: PlanPreviewItem[] | null | undefined) {
    const target = messages.value.find((msg) => msg.id === messageId)
    if (target) {
      target.plan_preview = items || []
    }
  }

  function upsertMessageStepStatus(messageId: number, item: StepStatusItem) {
    const target = messages.value.find((msg) => msg.id === messageId)
    if (!target) return
    const list = target.step_statuses || []
    const idx = list.findIndex((existing) => existing.step_id === item.step_id)
    if (idx >= 0) {
      list[idx] = { ...list[idx], ...item }
    } else {
      list.push(item)
    }
    target.step_statuses = [...list]
    if (target.plan_preview?.length) {
      target.plan_preview = target.plan_preview.map((preview) =>
        preview.step_id === item.step_id ? { ...preview, status: item.status } : preview,
      )
    }
  }

  function updateMessageVerificationSummary(messageId: number, summary: VerificationSummary | null | undefined) {
    const target = messages.value.find((msg) => msg.id === messageId)
    if (target) {
      target.verification_summary = summary || null
    }
  }

  function appendStreamToken(token: string) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.id === streamingMessageId.value) {
      last.content += token
    }
  }

  function startStreamingMessage(sessionId: string): number {
    const tempId = -(Date.now())
    streamingMessageId.value = tempId
    const placeholder: ChatMessage = {
      id: tempId,
      session_id: sessionId,
      role: 'assistant',
      content: '',
      is_compressed: false,
      created_at: new Date().toISOString(),
    }
    messages.value.push(placeholder)
    isStreaming.value = true
    return tempId
  }

  function finishStreamingMessage() {
    isStreaming.value = false
    streamingMessageId.value = null
  }

  function removeStreamingPlaceholderIfEmpty() {
    const sid = streamingMessageId.value
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.id === sid && !String(last.content || '').trim()) {
      messages.value.pop()
    }
    finishStreamingMessage()
  }

  function setPendingSkillConfirm(payload: SkillConfirmPayload | null) {
    pendingSkillConfirm.value = payload
  }

  function clearPendingSkillConfirm() {
    pendingSkillConfirm.value = null
  }

  function addOrUpdateSession(session: ChatSession) {
    const idx = sessions.value.findIndex((s) => s.session_id === session.session_id)
    if (idx >= 0) {
      sessions.value[idx] = session
    } else {
      sessions.value.unshift(session)
    }
    if (currentSessionId.value === session.session_id) {
      currentContextWindow.value = session.context_window || null
    }
  }

  function removeSession(sessionId: string) {
    sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
      currentRunningSummary.value = null
      currentRunningSummaryMode.value = null
      currentContextWindow.value = null
    }
  }

  function renameSession(sessionId: string, title: string) {
    const s = sessions.value.find((s) => s.session_id === sessionId)
    if (s) s.title = title
  }

  function setRunningSummary(summary: string | null) {
    currentRunningSummary.value = summary || null
  }

  function setRunningSummaryMode(mode: string | null | undefined) {
    currentRunningSummaryMode.value = mode || null
  }

  function setContextWindow(contextWindow: ChatContextWindow | null | undefined) {
    currentContextWindow.value = contextWindow || null
  }

  function updateSessionContext(sessionId: string, contextWindow: ChatContextWindow | null | undefined) {
    const target = sessions.value.find((s) => s.session_id === sessionId)
    if (target) target.context_window = contextWindow || null
    if (currentSessionId.value === sessionId) {
      currentContextWindow.value = contextWindow || null
    }
  }

  function setTaskStatus(status: 'idle' | 'queued' | 'running' | 'done' | 'failed', kind: string = '') {
    taskStatus.value = status
    taskKind.value = kind
  }

  function startPreCompaction(message = '正在压缩历史对话，以保留关键上下文…') {
    if (!isPreCompacting.value) {
      preCompactionShownCount.value += 1
      preCompactionStartedAt.value = Date.now()
    }
    isPreCompacting.value = true
    preCompactionMessage.value = message
    taskStatus.value = 'running'
    taskKind.value = 'pre_compaction'
  }

  function finishPreCompaction() {
    if (isPreCompacting.value && typeof preCompactionStartedAt.value === 'number') {
      const elapsedMs = Math.max(0, Date.now() - preCompactionStartedAt.value)
      preCompactionLastDurationMs.value = elapsedMs
      preCompactionTotalDurationMs.value += elapsedMs
    }
    isPreCompacting.value = false
    preCompactionMessage.value = ''
    preCompactionStartedAt.value = null
    if (taskKind.value === 'pre_compaction') {
      taskStatus.value = 'idle'
      taskKind.value = ''
    }
  }

  function reset() {
    sessions.value = []
    currentSessionId.value = null
    messages.value = []
    isLoading.value = false
    isSending.value = false
    isStreaming.value = false
    currentRunningSummary.value = null
    currentRunningSummaryMode.value = null
    currentContextWindow.value = null
    streamingMessageId.value = null
    taskStatus.value = 'idle'
    taskKind.value = ''
    isPreCompacting.value = false
    preCompactionMessage.value = ''
    preCompactionShownCount.value = 0
    preCompactionTotalDurationMs.value = 0
    preCompactionLastDurationMs.value = null
    preCompactionStartedAt.value = null
    pendingSkillConfirm.value = null
  }

  return {
    sessions,
    currentSessionId,
    messages,
    isLoading,
    isSending,
    isStreaming,
    currentRunningSummary,
    currentRunningSummaryMode,
    currentContextWindow,
    streamingMessageId,
    taskStatus,
    taskKind,
    isPreCompacting,
    preCompactionMessage,
    preCompactionShownCount,
    preCompactionTotalDurationMs,
    preCompactionLastDurationMs,
    preCompactionAverageDurationMs,
    pendingSkillConfirm,
    setCurrentSession,
    setSessions,
    setMessages,
    appendMessage,
    removeMessageById,
    updateMessageRouteSummary,
    updateMessagePlanPreview,
    upsertMessageStepStatus,
    updateMessageVerificationSummary,
    appendStreamToken,
    startStreamingMessage,
    finishStreamingMessage,
    removeStreamingPlaceholderIfEmpty,
    setPendingSkillConfirm,
    clearPendingSkillConfirm,
    addOrUpdateSession,
    removeSession,
    renameSession,
    setRunningSummary,
    setRunningSummaryMode,
    setContextWindow,
    updateSessionContext,
    setTaskStatus,
    startPreCompaction,
    finishPreCompaction,
    reset,
  }
})
