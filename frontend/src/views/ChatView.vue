<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import ChatHistorySidebar from '@/components/chat/ChatHistorySidebar.vue'
import ChatWindow from '@/components/chat/ChatWindow.vue'
import SkillConfirmCard from '@/components/chat/SkillConfirmCard.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import TemplatePrompts from '@/components/chat/TemplatePrompts.vue'
import MemorySidebar from '@/components/memory/MemorySidebar.vue'
import { useChat } from '@/composables/useChat'
import { useChatStore } from '@/stores/chatStore'

const chatStore = useChatStore()
const {
  templates,
  sopSkills,
  isLoadingSopSkills,
  selectedSopSkill,
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
} = useChat()

const showTemplates = computed(() => chatStore.messages.length === 0)
const debugMode = ref(false)
const summaryPanelOpen = ref(false)

onMounted(async () => {
  await Promise.all([loadSessions(), loadTemplates()])
})

async function handleSelectSession(id: string) {
  await loadMessages(id)
}

async function handleNewSession() {
  await newSession()
}

async function handleDelete(id: string) {
  await deleteSession(id)
}

async function handleRename(id: string, title: string) {
  await renameSession(id, title)
}

async function handleSend(text: string) {
  try {
    await sendMessageStream(text)
  } catch {
    await sendMessage(text)
  }
}

function handleTemplateSelect(content: string) {
  handleSend(content)
}
</script>

<template>
  <AppLayout :sidebar="true">
    <template #sidebar>
      <ChatHistorySidebar
        :sessions="chatStore.sessions"
        :current-id="chatStore.currentSessionId"
        @select="handleSelectSession"
        @new="handleNewSession"
        @delete="handleDelete"
        @rename="handleRename"
      />
    </template>

    <div class="flex flex-col h-full overflow-hidden">
      <div
        v-if="chatStore.currentSessionId"
        class="px-4 py-2 border-b border-slate-800 bg-[#0D1526] flex items-center justify-between"
      >
        <span class="text-xs text-slate-400 truncate max-w-xs">
          {{
            chatStore.sessions.find(s => s.session_id === chatStore.currentSessionId)?.title
            || '新对话'
          }}
        </span>
        <div class="text-[10px] text-slate-600 shrink-0 ml-2 text-right">
          <div>{{ chatStore.messages.length }} 条消息</div>
          <button
            class="mt-0.5 cursor-pointer select-none text-slate-600 hover:text-slate-400 transition-colors"
            :class="{ '!text-sky-400': debugMode }"
            @click="debugMode = !debugMode"
            title="切换调试信息"
          >
            {{ debugMode ? '🔍 调试' : '🔍' }}
          </button>
        </div>
      </div>

      <div
        v-if="chatStore.currentRunningSummary"
        class="mx-4 mt-2 rounded-lg bg-amber-900/30 border border-amber-700/50 overflow-hidden"
      >
        <button
          class="w-full px-3 py-2 flex items-center justify-between gap-2 hover:bg-amber-900/40 transition-colors"
          @click="summaryPanelOpen = !summaryPanelOpen"
        >
          <div class="flex items-center gap-2 min-w-0">
            <svg class="shrink-0 w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span class="text-xs text-amber-300 truncate">
              {{
                String(chatStore.currentRunningSummaryMode || '').includes('fallback')
                  ? '当前显示的是降级摘要，建议结合最新对话继续追问'
                  : '已压缩早期对话历史，AI 仍保有关键上下文记忆'
              }}
            </span>
          </div>
          <svg
            class="shrink-0 w-4 h-4 text-amber-400 transition-transform duration-200"
            :class="{ 'rotate-180': summaryPanelOpen }"
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        <div v-if="summaryPanelOpen" class="px-3 pb-3 border-t border-amber-700/40">
          <p class="mt-2 text-xs text-amber-200/90 leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto">{{ chatStore.currentRunningSummary }}</p>
        </div>
      </div>

      <div
        v-if="chatStore.isPreCompacting"
        class="mx-4 mt-2 flex items-center gap-2 rounded-lg border border-amber-700/30 bg-amber-950/20 px-3 py-2"
      >
        <span class="inline-flex h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
        <span class="text-xs text-amber-100">{{ chatStore.preCompactionMessage }}</span>
      </div>

      <div class="flex-1 overflow-hidden flex flex-col">
        <TemplatePrompts
          v-if="showTemplates"
          :templates="templates"
          @select="handleTemplateSelect"
        />
        <ChatWindow
          v-else
          :messages="chatStore.messages"
          :is-sending="chatStore.isSending && !chatStore.isStreaming"
          :streaming-message-id="chatStore.streamingMessageId"
          :debug-mode="debugMode"
        />
        <SkillConfirmCard
          v-if="chatStore.pendingSkillConfirm"
          :payload="chatStore.pendingSkillConfirm"
          :disabled="chatStore.isSending"
          @choose="confirmSkillChoice"
        />
      </div>

      <ChatInput
        :disabled="chatStore.isSending || chatStore.isStreaming || !!chatStore.pendingSkillConfirm"
        :sop-skills="sopSkills"
        :selected-sop-skill="selectedSopSkill"
        :sop-loading="isLoadingSopSkills"
        @open-sop-panel="loadSopSkills"
        @select-sop="selectSopSkill"
        @clear-sop="clearSelectedSopSkill"
        @send="handleSend"
      />
    </div>

    <template #memory>
      <MemorySidebar />
    </template>
  </AppLayout>
</template>
