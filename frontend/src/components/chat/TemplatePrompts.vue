<script setup lang="ts">
import type { ChatTemplate } from '@/api'

defineProps<{ templates: ChatTemplate[] }>()
const emit = defineEmits<{ (e: 'select', content: string): void }>()

const icons: Record<string, string> = {
  t1: '📊', t2: '⚠️', t3: '💰', t4: '📋', t5: '⚖️', t6: '🎯',
}
</script>

<template>
  <div class="flex flex-col items-center justify-center py-8 px-4">
    <div class="mb-6 text-center">
      <h2 class="text-lg font-semibold text-slate-200 font-serif mb-1">智能投研助手</h2>
      <p class="text-xs text-slate-500">选择常用问题快速开始，或直接输入您的问题</p>
    </div>

    <div class="grid grid-cols-2 gap-2.5 w-full max-w-xl">
      <button
        v-for="t in templates"
        :key="t.id"
        class="flex items-center gap-2.5 text-left px-3.5 py-3 bg-slate-900 border border-slate-700 rounded-xl hover:border-amber-500/50 hover:bg-slate-800 transition-all duration-150 group"
        @click="emit('select', t.content)"
      >
        <span class="text-lg shrink-0">{{ icons[t.id] || '💬' }}</span>
        <div>
          <div class="text-xs font-medium text-slate-300 group-hover:text-amber-300 transition-colors">
            {{ t.label }}
          </div>
          <div class="text-[11px] text-slate-500 mt-0.5 truncate">{{ t.content }}</div>
        </div>
      </button>
    </div>
  </div>
</template>
