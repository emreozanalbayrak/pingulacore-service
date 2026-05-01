import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { Save, X } from 'lucide-react'

import { ApiError, api } from '../lib/api'
import type { LegacyPipelineKind } from '../types'

interface YamlDrawerProps {
  open: boolean
  kind: LegacyPipelineKind | null
  yamlPath: string | null
  onClose: () => void
  onSaved?: (yamlPath: string) => void
}

export function YamlDrawer({ open, kind, yamlPath, onClose, onSaved }: YamlDrawerProps) {
  const [content, setContent] = useState('')
  const [original, setOriginal] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [isRepoYaml, setIsRepoYaml] = useState(false)

  useEffect(() => {
    if (!open || !kind || !yamlPath) return
    let cancelled = false
    setLoading(true)
    setError('')
    api
      .getLegacyYamlContent(kind, yamlPath)
      .then((res) => {
        if (cancelled) return
        setContent(res.content)
        setOriginal(res.content)
        setIsRepoYaml(res.is_repo_yaml)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof ApiError ? e.message : 'YAML okunamadı')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, kind, yamlPath])

  const dirty = content !== original

  const handleSave = async () => {
    if (!kind || !yamlPath) return
    setSaving(true)
    setError('')
    try {
      const res = await api.updateLegacyYamlContent(kind, { yaml_path: yamlPath, content })
      setOriginal(res.content)
      onSaved?.(yamlPath)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'YAML kaydedilemedi')
    } finally {
      setSaving(false)
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/40 z-40"
            onClick={onClose}
          />
          <motion.aside
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 220 }}
            className="fixed top-0 right-0 h-full w-full md:w-[640px] bg-card border-l border-border shadow-2xl z-50 flex flex-col"
          >
            <div className="px-5 py-4 border-b border-border flex items-center justify-between gap-3 bg-muted/30">
              <div className="min-w-0">
                <h3 className="text-base font-medium truncate" style={{ fontFamily: 'var(--font-display)' }}>
                  YAML Görüntüle / Düzenle
                </h3>
                <code className="text-xs text-muted-foreground break-all">{yamlPath}</code>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="p-1.5 rounded-lg hover:bg-accent"
                aria-label="Kapat"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {isRepoYaml && (
              <div className="px-5 py-2 text-xs bg-amber-50 text-amber-800 border-b border-amber-200">
                Repo YAML'ı düzenliyorsun — değişiklik diskte kalıcıdır. Orijinali otomatik <code>.bak</code>{' '}
                olarak yedeklenir.
              </div>
            )}

            <div className="flex-1 overflow-hidden flex flex-col">
              {loading ? (
                <div className="p-5 text-sm text-muted-foreground">YAML yükleniyor…</div>
              ) : (
                <textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  spellCheck={false}
                  className="flex-1 w-full p-4 font-mono text-xs leading-relaxed resize-none focus:outline-none bg-background"
                  style={{ fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}
                />
              )}
              {error && (
                <div className="px-5 py-2 text-sm text-red-700 bg-red-50 border-t border-red-200">{error}</div>
              )}
            </div>

            <div className="px-5 py-3 border-t border-border flex items-center justify-end gap-2 bg-muted/20">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-lg border-2 text-sm hover:bg-accent transition-colors"
                style={{ borderColor: 'var(--border)' }}
              >
                Kapat
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={!dirty || saving || loading}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-white text-sm font-medium shadow disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ background: `linear-gradient(to right, var(--primary), var(--secondary))` }}
              >
                <Save className="w-4 h-4" />
                {saving ? 'Kaydediliyor…' : 'Kaydet'}
              </button>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
