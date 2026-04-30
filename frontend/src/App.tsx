import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import {
  Sparkles,
  GitBranch,
  Split,
  Bot,
  Home,
  FolderTree,
  BookOpen,
  Archive,
  LogOut,
  ShieldCheck,
} from 'lucide-react'

import { ProtectedRoute } from './components/ProtectedRoute'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { api } from './lib/api'
import { AgentsPage } from './pages/AgentsPage'
import { FilesPage } from './pages/FilesPage'
import { FullPipelinePage } from './pages/FullPipelinePage'
import { HomePage } from './pages/HomePage'
import { LegacyPipelinePage } from './pages/LegacyPipelinePage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { SubPipelinesPage } from './pages/SubPipelinesPage'
import { TemplatesPage } from './pages/TemplatesPage'
import type { AuthUser, RuntimeInfoResponse } from './types'

const navigation = [
  { to: '/', label: 'Ana Sayfa', Icon: Home, end: true },
  { to: '/full', label: 'Full Pipeline', Icon: GitBranch, end: false },
  { to: '/sub-pipelines', label: 'Sub-Pipelines', Icon: Split, end: false },
  { to: '/agents', label: 'Standalone Agents', Icon: Bot, end: false },
  { to: '/files', label: 'Files & Favorites', Icon: FolderTree, end: false },
  { to: '/templates', label: 'Şablonlar', Icon: BookOpen, end: false },
  { to: '/legacy', label: 'Legacy Pipeline', Icon: Archive, end: false },
]

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  )
}

function AppLayout() {
  const { user, logout } = useAuth()
  const [runtime, setRuntime] = useState<RuntimeInfoResponse | null>(null)

  useEffect(() => {
    void api.getRuntimeInfo().then(setRuntime).catch(() => {})
  }, [])

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      {/* Sidebar */}
      <aside
        className="w-64 shrink-0 flex flex-col shadow-2xl"
        style={{
          background:
            'linear-gradient(to bottom, var(--secondary), color-mix(in srgb, var(--secondary) 90%, transparent))',
        }}
      >
        {/* Logo */}
        <div className="p-6 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center shadow-lg"
              style={{
                background: 'linear-gradient(to bottom right, var(--primary), rgba(255,255,255,0.2))',
              }}
            >
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-medium text-white" style={{ fontFamily: 'var(--font-display)' }}>
                Pingula UI
              </h1>
              <p className="text-xs text-white/60">Pipeline Manager</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
          {navigation.map(({ to, label, Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `w-full px-4 py-3 rounded-xl flex items-center gap-3 transition-all duration-200 text-left no-underline ${
                  isActive ? 'bg-white/20 shadow-lg' : 'hover:bg-white/10'
                }`
              }
            >
              {({ isActive }: { isActive: boolean }) => (
                <>
                  <Icon className={`w-5 h-5 shrink-0 ${isActive ? 'text-white' : 'text-white/70'}`} />
                  <span className={`text-sm ${isActive ? 'text-white font-medium' : 'text-white/70'}`}>
                    {label}
                  </span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Runtime Info */}
        <div className="px-4 py-3 border-t border-white/10">
          {runtime ? (
            <div className="space-y-1.5">
              <div
                className={`flex items-center gap-1.5 text-xs font-medium ${
                  runtime.use_stub_agents ? 'text-yellow-300/90' : 'text-green-300/90'
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    runtime.use_stub_agents ? 'bg-yellow-300' : 'bg-green-300 animate-pulse'
                  }`}
                />
                {runtime.use_stub_agents ? 'Stub Mode' : 'Real Model'}
              </div>
              <p className="text-xs text-white/40 truncate">Text: {runtime.text_model}</p>
              <p className="text-xs text-white/40 truncate">Image: {runtime.image_model}</p>
            </div>
          ) : (
            <p className="text-xs text-white/40 text-center">v1.0.0</p>
          )}
        </div>

        {/* User block */}
        {user && (
          <div className="p-4 border-t border-white/10">
            <UserBlock user={user} onLogout={logout} />
          </div>
        )}
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto bg-background">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/full" element={<FullPipelinePage />} />
          <Route path="/sub-pipelines" element={<SubPipelinesPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/files" element={<FilesPage />} />
          <Route path="/templates" element={<TemplatesPage />} />
          <Route path="/legacy" element={<LegacyPipelinePage />} />
        </Routes>
      </main>
    </div>
  )
}

function UserBlock({ user, onLogout }: { user: AuthUser; onLogout: () => Promise<void> }) {
  const initial = (user.display_name || user.email).trim().charAt(0).toUpperCase() || '?'
  return (
    <div className="flex items-center gap-3">
      <div
        className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-medium text-white shrink-0"
        style={{ background: 'var(--primary)' }}
        aria-hidden
      >
        {initial}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <p className="text-sm text-white truncate" title={user.display_name || user.email}>
            {user.display_name || user.email}
          </p>
          {user.is_admin && (
            <span
              className="inline-flex items-center gap-0.5 text-[10px] font-medium px-1.5 py-0.5 rounded-md"
              style={{
                background: 'color-mix(in srgb, var(--primary) 30%, transparent)',
                color: 'white',
              }}
              title="Yönetici"
            >
              <ShieldCheck className="w-3 h-3" />
              Admin
            </span>
          )}
        </div>
        <p className="text-xs text-white/50 truncate" title={user.email}>
          {user.email}
        </p>
      </div>
      <button
        type="button"
        onClick={() => void onLogout()}
        className="p-2 rounded-lg text-white/60 hover:text-white hover:bg-white/10 transition shrink-0"
        aria-label="Çıkış yap"
        title="Çıkış yap"
      >
        <LogOut className="w-4 h-4" />
      </button>
    </div>
  )
}
