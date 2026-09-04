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
  context_window?: ChatContextWindow | null
  memory_command?: MemoryCommandResult | null
  skill_confirmation?: SkillConfirmation | null
}

export interface SkillConfirmationCandidate {
  skill_name: string
  confidence: number
  version: string
  reason: string
}

export interface SkillConfirmation {
  candidates: SkillConfirmationCandidate[]
  reason: string
  registry_snapshot_hash: string
}

export type MemoryCommandStatus =
  | 'PENDING'
  | 'CONFIRMATION_REQUIRED'
  | 'SUCCEEDED'
  | 'PARTIAL'
  | 'FAILED'
  | 'REJECTED'
  | 'CANCELLED'
  | 'EXPIRED'

export interface MemoryCommandResult {
  status: MemoryCommandStatus
  command_kind?: 'INSPECT' | 'UPDATE' | 'DELETE' | 'FORGET' | 'CONFIRM' | 'CANCEL' | null
  command_ref?: string | null
  affected_count: number
  affected_record_ids: string[]
  consistency_status: string
  pending_confirmation_id?: string | null
  error_code?: string | null
  user_message: string
  preview_items: Array<{
    record_id: string
    category: string
    version: number
    snippet?: string
  }>
}

export interface ChatContextWindow {
  used_tokens: number
  budget_tokens: number
  usage_percent: number
  counting_mode: 'exact' | 'estimated' | string
  compression_status: 'idle' | 'queued' | 'running' | 'failed' | string
  strategy: 'dynamic_budget' | 'legacy_count' | string
  updated_at?: string | null
}

