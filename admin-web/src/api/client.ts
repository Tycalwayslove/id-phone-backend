import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type Schema = components['schemas']
const csrfKey = 'id-photo-admin.csrf'
let csrf = sessionStorage.getItem(csrfKey)
let sessionRevision = 0
const expirationListeners = new Set<() => void>()

export function csrfToken() {
  return csrf
}

export function setCsrfToken(value: string | null) {
  sessionRevision += 1
  csrf = value
  if (value) sessionStorage.setItem(csrfKey, value)
  else sessionStorage.removeItem(csrfKey)
}

export function onSessionExpired(listener: () => void) {
  expirationListeners.add(listener)
  return () => { expirationListeners.delete(listener) }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : '请求失败，请稍后重试。'
}

export function isSessionError(error: unknown) {
  return error instanceof ApiError
    && error.status === 401
    && (error.code === 'AUTH_REQUIRED' || error.code === 'AUTH_INVALID')
}

function parseError(status: number, payload: unknown) {
  const data = payload && typeof payload === 'object'
    ? payload as Partial<Schema['ErrorResponse']>
    : null
  const code = typeof data?.code === 'string' ? data.code : 'UNKNOWN_ERROR'
  if (status === 403 && code === 'PERMISSION_DENIED') {
    return new ApiError(status, code, '无权限执行此操作，或当前会话验证已失效。')
  }
  return new ApiError(status, code, typeof data?.message === 'string' ? data.message : '请求失败，请稍后重试。')
}

export const client = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: 'include',
  cache: 'no-store',
  redirect: 'error',
  async fetch(request) {
    const revision = sessionRevision
    if (request.method !== 'GET' && csrf) request.headers.set('X-CSRF-Token', csrf)
    const url = new URL(request.url)
    const isSessionEndpoint = url.pathname.startsWith('/api/v1/admin/auth/')
    if (request.method !== 'GET' && !isSessionEndpoint && !csrf) {
      throw new ApiError(403, 'PERMISSION_DENIED', '当前标签页缺少会话验证，请退出后重新登录。')
    }

    let response: Response
    try {
      response = await fetch(request)
    } catch (error) {
      if (request.signal.aborted) throw error
      throw new ApiError(0, 'NETWORK_ERROR', '无法连接服务，请检查网络后重试。')
    }
    if (!response.ok) {
      const error = parseError(response.status, await response.json().catch(() => null))
      if (isSessionError(error) && revision === sessionRevision && !request.signal.aborted) {
        setCsrfToken(null)
        expirationListeners.forEach((listener) => listener())
      }
      throw error
    }
    return response
  },
})

export function result<T>(response: { data?: T }) {
  if (response.data === undefined) {
    throw new ApiError(0, 'INVALID_RESPONSE', '服务返回的数据不完整，请稍后重试。')
  }
  return response.data
}
