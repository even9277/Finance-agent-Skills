/**
 * Axios 实例 + 全部 API 函数
 * 接口契约与 backend/schemas/ 保持一致
 */

import axios from 'axios'

export const ACCESS_TOKEN_KEY = 'finance_access_token'
export const AUTH_USER_KEY = 'finance_auth_user'

// ─────────────────────────────────────────────────────────────
// Axios 实例
// ─────────────────────────────────────────────────────────────
export const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(ACCESS_TOKEN_KEY)
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(msg))
  }
)

// ─────────────────────────────────────────────────────────────
// 类型定义（与 backend/schemas 对应）
// ─────────────────────────────────────────────────────────────
export interface ReportTaskResponse {
  task_id: string
  report_id: string
  status: string
}

export interface ReportStatusResponse {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  report_id?: string
  error_msg?: string
}

export interface ReportDetail {
  report_id: string
  task_id: string
  stock_code?: string
  company_name?: string
  content?: string
  status: string
  progress: number
  created_at: string
}

export interface ReportListItem {
  report_id: string
  stock_code?: string
  company_name?: string
  status: string
  progress: number
  created_at: string
}

export interface ChatMessageResponse {
  reply: string
  session_id: string
  // Phase 3：本次对话参考的用户画像（null 表示 ENABLE_MEMORY=false 或未设置）
  memory_profile?: MemoryProfile | null
}

export interface ChatSession {
  session_id: string
  mode: string
  title?: string
  running_summary?: string
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: number
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  is_compressed: boolean
  created_at: string
}

export interface ChatTemplate {
  id: string
  label: string
  content: string
}

export interface ChatSummaryItem {
  id: number
  session_id: string
  summary: string
  compressed_message_count: number
  total_message_count: number
  // Phase 2.1：更直观的压缩快照展示（后端兼容旧数据，前端用可选字段）
  compressed_user_count?: number | null
  compressed_assistant_count?: number | null
  start_message_id?: number | null
  end_message_id?: number | null
  start_created_at?: string | null
  end_created_at?: string | null
  created_at: string
}

export interface ChatSessionSummaries {
  session_id: string
  items: ChatSummaryItem[]
}

export interface UserProfile {
  user_id: string
  display_name?: string
  cold_start_done: boolean
  created_at: string
}

export interface AuthUser {
  user_id: string
  username: string
  display_name?: string
  cold_start_done: boolean
  created_at: string
}

export interface AuthLoginResponse extends AuthUser {
  access_token: string
  token_type: 'bearer'
}

export interface AuthRegisterRequest {
  username: string
  password: string
  display_name?: string
}

export interface MemoryProfile {
  // Phase 1 兼容字段
  risk_profile?: string
  sectors: string[]
  return_expectation?: number
  investment_horizon?: string
  watchlist: string[]
  // Phase 3 扩展字段
  risk_level?: string
  expected_return_min?: number
  expected_return_max?: number
  constraints?: string[]
  response_pref?: string
  updated_by?: string
  updated_at?: string
}

export interface MemoryItem {
  id: string
  content: string
  category: string
  source: string
  confidence: number
  evidence_ref: string
  /** 创建时间（ISO8601）；后端保证字段存在，缺失解析时为空串 */
  created_at: string
  metadata: Record<string, unknown>
}

export interface MemoryStats {
  from_conversations: number
  from_reports: number
  from_manual: number
  total_tasks: number
}

export interface MemoryProfileApiResponse {
  user_id: string
  profile: MemoryProfile
  total_memories: number
  stats: MemoryStats
  note: string
}

// ─────────────────────────────────────────────────────────────
// 报告 API
// ─────────────────────────────────────────────────────────────
export const reportApi = {
  generate: (command: string, userId: string) =>
    http.post<ReportTaskResponse>('/report/generate', { command, user_id: userId }),

  getStatus: (taskId: string) =>
    http.get<ReportStatusResponse>(`/report/status/${taskId}`),

  getReport: (reportId: string) =>
    http.get<ReportDetail>(`/report/${reportId}`),

  getDownloadUrl: (reportId: string) => `/api/report/${reportId}/download`,

  listHistory: (userId: string, q?: string) =>
    http.get<ReportListItem[]>('/report/history', { params: { user_id: userId, q } }),

  deleteReport: (reportId: string) =>
    http.delete(`/report/${reportId}`),
}

// ─────────────────────────────────────────────────────────────
// 对话 API
// ─────────────────────────────────────────────────────────────
export const chatApi = {
  sendMessage: (userId: string, message: string, sessionId?: string) =>
    http.post<ChatMessageResponse>('/chat/message', {
      user_id: userId,
      message,
      session_id: sessionId,
    }),

  listSessions: (userId: string, q?: string) =>
    http.get<ChatSession[]>('/chat/sessions', { params: { user_id: userId, q } }),

  renameSession: (sessionId: string, userId: string, title: string) =>
    http.patch(`/chat/sessions/${sessionId}`, { title }, { params: { user_id: userId } }),

  deleteSession: (sessionId: string, userId: string) =>
    http.delete(`/chat/sessions/${sessionId}`, { params: { user_id: userId } }),

  getMessages: (sessionId: string, userId: string) =>
    http.get<{ session_id: string; messages: ChatMessage[] }>(
      `/chat/sessions/${sessionId}/messages`,
      { params: { user_id: userId } }
    ),

  getSummaries: (sessionId: string, userId: string) =>
    http.get<ChatSessionSummaries>(`/chat/sessions/${sessionId}/summaries`, { params: { user_id: userId } }),

  getTemplates: () => http.get<ChatTemplate[]>('/chat/templates'),
}

