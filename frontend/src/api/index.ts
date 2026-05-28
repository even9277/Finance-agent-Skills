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

export interface SkillConfirmOption {
  key: string
  label: string
  recommended?: boolean
}

export interface SkillConfirmPayload {
  session_id: string
  options: SkillConfirmOption[]
  reasoning: string
  resolved_query: string
  confidence: number
}

export interface ChatMessageRequest {
  user_id: string
  message: string
  session_id?: string
  sop_skill_id?: string
}

export interface ChatMessageResponse {
  reply: string
  session_id: string
  // Phase 3：本次对话参考的用户画像（null 表示 ENABLE_MEMORY=false 或未设置）
  memory_profile?: MemoryProfile | null
  context_window?: ChatContextWindow | null
  route_summary?: ChatRouteSummary | null
  running_summary?: string | null
  running_summary_state?: Record<string, any> | null
  running_summary_mode?: string | null
  /** 低置信度路由：需用户确认，此时 reply 可能为空 */
  skill_confirm?: SkillConfirmPayload | null
  plan_artifact?: Record<string, any> | null
  skill_artifact?: Record<string, any> | null
  verification?: Record<string, any> | null
  allowed_claim_level?: string | null
}

export interface ChatRouteSummaryUserFacing {
  skill_label: string
  analysis_mode: string
  evidence_status: string
  failure_hint: string
}

export interface ChatRouteSummaryDebug {
  route_kind: string
  grounding_policy: string
  claim_policy: string
  skill_contract: string
  evidence_tier: string
  evidence_missing_dimensions: string[]
  evidence_allowed_claim_level: string
  failure_code: string
}

export interface ChatRouteSummary {
  selected_skill_family: string
  selected_skill: string
  skill_name?: string | null
  analysis_mode: string
  execution_policy: string
  reply_mode: string
  route_confidence: number
  used_tools: boolean
  evidence_ok: boolean
  tools_used: string[]
  tools_attempted: string[]
  notes: string[]
  // FIX-7: layered route summary
  route_kind?: string
  grounding_policy?: string
  claim_policy?: string
  skill_contract?: string
  failure_code?: string
  user_facing?: ChatRouteSummaryUserFacing | null
  debug?: ChatRouteSummaryDebug | null
}

export interface ChatContextWindow {
  used_tokens: number
  budget_tokens: number
  usage_percent: number
  counting_mode: 'exact' | 'estimated' | 'estimated_fallback' | string
  compression_status: 'idle' | 'queued' | 'running' | 'failed' | string
  strategy: 'dynamic_budget' | 'legacy_count' | string
  updated_at?: string | null
  memory_hint?: string | null
  memory_hint_level?: 'info' | 'warn' | string | null
  // FIX-5: structured budget info
  model_window_tokens?: number
  working_budget_tokens?: number
  reserved_output_tokens?: number
  budget_status?: 'healthy' | 'moderate' | 'high' | 'critical' | string
}

export interface ChatSession {
  session_id: string
  mode: string
  title?: string
  running_summary?: string
  running_summary_state?: Record<string, any> | null
  running_summary_mode?: string | null
  context_window?: ChatContextWindow | null
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
  route_summary?: ChatRouteSummary | null
  plan_artifact?: Record<string, any> | null
  skill_artifact?: Record<string, any> | null
  verification?: Record<string, any> | null
  allowed_claim_level?: string | null
  plan_preview?: PlanPreviewItem[]
  step_statuses?: StepStatusItem[]
  verification_summary?: VerificationSummary | null
}

export interface PlanPreviewItem {
  step_id: string
  title: string
  description?: string | null
  required?: boolean
  estimated_evidence?: string
  status?: string
  args_summary?: Record<string, string>
}

export interface StepStatusItem {
  plan_id?: string
  step_id: string
  tool_name?: string
  status: string
}

export interface VerificationSummary {
  plan_id?: string
  status: string
  evidence_score?: number
  allowed_claim_level?: string
  missing_dimensions?: string[]
}

export interface ChatTemplate {
  id: string
  label: string
  content: string
}

export interface SopSkillListItem {
  name: string
  official_name: string
  description: string
  execution_mode: string
}

export interface ChatSummaryItem {
  id: number
  session_id: string
  summary: string
  summary_payload?: Record<string, any> | null
  summary_mode?: string | null
  summary_trigger?: string | null
  compressed_message_count: number
  total_message_count: number
  created_at: string
}

