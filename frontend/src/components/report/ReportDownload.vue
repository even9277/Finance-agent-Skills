<script setup lang="ts">
defineProps<{
  reportId: string
  onDownload: () => void
  onPreview: () => void
}>()

async function copyContent() {
  const el = document.querySelector('.prose-finance')
  if (el) await navigator.clipboard.writeText(el.textContent || '')
}
</script>

<template>
  <div class="flex items-center gap-2 p-3 border-b border-slate-800 bg-[#0D1526]">
    <span class="text-xs text-slate-500 mr-auto">报告工具栏</span>

    <!-- 复制全文 -->
    <button
      class="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 px-2.5 py-1.5 rounded-md hover:bg-slate-800 transition-colors"
      title="复制全文"
      @click="copyContent"
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="9" y="9" width="13" height="13" rx="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      </svg>
      复制
    </button>

    <!-- 全屏预览 -->
    <button
      class="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 px-2.5 py-1.5 rounded-md hover:bg-slate-800 transition-colors"
      title="全屏预览"
      @click="onPreview"
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
      </svg>
      全屏
    </button>

    <!-- 下载 .md -->
    <button
      class="flex items-center gap-1.5 text-xs bg-amber-500 hover:bg-amber-400 text-black font-medium px-3 py-1.5 rounded-md transition-colors"
      title="下载 Markdown 文件"
      @click="onDownload"
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      下载 .md
    </button>
  </div>
</template>
