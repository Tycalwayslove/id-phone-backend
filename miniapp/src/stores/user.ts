/** 用户与令牌状态（令牌真正存储在 Taro storage，由 api/client 维护） */
import { create } from 'zustand'
import type { components } from '../api/schema'
import { silentLogin, logout as apiLogout } from '../api/auth'
import { clearSession, getToken, onSessionChange } from '../api/client'
import { bindPhone as apiBindPhone, getMe } from '../api/me'

type LoginResponse = components['schemas']['LoginResponse']
type MeOut = components['schemas']['MeOut']

/** 页面用到的用户资料（登录接口和 /me 的公共字段） */
export interface UserProfile {
  id: number
  nickname: string | null
  avatar_url: string | null
  phone_masked: string | null
}

interface UserState {
  token: string | null
  user: UserProfile | null
  /** 确保已登录（没有令牌就静默登录），并拉取资料 */
  ensureLogin: () => Promise<void>
  /** 重新拉取 /me */
  refreshMe: () => Promise<void>
  bindPhone: (code: string) => Promise<void>
  /** 主动退出 */
  logout: () => Promise<void>
  /** 仅清本地（注销账号后用） */
  clearLocal: () => void
}

function fromMe(me: MeOut): UserProfile {
  return { id: me.id, nickname: me.nickname, avatar_url: me.avatar_url, phone_masked: me.phone_masked }
}

export const useUserStore = create<UserState>((set, get) => ({
  token: getToken(),
  user: null,

  async ensureLogin() {
    if (!getToken()) await silentLogin()
    await get().refreshMe()
  },

  async refreshMe() {
    const me = await getMe()
    set({ user: fromMe(me), token: getToken() })
  },

  async bindPhone(code: string) {
    const me = await apiBindPhone(code)
    set({ user: fromMe(me) })
  },

  async logout() {
    try {
      await apiLogout()
    } finally {
      set({ token: null, user: null })
    }
  },

  clearLocal() {
    clearSession()
    set({ token: null, user: null })
  }
}))

// client 在 401 静默登录或清除会话时同步到 store
onSessionChange((login: LoginResponse | null) => {
  if (login) {
    const { user } = login
    useUserStore.setState({
      token: login.token,
      user: {
        id: user.id,
        nickname: user.nickname,
        avatar_url: user.avatar_url,
        phone_masked: user.phone_masked
      }
    })
  } else {
    useUserStore.setState({ token: null, user: null })
  }
})
