<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import ReportRenderer from './ReportRenderer.vue'

const props = defineProps<{ content: string; open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

function handleKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => document.addEventListener('keydown', handleKey))
onUnmounted(() => document.removeEventListener('keydown', handleKey))
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-start justify-center p-6 overflow-y-auto"
        @click.self="emit('close')"
      >
        <div class="w-full max-w-4xl bg-[#0F172A] border border-slate-700 rounded-xl shadow-2xl animate-fade-in">
          <!-- 顶栏 -->
          <div class="flex items-center justify-between px-6 py-3 border-b border-slate-800">
            <h2 class="text-sm font-medium text-slate-300 font-serif">报告预览</h2>
            <button
              class="text-slate-500 hover:text-slate-200 transition-colors p-1"
              @click="emit('close')"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
          <!-- 内容 -->
          <div class="p-6 md:p-10">
            <ReportRenderer :content="content" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
