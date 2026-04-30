import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import {
  ApiError,
  api,
  AUTH_UNAUTHORIZED_EVENT,
  getStoredAuthToken,
  setStoredAuthToken,
} from '../lib/api'
import type { AuthUser, LoginRequest, RegisterRequest } from '../types'

type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

interface AuthContextValue {
  user: AuthUser | null
  status: AuthStatus
  login: (payload: LoginRequest) => Promise<void>
  register: (payload: RegisterRequest) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [status, setStatus] = useState<AuthStatus>(() => (getStoredAuthToken() ? 'loading' : 'anonymous'))
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const setAnonymous = useCallback(() => {
    setStoredAuthToken(null)
    if (mountedRef.current) {
      setUser(null)
      setStatus('anonymous')
    }
  }, [])

  useEffect(() => {
    const token = getStoredAuthToken()
    if (!token) {
      setStatus('anonymous')
      return
    }
    let cancelled = false
    void api
      .me()
      .then((me) => {
        if (cancelled) return
        setUser(me)
        setStatus('authenticated')
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 401) {
          setAnonymous()
        } else {
          setAnonymous()
        }
      })
    return () => {
      cancelled = true
    }
  }, [setAnonymous])

  useEffect(() => {
    const handler = () => setAnonymous()
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handler)
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handler)
  }, [setAnonymous])

  const login = useCallback(async (payload: LoginRequest) => {
    const result = await api.login(payload)
    setStoredAuthToken(result.token)
    setUser(result.user)
    setStatus('authenticated')
  }, [])

  const register = useCallback(async (payload: RegisterRequest) => {
    const result = await api.register(payload)
    setStoredAuthToken(result.token)
    setUser(result.user)
    setStatus('authenticated')
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      /* server-side revoke is best-effort */
    }
    setAnonymous()
  }, [setAnonymous])

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, login, register, logout }),
    [user, status, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (ctx === null) {
    throw new Error('useAuth, AuthProvider içinde kullanılmalı')
  }
  return ctx
}
