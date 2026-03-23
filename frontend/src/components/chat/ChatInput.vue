<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{
  (e: 'send', text: string): void
}>()

const text = ref('')
const MAX_CHARS = 500

const charCount = computed(() => text.value.length)
const nearLimit = computed(() => charCount.value > MAX_CHARS * 0.8)

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    submit()
  }
}

function submit() {
  const trimmed = text.value.trim()
  if (!trimmed || props.disabled) return
  emit('send', trimmed)
  text.value = ''
}

function autoResize(e: Event) {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}
</script>

<template>
  <div class="border-t border-slate-800 bg-[#0D1526] px-4 py-3">
    <div class="flex gap-2 items-end bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 focus-within:border-amber-500/50 transition-colors">
      <textarea
        v-model="text"
        :disabled="disabled"
        rows="1"
        placeholder="输入问题... (Ctrl+Enter 发送)"
        class="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-500 resize-none focus:outline-none max-h-40 leading-relaxed disabled:opacity-50"
        @keydown="handleKeydown"
        @input="autoResize"
      />

      <div class="flex items-center gap-2 shrink-0">
        <!-- 字数计数 -->
        <span
          v-if="nearLimit"
          :class="['text-[10px]', charCount > MAX_CHARS ? 'text-red-400' : 'text-amber-400']"
        >
          {{ charCount }}/{{ MAX_CHARS }}
        </span>

        <!-- 发送按钮 -->
        <button
          :disabled="!text.trim() || disabled || charCount > MAX_CHARS"
          :class="[
            'w-8 h-8 rounded-lg flex items-center justify-center transition-all',
            text.trim() && !disabled && charCount <= MAX_CHARS
              ? 'bg-amber-500 hover:bg-amber-400 text-black'
              : 'bg-slate-700 text-slate-500 cursor-not-allowed',
          ]"
          title="发送 (Ctrl+Enter)"
          @click="submit"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
    <p class="text-[10px] text-slate-600 mt-1.5 text-right">Ctrl+Enter 发送</p>
  </div>
</template>
