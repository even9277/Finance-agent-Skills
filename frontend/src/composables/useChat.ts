import { getCurrentScope, onScopeDispose, ref } from 'vue'
import { chatApi, buildWsUrl, parseWsFrame, type ChatMessage, type ChatTemplate } from '@/api'
import { useChatStore } from '@/stores/chatStore'
import { useUserStore } from '@/stores/userStore'
import { useMemory } from '@/composables/useMemory'
import { useMemoryStore } from '@/stores/memoryStore'

let streamRequestCounter = 0

function createStreamRequestId(): string {
  streamRequestCounter += 1
  return `web_${Date.now().toString(36)}_${streamRequestCounter.toString(36)}`
}

export function useChat() {
  const userStore = useUserStore()
  const chatStore = useChatStore()
  const { loadProfile } = useMemory()
  const memoryStore = useMemoryStore()
  const templates = ref<ChatTemplate[]>([])
  let compressTimer: number | null = null
  let contextRefreshTimer: number | null = null
  let activeStreamSocket: WebSocket | null = null
  let activeStreamStop: (() => void) | null = null

  const closeActiveStream = () => {
    const socket = activeStreamSocket
    activeStreamSocket = null
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close(1000, 'client lifecycle ended')
    }
  }

  if (getCurrentScope()) {
    onScopeDispose(closeActiveStream)
  }

  function stopContextRefreshPolling() {
    if (contextRefreshTimer) {
      window.clearInterval(contextRefreshTimer)
      contextRefreshTimer = null
    }
  }

  function maybeStartContextRefreshPolling() {
    const status = chatStore.currentContextWindow?.compression_status
    if (!chatStore.currentSessionId || !status || !['queued', 'running'].includes(status)) {
      stopContextRefreshPolling()
      return
    }
    if (contextRefreshTimer) return
    contextRefreshTimer = window.setInterval(async () => {
      await loadSessions().catch(console.error)
      const nextStatus = chatStore.currentContextWindow?.compression_status
      if (!nextStatus || !['queued', 'running'].includes(nextStatus)) {
        stopContextRefreshPolling()
      }
    }, 3000)
  }

  async function loadSessions(q?: string) {
    const { data } = await chatApi.listSessions(userStore.userId, q)
    chatStore.setSessions(data)
    // 更新当前会话的 running_summary
    if (chatStore.currentSessionId) {
      const cur = data.find((s) => s.session_id === chatStore.currentSessionId)
      chatStore.setRunningSummary(cur?.running_summary || null)
      chatStore.setContextWindow(cur?.context_window || null)
      maybeStartContextRefreshPolling()
    }
  }

  async function loadMessages(sessionId: string) {
    chatStore.setCurrentSession(sessionId)
    const { data } = await chatApi.getMessages(sessionId, userStore.userId)
    chatStore.setMessages(data.messages)
    // 同步 running_summary
    const session = chatStore.sessions.find((s) => s.session_id === sessionId)
    chatStore.setRunningSummary(session?.running_summary || null)
    chatStore.setContextWindow(data.context_window || session?.context_window || null)
    maybeStartContextRefreshPolling()
  }

  // ─────────────────────────────────────────────────────────────
  // 同步发送（HTTP POST，Phase 1 保留兼容）
  // ─────────────────────────────────────────────────────────────
  async function sendMessage(
    text: string,
    explicitSkill?: string,
    appendUserMessage = true,
  ) {
    if (!text.trim() || chatStore.isSending) return

    chatStore.isSending = true
    if (!explicitSkill) chatStore.clearSkillConfirmation()

    // 乐观更新：先显示用户消息
    if (appendUserMessage) {
      const optimisticUser: ChatMessage = {
        id: Date.now(),
        session_id: chatStore.currentSessionId || '',
        role: 'user',
        content: text,
        is_compressed: false,
        created_at: new Date().toISOString(),
      }
      chatStore.appendMessage(optimisticUser)
    }

    try {
      const { data } = await chatApi.sendMessage(
        userStore.userId,
        text,
        chatStore.currentSessionId || undefined,
        explicitSkill,
      )

      if (!chatStore.currentSessionId) {
        chatStore.setCurrentSession(data.session_id)
      }
      chatStore.setContextWindow(data.context_window || null)
      chatStore.updateSessionContext(data.session_id, data.context_window || null)
      if (data.memory_command) {
        memoryStore.setCommandResult(data.memory_command)
      }
      if (data.skill_confirmation) {
        chatStore.setSkillConfirmation({
          originalMessage: text,
          sessionId: data.session_id,
          confirmation: data.skill_confirmation,
        })
      }
      maybeStartContextRefreshPolling()

      const aiMsg: ChatMessage = {
        id: Date.now() + 1,
        session_id: data.session_id,
        role: 'assistant',
        content: data.reply,
        is_compressed: false,
        created_at: new Date().toISOString(),
      }
      chatStore.appendMessage(aiMsg)

      // Phase 3: 检查回复中是否有 memory_profile 变化（对话中更新画像）
      if (data.memory_profile) {
        // 后端返回的 memory_profile 说明这轮对话可能触发了画像更新，刷新全局 memoryStore
        loadProfile().catch(e => console.warn('[useChat] 刷新画像失败:', e))
      }

      await loadSessions()
    } catch (e: unknown) {
      const errMsg: ChatMessage = {
        id: Date.now() + 2,
        session_id: chatStore.currentSessionId || '',
        role: 'assistant',
        content: `请求失败：${e instanceof Error ? e.message : '未知错误'}`,
        is_compressed: false,
        created_at: new Date().toISOString(),
      }
      chatStore.appendMessage(errMsg)
    } finally {
      chatStore.isSending = false
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Phase 2 流式发送（WebSocket，打字机效果）
  // ─────────────────────────────────────────────────────────────
  async function sendMessageStream(text: string, explicitSkill?: string) {
    if (!text.trim() || chatStore.isSending || chatStore.isStreaming) return

    chatStore.isSending = true
    if (!explicitSkill) chatStore.clearSkillConfirmation()

    // 先追加用户消息（乐观更新）
    const sessionIdForOptimistic = chatStore.currentSessionId || ''
    const optimisticUser: ChatMessage = {
      id: Date.now(),
      session_id: sessionIdForOptimistic,
      role: 'user',
      content: text,
      is_compressed: false,
      created_at: new Date().toISOString(),
    }
    chatStore.appendMessage(optimisticUser)

    // 占位 assistant 消息（流式追加用）
    const currentSid = chatStore.currentSessionId || `temp_${Date.now()}`
    chatStore.startStreamingMessage(currentSid)
    const requestId = createStreamRequestId()
    chatStore.beginControlledExecution({ requestId, sessionId: currentSid })

    return new Promise<void>((resolve, reject) => {
      let ws: WebSocket | null = null
      let settled = false
      let started = false
      let userCancelled = false
      let streamSessionId: string | null = null
      let expectedSequence = 1
      let receivedChunkCount = 0
      const closeOnPageExit = () => closeActiveStream()

      const clearCompressTimer = () => {
        if (compressTimer) {
          window.clearInterval(compressTimer)
          compressTimer = null
        }
      }

      const finish = (errorMessage?: string) => {
        if (settled) return
        settled = true
        window.removeEventListener('beforeunload', closeOnPageExit)
        if (activeStreamSocket === ws) activeStreamSocket = null
        activeStreamStop = null
        if (errorMessage) chatStore.appendStreamDelta(`\n\n[${errorMessage}]`)
        clearCompressTimer()
        chatStore.finishStreamingMessage()
        chatStore.isSending = false
        if (!errorMessage) {
          loadProfile().catch(e => console.warn('[useChat] 刷新画像失败:', e))
          loadSessions().catch(console.error)
          maybeStartContextRefreshPolling()
        }
        resolve()
      }

      const rejectBeforeStart = () => {
        if (settled) return
        settled = true
        window.removeEventListener('beforeunload', closeOnPageExit)
        if (activeStreamSocket === ws) activeStreamSocket = null
        activeStreamStop = null
        clearCompressTimer()
        chatStore.abortStreamingMessage()
        chatStore.isSending = false
        chatStore.markControlledExecutionUnavailable()
        reject(new Error('WebSocket unavailable'))
      }

      const failProtocol = () => {
        console.error('[WS] chat-stream-v2 协议错误')
        chatStore.finishControlledExecution('FAILED')
        finish('协议错误，请重试')
        try {
          ws?.close(1002, 'chat-stream-v2 protocol error')
        } catch {
          // 浏览器可能已经关闭连接；本地状态已完成失败收口。
        }
      }

      try {
        ws = new WebSocket(buildWsUrl('/chat/stream'))
        activeStreamSocket = ws
        window.addEventListener('beforeunload', closeOnPageExit, { once: true })
      } catch (err) {
        console.error('[WS] 连接失败:', err)
        rejectBeforeStart()
        return
      }

      activeStreamStop = () => {
        if (settled) return
        userCancelled = true
        chatStore.cancelControlledExecution()
        try {
          ws?.close(1000, 'user cancelled')
        } finally {
          finish()
        }
      }

      ws.onopen = () => {
        ws!.send(
          JSON.stringify({
            user_id: userStore.userId,
            message: text,
            session_id: chatStore.currentSessionId || undefined,
            request_id: requestId,
            explicit_skill: explicitSkill,
          })
        )
      }

      ws.onmessage = (event: MessageEvent) => {
        const raw = event.data as string
        const frame = parseWsFrame(raw)

        if (settled) return
        if (!frame || frame.request_id !== requestId || frame.sequence !== expectedSequence) {
          failProtocol()
          return
        }
        expectedSequence += 1

        if (streamSessionId && frame.session_id !== streamSessionId) {
          failProtocol()
          return
        }

        if (frame.type === 'stream_error') {
          if (frame.chunk_count !== receivedChunkCount) {
            failProtocol()
            return
          }
          console.error('[WS] 服务端错误:', frame.code)
          chatStore.finishControlledExecution('FAILED')
          finish(`错误：${frame.message}`)
          return
        }

        if (frame.type === 'stream_start') {
          if (started || (chatStore.currentSessionId
            && chatStore.currentSessionId !== frame.session_id)) {
            failProtocol()
            return
          }
          started = true
          streamSessionId = frame.session_id
          chatStore.bindControlledExecutionSession(requestId, frame.session_id)
          if (!chatStore.currentSessionId) chatStore.setCurrentSession(frame.session_id)
          chatStore.setStreamingSessionId(frame.session_id)
          return
        }

        if (!started || frame.session_id !== streamSessionId) {
          failProtocol()
          return
        }

        if (frame.type === 'trace_summary'
          || frame.type === 'plan_preview'
          || frame.type === 'step_status'
          || frame.type === 'tool_status'
          || frame.type === 'verification_summary') {
          chatStore.applyControlledFrame(frame)
        } else if (frame.type === 'content_delta') {
          if (frame.chunk_index !== receivedChunkCount + 1) {
            failProtocol()
            return
          }
          chatStore.appendStreamDelta(frame.content)
          receivedChunkCount += 1
        } else if (frame.type === 'context_update') {
          chatStore.setContextWindow(frame.context_window)
          chatStore.updateSessionContext(frame.session_id, frame.context_window)
          maybeStartContextRefreshPolling()
        } else if (frame.type === 'memory_command') {
          memoryStore.setCommandResult(frame.memory_command)
        } else if (frame.type === 'skill_confirm') {
          chatStore.setSkillConfirmation({
            originalMessage: text,
            sessionId: frame.session_id,
            confirmation: frame.confirmation,
          })
        } else if (frame.type === 'compaction_queued'
          || frame.type === 'compaction_running'
          || frame.type === 'compaction_done'
          || frame.type === 'compaction_failed') {
          chatStore.setContextWindow(frame.context_window)
          chatStore.updateSessionContext(frame.session_id, frame.context_window)
          maybeStartContextRefreshPolling()
        } else if (frame.type === 'compress_start') {
          chatStore.startCompress(frame.eta_seconds)
          clearCompressTimer()
          const eta = Math.max(2, frame.eta_seconds || 8)
          const startAt = Date.now()
          compressTimer = window.setInterval(() => {
            const elapsed = (Date.now() - startAt) / 1000
            const ratio = Math.min(1, elapsed / eta)
            const progress = Math.floor(ratio * 95)
            const etaLeft = Math.max(0, Math.ceil(eta - elapsed))
            chatStore.updateCompressProgress(progress, etaLeft)
            if (progress >= 95) {
              chatStore.updateCompressProgress(95, 0)
              clearCompressTimer()
            }
          }, 200)
        } else if (frame.type === 'compress_done') {
          clearCompressTimer()
          chatStore.finishCompress(typeof frame.percent === 'number' ? frame.percent : undefined)
          loadSessions().catch(console.error)
        } else if (frame.type === 'compress_skip') {
          clearCompressTimer()
          chatStore.finishCompress(undefined)
        } else if (frame.type === 'stream_end') {
          if (frame.chunk_count !== receivedChunkCount) {
            failProtocol()
            return
          }
          chatStore.finishControlledExecution(frame.status)
          finish()
        }
      }

      ws.onerror = (event) => {
        if (settled) return
        console.error('[WS] 连接错误:', event)
        if (!started) {
          rejectBeforeStart()
          return
        }
        chatStore.finishControlledExecution('FAILED')
        finish('连接错误，请重试')
      }

      ws.onclose = () => {
        if (settled) return
        if (userCancelled) {
          finish()
        } else if (!started) {
          rejectBeforeStart()
        } else {
          chatStore.finishControlledExecution('FAILED')
          finish('连接已中断，请重试')
        }
      }
    })
  }

  async function newSession() {
    chatStore.setCurrentSession(null)
    chatStore.setMessages([])
    stopContextRefreshPolling()
  }

  async function confirmSkill(skillName: string) {
    const pending = chatStore.pendingSkillConfirmation
    if (!pending || chatStore.isSending || chatStore.isStreaming) return
    if (!pending.confirmation.candidates.some((item) => item.skill_name === skillName)) return
    if (chatStore.currentSessionId !== pending.sessionId) return
    chatStore.clearSkillConfirmation()
    await sendMessage(pending.originalMessage, skillName, false)
  }

  function cancelSkillConfirmation() {
    chatStore.clearSkillConfirmation()
  }

  function stopStreaming() {
    activeStreamStop?.()
  }

  async function deleteSession(sessionId: string) {
    await chatApi.deleteSession(sessionId, userStore.userId)
    chatStore.removeSession(sessionId)
  }

  async function renameSession(sessionId: string, title: string) {
    await chatApi.renameSession(sessionId, userStore.userId, title)
    chatStore.renameSession(sessionId, title)
  }

  async function loadTemplates() {
    if (templates.value.length) return
    const { data } = await chatApi.getTemplates()
    templates.value = data
  }

  return {
    templates,
    loadSessions,
    loadMessages,
    sendMessage,
    sendMessageStream,
    stopStreaming,
    confirmSkill,
    cancelSkillConfirmation,
    newSession,
    deleteSession,
    renameSession,
    loadTemplates,
  }
}
