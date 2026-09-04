import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  ChatContextWindow,
  ChatControlledFrame,
  ChatMessage,
  ChatPlanStepPreview,
  ChatStepLifecycleStatus,
  ChatTerminalStatus,
  ChatToolLifecycleStatus,
  ChatSession,
  SkillConfirmation,
} from '@/api'

export interface PendingSkillConfirmation {
  originalMessage: string
  sessionId: string
  confirmation: SkillConfirmation
}

export interface ControlledPlanRevision {
  plan_id: string
  revision: number
  validated: true
  replan_reason?: string
  replaced_step_ids?: string[]
}

export interface ControlledExecutionStep extends Omit<ChatPlanStepPreview, 'status'> {
  plan_id: string
  revision: number
  status: ChatStepLifecycleStatus
  elapsed_ms?: number
  error_code?: string
}

export interface ControlledExecutionTool {
  plan_id: string
  revision: number
  tool_call_id: string
  step_id: string
  display_name: string
  status: ChatToolLifecycleStatus
  attempt: number
  elapsed_ms?: number
  parameter_summary: string[]
  result_summary?: string
  error_code?: string
}

export interface ControlledVerification {
  plan_id: string
  revision: number
  sufficiency: 'SUFFICIENT' | 'PARTIAL' | 'INSUFFICIENT'
  claim_level: 'ANALYTICAL' | 'DESCRIPTIVE' | 'REFUSE'
  accepted_count: number
  rejected_count: number
  covered_dimensions: string[]
  missing_dimensions: string[]
  limitation: string
}

export interface ControlledTraceSummary {
  stage: string
  status: 'STARTED' | 'SUCCEEDED' | 'FAILED' | 'SKIPPED' | 'PARTIAL'
  elapsed_ms: number
  summary: string
  error_code?: string
}

export interface ControlledExecutionState {
  requestId: string
  sessionId: string
  status: 'RUNNING' | 'UNAVAILABLE' | ChatTerminalStatus
  activeRevision: number
  traces: ControlledTraceSummary[]
  planHistory: ControlledPlanRevision[]
  steps: ControlledExecutionStep[]
  tools: ControlledExecutionTool[]
  verification: ControlledVerification | null
}