export interface ChatSessionSummaries {
  session_id: string
  items: ChatSummaryItem[]
}

export interface ChatSessionMessagesResponse {
  session_id: string
  messages: ChatMessage[]
  running_summary?: string | null
  running_summary_state?: Record<string, any> | null
  running_summary_mode?: string | null
  context_window?: ChatContextWindow | null
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
  mem0_id?: string
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
  sendMessage: (userId: string, message: string, sessionId?: string, sopSkillId?: string) =>
    http.post<ChatMessageResponse>('/chat/message', {
      user_id: userId,
      message,
      session_id: sessionId,
      sop_skill_id: sopSkillId,
    } as ChatMessageRequest),

  listSessions: (userId: string, q?: string) =>
    http.get<ChatSession[]>('/chat/sessions', { params: { user_id: userId, q } }),

  renameSession: (sessionId: string, userId: string, title: string) =>
    http.patch(`/chat/sessions/${sessionId}`, { title }, { params: { user_id: userId } }),

  deleteSession: (sessionId: string, userId: string) =>
    http.delete(`/chat/sessions/${sessionId}`, { params: { user_id: userId } }),

  getMessages: (sessionId: string, userId: string) =>
    http.get<ChatSessionMessagesResponse>(
      `/chat/sessions/${sessionId}/messages`,
      { params: { user_id: userId } }
    ),

  getSummaries: (sessionId: string, userId: string) =>
    http.get<ChatSessionSummaries>(`/chat/sessions/${sessionId}/summaries`, { params: { user_id: userId } }),

  getTemplates: () => http.get<ChatTemplate[]>('/chat/templates'),

  fetchSopSkills: () => http.get<SopSkillListItem[]>('/chat/sop-skills'),

  confirmSkill: (sessionId: string, userId: string, userChoice: string) =>
    http.post<ChatMessageResponse>(`/chat/sessions/${sessionId}/confirm-skill`, {
      user_id: userId,
      user_choice: userChoice,
    }),
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

// FIX-6: unified event protocol constants
export const WS_EVENT = {
  SESSION_ID: 'session_id',
  CONTEXT_UPDATE: 'context_update',
  TASK_STATUS_QUEUED: 'task_status_queued',
  TASK_STATUS_RUNNING: 'task_status_running',
  TASK_STATUS_DONE: 'task_status_done',
  TASK_STATUS_FAILED: 'task_status_failed',
  TRACE_SUMMARY: 'trace_summary',
  PLAN_PREVIEW: 'plan_preview',
  STEP_STATUS: 'step_status',
  VERIFICATION_SUMMARY: 'verification_summary',
  DONE: 'done',
  SKILL_CONFIRM: 'skill_confirm',
  ERROR: 'error',
} as const

export type WsControlFrame =
  | { type: 'session_id'; session_id: string }
  | { type: 'context_update'; session_id: string; context_window: ChatContextWindow }
  | { type: 'task_status_queued'; session_id: string; task_kind: string; context_window?: ChatContextWindow }
  | { type: 'task_status_running'; session_id: string; task_kind: string; context_window?: ChatContextWindow; progress?: number; eta_seconds?: number }
  | { type: 'task_status_done'; session_id: string; task_kind: string; context_window?: ChatContextWindow; progress?: number; elapsed_seconds?: number; snapshot_id?: number; compressed_message_count?: number; total_message_count?: number; percent?: number }
  | { type: 'task_status_failed'; session_id: string; task_kind: string; context_window?: ChatContextWindow; message?: string }
  | { type: 'trace_summary'; session_id: string; route_summary: ChatRouteSummary }
  | { type: 'plan_preview'; session_id: string; plan_id: string; items: PlanPreviewItem[] }
  | { type: 'step_status'; session_id: string; plan_id: string; step_id: string; tool_name?: string; status: string }
  | { type: 'verification_summary'; session_id: string; plan_id: string; status: string; evidence_score?: number; allowed_claim_level?: string; missing_dimensions?: string[] }
  | { type: 'skill_confirm'; session_id: string; options: SkillConfirmOption[]; reasoning?: string; resolved_query?: string; confidence?: number }
  | {
      type: 'done'
      session_id: string
      running_summary?: string
      running_summary_mode?: string
      context_window?: ChatContextWindow
      route_summary?: ChatRouteSummary
      awaiting_skill_confirm?: boolean
    }
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
