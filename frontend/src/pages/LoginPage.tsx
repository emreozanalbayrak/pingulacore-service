import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Loader2, Sparkles } from 'lucide-react'

import { useAuth } from '../contexts/AuthContext'
import { ApiError } from '../lib/api'

interface LocationState {
  from?: { pathname?: string }
}

export function LoginPage() {
  const { login, status } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const redirectTo = (location.state as LocationState | null)?.from?.pathname ?? '/'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    document.title = 'Giriş yap · Pingula UI'
  }, [])

  if (status === 'authenticated') {
    return <Navigate to={redirectTo} replace />
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (submitting) return
    setError(null)
    setSubmitting(true)
    try {
      await login({ email: email.trim().toLowerCase(), password })
      navigate(redirectTo, { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Giriş yapılamadı. Lütfen tekrar deneyin.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md">
        <div className="flex flex-col items-center gap-3 mb-8">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center shadow-lg"
            style={{
              background:
                'linear-gradient(to bottom right, var(--primary), color-mix(in srgb, var(--primary) 60%, transparent))',
            }}
          >
            <Sparkles className="w-7 h-7 text-white" />
          </div>
          <h1
            className="text-3xl text-foreground"
            style={{ fontFamily: 'var(--font-display)' }}
          >
            Pingula UI
          </h1>
          <p className="text-sm text-muted-foreground text-center">
            Hesabına giriş yap ve pipeline'larına devam et.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-card rounded-2xl shadow-xl border border-[color:var(--border)] p-6 sm:p-8 space-y-5"
          noValidate
        >
          {error && (
            <div
              role="alert"
              className="rounded-xl px-4 py-3 text-sm border"
              style={{
                background: 'color-mix(in srgb, var(--destructive) 10%, transparent)',
                borderColor: 'color-mix(in srgb, var(--destructive) 30%, transparent)',
                color: 'var(--destructive)',
              }}
            >
              {error}
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="email" className="text-sm font-medium text-foreground">
              E-posta
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={Boolean(error)}
              className="w-full px-4 py-2.5 rounded-xl border border-[color:var(--border)] bg-[color:var(--input-background)] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-[color:var(--ring)] focus:border-transparent transition"
              placeholder="ornek@firma.com"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="text-sm font-medium text-foreground">
              Şifre
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={Boolean(error)}
                className="w-full px-4 py-2.5 pr-11 rounded-xl border border-[color:var(--border)] bg-[color:var(--input-background)] text-foreground focus:outline-none focus:ring-2 focus:ring-[color:var(--ring)] focus:border-transparent transition"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute inset-y-0 right-0 px-3 flex items-center text-muted-foreground hover:text-foreground transition"
                aria-label={showPassword ? 'Şifreyi gizle' : 'Şifreyi göster'}
                tabIndex={-1}
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting || !email || !password}
            className="w-full px-4 py-2.5 rounded-xl text-sm font-medium text-white shadow-md transition disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            style={{ background: 'var(--primary)' }}
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            {submitting ? 'Giriş yapılıyor…' : 'Giriş yap'}
          </button>

          <p className="text-sm text-center text-muted-foreground">
            Hesabın yok mu?{' '}
            <Link
              to="/register"
              className="font-medium text-[color:var(--primary)] hover:underline"
            >
              Kayıt ol
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
