import { computed, ref } from 'vue'
import {
  chatApi,
  buildWsUrl,
  parseWsFrame,
  WS_EVENT,
  type ChatMessage,
  type ChatTemplate,
  type SopSkillListItem,
} from '@/api'
import { useChatStore } from '@/stores/chatStore'
import { useUserStore } from '@/stores/userStore'
import { useMemory } from '@/composables/useMemory'

export function useChat() {
  const userStore = useUserStore()
  const chatStore = useChatStore()
  const { loadProfile } = useMemory()
  const templates = ref<ChatTemplate[]>([])
  const sopSkills = ref<SopSkillListItem[]>([])
  const isLoadingSopSkills = ref(false)
  const selectedSopSkillId = ref<string | null>(null)

  const selectedSopSkill = computed(() =>
    sopSkills.value.find((item) => item.name === selectedSopSkillId.value) ?? null,
  )

  async function loadSessions(q?: string) {
    const { data } = await chatApi.listSessions(userStore.userId, q)
    chatStore.setSessions(data)
    if (chatStore.currentSessionId) {
      const cur = data.find((s) => s.session_id === chatStore.currentSessionId)
      chatStore.setRunningSummary(cur?.running_summary || null)
      chatStore.setRunningSummaryMode(cur?.running_summary_mode || null)
      chatStore.setContextWindow(cur?.context_window || null)
    }
  }

  async function loadMessages(sessionId: string) {
    chatStore.setCurrentSession(sessionId)
    const { data } = await chatApi.getMessages(sessionId, userStore.userId)
    chatStore.setMessages(data.messages)
    chatStore.setRunningSummary(data.running_summary || null)
    chatStore.setRunningSummaryMode(data.running_summary_mode || null)
    chatStore.setContextWindow(data.context_window || null)
  }

  async function loadSopSkills(force = false) {
    if (isLoadingSopSkills.value) return
    if (!force && sopSkills.value.length) return
    isLoadingSopSkills.value = true
    try {
      const { data } = await chatApi.fetchSopSkills()
      sopSkills.value = data || []
    } finally {
      isLoadingSopSkills.value = false
    }
  }

  function selectSopSkill(skillId: string) {
    selectedSopSkillId.value = skillId
  }

  function clearSelectedSopSkill() {
    selectedSopSkillId.value = null
  }

  async function sendMessage(text: string) {
    if (!text.trim() || chatStore.isSending) return

    chatStore.isSending = true
    const sopSkillId = selectedSopSkillId.value || undefined

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
        chatStore.currentSessionId || undefined,
        sopSkillId,
      )

      if (!chatStore.currentSessionId) {
        chatStore.setCurrentSession(data.session_id)
      }
      clearSelectedSopSkill()
      chatStore.setContextWindow(data.context_window || null)
      chatStore.setRunningSummary(data.running_summary ?? null)
      chatStore.setRunningSummaryMode(data.running_summary_mode ?? null)
      chatStore.updateSessionContext(data.session_id, data.context_window || null)

      if (data.skill_confirm) {
        chatStore.setPendingSkillConfirm(data.skill_confirm)
      } else {
        const aiMsg: ChatMessage = {
          id: Date.now() + 1,
          session_id: data.session_id,
          role: 'assistant',
          content: data.reply,
          is_compressed: false,
          created_at: new Date().toISOString(),
          route_summary: data.route_summary || null,
          plan_artifact: data.plan_artifact || null,
          verification: data.verification || null,
          allowed_claim_level: data.allowed_claim_level || null,
          plan_preview: (data.plan_artifact?.plan_preview || []) as ChatMessage['plan_preview'],
          verification_summary: data.verification
            ? {
                status: String(data.verification.status || ''),
                evidence_score: Number(data.verification.evidence_score || 0),
                allowed_claim_level: String(data.verification.allowed_claim_level || data.allowed_claim_level || ''),
                missing_dimensions: (data.verification.missing_dimensions || []) as string[],
              }
            : null,
        }
        chatStore.appendMessage(aiMsg)
      }

      if (data.memory_profile) {
        loadProfile().catch((e) => console.warn('[useChat] 刷新画像失败:', e))
      }

      await loadSessions()
    } catch (e: unknown) {
      chatStore.removeMessageById(optimisticUser.id)
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

  async function sendMessageStream(text: string) {
    if (!text.trim() || chatStore.isSending || chatStore.isStreaming) return

    chatStore.isSending = true
    const sopSkillId = selectedSopSkillId.value || undefined

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

    const currentSid = chatStore.currentSessionId || `temp_${Date.now()}`
    chatStore.startStreamingMessage(currentSid)

    return new Promise<void>((resolve) => {
      let ws: WebSocket | null = null
      let requestAccepted = false

      const acceptCurrentRequest = () => {
        if (requestAccepted) return
        requestAccepted = true
        clearSelectedSopSkill()
      }

      const rollbackRejectedTurn = (message: string) => {
        chatStore.removeMessageById(optimisticUser.id)
        chatStore.removeStreamingPlaceholderIfEmpty()
        chatStore.appendMessage({
          id: Date.now() + 3,
          session_id: chatStore.currentSessionId || '',
          role: 'assistant',
          content: message,
          is_compressed: false,
          created_at: new Date().toISOString(),
        })
      }

      try {
        ws = new WebSocket(buildWsUrl('/chat/stream'))
      } catch (err) {
        rollbackRejectedTurn('连接失败：无法建立实时会话')
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
            sop_skill_id: sopSkillId,
          }),
        )
      }

      ws.onmessage = (event: MessageEvent) => {
        const raw = event.data as string
        const frame = parseWsFrame(raw)

        if (frame) {
          if (frame.type !== WS_EVENT.ERROR) {
            acceptCurrentRequest()
          }

          switch (frame.type) {
            case WS_EVENT.SESSION_ID:
              if (!chatStore.currentSessionId) {
                chatStore.setCurrentSession(frame.session_id)
              }
              break

            case WS_EVENT.CONTEXT_UPDATE:
              chatStore.setContextWindow(frame.context_window)
              chatStore.updateSessionContext(frame.session_id, frame.context_window)
              break

            case WS_EVENT.TASK_STATUS_QUEUED:
              chatStore.setTaskStatus('queued', frame.task_kind)
              if ('context_window' in frame && frame.context_window) {
                chatStore.setContextWindow(frame.context_window)
                chatStore.updateSessionContext(frame.session_id, frame.context_window)
              }
              break

            case WS_EVENT.TASK_STATUS_RUNNING:
              chatStore.setTaskStatus('running', frame.task_kind)
              if ('context_window' in frame && frame.context_window) {
                chatStore.setContextWindow(frame.context_window)
                chatStore.updateSessionContext(frame.session_id, frame.context_window)
              }
              if (frame.task_kind === 'pre_compaction') {
                chatStore.startPreCompaction()
              }
              break

            case WS_EVENT.TASK_STATUS_DONE:
              chatStore.setTaskStatus('done', frame.task_kind)
              if ('context_window' in frame && frame.context_window) {
                chatStore.setContextWindow(frame.context_window)
                chatStore.updateSessionContext(frame.session_id, frame.context_window)
              }
              if (frame.task_kind === 'pre_compaction') {
                chatStore.finishPreCompaction()
              }
              break

            case WS_EVENT.TASK_STATUS_FAILED:
              chatStore.setTaskStatus('failed', frame.task_kind)
              if ('context_window' in frame && frame.context_window) {
                chatStore.setContextWindow(frame.context_window)
                chatStore.updateSessionContext(frame.session_id, frame.context_window)
              }
              if (frame.task_kind === 'pre_compaction') {
                chatStore.finishPreCompaction()
              }
              break

            case WS_EVENT.TRACE_SUMMARY:
              if (chatStore.streamingMessageId) {
                chatStore.updateMessageRouteSummary(chatStore.streamingMessageId, frame.route_summary)
              }
              break

            case WS_EVENT.PLAN_PREVIEW:
              if (chatStore.streamingMessageId) {
                chatStore.updateMessagePlanPreview(chatStore.streamingMessageId, frame.items || [])
              }
              break

            case WS_EVENT.STEP_STATUS:
              if (chatStore.streamingMessageId) {
                chatStore.upsertMessageStepStatus(chatStore.streamingMessageId, {
                  plan_id: frame.plan_id,
                  step_id: frame.step_id,
                  tool_name: frame.tool_name || '',
                  status: frame.status || 'planned',
                })
              }
              break

            case WS_EVENT.VERIFICATION_SUMMARY:
              if (chatStore.streamingMessageId) {
                chatStore.updateMessageVerificationSummary(chatStore.streamingMessageId, {
                  plan_id: frame.plan_id,
                  status: frame.status || '',
                  evidence_score: frame.evidence_score || 0,
                  allowed_claim_level: frame.allowed_claim_level || '',
                  missing_dimensions: frame.missing_dimensions || [],
                })
              }
              break

            case WS_EVENT.SKILL_CONFIRM:
              chatStore.removeStreamingPlaceholderIfEmpty()
              chatStore.setPendingSkillConfirm({
                session_id: frame.session_id,
                options: frame.options || [],
                reasoning: frame.reasoning || '',
                resolved_query: frame.resolved_query || '',
                confidence: typeof frame.confidence === 'number' ? frame.confidence : 0,
              })
              break

            case WS_EVENT.DONE:
              chatStore.finishPreCompaction()
              if ('awaiting_skill_confirm' in frame && frame.awaiting_skill_confirm) {
                chatStore.isSending = false
                loadProfile().catch((e) => console.warn('[useChat] 刷新画像失败:', e))
                void loadSessions().catch(console.error)
                resolve()
                break
              }
              void (async () => {
                try {
                  if ('context_window' in frame && frame.context_window) {
                    chatStore.setContextWindow(frame.context_window)
                    if (frame.session_id) chatStore.updateSessionContext(frame.session_id, frame.context_window)
                  }
                  if ('running_summary' in frame && frame.running_summary) {
                    chatStore.setRunningSummary(frame.running_summary)
                  }
                  if ('running_summary_mode' in frame) {
                    chatStore.setRunningSummaryMode(frame.running_summary_mode || null)
                  }
                  if ('route_summary' in frame && frame.route_summary && chatStore.streamingMessageId) {
                    chatStore.updateMessageRouteSummary(chatStore.streamingMessageId, frame.route_summary)
                  }
                  await loadSessions()
                } finally {
                  chatStore.finishStreamingMessage()
                  chatStore.isSending = false
                  loadProfile().catch((e) => console.warn('[useChat] 刷新画像失败:', e))
                  resolve()
                }
              })()
              break

            case WS_EVENT.ERROR:
              console.error('[WS] 服务端错误:', frame.message)
              chatStore.finishPreCompaction()
              if (!requestAccepted) {
                rollbackRejectedTurn(`请求失败：${frame.message}`)
              } else {
                chatStore.appendStreamToken(`\n\n[错误：${frame.message}]`)
                chatStore.finishStreamingMessage()
              }
              chatStore.isSending = false
              resolve()
              break
          }
        } else {
          chatStore.appendStreamToken(raw)
        }
      }

      ws.onerror = (event) => {
        console.error('[WS] 连接错误:', event)
        chatStore.finishPreCompaction()
        if (!requestAccepted) {
          rollbackRejectedTurn('连接错误：请求未被服务端接受')
        } else {
          chatStore.appendStreamToken('\n\n[连接错误，请重试]')
          chatStore.finishStreamingMessage()
        }
        chatStore.isSending = false
        resolve()
      }

      ws.onclose = () => {
        if (chatStore.isStreaming) {
          chatStore.finishPreCompaction()
          if (!requestAccepted) {
            rollbackRejectedTurn('连接已关闭：请求未完成发送')
          } else {
            chatStore.finishStreamingMessage()
          }
          chatStore.isSending = false
          resolve()
        }
      }
    })
  }

  async function newSession() {
    chatStore.setCurrentSession(null)
    chatStore.setMessages([])
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

  async function confirmSkillChoice(userChoice: string) {
    const sid = chatStore.currentSessionId
    if (!sid || !userStore.userId || chatStore.isSending) return
    chatStore.clearPendingSkillConfirm()
    chatStore.isSending = true
    try {
      const { data } = await chatApi.confirmSkill(sid, userStore.userId, userChoice)
      chatStore.setContextWindow(data.context_window || null)
      chatStore.setRunningSummary(data.running_summary ?? null)
      chatStore.setRunningSummaryMode(data.running_summary_mode ?? null)
      chatStore.updateSessionContext(data.session_id, data.context_window || null)
      const aiMsg: ChatMessage = {
        id: Date.now(),
        session_id: data.session_id,
        role: 'assistant',
        content: data.reply,
        is_compressed: false,
        created_at: new Date().toISOString(),
        route_summary: data.route_summary || null,
        plan_artifact: data.plan_artifact || null,
        verification: data.verification || null,
        allowed_claim_level: data.allowed_claim_level || null,
        plan_preview: (data.plan_artifact?.plan_preview || []) as ChatMessage['plan_preview'],
        verification_summary: data.verification
          ? {
              status: String(data.verification.status || ''),
              evidence_score: Number(data.verification.evidence_score || 0),
              allowed_claim_level: String(data.verification.allowed_claim_level || data.allowed_claim_level || ''),
              missing_dimensions: (data.verification.missing_dimensions || []) as string[],
            }
          : null,
      }
      chatStore.appendMessage(aiMsg)
      if (data.memory_profile) {
        loadProfile().catch((e) => console.warn('[useChat] 刷新画像失败:', e))
      }
      await loadSessions()
    } catch (e: unknown) {
      const errMsg: ChatMessage = {
        id: Date.now() + 1,
        session_id: sid,
        role: 'assistant',
        content: `确认失败：${e instanceof Error ? e.message : '未知错误'}`,
        is_compressed: false,
        created_at: new Date().toISOString(),
      }
      chatStore.appendMessage(errMsg)
    } finally {
      chatStore.isSending = false
    }
  }

  return {
    templates,
    sopSkills,
    isLoadingSopSkills,
    selectedSopSkill,
    selectedSopSkillId,
    loadSessions,
    loadMessages,
    loadSopSkills,
    selectSopSkill,
    clearSelectedSopSkill,
    sendMessage,
    sendMessageStream,
    confirmSkillChoice,
    newSession,
    deleteSession,
    renameSession,
    loadTemplates,
  }
}
