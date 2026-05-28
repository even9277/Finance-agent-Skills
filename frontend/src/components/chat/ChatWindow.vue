<script setup lang="ts">
import { nextTick, watch, ref } from 'vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import type { ChatMessage, ChatRouteSummary } from '@/api'
import PlanPreviewCard from './PlanPreviewCard.vue'
import StepStatusList from './StepStatusList.vue'

const props = defineProps<{
  messages: ChatMessage[]
  isSending: boolean
  streamingMessageId?: number | null
  debugMode?: boolean
}>()

const listRef = ref<HTMLElement | null>(null)

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

// FIX-7: user-facing skill label (prefers user_facing.skill_label when available)
function routeSummaryTitle(summary?: ChatRouteSummary | null) {
  if (!summary) return ''
  if (summary.user_facing?.skill_label) return summary.user_facing.skill_label
  if (summary.skill_name) return summary.skill_name
  if (summary.selected_skill === 'fallback') return '普通对话'
  return summary.selected_skill
}

function routeModeLabel(summary?: ChatRouteSummary | null) {
  if (!summary) return ''
  const mode = summary.user_facing?.analysis_mode || summary.analysis_mode
  const modeMap: Record<string, string> = {
    general_chat: '通用问答',
    single_stock_data: '单股数据',
    single_stock_fundamental: '单股投研',
    sector_market: '板块行业',
    stock_selection: '选股筛选',
  }
  return modeMap[mode] || mode
}

// FIX-7: evidence status for user-facing display
function evidenceLabel(summary?: ChatRouteSummary | null) {
  if (!summary) return ''
  const status = summary.user_facing?.evidence_status
  if (status === 'ok') return '数据已验证'
  if (status === 'partial') return '部分数据'
  if (status === 'missing') return '数据待补强'
  return summary.evidence_ok ? '证据已校验' : '证据待补强'
}

function evidenceIsOk(summary?: ChatRouteSummary | null) {
  if (!summary) return false
  if (summary.user_facing?.evidence_status) return summary.user_facing.evidence_status === 'ok'
  return summary.evidence_ok
}

// FIX-7: failure hint for user-facing
function failureHintLabel(summary?: ChatRouteSummary | null) {
  if (!summary?.user_facing?.failure_hint) return ''
  const hintMap: Record<string, string> = {
    symbol_resolution_failed: '未识别到标的',
    tool_timeout: '数据源暂不可用',
    tool_auth_failed: '数据源暂不可用',
    tool_empty_payload: '当前暂无数据',
    insufficient_evidence: '数据不足以支持完整分析',
    wrong_mode_or_policy: '当前暂无数据',
  }
  return hintMap[summary.user_facing.failure_hint] || ''
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

        <PlanPreviewCard
          v-if="msg.role === 'assistant' && msg.plan_preview?.length"
          :items="msg.plan_preview"
        />

        <StepStatusList
          v-if="msg.role === 'assistant' && (msg.step_statuses?.length || msg.verification_summary)"
          :steps="msg.step_statuses"
          :verification="msg.verification_summary"
        />

        <!-- FIX-7: user-facing route summary (always shown) -->
        <div
          v-if="msg.role === 'assistant' && msg.route_summary"
          class="mt-2 max-w-full rounded-xl border border-slate-700/70 bg-slate-900/80 px-3 py-2 text-[11px] text-slate-300"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-slate-500">本轮路由</span>
            <span class="rounded-full bg-sky-500/15 px-2 py-0.5 text-sky-300">
              {{ routeSummaryTitle(msg.route_summary) }}
            </span>
            <span class="rounded-full bg-slate-700 px-2 py-0.5 text-slate-300">
              {{ routeModeLabel(msg.route_summary) }}
            </span>
            <span class="rounded-full px-2 py-0.5" :class="evidenceIsOk(msg.route_summary) ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'">
              {{ evidenceLabel(msg.route_summary) }}
            </span>
          </div>

          <!-- FIX-9: user-facing failure hint -->
          <div
            v-if="failureHintLabel(msg.route_summary)"
            class="mt-2 rounded-lg bg-amber-500/10 px-2 py-1.5 text-amber-200"
          >
            {{ failureHintLabel(msg.route_summary) }}
          </div>

          <div class="mt-2 flex flex-wrap items-center gap-2">
            <span class="text-slate-500">工具调用</span>
            <template v-if="msg.route_summary.tools_used?.length">
              <span
                v-for="tool in msg.route_summary.tools_used"
                :key="tool"
                class="rounded-full bg-emerald-500/10 px-2 py-0.5 text-emerald-300"
              >
                {{ tool }}
              </span>
            </template>
            <template v-else-if="msg.route_summary.tools_attempted?.length">
              <span
                v-for="tool in msg.route_summary.tools_attempted"
                :key="tool"
                class="rounded-full bg-slate-700 px-2 py-0.5 text-slate-300"
              >
                {{ tool }}
              </span>
            </template>
            <span v-else class="text-slate-500">未调用外部工具</span>
          </div>

          <!-- FIX-7: debug panel (only shown in debug mode) -->
          <div
            v-if="debugMode && msg.route_summary.debug"
            class="mt-2 rounded-lg border border-slate-800 bg-slate-950/60 px-2 py-2 space-y-1 text-[10px] text-slate-500"
          >
            <div class="text-slate-400 font-semibold mb-1">调试信息</div>
            <div>route_kind: {{ msg.route_summary.debug.route_kind }}</div>
            <div>grounding_policy: {{ msg.route_summary.debug.grounding_policy }}</div>
            <div>claim_policy: {{ msg.route_summary.debug.claim_policy }}</div>
            <div v-if="msg.route_summary.debug.skill_contract">skill_contract: {{ msg.route_summary.debug.skill_contract }}</div>
            <div v-if="msg.route_summary.debug.evidence_tier">evidence_tier: {{ msg.route_summary.debug.evidence_tier }}</div>
            <div v-if="msg.route_summary.debug.evidence_missing_dimensions?.length">missing: {{ msg.route_summary.debug.evidence_missing_dimensions.join(', ') }}</div>
            <div v-if="msg.route_summary.debug.failure_code">failure_code: {{ msg.route_summary.debug.failure_code }}</div>
            <div>confidence: {{ Number(msg.route_summary.route_confidence || 0).toFixed(2) }}</div>
            <div>execution_policy: {{ msg.route_summary.execution_policy || 'agentic' }}</div>
          </div>

          <!-- Non-debug: minimal footer -->
          <div v-if="!debugMode" class="mt-2 flex flex-wrap items-center gap-3 text-slate-500">
            <span>置信度: {{ Number(msg.route_summary.route_confidence || 0).toFixed(2) }}</span>
          </div>

          <div
            v-if="msg.route_summary.notes?.length"
            class="mt-2 rounded-lg bg-amber-500/10 px-2 py-1.5 text-amber-200"
          >
            {{ msg.route_summary.notes.join('；') }}
          </div>
        </div>
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
