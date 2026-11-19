import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { adminApi } from './api/admin'
import { isSessionError, onSessionExpired, setCsrfToken, type Schema } from './api/client'

type Account = Schema['AdminMeOut']
type SessionState =
  | { status: 'checking' }
  | { status: 'anonymous' }
  | { status: 'failed'; error: unknown }
  | { status: 'ready'; account: Account }

type Session = {
  state: SessionState
  check: () => void
  login: (body: Schema['AdminLoginIn']) => Promise<void>
  logout: () => Promise<void>
}

const SessionContext = createContext<Session | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const cache = useQueryClient()
  const [state, setState] = useState<SessionState>({ status: 'checking' })
  const [checkVersion, setCheckVersion] = useState(0)

  const endSession = useCallback(() => {
    cache.clear()
    setState({ status: 'anonymous' })
  }, [cache])

  useEffect(() => onSessionExpired(endSession), [endSession])

  useEffect(() => {
    const controller = new AbortController()
    void adminApi.me(controller.signal).then(
      (account) => {
        if (!controller.signal.aborted) setState({ status: 'ready', account })
      },
      (error: unknown) => {
        if (!controller.signal.aborted && !isSessionError(error)) {
          setState({ status: 'failed', error })
        }
      },
    )
    return () => controller.abort()
  }, [checkVersion])

  async function login(body: Schema['AdminLoginIn']) {
    const loginResult = await adminApi.login(body)
    setCsrfToken(loginResult.csrf_token)
    cache.clear()
    check()
  }

  async function logout() {
    await adminApi.logout()
    setCsrfToken(null)
    endSession()
  }

  function check() {
    setState({ status: 'checking' })
    setCheckVersion((current) => current + 1)
  }

  return <SessionContext.Provider value={{ state, check, login, logout }}>{children}</SessionContext.Provider>
}

export function useSession() {
  const session = useContext(SessionContext)
  if (!session) throw new Error('SessionProvider is required')
  return session
}

export function usePermission(permission: string) {
  const { state } = useSession()
  return state.status === 'ready' && state.account.permissions.includes(permission)
}
