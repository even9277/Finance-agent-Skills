<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import ChatHistorySidebar from '@/components/chat/ChatHistorySidebar.vue'
import ChatWindow from '@/components/chat/ChatWindow.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import TemplatePrompts from '@/components/chat/TemplatePrompts.vue'
import MemorySidebar from '@/components/memory/MemorySidebar.vue'
import { useChat } from '@/composables/useChat'
import { useChatStore } from '@/stores/chatStore'
import { chatApi, type ChatSummaryItem } from '@/api'
import { useUserStore } from '@/stores/userStore'

const chatStore = useChatStore()
const userStore = useUserStore()
const {
  templates,
  loadSessions, loadMessages, sendMessage, sendMessageStream,
  newSession, deleteSession, renameSession, loadTemplates,
} = useChat()

// 是否显示模板（无消息时显示）
const showTemplates = computed(() => chatStore.messages.length === 0)

// Phase 2：摘要历史面板（替代完整对话历史）
const showSummaryHistory = ref(false)
const summaryItems = ref<ChatSummaryItem[]>([])
const isLoadingSummaries = ref(false)

onMounted(async () => {
  await Promise.all([loadSessions(), loadTemplates()])
})

async function handleSelectSession(id: string) {
  await loadMessages(id)
  showSummaryHistory.value = false
}

async function handleNewSession() {
  await newSession()
  showSummaryHistory.value = false
}

async function handleDelete(id: string) {
  await deleteSession(id)
  showSummaryHistory.value = false
}

async function handleRename(id: string, title: string) {
  await renameSession(id, title)
}

// Phase 2：优先使用 WebSocket 流式发送，降级到 HTTP POST
async function handleSend(text: string) {
  try {
    await sendMessageStream(text)
  } catch {
    // WebSocket 不可用时降级同步
    await sendMessage(text)
  }
}

function handleTemplateSelect(content: string) {
  handleSend(content)
}

// Phase 2：加载并展示摘要历史（压缩快照）
async function handleViewSummaryHistory() {
  if (!chatStore.currentSessionId) return
  isLoadingSummaries.value = true
  try {
    const { data } = await chatApi.getSummaries(chatStore.currentSessionId, userStore.userId)
    summaryItems.value = data.items || []
    showSummaryHistory.value = true
  } catch (e) {
    console.error('加载摘要历史失败', e)
  } finally {
    isLoadingSummaries.value = false
  }
}
</script>

