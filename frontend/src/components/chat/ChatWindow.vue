<script setup lang="ts">
import { nextTick, watch, ref } from 'vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import type { ChatMessage } from '@/api'

const props = defineProps<{
  messages: ChatMessage[]
  isSending: boolean
  streamingMessageId?: number | null
}>()

const listRef = ref<HTMLElement | null>(null)

// 配置 marked 行内渲染
const renderer = new marked.Renderer()
renderer.code = (code: string, lang?: string) => {
  const validLang = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
  const highlighted = hljs.highlight(code, { language: validLang }).value
  return `<pre class="!my-2"><code class="hljs language-${validLang}">${highlighted}</code></pre>`
}
marked.use({ renderer, breaks: true, gfm: true })

function renderMarkdown(text: string) {
  return marked.parse(text) as string
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    listRef.value?.scrollTo({ top: listRef.value.scrollHeight, behavior: 'smooth' })
  }
)
</script>

<template>
  <div ref="listRef" class="flex-1 overflow-y-auto px-4 py-4 space-y-4">
    <div
      v-for="msg in messages"
      :key="msg.id"
      :class="['flex gap-3 animate-fade-in', msg.role === 'user' ? 'flex-row-reverse' : 'flex-row']"
    >
      <!-- 头像 -->
      <div
        :class="[
          'w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold mt-0.5',
          msg.role === 'user'
            ? 'bg-amber-500 text-black'
            : 'bg-slate-700 text-slate-200',
        ]"
      >
        {{ msg.role === 'user' ? 'U' : '🤖' }}
      </div>

      <!-- 气泡 -->
      <div :class="['group flex flex-col', msg.role === 'user' ? 'items-end' : 'items-start']" style="max-width:75%">
        <div
          :class="[
            'px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed',
            msg.role === 'user'
              ? 'bg-amber-500 text-black rounded-tr-sm'
              : 'bg-slate-800 text-slate-200 rounded-tl-sm prose-finance',
          ]"
        >
          <!-- 流式消息：内容为空时显示等待光标，有内容时渲染 Markdown + 光标 -->
          <template v-if="msg.role === 'assistant'">
            <div
              v-if="msg.content"
              class="prose-finance"
              v-html="renderMarkdown(msg.content)"
            />
            <!-- 流式光标（仅对正在流式输出的消息显示） -->
            <span
              v-if="streamingMessageId === msg.id"
              class="inline-block w-0.5 h-4 bg-amber-400 animate-blink ml-0.5 align-middle"
            />
            <!-- 等待首个 token：显示三点 -->
            <div
              v-if="streamingMessageId === msg.id && !msg.content"
              class="flex gap-1 items-center h-4"
            >
              <span
                v-for="i in 3"
                :key="i"
                class="w-1.5 h-1.5 bg-slate-400 rounded-full animate-pulse-dot"
                :style="{ animationDelay: `${(i - 1) * 0.16}s` }"
              />
            </div>
          </template>
          <span v-else>{{ msg.content }}</span>
        </div>

        <!-- 时间戳（hover 显示）-->
        <span class="text-[10px] text-slate-600 mt-1 opacity-0 group-hover:opacity-100 transition-opacity px-1">
          {{ formatTime(msg.created_at) }}
          <span v-if="msg.is_compressed" class="ml-1 text-amber-500/60">[已压缩]</span>
        </span>
      </div>
    </div>

    <!-- AI 回复加载动画 -->
    <div v-if="isSending" class="flex gap-3 animate-fade-in">
      <div class="w-7 h-7 rounded-full bg-slate-700 flex items-center justify-center text-xs shrink-0 mt-0.5">🤖</div>
      <div class="bg-slate-800 px-4 py-3 rounded-2xl rounded-tl-sm">
        <div class="flex gap-1 items-center h-4">
          <span
            v-for="i in 3"
            :key="i"
            class="w-1.5 h-1.5 bg-slate-400 rounded-full animate-pulse-dot"
            :style="{ animationDelay: `${(i - 1) * 0.16}s` }"
          />
        </div>
      </div>
    </div>
  </div>
</template>
