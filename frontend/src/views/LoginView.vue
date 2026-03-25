<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useUserStore } from '@/stores/userStore'
import { useMemory } from '@/composables/useMemory'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const userStore = useUserStore()
const { loadProfile } = useMemory()
const isSwitchMode = computed(() => route.query.switch === '1')
const mode = ref<'login' | 'register'>(
  route.query.mode === 'register' ? 'register' : 'login'
)

const username = ref('test1')
const password = ref('test1')
const displayName = ref('')
const confirmPassword = ref('')
const errorMessage = ref('')
const canSubmit = computed(() => {
  if (authStore.loading) return false
  if (!username.value.trim() || !password.value.trim()) return false
  if (mode.value === 'register') {
    return password.value === confirmPassword.value && password.value.length >= 6
  }
  return true
})

watch(
  () => route.query.mode,
  (value) => {
    mode.value = value === 'register' ? 'register' : 'login'
    errorMessage.value = ''
  }
)

async function handleSubmit() {
  if (!canSubmit.value) return
  errorMessage.value = ''
  try {
    if (mode.value === 'register') {
      if (password.value !== confirmPassword.value) {
        errorMessage.value = '两次输入的密码不一致'
        return
      }
      await authStore.register(
        username.value.trim(),
        password.value,
        displayName.value.trim() || username.value.trim(),
      )
    } else {
      await authStore.login(username.value.trim(), password.value)
    }
    await userStore.init()
    if (userStore.userId) {
      await loadProfile()
    }
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '登录失败，请稍后重试'
  }
}

function fillDemoAccount(name: 'test1' | 'test2') {
  username.value = name
  password.value = name
  confirmPassword.value = name
  displayName.value = name
  mode.value = 'login'
}

function switchMode(nextMode: 'login' | 'register') {
  mode.value = nextMode
  errorMessage.value = ''
  if (nextMode === 'login') {
    confirmPassword.value = ''
  } else if (!displayName.value.trim()) {
    displayName.value = username.value.trim()
  }
}
</script>

<template>
  <div class="min-h-screen bg-[#0F172A] flex items-center justify-center p-4">
    <div class="w-full max-w-md bg-[#1E293B] border border-slate-700 rounded-2xl p-8 shadow-2xl">
      <div class="text-center mb-6">
        <div class="w-14 h-14 bg-amber-500 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
            <polyline points="16 7 22 7 22 13" />
          </svg>
        </div>
        <h1 class="text-2xl font-bold text-slate-100 font-serif">
          {{ mode === 'register' ? '注册智投助手账号' : '登录智投助手' }}
        </h1>
        <p class="text-slate-500 text-sm mt-2">
          {{
            isSwitchMode && mode === 'login'
              ? '请选择要切换登录的账号'
              : mode === 'register'
                ? '新账号注册后会直接进入原有冷启动流程，继续体验对话、报告、记忆与画像能力'
                : '登录后即可继续使用对话、报告、记忆与画像功能'
          }}
        </p>
      </div>

      <div class="mb-6 rounded-xl bg-slate-900/60 p-1 grid grid-cols-2 gap-1">
        <button
          type="button"
          class="px-3 py-2 rounded-lg text-sm font-medium transition-colors"
          :class="mode === 'login' ? 'bg-amber-500 text-black' : 'text-slate-300 hover:text-slate-100'"
          @click="switchMode('login')"
        >
          登录
        </button>
        <button
          type="button"
          class="px-3 py-2 rounded-lg text-sm font-medium transition-colors"
          :class="mode === 'register' ? 'bg-amber-500 text-black' : 'text-slate-300 hover:text-slate-100'"
          @click="switchMode('register')"
        >
          注册
        </button>
      </div>

      <form class="space-y-4" @submit.prevent="handleSubmit">
        <div>
          <label class="text-xs text-slate-400 block mb-1.5">用户名</label>
          <input
            v-model="username"
            type="text"
            autocomplete="username"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-amber-500/60 transition-colors"
            placeholder="请输入用户名"
          />
          <p v-if="mode === 'register'" class="text-[11px] text-slate-500 mt-1">
            建议使用 3-32 位字母、数字、下划线或短横线。
          </p>
        </div>

        <div v-if="mode === 'register'">
          <label class="text-xs text-slate-400 block mb-1.5">显示名称</label>
          <input
            v-model="displayName"
            type="text"
            autocomplete="nickname"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-amber-500/60 transition-colors"
            placeholder="可选，不填则默认使用用户名"
          />
        </div>

        <div>
          <label class="text-xs text-slate-400 block mb-1.5">密码</label>
          <input
            v-model="password"
            type="password"
            :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-amber-500/60 transition-colors"
            placeholder="请输入密码"
          />
        </div>

        <div v-if="mode === 'register'">
          <label class="text-xs text-slate-400 block mb-1.5">确认密码</label>
          <input
            v-model="confirmPassword"
            type="password"
            autocomplete="new-password"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-amber-500/60 transition-colors"
            placeholder="请再次输入密码"
          />
        </div>

        <p v-if="errorMessage" class="text-xs text-red-400">{{ errorMessage }}</p>
        <p v-else-if="mode === 'register' && password && confirmPassword && password !== confirmPassword" class="text-xs text-amber-400">
          两次输入的密码暂时不一致
        </p>

        <button
          type="submit"
          :disabled="!canSubmit"
          class="w-full px-4 py-2.5 rounded-lg text-sm font-semibold transition-all"
          :class="canSubmit ? 'bg-amber-500 hover:bg-amber-400 text-black' : 'bg-slate-700 text-slate-500 cursor-not-allowed'"
        >
          {{
            authStore.loading
              ? (mode === 'register' ? '注册中...' : '登录中...')
              : (mode === 'register' ? '注册并进入系统' : '登录')
          }}
        </button>
      </form>

      <div class="mt-6 pt-4 border-t border-slate-700">
        <div class="flex items-center justify-between gap-3 mb-2">
          <p class="text-xs text-slate-500">测试账号</p>
          <button
            v-if="mode === 'register'"
            type="button"
            class="text-xs text-amber-300 hover:text-amber-200 transition-colors"
            @click="switchMode('login')"
          >
            返回测试账号登录
          </button>
        </div>
        <div class="flex gap-2">
          <button
            type="button"
            class="flex-1 px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-xs text-slate-300 hover:border-amber-500/40 hover:text-amber-300 transition-colors"
            @click="fillDemoAccount('test1')"
          >
            test1 / test1
          </button>
          <button
            type="button"
            class="flex-1 px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-xs text-slate-300 hover:border-amber-500/40 hover:text-amber-300 transition-colors"
            @click="fillDemoAccount('test2')"
          >
            test2 / test2
          </button>
        </div>
        <p class="text-[11px] text-slate-500 mt-3">
          想体验全新账号流程时，可以直接切到“注册”，系统会为你创建独立用户并保留后续对话、报告和画像数据。
        </p>
      </div>
    </div>
  </div>
</template>
