import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { Archive, FileCode, Hash, Play, RefreshCw, Upload } from 'lucide-react'

import { LogStreamPanel } from '../components/LogStreamPanel'
import { StatusBadge } from '../components/StatusBadge'
import { useLogStream } from '../hooks/useLogStream'
import { usePolling } from '../hooks/usePolling'
import { ApiError, api } from '../lib/api'
import type {
  LegacyPipelineDescriptor,
  LegacyPipelineKind,
  LegacyRunDetailResponse,
} from '../types'

const DIFFICULTIES = ['kolay', 'orta', 'zor'] as const
type Difficulty = (typeof DIFFICULTIES)[number]

interface YamlState {
  files: string[]
  loading: boolean
  error: string | null
}

const EMPTY_YAML_STATE: YamlState = { files: [], loading: false, error: null }

function isImageUrl(url: string): boolean {
  return /\.(png|jpe?g|gif|webp|svg)$/i.test(url)
}

function isPdfUrl(url: string): boolean {
  return /\.pdf$/i.test(url)
}

function isJsonUrl(url: string): boolean {
  return /\.json$/i.test(url)
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(2)} MB`
}

export function LegacyPipelinePage() {
  const [pipelines, setPipelines] = useState<LegacyPipelineDescriptor[]>([])
  const [pipelinesError, setPipelinesError] = useState('')

  const [selectedKind, setSelectedKind] = useState<LegacyPipelineKind | null>(null)
  const [yamlByKind, setYamlByKind] = useState<Record<LegacyPipelineKind, YamlState>>({
    geometry: EMPTY_YAML_STATE,
    turkce: EMPTY_YAML_STATE,
  })
  const [yamlPath, setYamlPath] = useState('')
  const [difficulty, setDifficulty] = useState<Difficulty>('orta')
  const [variantName, setVariantName] = useState('')

  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')
  const [runId, setRunId] = useState<string | null>(null)
  const [runDetail, setRunDetail] = useState<LegacyRunDetailResponse | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const { lines, connected, done, active, connect } = useLogStream()

  // Pipeline listesi + her iki YAML listesini paralel yükle.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await api.listLegacyPipelines()
        if (cancelled) return
        setPipelines(res.pipelines)
        const firstEnabled = res.pipelines.find((p) => p.enabled)
        if (firstEnabled) setSelectedKind(firstEnabled.kind)

        for (const p of res.pipelines) {
          if (!p.enabled) continue
          setYamlByKind((prev) => ({
            ...prev,
            [p.kind]: { ...prev[p.kind], loading: true, error: null },
          }))
          api
            .listLegacyYamlFiles(p.kind)
            .then((r) => {
              if (cancelled) return
              setYamlByKind((prev) => ({
                ...prev,
                [p.kind]: { files: r.files, loading: false, error: null },
              }))
            })
            .catch((e) => {
              if (cancelled) return
              setYamlByKind((prev) => ({
                ...prev,
                [p.kind]: {
                  files: [],
                  loading: false,
                  error: e instanceof Error ? e.message : 'YAML listesi alınamadı',
                },
              }))
            })
        }
      } catch (e) {
        if (cancelled) return
        setPipelinesError(e instanceof Error ? e.message : 'Pipeline listesi alınamadı')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const currentYaml = selectedKind ? yamlByKind[selectedKind] : EMPTY_YAML_STATE

  // Seçilen pipeline değiştiğinde YAML seçimini sıfırla.
  useEffect(() => {
    if (!selectedKind) return
    const files = yamlByKind[selectedKind].files
    if (files.length > 0) setYamlPath(files[0])
    else setYamlPath('')
  }, [selectedKind, yamlByKind])

  const selectedDescriptor = useMemo(
    () => pipelines.find((p) => p.kind === selectedKind) ?? null,
    [pipelines, selectedKind],
  )

  const refreshRun = async () => {
    if (!runId) return
    try {
      const detail = await api.getLegacyRun(runId)
      setRunDetail(detail)
    } catch {
      // sessizce geç — polling tekrar dener
    }
  }

  const reloadYamlFiles = async (kind: LegacyPipelineKind) => {
    setYamlByKind((prev) => ({
      ...prev,
      [kind]: { ...prev[kind], loading: true, error: null },
    }))
    try {
      const r = await api.listLegacyYamlFiles(kind)
      setYamlByKind((prev) => ({
        ...prev,
        [kind]: { files: r.files, loading: false, error: null },
      }))
      return r.files
    } catch (e) {
      setYamlByKind((prev) => ({
        ...prev,
        [kind]: {
          files: [],
          loading: false,
          error: e instanceof Error ? e.message : 'YAML listesi alınamadı',
        },
      }))
      return []
    }
  }

  const handleUpload = async (file: File | null | undefined) => {
    if (!file || !selectedKind) return
    setUploadError('')
    setUploading(true)
    try {
      const res = await api.uploadLegacyYaml(selectedKind, file)
      await reloadYamlFiles(selectedKind)
      setYamlPath(res.yaml_path)
    } catch (e) {
      setUploadError(e instanceof ApiError ? e.message : 'YAML yüklenemedi')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  usePolling(
    refreshRun,
    Boolean(runId) && (runDetail?.status ?? 'running') === 'running',
    2500,
  )

  const handleRun = async () => {
    if (!selectedKind) return
    if (!yamlPath) {
      setRunError('YAML seçilmedi.')
      return
    }
    setRunError('')
    setRunDetail(null)
    setRunning(true)

    const streamKey = crypto.randomUUID()
    connect(streamKey)

    const params: Record<string, string | number | boolean> = {}
    if (selectedKind === 'geometry') {
      params.difficulty = difficulty
      if (variantName.trim()) params.variant_name = variantName.trim()
    }

    try {
      const res = await api.runLegacyPipeline(selectedKind, {
        yaml_path: yamlPath,
        params,
        stream_key: streamKey,
      })
      setRunId(res.run_id)
      // İlk anlık snapshot
      void refreshRun()
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : 'Pipeline çalıştırılamadı')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="space-y-6"
      >
        <div>
          <h1 className="text-3xl mb-1" style={{ fontFamily: 'var(--font-display)' }}>
            Legacy Pipeline
          </h1>
          <p className="text-muted-foreground">
            Eski Geometri ve Türkçe pipeline'larını mevcut YAML'larla çalıştır.
          </p>
        </div>

        {pipelinesError && (
          <div className="px-5 py-4 rounded-xl border text-sm bg-red-50 border-red-200 text-red-700">
            {pipelinesError}
          </div>
        )}

        {/* Pipeline tipi seçimi */}
        <div className="bg-card rounded-2xl shadow-xl border border-border overflow-hidden">
          <div
            className="px-8 py-5 border-b border-border"
            style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}
          >
            <h2 className="text-xl" style={{ fontFamily: 'var(--font-display)' }}>
              Pipeline Seçimi
            </h2>
          </div>
          <div className="p-8 grid gap-4 md:grid-cols-2">
            {pipelines.map((p) => {
              const active = p.kind === selectedKind
              return (
                <button
                  key={p.kind}
                  type="button"
                  disabled={!p.enabled}
                  onClick={() => setSelectedKind(p.kind)}
                  className={`flex items-start gap-3 rounded-xl border-2 p-4 text-left transition-all ${
                    active ? 'border-primary bg-accent' : 'border-border bg-background hover:bg-accent'
                  } ${!p.enabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <Archive className="w-5 h-5 mt-0.5" style={{ color: 'var(--primary)' }} />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-base font-medium">{p.label}</span>
                      {!p.enabled && (
                        <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                          disabled
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">YAML kökü: {p.yaml_root}</p>
                    {!p.enabled && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {p.kind === 'geometry'
                          ? 'Gerekli: GOOGLE_API_KEY/GEMINI_API_KEY ve LEGACY_GEO_YAML_DIR'
                          : 'Gerekli: GOOGLE_API_KEY/GEMINI_API_KEY, LEGACY_TURKCE_CONFIGS_DIR ve LEGACY_TURKCE_TEMPLATES_DIR'}
                      </p>
                    )}
                  </div>
                </button>
              )
            })}
            {pipelines.length === 0 && (
              <p className="text-sm text-muted-foreground md:col-span-2">
                {pipelinesError
                  ? 'Pipeline listesi alınamadı — backend (FastAPI :8000) çalışıyor mu?'
                  : 'Pipeline\'lar yükleniyor…'}
              </p>
            )}
          </div>
        </div>

        {/* Konfigurasyon */}
        {selectedDescriptor && selectedDescriptor.enabled && (
          <div className="bg-card rounded-2xl shadow-xl border border-border overflow-hidden">
            <div
              className="px-8 py-5 border-b border-border"
              style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}
            >
              <h2 className="text-xl" style={{ fontFamily: 'var(--font-display)' }}>
                {selectedDescriptor.label} — Çalıştırma
              </h2>
            </div>

            <div className="p-8 space-y-6">
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <FileCode className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                    YAML Dosyası
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".yaml,.yml,application/x-yaml,text/yaml"
                      onChange={(e) => void handleUpload(e.target.files?.[0])}
                      className="hidden"
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg border-2 text-sm hover:bg-accent transition-colors disabled:opacity-50"
                      style={{ borderColor: 'var(--border)' }}
                    >
                      <Upload className="w-4 h-4" />
                      {uploading ? 'Yükleniyor…' : 'YAML Yükle'}
                    </button>
                  </div>
                </div>
                {uploadError && (
                  <p className="text-sm text-destructive">{uploadError}</p>
                )}
                {currentYaml.loading ? (
                  <p className="text-sm text-muted-foreground">YAML listesi yükleniyor…</p>
                ) : currentYaml.error ? (
                  <p className="text-sm text-destructive">{currentYaml.error}</p>
                ) : currentYaml.files.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Bu pipeline için YAML bulunamadı. Yukarıdan kendi YAML'ını yükleyebilirsin.</p>
                ) : (
                  <select
                    value={yamlPath}
                    onChange={(e) => setYamlPath(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    {currentYaml.files.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {selectedKind === 'geometry' && (
                <div className="grid gap-5 md:grid-cols-2">
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <Hash className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                      Difficulty
                    </label>
                    <select
                      value={difficulty}
                      onChange={(e) => setDifficulty(e.target.value as Difficulty)}
                      className="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none"
                      style={{ borderColor: 'var(--border)' }}
                    >
                      {DIFFICULTIES.map((d) => (
                        <option key={d} value={d}>
                          {d}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <Hash className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                      Variant Name (opsiyonel)
                    </label>
                    <input
                      type="text"
                      value={variantName}
                      onChange={(e) => setVariantName(e.target.value)}
                      className="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none"
                      style={{ borderColor: 'var(--border)' }}
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="px-8 py-5 border-t border-border flex gap-3 bg-muted/20">
              <button
                type="button"
                onClick={() => void handleRun()}
                disabled={running || !yamlPath}
                className="flex items-center gap-2 px-6 py-3 rounded-xl text-white font-medium shadow-lg hover:shadow-xl hover:scale-[1.02] transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                style={{ background: `linear-gradient(to right, var(--primary), var(--secondary))` }}
              >
                <Play className="w-4 h-4" fill="currentColor" />
                {running ? 'Başlatılıyor…' : 'Çalıştır'}
              </button>
              {runId && (
                <button
                  type="button"
                  onClick={() => void refreshRun()}
                  className="flex items-center gap-2 px-6 py-3 rounded-xl border-2 font-medium hover:bg-accent transition-all duration-200"
                  style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
                >
                  <RefreshCw className="w-4 h-4" />
                  Yenile
                </button>
              )}
            </div>
          </div>
        )}

        {runError && (
          <div className="px-5 py-4 rounded-xl border text-sm bg-red-50 border-red-200 text-red-700">
            {runError}
          </div>
        )}

        {/* Run sonucu */}
        {runDetail && (
          <div className="bg-card rounded-2xl border border-border p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-medium" style={{ fontFamily: 'var(--font-display)' }}>
                Run Detayı
              </h3>
              <StatusBadge status={runDetail.status} />
            </div>
            <div className="space-y-1 text-sm">
              <div className="flex gap-3">
                <span className="text-muted-foreground w-28 shrink-0">run_id</span>
                <code className="text-xs bg-muted px-2 py-1 rounded-lg truncate">{runDetail.run_id}</code>
              </div>
              <div className="flex gap-3">
                <span className="text-muted-foreground w-28 shrink-0">YAML</span>
                <code className="text-xs">{runDetail.yaml_path}</code>
              </div>
              {runDetail.error && (
                <div className="flex gap-3">
                  <span className="text-muted-foreground w-28 shrink-0">error</span>
                  <span className="text-xs text-red-700">{runDetail.error}</span>
                </div>
              )}
            </div>

            {runDetail.outputs.length > 0 && (
              <div>
                <h4 className="text-sm font-medium text-foreground mb-2">
                  Çıktı Dosyaları ({runDetail.outputs.length})
                </h4>
                <div className="grid gap-3 md:grid-cols-2">
                  {runDetail.outputs.map((o) => (
                    <div key={o.url} className="rounded-xl border border-border p-3 bg-background">
                      <div className="flex items-center justify-between mb-2">
                        <code className="text-xs truncate">{o.url.split('/').slice(-1)[0]}</code>
                        <span className="text-xs text-muted-foreground">{formatBytes(o.size)}</span>
                      </div>
                      {isImageUrl(o.url) ? (
                        <img
                          src={o.url}
                          alt={o.path}
                          className="w-full rounded-lg border border-border"
                          style={{ maxWidth: 480 }}
                        />
                      ) : isPdfUrl(o.url) ? (
                        <a
                          href={o.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm text-primary underline"
                        >
                          PDF'i aç
                        </a>
                      ) : isJsonUrl(o.url) ? (
                        <a
                          href={o.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm text-primary underline"
                        >
                          JSON'u görüntüle
                        </a>
                      ) : (
                        <a
                          href={o.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm text-primary underline"
                        >
                          İndir
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <LogStreamPanel
          lines={lines}
          connected={connected}
          done={done}
          active={active}
          title="Legacy Pipeline Logs"
        />
      </motion.div>
    </div>
  )
}
