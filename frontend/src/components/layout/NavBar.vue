<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/userStore'
import ModeToggle from './ModeToggle.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const isReport = () => route.name === 'Report'
const isChat = () => route.name === 'Chat'
</script>

<template>
  <header class="h-14 bg-[#0D1526] border-b border-slate-800 flex items-center px-4 gap-4 z-40 flex-shrink-0">
    <!-- Logo -->
    <button
      class="flex items-center gap-2 hover:opacity-80 transition-opacity"
      @click="router.push('/')"
    >
      <div class="w-7 h-7 rounded bg-amber-500 flex items-center justify-center">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
          <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
          <polyline points="16 7 22 7 22 13" />
        </svg>
      </div>
      <span class="text-slate-100 font-semibold text-sm hidden sm:block font-serif">智投助手</span>
    </button>

    <!-- 模式切换 -->
    <div v-if="route.name === 'Report' || route.name === 'Chat'" class="flex-1 flex justify-center">
      <ModeToggle />
    </div>
    <div v-else class="flex-1" />

    <!-- 右侧：持仓入口（预留） + 用户名 -->
    <div class="flex items-center gap-3">
      <button
        class="relative flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-400 transition-colors cursor-not-allowed"
        title="持仓管理（即将推出）"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="2" y="3" width="20" height="14" rx="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
        <span class="hidden sm:block">持仓</span>
        <span class="absolute -top-1 -right-1 bg-amber-500 text-[9px] text-black font-bold px-1 rounded">soon</span>
      </button>

      <div v-if="userStore.displayName" class="text-xs text-slate-400 hidden sm:block">
        {{ userStore.displayName }}
      </div>
    </div>
  </header>
</template>
