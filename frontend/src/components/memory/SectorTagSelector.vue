<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ selected: string[]; readonly?: boolean }>()
const emit = defineEmits<{ (e: 'update', val: string[]): void }>()

const BUILTIN_TAGS = [
  '科技/半导体', '消费/白酒', '金融/银行', '医疗/医药',
  '能源/煤炭', '新能源/电动车', '红利/央国企', '黄金/贵金属',
  'AI/大模型', '房地产', '军工', '农业',
]

const customInput = ref('')

function toggle(tag: string) {
  if (props.readonly) return
  const next = props.selected.includes(tag)
    ? props.selected.filter((t) => t !== tag)
    : [...props.selected, tag]
  emit('update', next)
}

function addCustom() {
  const tag = customInput.value.trim()
  if (!tag || props.selected.includes(tag)) { customInput.value = ''; return }
  emit('update', [...props.selected, tag])
  customInput.value = ''
}
</script>

<template>
  <div>
    <p class="text-xs text-slate-500 mb-3">关注板块</p>
    <div class="flex flex-wrap gap-1.5 mb-2">
      <button
        v-for="tag in BUILTIN_TAGS"
        :key="tag"
        :disabled="readonly"
        :class="[
          'text-[11px] px-2 py-1 rounded-md border transition-all',
          selected.includes(tag)
            ? 'bg-amber-500/20 border-amber-500 text-amber-300'
            : 'border-slate-700 text-slate-500 hover:border-slate-500 hover:text-slate-300',
          readonly ? 'cursor-default' : 'cursor-pointer',
        ]"
        @click="toggle(tag)"
      >
        {{ tag }}
      </button>
    </div>

    <!-- 自定义输入 -->
    <div v-if="!readonly" class="flex gap-1.5 mt-2">
      <input
        v-model="customInput"
        type="text"
        placeholder="自定义板块..."
        class="flex-1 bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-amber-500/50"
        @keyup.enter="addCustom"
      />
      <button
        class="px-2.5 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded-md transition-colors"
        @click="addCustom"
      >添加</button>
    </div>

    <!-- 已选自定义标签 -->
    <div v-if="selected.some(t => !BUILTIN_TAGS.includes(t))" class="flex flex-wrap gap-1.5 mt-2">
      <span
        v-for="tag in selected.filter(t => !BUILTIN_TAGS.includes(t))"
        :key="tag"
        class="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md bg-blue-500/20 border border-blue-500/50 text-blue-300"
      >
        {{ tag }}
        <button v-if="!readonly" class="hover:text-white" @click="toggle(tag)">✕</button>
      </span>
    </div>
  </div>
</template>
