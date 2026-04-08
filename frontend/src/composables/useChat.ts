import { ref } from 'vue'
import { chatApi, buildWsUrl, parseWsFrame, type ChatMessage, type ChatTemplate } from '@/api'
import { useChatStore } from '@/stores/chatStore'
import { useUserStore } from '@/stores/userStore'
import { useMemory } from '@/composables/useMemory'

export function useChat() {
  const userStore = useUserStore()
  const chatStore = useChatStore()
  const { loadProfile } = useMemory()
  const templates = ref<ChatTemplate[]>([])
  let compressTimer: number | null = null
  let contextRefreshTimer: number | null = null

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
  async function sendMessage(text: string) {
    if (!text.trim() || chatStore.isSending) return

    chatStore.isSending = true

    // 乐观更新：先显示用户消息
    const optimisticUser: ChatMessage = {
      id: Date.now(),
      session_id: chatStore.currentSessionId || '',
      role: 'user',
      content: text,
      is_compressed: false,
      created_at: new Date().toISOString(),
    }
    chatStore.appendMessage(optimisticUser)

    try {
      const { data } = await chatApi.sendMessage(
        userStore.userId,
        text,
        chatStore.currentSessionId || undefined
      )

      if (!chatStore.currentSessionId) {
        chatStore.setCurrentSession(data.session_id)
      }
      chatStore.setContextWindow(data.context_window || null)
      chatStore.updateSessionContext(data.session_id, data.context_window || null)
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
  async function sendMessageStream(text: string) {
    if (!text.trim() || chatStore.isSending || chatStore.isStreaming) return

    chatStore.isSending = true

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

    return new Promise<void>((resolve) => {
      let ws: WebSocket | null = null
      try {
        ws = new WebSocket(buildWsUrl('/chat/stream'))
      } catch (err) {
        chatStore.finishStreamingMessage()
        chatStore.isSending = false
        console.error('[WS] 连接失败:', err)
        resolve()
        return
      }

      ws.onopen = () => {
        ws!.send(
          JSON.stringify({
            user_id: userStore.userId,
            message: text,
            session_id: chatStore.currentSessionId || undefined,
          })
        )
      }

      ws.onmessage = (event: MessageEvent) => {
        const raw = event.data as string
        const frame = parseWsFrame(raw)

        if (frame) {
          if (frame.type === 'session_id') {
            // 新建会话时更新 store 的 currentSessionId
            if (!chatStore.currentSessionId) {
              chatStore.setCurrentSession(frame.session_id)
            }
          } else if (frame.type === 'context_update') {
            chatStore.setContextWindow(frame.context_window)
            chatStore.updateSessionContext(frame.session_id, frame.context_window)
            maybeStartContextRefreshPolling()
          } else if (frame.type === 'compaction_queued' || frame.type === 'compaction_running' || frame.type === 'compaction_done' || frame.type === 'compaction_failed') {
            chatStore.setContextWindow(frame.context_window)
            chatStore.updateSessionContext(frame.session_id, frame.context_window)
            maybeStartContextRefreshPolling()
          } else if (frame.type === 'compress_start') {
            chatStore.startCompress(frame.eta_seconds)
            // 用 ETA 模拟平滑进度（0% → 95%），收到 compress_done 再置 100%
            if (compressTimer) window.clearInterval(compressTimer)
            const eta = Math.max(2, frame.eta_seconds || 8)
            const startAt = Date.now()
            compressTimer = window.setInterval(() => {
              const elapsed = (Date.now() - startAt) / 1000
              const ratio = Math.min(1, elapsed / eta)
              const progress = Math.floor(ratio * 95)
              const etaLeft = Math.max(0, Math.ceil(eta - elapsed))
              chatStore.updateCompressProgress(progress, etaLeft)
              if (progress >= 95) {
                // 到 95% 后停住，等待服务端 done
                chatStore.updateCompressProgress(95, 0)
                if (compressTimer) {
                  window.clearInterval(compressTimer)
                  compressTimer = null
                }
              }
            }, 200)
          } else if (frame.type === 'compress_done') {
            if (compressTimer) {
              window.clearInterval(compressTimer)
              compressTimer = null
            }
            chatStore.finishCompress(typeof frame.percent === 'number' ? frame.percent : undefined)
            // 压缩完成后，刷新 running_summary / 摘要历史入口依赖 sessions
            loadSessions().catch(console.error)
          } else if (frame.type === 'compress_skip') {
            if (compressTimer) {
              window.clearInterval(compressTimer)
              compressTimer = null
            }
            chatStore.finishCompress(undefined)
          } else if (frame.type === 'done') {
            if (compressTimer) {
              window.clearInterval(compressTimer)
              compressTimer = null
            }
            chatStore.finishStreamingMessage()
            chatStore.isSending = false
            // Phase 3: 流式结束后同步刷新画像（防止对话中用 <action> 更新了画像但前端未刷新）
            loadProfile().catch(e => console.warn('[useChat] 刷新画像失败:', e))
            // 刷新会话列表（获取最新 running_summary）
            loadSessions().catch(console.error)
            maybeStartContextRefreshPolling()
            resolve()
          } else if (frame.type === 'error') {
            console.error('[WS] 服务端错误:', frame.message)
            chatStore.appendStreamToken(`\n\n[错误：${frame.message}]`)
            if (compressTimer) {
              window.clearInterval(compressTimer)
              compressTimer = null
            }
            chatStore.finishStreamingMessage()
            chatStore.isSending = false
            resolve()
          }
        } else {
          // 普通 token，追加到最后的 assistant 消息
          chatStore.appendStreamToken(raw)
        }
      }

      ws.onerror = (event) => {
        console.error('[WS] 连接错误:', event)
        chatStore.appendStreamToken('\n\n[连接错误，请重试]')
        if (compressTimer) {
          window.clearInterval(compressTimer)
          compressTimer = null
        }
        chatStore.finishStreamingMessage()
        chatStore.isSending = false
        resolve()
      }

      ws.onclose = () => {
        // 若还在流式状态（非正常关闭），强制结束
        if (chatStore.isStreaming) {
          if (compressTimer) {
            window.clearInterval(compressTimer)
            compressTimer = null
          }
          chatStore.finishStreamingMessage()
          chatStore.isSending = false
          resolve()
        }
      }
    })
  }

  async function newSession() {
    chatStore.setCurrentSession(null)
    chatStore.setMessages([])
    stopContextRefreshPolling()
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
    newSession,
    deleteSession,
    renameSession,
    loadTemplates,
  }
}