export interface ChatSession {
  session_id: string
  mode: string
  title?: string
  running_summary?: string
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

export interface ChatSessionMessagesResponse {
  session_id: string
  messages: ChatMessage[]
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
  sendMessage: (
    userId: string,
    message: string,
    sessionId?: string,
    explicitSkill?: string,
  ) =>
    http.post<ChatMessageResponse>('/chat/message', {
      user_id: userId,
      message,
      session_id: sessionId,
      explicit_skill: explicitSkill,
    }),

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
  request_id?: string
  explicit_skill?: string
}

export const CHAT_STREAM_PROTOCOL_VERSION = 'chat-stream-v2' as const

export interface WsStreamEnvelope {
  protocol_version: typeof CHAT_STREAM_PROTOCOL_VERSION
  request_id: string
  session_id: string
  sequence: number
}

export type ChatTerminalStatus =
  | 'SUCCEEDED'
  | 'PARTIAL'
  | 'NEEDS_CLARIFICATION'
  | 'REJECTED'
  | 'FAILED'
  | 'CANCELLED'
  | 'UNSUPPORTED'

export type ChatStreamErrorCode =
  | 'CHAT_STREAM_FAILED'
  | 'CHAT_INVALID_JSON'
  | 'CHAT_INVALID_REQUEST'
  | 'CHAT_INTERNAL_ERROR'
  | 'CHAT_STREAM_INCOMPLETE'

export type ChatStepLifecycleStatus =
  | 'PLANNED'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'SKIPPED'
  | 'REPLANNED'
  | 'CANCELLED'

export type ChatToolLifecycleStatus =
  | 'STARTED'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'SKIPPED'
  | 'CANCELLED'

export type ChatEvidenceSufficiency = 'SUFFICIENT' | 'PARTIAL' | 'INSUFFICIENT'

export interface ChatPlanStepPreview {
  step_id: string
  title: string
  purpose: string
  required: boolean
  status: 'PLANNED'
  depends_on: string[]
  subject_summary: string
}

export type ChatTraceSummaryFrame = WsStreamEnvelope & {
  type: 'trace_summary'
  stage: string
  status: 'STARTED' | 'SUCCEEDED' | 'FAILED' | 'SKIPPED' | 'PARTIAL'
  elapsed_ms: number
  summary: string
  error_code?: string
}

export type ChatPlanPreviewFrame = WsStreamEnvelope & {
  type: 'plan_preview'
  plan_id: string
  revision: number
  validated: true
  steps: ChatPlanStepPreview[]
  replan_reason?: string
  replaced_step_ids?: string[]
}

export type ChatStepStatusFrame = WsStreamEnvelope & {
  type: 'step_status'
  plan_id: string
  revision: number
  step_id: string
  status: ChatStepLifecycleStatus
  elapsed_ms?: number
  error_code?: string
}

export type ChatToolStatusFrame = WsStreamEnvelope & {
  type: 'tool_status'
  plan_id: string
  revision: number
  tool_call_id: string
  step_id: string
  display_name: string
  status: ChatToolLifecycleStatus
  attempt: number
  elapsed_ms?: number
  parameter_summary: string[]
  result_summary?: string
  error_code?: string
}

export type ChatVerificationSummaryFrame = WsStreamEnvelope & {
  type: 'verification_summary'
  plan_id: string
  revision: number
  sufficiency: ChatEvidenceSufficiency
  claim_level: 'ANALYTICAL' | 'DESCRIPTIVE' | 'REFUSE'
  accepted_count: number
  rejected_count: number
  covered_dimensions: string[]
  missing_dimensions: string[]
  limitation: string
}

export type ChatControlledFrame =
  | ChatTraceSummaryFrame
  | ChatPlanPreviewFrame
  | ChatStepStatusFrame
  | ChatToolStatusFrame
  | ChatVerificationSummaryFrame

export type WsStreamV2Frame = WsStreamEnvelope & (
  | { type: 'stream_start' }
  | ChatControlledFrame
  | { type: 'content_delta'; content: string; chunk_index: number }
  | { type: 'stream_end'; status: ChatTerminalStatus; chunk_count: number; content_sha256: string }
  | { type: 'stream_error'; code: ChatStreamErrorCode; message: string; chunk_count: number }
  | { type: 'context_update'; context_window: ChatContextWindow }
  | { type: 'memory_command'; memory_command: MemoryCommandResult }
  | { type: 'skill_confirm'; confirmation: SkillConfirmation }
  | { type: 'compaction_queued'; context_window: ChatContextWindow }
  | { type: 'compaction_running'; context_window: ChatContextWindow }
  | { type: 'compaction_done'; context_window: ChatContextWindow }
  | { type: 'compaction_failed'; context_window: ChatContextWindow; message?: string }
  | { type: 'compress_start'; progress: number; eta_seconds: number }
  | { type: 'compress_done'; progress: number; eta_seconds: number; elapsed_seconds: number; snapshot_id?: number; compressed_message_count?: number; total_message_count?: number; percent?: number }
  | { type: 'compress_skip'; progress: number; eta_seconds: number }
)

const CHAT_TERMINAL_STATUSES = new Set<ChatTerminalStatus>([
  'SUCCEEDED',
  'PARTIAL',
  'NEEDS_CLARIFICATION',
  'REJECTED',
  'FAILED',
  'CANCELLED',
  'UNSUPPORTED',
])

const CHAT_STREAM_ERROR_CODES = new Set<ChatStreamErrorCode>([
  'CHAT_STREAM_FAILED',
  'CHAT_INVALID_JSON',
  'CHAT_INVALID_REQUEST',
  'CHAT_INTERNAL_ERROR',
  'CHAT_STREAM_INCOMPLETE',
])

const CHAT_STEP_STATUSES = new Set<ChatStepLifecycleStatus>([
  'PLANNED',
  'RUNNING',
  'SUCCEEDED',
  'FAILED',
  'SKIPPED',
  'REPLANNED',
  'CANCELLED',
])

const CHAT_TOOL_STATUSES = new Set<ChatToolLifecycleStatus>([
  'STARTED',
  'SUCCEEDED',
  'FAILED',
  'SKIPPED',
  'CANCELLED',
])

const CHAT_EVIDENCE_SUFFICIENCY = new Set<ChatEvidenceSufficiency>([
  'SUFFICIENT',
  'PARTIAL',
  'INSUFFICIENT',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 1
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isNonNegativeNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyString)
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedKeys = new Set([
    'protocol_version',
    'request_id',
    'session_id',
    'sequence',
    'type',
    ...allowed,
  ])
  return Object.keys(value).every((key) => allowedKeys.has(key))
}

function isOptionalString(value: unknown): boolean {
  return value === undefined || isNonEmptyString(value)
}

function isOptionalElapsed(value: unknown): boolean {
  return value === undefined || isNonNegativeNumber(value)
}

function isPlanStep(value: unknown): value is ChatPlanStepPreview {
  if (!isRecord(value) || !hasOnlyKeys(value, [
    'step_id', 'title', 'purpose', 'required', 'status', 'depends_on', 'subject_summary',
  ])) return false
  return isNonEmptyString(value.step_id)
    && isNonEmptyString(value.title)
    && isNonEmptyString(value.purpose)
    && typeof value.required === 'boolean'
    && value.status === 'PLANNED'
    && isStringArray(value.depends_on)
    && isNonEmptyString(value.subject_summary)
}

function isContextWindow(value: unknown): value is ChatContextWindow {
  if (!isRecord(value)) return false
  return isNonNegativeInteger(value.used_tokens)
    && isNonNegativeInteger(value.budget_tokens)
    && isNonNegativeInteger(value.usage_percent)
    && isNonEmptyString(value.counting_mode)
    && isNonEmptyString(value.compression_status)
    && isNonEmptyString(value.strategy)
    && (value.updated_at === undefined || value.updated_at === null || typeof value.updated_at === 'string')
}

function isSkillConfirmation(value: unknown): value is SkillConfirmation {
  if (!isRecord(value) || !Array.isArray(value.candidates)) return false
  return isNonEmptyString(value.reason)
    && isNonEmptyString(value.registry_snapshot_hash)
    && value.candidates.every((candidate) => (
      isRecord(candidate)
      && isNonEmptyString(candidate.skill_name)
      && isFiniteNumber(candidate.confidence)
      && isNonEmptyString(candidate.version)
      && isNonEmptyString(candidate.reason)
    ))
}

function isMemoryCommandResult(value: unknown): value is MemoryCommandResult {
  if (!isRecord(value)) return false
  return isNonEmptyString(value.status)
    && isNonNegativeInteger(value.affected_count)
    && Array.isArray(value.affected_record_ids)
    && value.affected_record_ids.every(isNonEmptyString)
    && isNonEmptyString(value.consistency_status)
    && typeof value.user_message === 'string'
    && Array.isArray(value.preview_items)
}

function hasV2Envelope(value: Record<string, unknown>): boolean {
  return value.protocol_version === CHAT_STREAM_PROTOCOL_VERSION
    && isNonEmptyString(value.request_id)
    && isNonEmptyString(value.session_id)
    && isPositiveInteger(value.sequence)
}

function isContextFrame(value: Record<string, unknown>): boolean {
  return isContextWindow(value.context_window)
}

function isCompressBase(value: Record<string, unknown>): boolean {
  return isFiniteNumber(value.progress) && isFiniteNumber(value.eta_seconds)
}

function isWsStreamV2Frame(value: unknown): value is WsStreamV2Frame {
  if (!isRecord(value) || !hasV2Envelope(value) || typeof value.type !== 'string') return false

  switch (value.type) {
    case 'stream_start':
      return true
    case 'trace_summary':
      return hasOnlyKeys(value, ['stage', 'status', 'elapsed_ms', 'summary', 'error_code'])
        && isNonEmptyString(value.stage)
        && typeof value.status === 'string'
        && ['STARTED', 'SUCCEEDED', 'FAILED', 'SKIPPED', 'PARTIAL'].includes(value.status)
        && isNonNegativeNumber(value.elapsed_ms)
        && isNonEmptyString(value.summary)
        && isOptionalString(value.error_code)
    case 'plan_preview':
      return hasOnlyKeys(value, [
        'plan_id', 'revision', 'validated', 'steps', 'replan_reason', 'replaced_step_ids',
      ])
        && isNonEmptyString(value.plan_id)
        && isPositiveInteger(value.revision)
        && value.validated === true
        && Array.isArray(value.steps)
        && value.steps.every(isPlanStep)
        && isOptionalString(value.replan_reason)
        && (value.replaced_step_ids === undefined || isStringArray(value.replaced_step_ids))
    case 'step_status':
      return hasOnlyKeys(value, [
        'plan_id', 'revision', 'step_id', 'status', 'elapsed_ms', 'error_code',
      ])
        && isNonEmptyString(value.plan_id)
        && isPositiveInteger(value.revision)
        && isNonEmptyString(value.step_id)
        && typeof value.status === 'string'
        && CHAT_STEP_STATUSES.has(value.status as ChatStepLifecycleStatus)
        && isOptionalElapsed(value.elapsed_ms)
        && isOptionalString(value.error_code)
    case 'tool_status':
      return hasOnlyKeys(value, [
        'plan_id', 'revision', 'tool_call_id', 'step_id', 'display_name', 'status', 'attempt',
        'elapsed_ms', 'parameter_summary', 'result_summary', 'error_code',
      ])
        && isNonEmptyString(value.plan_id)
        && isPositiveInteger(value.revision)
        && isNonEmptyString(value.tool_call_id)
        && isNonEmptyString(value.step_id)
        && isNonEmptyString(value.display_name)
        && typeof value.status === 'string'
        && CHAT_TOOL_STATUSES.has(value.status as ChatToolLifecycleStatus)
        && isNonNegativeInteger(value.attempt)
        && isOptionalElapsed(value.elapsed_ms)
        && isStringArray(value.parameter_summary)
        && isOptionalString(value.result_summary)
        && isOptionalString(value.error_code)
    case 'verification_summary':
      return hasOnlyKeys(value, [
        'plan_id', 'revision', 'sufficiency', 'claim_level', 'accepted_count',
        'rejected_count', 'covered_dimensions', 'missing_dimensions', 'limitation',
      ])
        && isNonEmptyString(value.plan_id)
        && isPositiveInteger(value.revision)
        && typeof value.sufficiency === 'string'
        && CHAT_EVIDENCE_SUFFICIENCY.has(value.sufficiency as ChatEvidenceSufficiency)
        && typeof value.claim_level === 'string'
        && ['ANALYTICAL', 'DESCRIPTIVE', 'REFUSE'].includes(value.claim_level)
        && isNonNegativeInteger(value.accepted_count)
        && isNonNegativeInteger(value.rejected_count)
        && isStringArray(value.covered_dimensions)
        && isStringArray(value.missing_dimensions)
        && isNonEmptyString(value.limitation)
    case 'content_delta':
      return isNonEmptyString(value.content) && isPositiveInteger(value.chunk_index)
    case 'stream_end':
      return typeof value.status === 'string'
        && CHAT_TERMINAL_STATUSES.has(value.status as ChatTerminalStatus)
        && isNonNegativeInteger(value.chunk_count)
        && typeof value.content_sha256 === 'string'
        && /^[a-f0-9]{64}$/.test(value.content_sha256)
    case 'stream_error':
      return typeof value.code === 'string'
        && CHAT_STREAM_ERROR_CODES.has(value.code as ChatStreamErrorCode)
        && isNonEmptyString(value.message)
        && isNonNegativeInteger(value.chunk_count)
    case 'context_update':
    case 'compaction_queued':
    case 'compaction_running':
    case 'compaction_done':
      return isContextFrame(value)
    case 'compaction_failed':
      return isContextFrame(value)
        && (value.message === undefined || typeof value.message === 'string')
    case 'memory_command':
      return isMemoryCommandResult(value.memory_command)
    case 'skill_confirm':
      return isSkillConfirmation(value.confirmation)
    case 'compress_start':
    case 'compress_skip':
      return isCompressBase(value)
    case 'compress_done':
      return isCompressBase(value)
        && isFiniteNumber(value.elapsed_seconds)
        && (value.snapshot_id === undefined || isNonNegativeInteger(value.snapshot_id))
        && (value.compressed_message_count === undefined
          || isNonNegativeInteger(value.compressed_message_count))
        && (value.total_message_count === undefined
          || isNonNegativeInteger(value.total_message_count))
        && (value.percent === undefined || isFiniteNumber(value.percent))
    default:
      return false
  }
}

/**
 * 解析并校验 WebSocket ``chat-stream-v2`` 帧。
 * Legacy 控制帧、裸文本、未知事件和字段不完整的 JSON 一律拒绝，不再保留双协议。
 */
export function parseWsFrame(raw: string): WsStreamV2Frame | null {
  try {
    const value: unknown = JSON.parse(raw)
    return isWsStreamV2Frame(value) ? value : null
  } catch {
    return null
  }
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
