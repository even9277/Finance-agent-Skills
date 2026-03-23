<script setup lang="ts">
const props = defineProps<{ value?: string; readonly?: boolean }>()
const emit = defineEmits<{ (e: 'update', val: string): void }>()

const options = [
  { id: 'conservative', label: '保守', desc: '最大回撤约 10% 以内', color: 'from-emerald-600 to-emerald-500', ring: 'ring-emerald-500' },
  { id: 'balanced_conservative', label: '稳健', desc: '最大回撤约 20%', color: 'from-teal-600 to-teal-500', ring: 'ring-teal-500' },
  { id: 'balanced', label: '平衡', desc: '最大回撤约 30%', color: 'from-blue-600 to-blue-500', ring: 'ring-blue-500' },
  { id: 'aggressive', label: '进取', desc: '最大回撤约 40%', color: 'from-orange-600 to-orange-500', ring: 'ring-orange-500' },
  { id: 'very_aggressive', label: '激进', desc: '最大回撤 40%+', color: 'from-red-600 to-red-500', ring: 'ring-red-500' },
]
</script>

<template>
  <div class="space-y-2">
    <p class="text-xs text-slate-500 mb-3">风险偏好</p>
    <div class="grid grid-cols-1 gap-1.5">
      <button
        v-for="opt in options"
        :key="opt.id"
        :disabled="readonly"
        :class="[
          'flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-all text-left',
          value === opt.id
            ? `bg-gradient-to-r ${opt.color} border-transparent ring-1 ${opt.ring} text-white`
            : 'border-slate-700 bg-slate-900/50 text-slate-400 hover:border-slate-600 hover:text-slate-300',
          readonly ? 'cursor-default' : 'cursor-pointer',
        ]"
        @click="!readonly && emit('update', opt.id)"
      >
        <div
          :class="[
            'w-2 h-2 rounded-full shrink-0',
            value === opt.id ? 'bg-white' : 'bg-slate-600',
          ]"
        />
        <div class="flex-1 min-w-0">
          <div class="text-xs font-medium">{{ opt.label }}</div>
          <div class="text-[10px] opacity-70 truncate">{{ opt.desc }}</div>
        </div>
        <span v-if="value === opt.id" class="text-white text-xs">✓</span>
      </button>
    </div>
  </div>
</template>