<template>
  <AppLayout :sidebar="true">
    <!-- 左侧：会话历史侧边栏 -->
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

    <!-- 主内容区：对话 -->
    <div class="flex flex-col h-full overflow-hidden">
      <!-- 对话区顶部信息条（有会话时显示） -->
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
          <div v-if="chatStore.currentContextWindow">
            Context {{ chatStore.currentContextWindow.usage_percent }}%
            · {{ chatStore.currentContextWindow.compression_status }}
          </div>
        </div>
      </div>

      <!-- Phase 2：STM 压缩提示条（running_summary 存在时显示） -->
      <div
        v-if="chatStore.currentRunningSummary"
        class="mx-4 mt-2 px-3 py-2 rounded-lg bg-amber-900/30 border border-amber-700/50 flex items-center justify-between gap-2"
      >
        <div class="flex items-center gap-2 min-w-0">
          <svg class="shrink-0 w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span class="text-xs text-amber-300 truncate">
            已压缩早期对话历史，AI 仍保有关键上下文记忆
          </span>
        </div>
        <button
          class="shrink-0 text-xs text-amber-400 hover:text-amber-200 underline transition-colors"
          :disabled="isLoadingSummaries"
          @click="handleViewSummaryHistory"
        >
          {{ isLoadingSummaries ? '加载中…' : '查看摘要历史' }}
        </button>
      </div>

      <!-- Phase 2：压缩进度条（百分比 + ETA） -->
      <div
        v-if="chatStore.isCompressing"
        class="mx-4 mt-2 px-3 py-2 rounded-lg bg-slate-900/60 border border-slate-700/60"
      >
        <div class="flex items-center justify-between">
          <span class="text-xs text-slate-300">正在压缩对话历史</span>
          <span class="text-[10px] text-slate-500">
            {{ chatStore.compressProgress }}%
            <span v-if="typeof chatStore.compressEtaSeconds === 'number' && chatStore.compressEtaSeconds > 0">
              · 预计 {{ chatStore.compressEtaSeconds }}s
            </span>
          </span>
        </div>
        <div class="mt-2 h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
          <div
            class="h-full bg-amber-500 transition-all duration-300"
            :style="{ width: `${chatStore.compressProgress}%` }"
          />
        </div>
        <p class="mt-2 text-[10px] text-slate-600">
          压缩完成后可在“摘要历史”查看每次摘要快照与覆盖比例
        </p>
      </div>

      <!-- 消息列表 or 模板提示 -->
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
        />
      </div>

      <!-- 底部输入框 -->
      <ChatInput
        :disabled="chatStore.isSending || chatStore.isStreaming"
        :context-window="chatStore.currentContextWindow"
        @send="handleSend"
      />

    </div>

    <!-- 右侧：记忆画像侧边栏 -->
    <template #memory>
      <MemorySidebar />
    </template>

    <!-- Phase 2：完整历史弹窗 -->
    <Teleport to="body">
      <div
        v-if="showSummaryHistory"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
        @click.self="showSummaryHistory = false"
      >
        <div class="relative w-full max-w-2xl max-h-[80vh] bg-[#0F172A] border border-slate-700 rounded-xl shadow-2xl flex flex-col mx-4">
          <!-- 弹窗头部 -->
          <div class="flex items-center justify-between px-5 py-4 border-b border-slate-800">
            <h3 class="text-sm font-semibold text-slate-200">摘要历史</h3>
            <button
              class="text-slate-500 hover:text-slate-300 transition-colors"
              @click="showSummaryHistory = false"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- 摘要列表 -->
          <div class="overflow-y-auto flex-1 px-5 py-4 space-y-3">
            <div
              v-for="item in summaryItems"
              :key="item.id"
              class="p-3 rounded-xl border border-slate-800 bg-slate-900/40"
            >
              <div class="flex items-center justify-between">
                <span class="text-[10px] text-slate-500">
                  {{ new Date(item.created_at).toLocaleString('zh-CN') }}
                </span>
                <span class="text-[10px] text-amber-400">
                  <template v-if="typeof item.compressed_user_count === 'number' && typeof item.compressed_assistant_count === 'number'">
                    压缩了 {{ item.compressed_user_count }} 条用户消息 + {{ item.compressed_assistant_count }} 条助手消息
                  </template>
                  <template v-else>
                    压缩了 {{ item.compressed_message_count }} 条消息
                  </template>
                </span>
              </div>
              <div class="mt-1 flex items-center justify-between">
                <span class="text-[10px] text-slate-600">
                  <template v-if="item.start_created_at && item.end_created_at">
                    时间轴：{{ new Date(item.start_created_at).toLocaleString('zh-CN') }} → {{ new Date(item.end_created_at).toLocaleString('zh-CN') }}
                  </template>
                  <template v-else>
                    时间轴：{{ new Date(item.created_at).toLocaleString('zh-CN') }}
                  </template>
                </span>
                <span class="text-[10px] text-slate-600">
                  <template v-if="item.total_message_count">
                    覆盖 {{ Math.round((item.compressed_message_count / item.total_message_count) * 100) }}%
                    （{{ item.compressed_message_count }}/{{ item.total_message_count }}）
                  </template>
                </span>
              </div>
              <p class="mt-2 text-xs text-slate-200 whitespace-pre-wrap leading-relaxed">
                {{ item.summary }}
              </p>
            </div>
          </div>

          <!-- 弹窗底部 -->
          <div class="px-5 py-3 border-t border-slate-800 text-[10px] text-slate-600">
            共 {{ summaryItems.length }} 条摘要快照
          </div>
        </div>
      </div>
    </Teleport>
  </AppLayout>
</template>
