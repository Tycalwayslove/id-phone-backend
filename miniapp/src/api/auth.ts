import type { components } from './schema'
import { clearSession, ensureLogin, request } from './client'

type LoginResponse = components['schemas']['LoginResponse']

/** 静默登录（wx.login → 换令牌），并发调用共享同一次登录 */
export function silentLogin(): Promise<LoginResponse> {
  return ensureLogin()
}

/** 退出登录：通知服务端失效令牌，无论成败都清本地 */
export async function logout(): Promise<void> {
  try {
    await request<components['schemas']['OkResponse']>({ method: 'POST', path: '/auth/logout' })
  } finally {
    clearSession()
  }
}
