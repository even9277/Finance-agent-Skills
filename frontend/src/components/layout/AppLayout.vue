<script setup lang="ts">
import { ref } from 'vue'
import NavBar from './NavBar.vue'

const props = defineProps<{
  sidebar?: boolean  // 是否显示侧边栏插槽
}>()

const sidebarCollapsed = ref(false)
</script>

<template>
  <div class="flex flex-col h-screen bg-[#0F172A] overflow-hidden">
    <NavBar />
    <div class="flex flex-1 overflow-hidden">
      <!-- 侧边栏插槽 -->
      <aside
        v-if="sidebar"
        :class="[
          'flex-shrink-0 border-r border-slate-800 bg-[#0D1526] transition-all duration-200 overflow-hidden',
          sidebarCollapsed ? 'w-0' : 'w-64',
        ]"
      >
        <slot name="sidebar" />
      </aside>

      <!-- 主内容区 -->
      <main class="flex-1 overflow-hidden flex flex-col">
        <slot />
      </main>

      <!-- 右侧记忆画像插槽（可选）-->
      <aside
        v-if="$slots.memory"
        class="flex-shrink-0 w-64 border-l border-slate-800 bg-[#0D1526] overflow-y-auto"
      >
        <slot name="memory" />
      </aside>
    </div>
  </div>
</template>
