<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import ReportProgress from '@/components/report/ReportProgress.vue'
import ReportRenderer from '@/components/report/ReportRenderer.vue'
import ReportDownload from '@/components/report/ReportDownload.vue'
import ReportPreview from '@/components/report/ReportPreview.vue'
import ReportHistoryList from '@/components/report/ReportHistoryList.vue'
import MemorySidebar from '@/components/memory/MemorySidebar.vue'
import { useReport } from '@/composables/useReport'

const route = useRoute()
const {
  status, progress, report, errorMsg, isGenerating,
  history, previewOpen,
  generateReport, loadHistory, loadReport,
  downloadMarkdown, openPreview, closePreview, deleteReport,
} = useReport()

const command = ref('')

onMounted(async () => {
  await loadHistory()
  // 支持从自选股快捷跳转：?q=600519
  const q = route.query.q as string
  if (q) command.value = q
})

async function handleGenerate() {
  if (!command.value.trim()) return
  await generateReport(command.value.trim())
  await loadHistory()
}

async function handleSelectHistory(id: string) {
  await loadReport(id)
}
</script>

<template>
  <AppLayout :sidebar="true">
    <!-- 左侧：历史报告列表 -->
    <template #sidebar>
      <div class="flex flex-col h-full">
        <div class="px-3 py-2.5 border-b border-slate-800 flex items-center justify-between">
          <span class="text-xs font-semibold text-slate-400">历史报告</span>
          <span class="text-[10px] text-slate-600">{{ history.length }} 条</span>
        </div>
        <ReportHistoryList
          :history="history"
          :current-id="report?.report_id"
          @select="handleSelectHistory"
          @delete="deleteReport"
        />
      </div>
    </template>

    <!-- 主内容区 -->
    <div class="flex flex-col h-full overflow-hidden">
      <!-- 顶部：搜索栏 -->
      <div class="px-4 py-3 border-b border-slate-800 bg-[#0D1526] flex gap-2">
        <div class="flex-1 flex items-center gap-2 bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 focus-within:border-amber-500/50 transition-colors">
          <svg class="text-slate-600 shrink-0" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            v-model="command"
            type="text"
            placeholder="输入股票名称或代码，例如：帮我分析茅台(600519)"
            class="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-500 focus:outline-none"
            @keyup.enter="handleGenerate"
          />
          <button
            v-if="command"
            class="text-slate-600 hover:text-slate-400"
            @click="command = ''"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <button
          :disabled="!command.trim() || isGenerating"
          :class="[
            'flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all',
            command.trim() && !isGenerating
              ? 'bg-amber-500 hover:bg-amber-400 text-black'
              : 'bg-slate-800 text-slate-500 cursor-not-allowed',
          ]"
          @click="handleGenerate"
        >
          <svg v-if="isGenerating" class="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-dasharray="30 60" />
          </svg>
          <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
          </svg>
          {{ isGenerating ? '分析中...' : '生成报告' }}
        </button>
      </div>

      <!-- 内容区：报告或引导 -->
      <div class="flex-1 overflow-y-auto">
        <!-- 生成中：进度条 -->
        <div v-if="isGenerating" class="px-6 pt-6 pb-2">
          <ReportProgress :progress="progress" :status="status" />
          <div class="mt-4 text-center text-xs text-slate-500 animate-pulse">
            正在调用多智能体分析工作流，通常需要 2-5 分钟...
          </div>
        </div>

        <!-- 失败状态 -->
        <div
          v-else-if="status === 'failed'"
          class="m-6 p-4 bg-red-950/50 border border-red-800 rounded-xl"
        >
          <div class="flex items-start gap-3">
            <svg class="text-red-400 shrink-0 mt-0.5" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <div>
              <p class="text-sm text-red-300 font-medium mb-1">报告生成失败</p>
              <p class="text-xs text-red-400/80">{{ errorMsg || '请检查 MCP 服务和 API 配置后重试' }}</p>
            </div>
          </div>
        </div>

        <!-- 报告展示 -->
        <template v-else-if="report?.content">
          <!-- 工具栏 -->
          <ReportDownload
            :report-id="report.report_id"
            :on-download="downloadMarkdown"
            :on-preview="openPreview"
          />
          <!-- Markdown 内容 -->
          <div class="px-6 py-5">
            <ReportRenderer :content="report.content" />
          </div>
        </template>

        <!-- 空态：引导 -->
        <div
          v-else
          class="flex flex-col items-center justify-center h-full py-20 px-8 text-center"
        >
          <div class="w-16 h-16 bg-slate-800 rounded-2xl flex items-center justify-center mb-4">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="1.5">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          </div>
          <p class="text-slate-400 text-sm font-medium mb-1.5 font-serif">输入股票信息生成投研报告</p>
          <p class="text-slate-600 text-xs max-w-sm">
            支持股票名称、代码或自然语言描述，例如：<br />
            「帮我分析茅台(600519)的投资价值」
          </p>
          <div class="mt-5 flex flex-wrap gap-2 justify-center">
            <button
              v-for="eg in ['分析茅台(600519)', '宁德时代(300750)估值怎么样', '帮我看看比亚迪']"
              :key="eg"
              class="text-xs px-3 py-1.5 border border-slate-700 text-slate-500 rounded-full hover:border-amber-500/50 hover:text-amber-400 transition-colors"
              @click="command = eg; handleGenerate()"
            >
              {{ eg }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧：记忆画像侧边栏 -->
    <template #memory>
      <MemorySidebar />
    </template>
  </AppLayout>

  <!-- 全屏预览 -->
  <ReportPreview
    :content="report?.content || ''"
    :open="previewOpen"
    @close="closePreview"
  />
</template>
