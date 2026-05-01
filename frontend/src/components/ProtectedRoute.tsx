import { type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Sparkles } from 'lucide-react'

import { useAuth } from '../contexts/AuthContext'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3 text-muted-foreground">
          <div
            className="w-12 h-12 rounded-2xl flex items-center justify-center shadow-lg animate-pulse"
            style={{
              background:
                'linear-gradient(to bottom right, var(--primary), color-mix(in srgb, var(--primary) 60%, transparent))',
            }}
          >
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <span className="text-sm">Oturum doğrulanıyor…</span>
        </div>
      </div>
    )
  }

  if (status === 'anonymous') {
    return <Navigate to="/register" state={{ from: location }} replace />
  }

  return <>{children}</>
}
