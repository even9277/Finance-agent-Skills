import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatMessage, ChatSession } from '@/api'

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const isSending = ref(false)

  // Phase 2 新增：流式输出状态
  const isStreaming = ref(false)
  // Phase 2：当前会话的 running_summary（存在时前端显示压缩提示条）
  const currentRunningSummary = ref<string | null>(null)
  // Phase 2：流式输出时正在追加的 AI 消息临时 ID
  const streamingMessageId = ref<number | null>(null)

  // Phase 2：压缩进度 UI（百分比 + ETA）
  const isCompressing = ref(false)
  const compressProgress = ref(0) // 0-100
  const compressEtaSeconds = ref<number | null>(null)
  const lastCompressPercent = ref<number | null>(null) // 本次压缩覆盖比例（用于摘要历史页展示）

  function setCurrentSession(sessionId: string | null) {
    currentSessionId.value = sessionId
    if (!sessionId) {
      messages.value = []
      currentRunningSummary.value = null
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

  // Phase 2：追加 token 到最后一条 assistant 消息（流式输出）
  function appendStreamToken(token: string) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.id === streamingMessageId.value) {
      last.content += token
    }
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
  }

  function removeSession(sessionId: string) {
    sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
      currentRunningSummary.value = null
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

  return {
    sessions,
    currentSessionId,
    messages,
    isLoading,
    isSending,
    isStreaming,
    currentRunningSummary,
    streamingMessageId,
    isCompressing,
    compressProgress,
    compressEtaSeconds,
    lastCompressPercent,
    setCurrentSession,
    setSessions,
    setMessages,
    appendMessage,
    appendStreamToken,
    startStreamingMessage,
    finishStreamingMessage,
    startCompress,
    updateCompressProgress,
    finishCompress,
    addOrUpdateSession,
    removeSession,
    renameSession,
    setRunningSummary,
  }
})
