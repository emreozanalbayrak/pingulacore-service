import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Loader2, Sparkles } from 'lucide-react'

import { useAuth } from '../contexts/AuthContext'
import { ApiError } from '../lib/api'

const MIN_PASSWORD_LENGTH = 8

export function RegisterPage() {
  const { register, status } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    document.title = 'Kayıt ol · Pingula UI'
  }, [])

  if (status === 'authenticated') {
    return <Navigate to="/" replace />
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (submitting) return
    setError(null)

    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Şifre en az ${MIN_PASSWORD_LENGTH} karakter olmalı.`)
      return
    }
    if (password !== confirmPassword) {
      setError('Şifreler eşleşmiyor.')
      return
    }

    setSubmitting(true)
    try {
      await register({
        email: email.trim().toLowerCase(),
        password,
        display_name: displayName.trim() || undefined,
      })
      navigate('/', { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Kayıt oluşturulamadı. Lütfen tekrar deneyin.')
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
            Hesap oluştur
          </h1>
          <p className="text-sm text-muted-foreground text-center">
            Dakikalar içinde başla — birkaç bilgi yeterli.
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
            <label htmlFor="display_name" className="text-sm font-medium text-foreground">
              Görünen ad <span className="text-muted-foreground font-normal">(opsiyonel)</span>
            </label>
            <input
              id="display_name"
              type="text"
              autoComplete="name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl border border-[color:var(--border)] bg-[color:var(--input-background)] text-foreground focus:outline-none focus:ring-2 focus:ring-[color:var(--ring)] focus:border-transparent transition"
              placeholder="Ad Soyad"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="email" className="text-sm font-medium text-foreground">
              E-posta
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={Boolean(error)}
              className="w-full px-4 py-2.5 rounded-xl border border-[color:var(--border)] bg-[color:var(--input-background)] text-foreground focus:outline-none focus:ring-2 focus:ring-[color:var(--ring)] focus:border-transparent transition"
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
                autoComplete="new-password"
                required
                minLength={MIN_PASSWORD_LENGTH}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={Boolean(error)}
                className="w-full px-4 py-2.5 pr-11 rounded-xl border border-[color:var(--border)] bg-[color:var(--input-background)] text-foreground focus:outline-none focus:ring-2 focus:ring-[color:var(--ring)] focus:border-transparent transition"
                placeholder="En az 8 karakter"
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

          <div className="space-y-1.5">
            <label htmlFor="confirm_password" className="text-sm font-medium text-foreground">
              Şifre (tekrar)
            </label>
            <input
              id="confirm_password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="new-password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              aria-invalid={Boolean(error)}
              className="w-full px-4 py-2.5 rounded-xl border border-[color:var(--border)] bg-[color:var(--input-background)] text-foreground focus:outline-none focus:ring-2 focus:ring-[color:var(--ring)] focus:border-transparent transition"
              placeholder="Şifrenizi tekrar girin"
            />
          </div>

          <button
            type="submit"
            disabled={submitting || !email || !password || !confirmPassword}
            className="w-full px-4 py-2.5 rounded-xl text-sm font-medium text-white shadow-md transition disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            style={{ background: 'var(--primary)' }}
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            {submitting ? 'Hesap oluşturuluyor…' : 'Hesap oluştur'}
          </button>

          <p className="text-sm text-center text-muted-foreground">
            Zaten hesabın var mı?{' '}
            <Link to="/login" className="font-medium text-[color:var(--primary)] hover:underline">
              Giriş yap
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
