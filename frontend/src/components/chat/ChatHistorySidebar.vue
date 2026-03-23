<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ChatSession } from '@/api'

const props = defineProps<{
  sessions: ChatSession[]
  currentId: string | null
}>()

const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'new'): void
  (e: 'delete', id: string): void
  (e: 'rename', id: string, title: string): void
}>()

const searchQ = ref('')
const renamingId = ref<string | null>(null)
const renameValue = ref('')

const filtered = computed(() => {
  if (!searchQ.value.trim()) return props.sessions
  const q = searchQ.value.toLowerCase()
  return props.sessions.filter(
    (s) => s.title?.toLowerCase().includes(q)
  )
})

function startRename(session: ChatSession) {
  renamingId.value = session.session_id
  renameValue.value = session.title || ''
}

function confirmRename(id: string) {
  if (renameValue.value.trim()) {
    emit('rename', id, renameValue.value.trim())
  }
  renamingId.value = null
}

function formatDate(d: string) {
  const date = new Date(d)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - date.getTime()) / 86400000)
  if (diffDays === 0) return '今天'
  if (diffDays === 1) return '昨天'
  if (diffDays < 7) return `${diffDays}天前`
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 顶部：新建 + 搜索 -->
    <div class="p-3 space-y-2 border-b border-slate-800">
      <button
        class="w-full flex items-center justify-center gap-2 py-2 bg-amber-500 hover:bg-amber-400 text-black text-xs font-semibold rounded-lg transition-colors"
        @click="emit('new')"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
        </svg>
        新建对话
      </button>
      <input
        v-model="searchQ"
        type="text"
        placeholder="搜索对话..."
        class="w-full bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-300 placeholder-slate-500 focus:outline-none focus:border-amber-500/60 transition-colors"
      />
    </div>

    <!-- 会话列表 -->
    <div class="flex-1 overflow-y-auto">
      <div
        v-for="session in filtered"
        :key="session.session_id"
        :class="[
          'group flex items-start gap-2 px-3 py-2.5 cursor-pointer transition-colors',
          currentId === session.session_id
            ? 'bg-amber-500/10 border-l-2 border-l-amber-500'
            : 'border-l-2 border-l-transparent hover:bg-slate-800/60',
        ]"
        @click="emit('select', session.session_id)"
      >
        <svg class="mt-0.5 shrink-0 text-slate-600" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>

        <div class="flex-1 min-w-0">
          <!-- 重命名输入 -->
          <div v-if="renamingId === session.session_id" class="flex gap-1" @click.stop>
            <input
              v-model="renameValue"
              class="flex-1 bg-slate-700 border border-amber-500/50 rounded px-1.5 py-0.5 text-xs text-slate-100 focus:outline-none"
              @keyup.enter="confirmRename(session.session_id)"
              @keyup.esc="renamingId = null"
              @blur="confirmRename(session.session_id)"
            />
          </div>
          <div v-else>
            <p class="text-xs text-slate-200 truncate">
              {{ session.title || '新对话' }}
            </p>
            <p class="text-[10px] text-slate-600 mt-0.5">{{ formatDate(session.updated_at) }}</p>
          </div>
        </div>

        <!-- 操作按钮（hover 显示） -->
        <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
          <button
            class="p-0.5 text-slate-500 hover:text-slate-300 transition-colors"
            title="重命名"
            @click.stop="startRename(session)"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
          </button>
          <button
            class="p-0.5 text-slate-500 hover:text-red-400 transition-colors"
            title="删除"
            @click.stop="emit('delete', session.session_id)"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
            </svg>
          </button>
        </div>
      </div>

      <div v-if="!filtered.length" class="text-center py-10 text-slate-600 text-xs">
        {{ searchQ ? '无匹配对话' : '暂无对话记录' }}
      </div>
    </div>
  </div>
</template>
