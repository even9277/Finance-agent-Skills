/** `report-progress-v1` 浏览器协议类型与严格 SSE 增量解析器。 */

export const REPORT_PROGRESS_PROTOCOL_VERSION = 'report-progress-v1' as const

export const REPORT_STAGES = [
  'PREPARING',
  'FUNDAMENTAL_ANALYSIS',
  'TECHNICAL_ANALYSIS',
  'VALUATION_ANALYSIS',
  'NEWS_ANALYSIS',
  'PERSONALIZATION',
  'SYNTHESIZING',
] as const

export const REPORT_STAGE_STATUSES = [
  'RUNNING',
  'SUCCEEDED',
  'FAILED',
  'SKIPPED',
] as const

export const REPORT_TASK_STATUSES = [
  'pending',
  'running',
  'completed',
  'failed',
] as const

export type ReportStage = typeof REPORT_STAGES[number]
export type ReportStageStatus = typeof REPORT_STAGE_STATUSES[number]
export type ReportTaskStatus = typeof REPORT_TASK_STATUSES[number]

export interface ReportStageFrameState {
  stage: ReportStage
  status: ReportStageStatus
}

interface ReportProgressEnvelope {
  protocol_version: typeof REPORT_PROGRESS_PROTOCOL_VERSION
  task_id: string
  report_id: string
  /** 当前 SSE 连接内从 1 开始递增，不用于跨连接重放。 */
  sequence: number
  emitted_at: string
}

type ValidEnvelopeRecord = Record<string, unknown> & ReportProgressEnvelope

export type ReportStreamReadyFrame = ReportProgressEnvelope & {
  type: 'stream_ready'
  status: ReportTaskStatus
  /** 数据库权威总进度，单位为百分比，取值 0..100。 */
  progress: number
  stages: ReportStageFrameState[]
}

export type ReportStageUpdateFrame = ReportProgressEnvelope & {
  type: 'stage_update'
  stage: ReportStage
  stage_status: ReportStageStatus
  progress: number
}

export type ReportTaskTerminalFrame = ReportProgressEnvelope & {
  type: 'task_terminal'
  status: 'completed' | 'failed'
  progress: number
  error_code: string | null
  message: string | null
}

export type ReportProgressFrame =
  | ReportStreamReadyFrame
  | ReportStageUpdateFrame
  | ReportTaskTerminalFrame

export interface ReportSseParser {
  /** 接收任意边界的已解码 UTF-8 文本。 */
  push(chunk: string): void
  /** 在流结束时派发最后一个没有空行结尾的完整事件。 */
  finish(): void
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1
}

function isProgress(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100
}

function isTimestamp(value: unknown): value is string {
  return isNonEmptyString(value) && Number.isFinite(Date.parse(value))
}

function isMember<T extends string>(value: unknown, choices: readonly T[]): value is T {
  return typeof value === 'string' && choices.some((choice) => choice === value)
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedKeys = new Set(allowed)
  return Object.keys(value).every((key) => allowedKeys.has(key))
}

function hasEnvelope(value: Record<string, unknown>): value is ValidEnvelopeRecord {
  return value.protocol_version === REPORT_PROGRESS_PROTOCOL_VERSION
    && isNonEmptyString(value.task_id)
    && isNonEmptyString(value.report_id)
    && isPositiveInteger(value.sequence)
    && isTimestamp(value.emitted_at)
}

function parseStageState(value: unknown): ReportStageFrameState | null {
  if (!isRecord(value)
    || !hasOnlyKeys(value, ['stage', 'status'])
    || !isMember(value.stage, REPORT_STAGES)
    || !isMember(value.status, REPORT_STAGE_STATUSES)) return null
  return { stage: value.stage, status: value.status }
}

