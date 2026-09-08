/** D06 浏览器标签页内的报告任务恢复记录。 */

const STORAGE_PREFIX = 'finance-report-task:v1:'
const IDEMPOTENCY_KEY_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const SHA256_PATTERN = /^[0-9a-f]{64}$/

export interface ActiveReportTaskReference {
  task_id: string
  report_id: string
  idempotency_key: string
  request_fingerprint: string
}

function hasWebCrypto(): boolean {
  return typeof globalThis.crypto?.subtle?.digest === 'function'
}

async function sha256Hex(value: string): Promise<string | null> {
  if (!hasWebCrypto()) return null
  const bytes = new TextEncoder().encode(value)
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function parseReference(raw: string): ActiveReportTaskReference | null {
  try {
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
    const record = value as Record<string, unknown>
    if (Object.keys(record).sort().join(',') !== [
      'idempotency_key',
      'report_id',
      'request_fingerprint',
      'task_id',
    ].join(',')) return null
    if (!isNonEmptyString(record.task_id)
      || !isNonEmptyString(record.report_id)
      || typeof record.idempotency_key !== 'string'
      || !IDEMPOTENCY_KEY_PATTERN.test(record.idempotency_key)
      || typeof record.request_fingerprint !== 'string'
      || !SHA256_PATTERN.test(record.request_fingerprint)) return null
    return {
      task_id: record.task_id,
      report_id: record.report_id,
      idempotency_key: record.idempotency_key,
      request_fingerprint: record.request_fingerprint,
    }
  } catch {
    return null
  }
}

/** 生成不包含原始用户标识的标签页存储键。 */
export async function reportTaskStorageKey(userId: string): Promise<string | null> {
  if (!userId) return null
  const ownerDigest = await sha256Hex(`finance-report-task-owner-v1\0${userId}`)
  return ownerDigest ? `${STORAGE_PREFIX}${ownerDigest.slice(0, 24)}` : null
}

/** 按后端 NFKC/空白规则计算只用于本地完整性识别的命令指纹。 */
export async function reportRequestFingerprint(command: string): Promise<string | null> {
  const normalized = command.normalize('NFKC').trim().replace(/\s+/g, ' ')
  return sha256Hex(normalized)
}

/** 使用密码学安全随机源生成一次明确用户意图对应的 UUIDv4。 */
export function createReportIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID()
  }
  if (typeof globalThis.crypto?.getRandomValues !== 'function') {
    throw new Error('当前浏览器不支持安全随机数，无法创建报告请求')
  }
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/** 写入当前用户唯一的最小活动任务引用；存储不可用时安全降级。 */
export async function saveActiveReportTask(
  userId: string,
  reference: ActiveReportTaskReference,
): Promise<string | null> {
  const storageKey = await reportTaskStorageKey(userId)
  if (!storageKey) return null
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(reference))
    return storageKey
  } catch {
    return null
  }
}

/** 读取并严格校验当前用户的活动任务；损坏记录只删除自身键。 */
export async function loadActiveReportTask(
  userId: string,
): Promise<{ storageKey: string; reference: ActiveReportTaskReference } | null> {
  const storageKey = await reportTaskStorageKey(userId)
  if (!storageKey) return null
  try {
    const raw = sessionStorage.getItem(storageKey)
    if (!raw) return null
    const reference = parseReference(raw)
    if (!reference) {
      sessionStorage.removeItem(storageKey)
      return null
    }
    return { storageKey, reference }
  } catch {
    return null
  }
}

/** 删除一个已验证的报告任务存储键，不清空同标签页其他数据。 */
export function clearActiveReportTask(storageKey: string | null): void {
  if (!storageKey || !storageKey.startsWith(STORAGE_PREFIX)) return
  try {
    sessionStorage.removeItem(storageKey)
  } catch {
    // 浏览器禁用存储时没有可清理的持久引用。
  }
}
