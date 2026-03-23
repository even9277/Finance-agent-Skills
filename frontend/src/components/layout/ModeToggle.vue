<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const isReport = () => route.name === 'Report'
const isChat = () => route.name === 'Chat'
</script>

<template>
  <div class="flex items-center bg-slate-900 border border-slate-700 rounded-lg p-0.5 gap-0.5">
    <button
      :class="[
        'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200',
        isReport()
          ? 'bg-amber-500 text-black shadow-sm'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
      ]"
      @click="router.push('/report')"
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
      调研报告
    </button>
    <button
      :class="[
        'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200',
        isChat()
          ? 'bg-amber-500 text-black shadow-sm'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
      ]"
      @click="router.push('/chat')"
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
      对话
    </button>
  </div>
</template>
