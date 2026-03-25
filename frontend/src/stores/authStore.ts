import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ACCESS_TOKEN_KEY, AUTH_USER_KEY, authApi, type AuthUser } from '@/api'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string>('')
  const currentUser = ref<AuthUser | null>(null)
  const initialized = ref(false)
  const loading = ref(false)

  const isAuthenticated = computed(() => !!accessToken.value && !!currentUser.value)

  function _persist() {
    if (accessToken.value) {
      localStorage.setItem(ACCESS_TOKEN_KEY, accessToken.value)
    } else {
      localStorage.removeItem(ACCESS_TOKEN_KEY)
    }
    if (currentUser.value) {
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(currentUser.value))
    } else {
      localStorage.removeItem(AUTH_USER_KEY)
    }
  }

  function _loadFromStorage() {
    accessToken.value = localStorage.getItem(ACCESS_TOKEN_KEY) || ''
    const raw = localStorage.getItem(AUTH_USER_KEY)
    if (!raw) {
      currentUser.value = null
      return
    }
    try {
      currentUser.value = JSON.parse(raw) as AuthUser
    } catch {
      currentUser.value = null
      localStorage.removeItem(AUTH_USER_KEY)
    }
  }

  function applyAuth(payload: AuthUser, token: string) {
    currentUser.value = payload
    accessToken.value = token
    _persist()
  }

  function updateUserPatch(patch: Partial<AuthUser>) {
    if (!currentUser.value) return
    currentUser.value = { ...currentUser.value, ...patch }
    _persist()
  }

  async function init() {
    if (initialized.value) return
    _loadFromStorage()
    if (!accessToken.value) {
      initialized.value = true
      return
    }
    try {
      const { data } = await authApi.me()
      currentUser.value = data
      _persist()
    } catch {
      clearAuth()
    } finally {
      initialized.value = true
    }
  }

  async function login(username: string, password: string) {
    loading.value = true
    try {
      const { data } = await authApi.login(username, password)
      applyAuth(
        {
          user_id: data.user_id,
          username: data.username,
          display_name: data.display_name,
          cold_start_done: data.cold_start_done,
          created_at: data.created_at,
        },
        data.access_token,
      )
      initialized.value = true
      return data
    } finally {
      loading.value = false
    }
  }

  async function register(username: string, password: string, displayName?: string) {
    loading.value = true
    try {
      const { data } = await authApi.register({
        username,
        password,
        display_name: displayName,
      })
      applyAuth(
        {
          user_id: data.user_id,
          username: data.username,
          display_name: data.display_name,
          cold_start_done: data.cold_start_done,
          created_at: data.created_at,
        },
        data.access_token,
      )
      initialized.value = true
      return data
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      if (accessToken.value) {
        await authApi.logout()
      }
    } catch {
      // 退出登录失败不阻塞本地清理
    } finally {
      clearAuth()
      initialized.value = true
    }
  }

  function clearAuth() {
    accessToken.value = ''
    currentUser.value = null
    _persist()
  }

  return {
    accessToken,
    currentUser,
    initialized,
    loading,
    isAuthenticated,
    init,
    login,
    register,
    logout,
    clearAuth,
    updateUserPatch,
  }
})