function parseFrameValue(value: unknown): ReportProgressFrame | null {
  if (!isRecord(value) || !hasEnvelope(value) || typeof value.type !== 'string') return null
  const envelope = {
    protocol_version: REPORT_PROGRESS_PROTOCOL_VERSION,
    task_id: value.task_id,
    report_id: value.report_id,
    sequence: value.sequence,
    emitted_at: value.emitted_at,
  }

  if (value.type === 'stream_ready') {
    if (!hasOnlyKeys(value, [
      'protocol_version', 'task_id', 'report_id', 'sequence', 'emitted_at',
      'type', 'status', 'progress', 'stages',
    ])
      || !isMember(value.status, REPORT_TASK_STATUSES)
      || !isProgress(value.progress)
      || !Array.isArray(value.stages)) return null
    const stages = value.stages.map(parseStageState)
    if (stages.some((stage) => stage === null)) return null
    return {
      ...envelope,
      type: 'stream_ready',
      status: value.status,
      progress: value.progress,
      stages: stages.filter((stage): stage is ReportStageFrameState => stage !== null),
    }
  }

  if (value.type === 'stage_update') {
    if (!hasOnlyKeys(value, [
      'protocol_version', 'task_id', 'report_id', 'sequence', 'emitted_at',
      'type', 'stage', 'stage_status', 'progress',
    ])
      || !isMember(value.stage, REPORT_STAGES)
      || !isMember(value.stage_status, REPORT_STAGE_STATUSES)
      || !isProgress(value.progress)) return null
    return {
      ...envelope,
      type: 'stage_update',
      stage: value.stage,
      stage_status: value.stage_status,
      progress: value.progress,
    }
  }

  if (value.type === 'task_terminal') {
    if (!hasOnlyKeys(value, [
      'protocol_version', 'task_id', 'report_id', 'sequence', 'emitted_at',
      'type', 'status', 'progress', 'error_code', 'message',
    ])
      || (value.status !== 'completed' && value.status !== 'failed')
      || !isProgress(value.progress)
      || !isNullableString(value.error_code)
      || !isNullableString(value.message)) return null
    return {
      ...envelope,
      type: 'task_terminal',
      status: value.status,
      progress: value.progress,
      error_code: value.error_code,
      message: value.message,
    }
  }

  return null
}

/**
 * 解析一个报告进度业务帧。
 *
 * 未知字段、未知枚举、越界进度与非 JSON 输入都会返回 `null`，避免把后端
 * 私有事件、报告正文或认证信息带入 UI 状态。
 */
export function parseReportProgressFrame(raw: string): ReportProgressFrame | null {
  try {
    const value: unknown = JSON.parse(raw)
    return parseFrameValue(value)
  } catch {
    return null
  }
}

/**
 * 创建符合 SSE 行分隔规则的增量解析器。
 *
 * `data:` 多行会以换行连接；comment/`event:`/`id:` 不进入业务 reducer。
 * 有 data 但协议非法时调用 `onInvalidFrame`，由 transport 决定是否降级。
 */
export function createReportSseParser(
  onFrame: (frame: ReportProgressFrame) => void,
  onInvalidFrame: (raw: string) => void = () => undefined,
): ReportSseParser {
  let pending = ''
  let dataLines: string[] = []
  let finished = false

  function dispatch(): void {
    if (dataLines.length === 0) return
    const raw = dataLines.join('\n')
    dataLines = []
    const frame = parseReportProgressFrame(raw)
    if (frame) onFrame(frame)
    else onInvalidFrame(raw)
  }

  function consumeLine(line: string): void {
    if (line === '') {
      dispatch()
      return
    }
    if (line.startsWith(':')) return
    const separator = line.indexOf(':')
    const field = separator < 0 ? line : line.slice(0, separator)
    let value = separator < 0 ? '' : line.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'data') dataLines.push(value)
  }

  function drain(final: boolean): void {
    while (pending.length > 0) {
      const crIndex = pending.indexOf('\r')
      const lfIndex = pending.indexOf('\n')
      const candidates = [crIndex, lfIndex].filter((index) => index >= 0)
      if (candidates.length === 0) break
      const lineEnd = Math.min(...candidates)
      if (!final && pending[lineEnd] === '\r' && lineEnd === pending.length - 1) break
      const separatorLength = pending[lineEnd] === '\r' && pending[lineEnd + 1] === '\n' ? 2 : 1
      consumeLine(pending.slice(0, lineEnd))
      pending = pending.slice(lineEnd + separatorLength)
    }
    if (final && pending.length > 0) {
      consumeLine(pending)
      pending = ''
    }
  }

  return {
    push(chunk: string): void {
      if (finished || chunk.length === 0) return
      pending += chunk
      drain(false)
    },
    finish(): void {
      if (finished) return
      finished = true
      drain(true)
      dispatch()
    },
  }
}