// ─────────────────────────────────────────────────────────────
// 用户 API
// ─────────────────────────────────────────────────────────────
export const userApi = {
  init: (userId: string, displayName?: string, preferences?: Record<string, unknown>) =>
    http.post<UserProfile>('/user/init', {
      user_id: userId,
      display_name: displayName,
      preferences,
    }),

  getProfile: (userId: string) =>
    http.get<UserProfile>('/user/profile', { params: { user_id: userId } }),

  updateProfile: (userId: string, displayName?: string) =>
    http.put('/user/profile', { display_name: displayName }, { params: { user_id: userId } }),
}

// ─────────────────────────────────────────────────────────────
// 鉴权 API
// ─────────────────────────────────────────────────────────────
export const authApi = {
  login: (username: string, password: string) =>
    http.post<AuthLoginResponse>('/auth/login', { username, password }),

  register: (payload: AuthRegisterRequest) =>
    http.post<AuthLoginResponse>('/auth/register', payload),

  me: () => http.get<AuthUser>('/auth/me'),

  logout: () => http.post<{ message: string }>('/auth/logout'),
}

// ─────────────────────────────────────────────────────────────
// 记忆 API（Phase 3 完整实现）
// ─────────────────────────────────────────────────────────────
export const memoryApi = {
  // 画像读取
  getProfile: (userId: string) =>
    http.get<MemoryProfileApiResponse>('/memory/profile', { params: { user_id: userId } }),

  // 画像写入（显式 UI 操作，权威表立即更新，Mem0 异步同步）
  updateRisk: (userId: string, riskProfile: string) =>
    http.put('/memory/profile/risk', { risk_profile: riskProfile }, { params: { user_id: userId } }),

  updateSectors: (userId: string, sectors: string[]) =>
    http.put('/memory/profile/sectors', { sectors }, { params: { user_id: userId } }),

  updateReturn: (userId: string, returnExpectation: number, returnMax?: number, horizon?: string) =>
    http.put(
      '/memory/profile/return',
      { return_expectation: returnExpectation, return_max: returnMax, investment_horizon: horizon },
      { params: { user_id: userId } }
    ),

  updateHorizon: (userId: string, horizon: string) =>
    http.put('/memory/profile/horizon', { investment_horizon: horizon }, { params: { user_id: userId } }),

  updateResponsePref: (userId: string, pref: string) =>
    http.put('/memory/profile/pref', { response_pref: pref }, { params: { user_id: userId } }),

  // 记忆条目 CRUD（Mem0 语义层）
  getItems: (userId: string, page = 1, size = 20) =>
    http.get<{ items: MemoryItem[]; total: number; page: number; page_size: number }>(
      '/memory/items',
      { params: { user_id: userId, page, size } }
    ),

  addItem: (userId: string, category: string, content: string, metadata = {}) =>
    http.post<{ id: string; content: string }>(
      '/memory/items',
      { category, content, metadata },
      { params: { user_id: userId } }
    ),

  updateItem: (userId: string, memoryId: string, content: string, metadata = {}) =>
    http.put(`/memory/items/${memoryId}`, { content, metadata }, { params: { user_id: userId } }),

  deleteItem: (userId: string, memoryId: string) =>
    http.delete(`/memory/items/${memoryId}`, { params: { user_id: userId } }),

  deleteAll: (userId: string) =>
    http.delete('/memory/all', { params: { user_id: userId, confirm: true } }),

  getEvidence: (userId: string, memoryId: string) =>
    http.get(`/memory/items/${memoryId}/evidence`, { params: { user_id: userId } }),
}

// ─────────────────────────────────────────────────────────────
// 健康检查
// ─────────────────────────────────────────────────────────────
export const healthApi = {
  check: () => http.get<{ status: string; version: string }>('/health'),
}

// ─────────────────────────────────────────────────────────────
// Phase 2：WebSocket 流式对话
// ─────────────────────────────────────────────────────────────

export interface WsStreamPayload {
  user_id: string
  message: string
  session_id?: string
}

export type WsControlFrame =
  | { type: 'session_id'; session_id: string }
  | { type: 'done'; session_id: string }
  | { type: 'compress_start'; session_id: string; progress: number; eta_seconds: number }
  | { type: 'compress_done'; session_id: string; progress: number; eta_seconds: number; elapsed_seconds: number; snapshot_id?: number; compressed_message_count?: number; total_message_count?: number; percent?: number }
  | { type: 'compress_skip'; session_id: string; progress: number; eta_seconds: number }
  | { type: 'error'; message: string }

/**
 * 解析 WebSocket 收到的帧：
 * - 若是控制帧（JSON，包含 type 字段）返回 WsControlFrame
 * - 否则视为普通 token 文本，返回 null（由调用方直接追加）
 */
export function parseWsFrame(raw: string): WsControlFrame | null {
  if (raw.startsWith('{')) {
    try {
      const obj = JSON.parse(raw) as WsControlFrame
      if ('type' in obj) return obj
    } catch {
      // 不是 JSON，当作普通文本
    }
  }
  return null
}

/**
 * 构建 WebSocket 连接 URL（ws:// 或 wss://）
 * 自动根据 http/https 协议切换。
 */
export function buildWsUrl(path: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = window.location.host
  const url = new URL(`${protocol}://${host}/api${path}`)
  const token = localStorage.getItem(ACCESS_TOKEN_KEY)
  if (token) {
    url.searchParams.set('token', token)
  }
  return url.toString()
}
