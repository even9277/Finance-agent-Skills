<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { SopSkillListItem } from '@/api'

const props = withDefaults(defineProps<{
  disabled?: boolean
  sopSkills?: SopSkillListItem[]
  selectedSopSkill?: SopSkillListItem | null
  sopLoading?: boolean
}>(), {
  disabled: false,
  sopSkills: () => [],
  selectedSopSkill: null,
  sopLoading: false,
})

const emit = defineEmits<{
  (e: 'send', text: string): void
  (e: 'open-sop-panel'): void
  (e: 'select-sop', skillId: string): void
  (e: 'clear-sop'): void
}>()

const text = ref('')
const panelOpen = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const MAX_CHARS = 500

const charCount = computed(() => text.value.length)
const nearLimit = computed(() => charCount.value > MAX_CHARS * 0.8)
const selectedSopLabel = computed(() =>
  props.selectedSopSkill?.official_name || props.selectedSopSkill?.name || ''
)

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    submit()
  }
  if (e.key === 'Escape') {
    panelOpen.value = false
  }
}

function resetTextareaHeight() {
  if (!textareaRef.value) return
  textareaRef.value.style.height = 'auto'
}

function submit() {
  const trimmed = text.value.trim()
  if (!trimmed || props.disabled) return
  emit('send', trimmed)
  text.value = ''
  resetTextareaHeight()
}

function autoResize(e: Event) {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function togglePanel() {
  panelOpen.value = !panelOpen.value
  if (panelOpen.value) {
    emit('open-sop-panel')
  }
}

function selectSop(skillId: string) {
  emit('select-sop', skillId)
  panelOpen.value = false
}

function clearSopSelection() {
  emit('clear-sop')
}

function handleDocumentPointerDown(event: Event) {
  if (!panelOpen.value) return
  const target = event.target as Node | null
  if (rootRef.value && target && !rootRef.value.contains(target)) {
    panelOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
})
</script>

<template>
  <div ref="rootRef" class="border-t border-slate-800 bg-[#0D1526] px-4 py-3">
    <div class="relative">
      <div
        v-if="selectedSopSkill"
        class="mb-2 flex flex-wrap items-center gap-2"
      >
        <span class="inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-[11px] text-amber-200">
          <span class="text-amber-400">SOP</span>
          <span class="max-w-[240px] truncate">{{ selectedSopLabel }}</span>
          <span
            v-if="selectedSopSkill.execution_mode === 'deterministic'"
            class="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-300"
          >
            确定性
          </span>
        </span>
        <button
          type="button"
          class="text-[11px] text-slate-400 transition-colors hover:text-slate-200"
          @click="clearSopSelection"
        >
          清除
        </button>
      </div>

      <div class="flex gap-2 items-end bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 focus-within:border-amber-500/50 transition-colors">
        <button
          type="button"
          :disabled="disabled"
          class="mb-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-700 text-slate-300 transition-colors hover:border-amber-500/50 hover:text-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
          title="选择 SOP 技能"
          @click="togglePanel"
        >
          <span class="text-base leading-none">+</span>
        </button>

        <textarea
          ref="textareaRef"
          v-model="text"
          :disabled="disabled"
          rows="1"
          placeholder="输入问题... (Ctrl+Enter 发送)"
          class="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-500 resize-none focus:outline-none max-h-40 leading-relaxed disabled:opacity-50"
          @keydown="handleKeydown"
          @input="autoResize"
        />

        <div class="flex items-center gap-2 shrink-0">
          <span
            v-if="nearLimit"
            :class="['text-[10px]', charCount > MAX_CHARS ? 'text-red-400' : 'text-amber-400']"
          >
            {{ charCount }}/{{ MAX_CHARS }}
          </span>

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

      <div
        v-if="panelOpen"
        class="absolute bottom-full left-0 z-20 mb-3 w-full max-w-xl overflow-hidden rounded-2xl border border-slate-700 bg-slate-950/95 shadow-2xl backdrop-blur"
      >
        <div class="border-b border-slate-800 px-4 py-3">
          <div class="text-xs font-medium text-slate-200">显式选择 SOP</div>
          <p class="mt-1 text-[11px] text-slate-500">
            选中后本轮消息会直接走对应 skill，不再让路由器决定 SOP。
          </p>
        </div>

        <div v-if="sopLoading" class="px-4 py-5 text-sm text-slate-400">
          正在加载可用技能...
        </div>
        <div v-else-if="!sopSkills.length" class="px-4 py-5 text-sm text-slate-500">
          当前没有可显式选择的 SOP skill。
        </div>
        <div v-else class="max-h-80 overflow-y-auto px-2 py-2">
          <button
            v-for="skill in sopSkills"
            :key="skill.name"
            type="button"
            class="w-full rounded-xl px-3 py-3 text-left transition-colors hover:bg-slate-900"
            @click="selectSop(skill.name)"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="text-sm font-medium text-slate-200">
                  {{ skill.official_name || skill.name }}
                </div>
                <div class="mt-1 text-[11px] text-slate-500">
                  {{ skill.description || skill.name }}
                </div>
              </div>
              <span
                class="shrink-0 rounded-full px-2 py-0.5 text-[10px]"
                :class="skill.execution_mode === 'deterministic'
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : 'bg-sky-500/15 text-sky-300'"
              >
                {{ skill.execution_mode === 'deterministic' ? '确定性' : 'Agentic' }}
              </span>
            </div>
          </button>
        </div>
      </div>
    </div>

    <p class="text-[10px] text-slate-600 mt-1.5 text-right">Ctrl+Enter 发送</p>
  </div>
</template>
