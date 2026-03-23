<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/userStore'
import ColdStartWizard from '@/components/memory/ColdStartWizard.vue'

const router = useRouter()
const userStore = useUserStore()

const showWizard = computed(() => !userStore.coldStartDone)
</script>

<template>
  <!-- 冷启动引导（未完成时直接展示向导） -->
  <ColdStartWizard v-if="showWizard" />

  <!-- 已完成冷启动：欢迎首页 -->
  <div
    v-else
    class="min-h-screen bg-[#0F172A] flex flex-col items-center justify-center p-8"
  >
    <!-- Logo 区 -->
    <div class="text-center mb-12">
      <div class="w-20 h-20 bg-amber-500 rounded-3xl flex items-center justify-center mx-auto mb-5 shadow-lg shadow-amber-500/20">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
          <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
          <polyline points="16 7 22 7 22 13" />
        </svg>
      </div>
      <h1 class="text-3xl font-bold text-slate-100 font-serif mb-2">
        Finance 智投助手
      </h1>
      <p class="text-slate-500 text-sm">
        欢迎回来，{{ userStore.displayName || '投资者' }}
      </p>
    </div>

    <!-- 双模式入口卡片 -->
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-2xl mb-8">
      <!-- 调研报告模式 -->
      <button
        class="group flex flex-col items-start p-6 bg-[#1E293B] border border-slate-700 rounded-2xl hover:border-amber-500/60 hover:bg-[#243044] transition-all duration-200 text-left"
        @click="router.push('/report')"
      >
        <div class="w-10 h-10 bg-amber-500/15 rounded-xl flex items-center justify-center mb-4 group-hover:bg-amber-500/25 transition-colors">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
        </div>
        <h2 class="text-base font-semibold text-slate-200 font-serif mb-1.5 group-hover:text-amber-300 transition-colors">
          调研报告
        </h2>
        <p class="text-xs text-slate-500 leading-relaxed">
          触发完整多 Agent 分析工作流，生成专业投研报告，支持 Markdown 预览与下载
        </p>
        <div class="mt-3 flex flex-wrap gap-1.5">
          <span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-500 rounded-full">基本面</span>
          <span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-500 rounded-full">技术面</span>
          <span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-500 rounded-full">估值</span>
          <span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-500 rounded-full">新闻</span>
        </div>
      </button>

      <!-- 对话模式 -->
      <button
        class="group flex flex-col items-start p-6 bg-[#1E293B] border border-slate-700 rounded-2xl hover:border-amber-500/60 hover:bg-[#243044] transition-all duration-200 text-left"
        @click="router.push('/chat')"
      >
        <div class="w-10 h-10 bg-amber-500/15 rounded-xl flex items-center justify-center mb-4 group-hover:bg-amber-500/25 transition-colors">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        </div>
        <h2 class="text-base font-semibold text-slate-200 font-serif mb-1.5 group-hover:text-amber-300 transition-colors">
          智能对话
        </h2>
        <p class="text-xs text-slate-500 leading-relaxed">
          ChatGPT 风格多轮问答，快速获取投资见解，历史会话管理，常用问题模板一键填充
        </p>
        <div class="mt-3 flex flex-wrap gap-1.5">
          <span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-500 rounded-full">多轮对话</span>
          <span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-500 rounded-full">历史管理</span>
          <span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-500 rounded-full">模板问题</span>
        </div>
      </button>
    </div>

    <!-- 底部提示 -->
    <p class="text-xs text-slate-600">
      v1.2 · Phase 1 · 现有 CLI 工具仍可独立使用
    </p>
  </div>
</template>
