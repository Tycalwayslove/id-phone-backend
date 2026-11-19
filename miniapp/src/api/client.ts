/**
 * 请求封装：自动带令牌、401 静默登录后重试一次、统一抛 ApiError、支持 Idempotency-Key、上传。
 * 令牌只放请求头，绝不放 URL；也不要在日志里打印令牌。
 */
import Taro from '@tarojs/taro'
import type { components } from './schema'

type ErrorResponse = components['schemas']['ErrorResponse']
type FieldError = components['schemas']['FieldError']
type LoginResponse = components['schemas']['LoginResponse']
type UploadOut = components['schemas']['UploadOut']

/** 后端根地址，来自 .env.*（必须写成字面量，编译期才会被替换） */
export const API_BASE: string = process.env.TARO_APP_API_BASE ?? ''
const API_PREFIX = `${API_BASE}/api/v1`
const TOKEN_KEY = 'auth_token'

/** 接口失败统一异常 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly errors: FieldError[] | null

  constructor(status: number, code: string, message: string, errors: FieldError[] | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.errors = errors
  }
}

// ---------- 令牌与会话 ----------

export function getToken(): string | null {
  const v: unknown = Taro.getStorageSync(TOKEN_KEY)
  return typeof v === 'string' && v ? v : null
}

export function setToken(token: string): void {
  Taro.setStorageSync(TOKEN_KEY, token)
}

export function clearToken(): void {
  Taro.removeStorageSync(TOKEN_KEY)
}

type SessionListener = (login: LoginResponse | null) => void
const listeners = new Set<SessionListener>()

/** 订阅会话变化（登录成功传 LoginResponse，清除传 null），返回取消订阅函数 */
export function onSessionChange(fn: SessionListener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

/** 清除本地会话并通知订阅者 */
export function clearSession(): void {
  clearToken()
  listeners.forEach((fn) => fn(null))
}

/** 把相对路径（如 /files/xxx）补成完整地址，用于图片和下载链接 */
export function resolveUrl(url: string): string {
  return url.startsWith('/') ? `${API_BASE}${url}` : url
}

// ---------- 底层请求 ----------

type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
type QueryValue = string | number | boolean | null | undefined

export interface RequestOptions {
  method?: Method
  /** 相对 /api/v1 的路径，如 /specs */
  path: string
  query?: Record<string, QueryValue>
  body?: object
  /** 幂等键，下单、提交回执、重提时传入 */
  idempotencyKey?: string
  /** 是否需要登录，默认 true；登录接口自己传 false */
  auth?: boolean
}

function buildQuery(query?: Record<string, QueryValue>): string {
  if (!query) return ''
  const parts: string[] = []
  Object.keys(query).forEach((k) => {
    const v = query[k]
    if (v === undefined || v === null || v === '') return
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  })
  return parts.length ? `?${parts.join('&')}` : ''
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null
}

/** 把响应体转成 ApiError（响应体不是约定格式时给兜底） */
function toApiError(status: number, data: unknown): ApiError {
  if (isRecord(data) && typeof data.code === 'string') {
    const body = data as unknown as ErrorResponse
    return new ApiError(status, body.code, body.message ?? '', body.errors ?? null)
  }
  return new ApiError(status, 'UNKNOWN_ERROR', '请求失败，请稍后再试')
}

function networkError(): ApiError {
  return new ApiError(0, 'NETWORK_ERROR', '网络不太好，请检查网络后重试')
}

function isAuthError(e: ApiError): boolean {
  return e.status === 401 && (e.code === 'AUTH_REQUIRED' || e.code === 'AUTH_INVALID')
}

function authHeader(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function send<T>(opts: RequestOptions): Promise<T> {
  const header: Record<string, string> = { 'Content-Type': 'application/json' }
  if (opts.auth !== false) Object.assign(header, authHeader())
  if (opts.idempotencyKey) header['Idempotency-Key'] = opts.idempotencyKey
  let res: Taro.request.SuccessCallbackResult<unknown>
  try {
    res = await Taro.request<unknown>({
      url: `${API_PREFIX}${opts.path}${buildQuery(opts.query)}`,
      method: opts.method ?? 'GET',
      data: opts.body,
      header
    })
  } catch {
    throw networkError()
  }
  if (res.statusCode >= 200 && res.statusCode < 300) return res.data as T
  throw toApiError(res.statusCode, res.data)
}

// ---------- 静默登录（并发只登一次） ----------

let loginPromise: Promise<LoginResponse> | null = null

async function getLoginCode(): Promise<string> {
  if (Taro.getEnv() === Taro.ENV_TYPE.WEAPP) {
    const r = await Taro.login()
    return r.code
  }
  // H5 没有 wx.login，走后端 fake 登录
  return 'dev:h5user'
}

/** 静默登录：多个调用方共享同一个 Promise */
export function ensureLogin(): Promise<LoginResponse> {
  if (!loginPromise) {
    loginPromise = (async () => {
      const code = await getLoginCode()
      const data = await send<LoginResponse>({
        method: 'POST',
        path: '/auth/wechat-mini/login',
        body: { code },
        auth: false
      })
      setToken(data.token)
      listeners.forEach((fn) => fn(data))
      return data
    })().finally(() => {
      loginPromise = null
    })
  }
  return loginPromise
}

/**
 * 遇到 401 时的处理：
 * 如果别的请求已经换了新令牌，直接用新令牌重试，否则登录一次。
 */
async function recoverAuth(tokenUsed: string | null): Promise<void> {
  const current = getToken()
  if (current && current !== tokenUsed) return
  await ensureLogin()
}

/** 通用请求：401 时静默登录并重试一次 */
export async function request<T>(opts: RequestOptions): Promise<T> {
  const tokenUsed = getToken()
  try {
    return await send<T>(opts)
  } catch (e) {
    if (e instanceof ApiError && opts.auth !== false && isAuthError(e)) {
      await recoverAuth(tokenUsed)
      return send<T>(opts)
    }
    throw e
  }
}

// ---------- 上传 ----------

async function sendUpload(filePath: string): Promise<UploadOut> {
  let res: Taro.uploadFile.SuccessCallbackResult
  try {
    res = await Taro.uploadFile({
      url: `${API_PREFIX}/uploads`,
      filePath,
      name: 'file',
      header: authHeader()
    })
  } catch {
    throw networkError()
  }
  let data: unknown = res.data
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data)
    } catch {
      data = null
    }
  }
  if (res.statusCode >= 200 && res.statusCode < 300 && isRecord(data)) {
    return data as unknown as UploadOut
  }
  throw toApiError(res.statusCode, data)
}

/** 上传本地图片（POST /uploads，表单字段 file），同样支持 401 重试 */
export async function uploadFile(filePath: string): Promise<UploadOut> {
  const tokenUsed = getToken()
  try {
    return await sendUpload(filePath)
  } catch (e) {
    if (e instanceof ApiError && isAuthError(e)) {
      await recoverAuth(tokenUsed)
      return sendUpload(filePath)
    }
    throw e
  }
}
