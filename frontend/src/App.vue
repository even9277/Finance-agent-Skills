<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/userStore'
import { useMemory } from '@/composables/useMemory'

const userStore = useUserStore()
const router = useRouter()
const { loadProfile } = useMemory()

onMounted(async () => {
  await userStore.init()
  // Phase 3：应用启动后全局加载用户画像到 memoryStore，确保对话模式和报告模式共享同一份
  if (userStore.userId) {
    await loadProfile()
  }
})
</script>

<template>
  <RouterView />
</template>