const STEP_TERMINAL_STATUSES = new Set<ChatStepLifecycleStatus>([
  'SUCCEEDED', 'FAILED', 'SKIPPED', 'REPLANNED', 'CANCELLED',
])
const TOOL_TERMINAL_STATUSES = new Set<ChatToolLifecycleStatus>([
  'SUCCEEDED', 'FAILED', 'SKIPPED', 'CANCELLED',
])

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const isSending = ref(false)
  const pendingSkillConfirmation = ref<PendingSkillConfirmation | null>(null)
  const controlledExecution = ref<ControlledExecutionState | null>(null)

  // Phase 2 新增：流式输出状态
  const isStreaming = ref(false)
  // Phase 2：当前会话的 running_summary（存在时前端显示压缩提示条）
  const currentRunningSummary = ref<string | null>(null)
  const currentContextWindow = ref<ChatContextWindow | null>(null)
  // Phase 2：流式输出时正在追加的 AI 消息临时 ID
  const streamingMessageId = ref<number | null>(null)

  // Phase 2：压缩进度 UI（百分比 + ETA）
  const isCompressing = ref(false)
  const compressProgress = ref(0) // 0-100
  const compressEtaSeconds = ref<number | null>(null)
  const lastCompressPercent = ref<number | null>(null) // 本次压缩覆盖比例（用于摘要历史页展示）

  function setCurrentSession(sessionId: string | null) {
    if (
      pendingSkillConfirmation.value
      && pendingSkillConfirmation.value.sessionId !== sessionId
    ) {
      pendingSkillConfirmation.value = null
    }
    if (controlledExecution.value?.sessionId !== sessionId) {
      controlledExecution.value = null
    }
    currentSessionId.value = sessionId
    if (!sessionId) {
      messages.value = []
      currentRunningSummary.value = null
      currentContextWindow.value = null
    }
  }

  function setSessions(list: ChatSession[]) {
    sessions.value = list
  }

  function setMessages(list: ChatMessage[]) {
    messages.value = list
    pendingSkillConfirmation.value = null
    controlledExecution.value = null
  }

  function appendMessage(msg: ChatMessage) {
    messages.value.push(msg)
  }

  // D03：只把已通过 v2 sequence 校验的正文增量追加到当前 assistant 占位消息。
  function appendStreamDelta(content: string) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.id === streamingMessageId.value) {
      last.content += content
    }
  }

  function setStreamingSessionId(sessionId: string) {
    const target = messages.value.find((item) => item.id === streamingMessageId.value)
    if (target?.role === 'assistant') target.session_id = sessionId
  }

  // Phase 2：开始流式输出，先占位一条空白 assistant 消息
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

  // Phase 2：流式输出完成
  function finishStreamingMessage() {
    isStreaming.value = false
    streamingMessageId.value = null
  }

  function startCompress(etaSeconds?: number) {
    isCompressing.value = true
    compressProgress.value = 0
    compressEtaSeconds.value = typeof etaSeconds === 'number' ? etaSeconds : null
  }

  function updateCompressProgress(progress: number, etaSeconds?: number) {
    compressProgress.value = Math.max(0, Math.min(100, progress))
    if (typeof etaSeconds === 'number') compressEtaSeconds.value = etaSeconds
  }

  function finishCompress(percent?: number) {
    isCompressing.value = false
    compressProgress.value = 100
    compressEtaSeconds.value = 0
    if (typeof percent === 'number') lastCompressPercent.value = percent
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

  function abortStreamingMessage() {
    const targetId = streamingMessageId.value
    if (targetId !== null) {
      messages.value = messages.value.filter((item) => item.id !== targetId)
    }
    finishStreamingMessage()
  }

  function beginControlledExecution(input: { requestId: string; sessionId: string }) {
    controlledExecution.value = {
      requestId: input.requestId,
      sessionId: input.sessionId,
      status: 'RUNNING',
      activeRevision: 0,
      traces: [],
      planHistory: [],
      steps: [],
      tools: [],
      verification: null,
    }
  }

  function bindControlledExecutionSession(requestId: string, sessionId: string) {
    if (controlledExecution.value?.requestId === requestId) {
      controlledExecution.value.sessionId = sessionId
    }
  }

  function applyControlledFrame(frame: ChatControlledFrame) {
    const execution = controlledExecution.value
    if (!execution
      || execution.requestId !== frame.request_id
      || execution.sessionId !== frame.session_id
      || execution.status !== 'RUNNING') return

    if (frame.type === 'trace_summary') {
      execution.traces.push({
        stage: frame.stage,
        status: frame.status,
        elapsed_ms: frame.elapsed_ms,
        summary: frame.summary,
        error_code: frame.error_code,
      })
      return
    }

    if (frame.type === 'plan_preview') {
      if (!frame.validated || frame.revision < execution.activeRevision) return
      if (!execution.planHistory.some((item) => item.revision === frame.revision)) {
        execution.planHistory.push({
          plan_id: frame.plan_id,
          revision: frame.revision,
          validated: true,
          replan_reason: frame.replan_reason,
          replaced_step_ids: frame.replaced_step_ids,
        })
        execution.planHistory.sort((left, right) => left.revision - right.revision)
      }
      execution.activeRevision = Math.max(execution.activeRevision, frame.revision)
      for (const step of frame.steps) {
        if (execution.steps.some((item) => item.step_id === step.step_id)) continue
        execution.steps.push({
          ...step,
          plan_id: frame.plan_id,
          revision: frame.revision,
        })
      }
      return
    }

    if (frame.type === 'step_status') {
      const step = execution.steps.find((item) => item.step_id === frame.step_id)
      if (!step || frame.revision < step.revision) return
      if (STEP_TERMINAL_STATUSES.has(step.status) && frame.status !== step.status) return
      if (step.status === 'RUNNING' && frame.status === 'PLANNED') return
      step.status = frame.status
      step.elapsed_ms = frame.elapsed_ms
      step.error_code = frame.error_code
      return
    }

    if (frame.type === 'tool_status') {
      const current = execution.tools.find((item) => item.tool_call_id === frame.tool_call_id)
      if (current) {
        if (TOOL_TERMINAL_STATUSES.has(current.status) && frame.status !== current.status) return
        current.status = frame.status
        current.elapsed_ms = frame.elapsed_ms
        current.result_summary = frame.result_summary
        current.error_code = frame.error_code
      } else {
        execution.tools.push({
          plan_id: frame.plan_id,
          revision: frame.revision,
          tool_call_id: frame.tool_call_id,
          step_id: frame.step_id,
          display_name: frame.display_name,
          status: frame.status,
          attempt: frame.attempt,
          elapsed_ms: frame.elapsed_ms,
          parameter_summary: [...frame.parameter_summary],
          result_summary: frame.result_summary,
          error_code: frame.error_code,
        })
      }
      return
    }

    if (frame.type === 'verification_summary'
      && (!execution.verification || frame.revision >= execution.verification.revision)) {
      execution.verification = {
        plan_id: frame.plan_id,
        revision: frame.revision,
        sufficiency: frame.sufficiency,
        claim_level: frame.claim_level,
        accepted_count: frame.accepted_count,
        rejected_count: frame.rejected_count,
        covered_dimensions: [...frame.covered_dimensions],
        missing_dimensions: [...frame.missing_dimensions],
        limitation: frame.limitation,
      }
    }
  }

  function finishControlledExecution(status: ChatTerminalStatus) {
    if (controlledExecution.value?.status === 'RUNNING') {
      controlledExecution.value.status = status
    }
  }

  function cancelControlledExecution() {
    const execution = controlledExecution.value
    if (!execution || execution.status !== 'RUNNING') return
    execution.status = 'CANCELLED'
    for (const step of execution.steps) {
      if (step.status === 'RUNNING') step.status = 'CANCELLED'
      else if (step.status === 'PLANNED') step.status = 'SKIPPED'
    }
    for (const tool of execution.tools) {
      if (tool.status === 'STARTED') tool.status = 'CANCELLED'
    }
  }

  function markControlledExecutionUnavailable() {
    if (controlledExecution.value?.status === 'RUNNING') {
      controlledExecution.value.status = 'UNAVAILABLE'
      controlledExecution.value.steps = []
      controlledExecution.value.tools = []
    }
  }

  function setSkillConfirmation(value: PendingSkillConfirmation) {
    pendingSkillConfirmation.value = value
  }

  function clearSkillConfirmation() {
    pendingSkillConfirmation.value = null
  }

  function removeSession(sessionId: string) {
    sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
      currentRunningSummary.value = null
      currentContextWindow.value = null
      controlledExecution.value = null
    }
  }

  function renameSession(sessionId: string, title: string) {
    const s = sessions.value.find((s) => s.session_id === sessionId)
    if (s) s.title = title
  }

  // Phase 2：更新当前会话的 running_summary
  function setRunningSummary(summary: string | null) {
    currentRunningSummary.value = summary || null
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

  function reset() {
    sessions.value = []
    currentSessionId.value = null
    messages.value = []
    isLoading.value = false
    isSending.value = false
    isStreaming.value = false
    currentRunningSummary.value = null
    currentContextWindow.value = null
    streamingMessageId.value = null
    isCompressing.value = false
    compressProgress.value = 0
    compressEtaSeconds.value = null
    lastCompressPercent.value = null
    pendingSkillConfirmation.value = null
    controlledExecution.value = null
  }

  return {
    sessions,
    currentSessionId,
    messages,
    isLoading,
    isSending,
    pendingSkillConfirmation,
    controlledExecution,
    isStreaming,
    currentRunningSummary,
    currentContextWindow,
    streamingMessageId,
    isCompressing,
    compressProgress,
    compressEtaSeconds,
    lastCompressPercent,
    setCurrentSession,
    setSessions,
    setMessages,
    appendMessage,
    appendStreamDelta,
    startStreamingMessage,
    setStreamingSessionId,
    finishStreamingMessage,
    abortStreamingMessage,
    beginControlledExecution,
    bindControlledExecutionSession,
    applyControlledFrame,
    finishControlledExecution,
    cancelControlledExecution,
    markControlledExecutionUnavailable,
    setSkillConfirmation,
    clearSkillConfirmation,
    startCompress,
    updateCompressProgress,
    finishCompress,
    addOrUpdateSession,
    removeSession,
    renameSession,
    setRunningSummary,
    setContextWindow,
    updateSessionContext,
    reset,
  }
})
