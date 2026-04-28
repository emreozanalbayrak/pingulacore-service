import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import {
  Archive,
  Download,
  Eye,
  FileCode,
  Hash,
  Play,
  RefreshCw,
  Search,
  Upload,
  X,
} from 'lucide-react'

import { LogStreamPanel } from '../components/LogStreamPanel'
import { StatusBadge } from '../components/StatusBadge'
import { YamlDrawer } from '../components/YamlDrawer'
import { OutputTree, OutputPreviewGrid } from '../components/OutputTree'
import { useLogStream } from '../hooks/useLogStream'
import { usePolling } from '../hooks/usePolling'
import { ApiError, api } from '../lib/api'
import { downloadFromUrl } from '../lib/download'
import type {
  LegacyBatchDetailResponse,
  LegacyPipelineDescriptor,
  LegacyPipelineKind,
  LegacyYamlInfoResponse,
} from '../types'

const DIFFICULTIES = ['kolay', 'orta', 'zor'] as const
type Difficulty = (typeof DIFFICULTIES)[number]

interface YamlState {
  files: string[]
  loading: boolean
  error: string | null
}

const EMPTY_YAML_STATE: YamlState = { files: [], loading: false, error: null }

interface SelectedYaml {
  path: string
  info?: LegacyYamlInfoResponse
  loadingInfo: boolean
  infoError?: string
  requestedCount: number // 0 = no variants requested (or no variant support)
  selectedVariants: string[]
}

export function LegacyPipelinePage() {
  const [pipelines, setPipelines] = useState<LegacyPipelineDescriptor[]>([])
  const [pipelinesError, setPipelinesError] = useState('')

  const [selectedKind, setSelectedKind] = useState<LegacyPipelineKind | null>(null)
  const [yamlByKind, setYamlByKind] = useState<Record<LegacyPipelineKind, YamlState>>({
    geometry: EMPTY_YAML_STATE,
    turkce: EMPTY_YAML_STATE,
  })
  const [selectedYamls, setSelectedYamls] = useState<SelectedYaml[]>([])
  const [yamlSearch, setYamlSearch] = useState('')
  const [difficulty, setDifficulty] = useState<Difficulty>('orta')
  const [parallelism, setParallelism] = useState<number>(4)

  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')
  const [batchId, setBatchId] = useState<string | null>(null)
  const [batchDetail, setBatchDetail] = useState<LegacyBatchDetailResponse | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerYaml, setDrawerYaml] = useState<string | null>(null)

  const { lines, connected, done, active, connect } = useLogStream()

  // Pipeline list + her iki YAML listesini paralel yükle.
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

  // Pipeline türü değişince seçimleri sıfırla.
  useEffect(() => {
    setSelectedYamls([])
    setBatchId(null)
    setBatchDetail(null)
  }, [selectedKind])

  const filteredYamls = useMemo(() => {
    const q = yamlSearch.trim().toLowerCase()
    if (!q) return currentYaml.files
    return currentYaml.files.filter((f) => f.toLowerCase().includes(q))
  }, [currentYaml.files, yamlSearch])

  const isSelected = (path: string) => selectedYamls.some((y) => y.path === path)

  const toggleSelect = async (path: string) => {
    if (!selectedKind) return
    const already = selectedYamls.find((y) => y.path === path)
    if (already) {
      setSelectedYamls((prev) => prev.filter((y) => y.path !== path))
      return
    }
    const placeholder: SelectedYaml = {
      path,
      loadingInfo: true,
      requestedCount: 0,
      selectedVariants: [],
    }
    setSelectedYamls((prev) => [...prev, placeholder])
    try {
      const info = await api.getLegacyYamlInfo(selectedKind, path)
      setSelectedYamls((prev) =>
        prev.map((y) =>
          y.path === path
            ? {
                ...y,
                info,
                loadingInfo: false,
                requestedCount: info.has_variants ? info.variant_count : 0,
                selectedVariants: info.has_variants ? info.variant_names : [],
              }
            : y,
        ),
      )
    } catch (e) {
      setSelectedYamls((prev) =>
        prev.map((y) =>
          y.path === path
            ? {
                ...y,
                loadingInfo: false,
                infoError: e instanceof ApiError ? e.message : 'Varyant bilgisi alınamadı',
              }
            : y,
        ),
      )
    }
  }

  const updateRequestedCount = (path: string, count: number) => {
    setSelectedYamls((prev) =>
      prev.map((y) => {
        if (y.path !== path || !y.info?.has_variants) return y
        const max = y.info.variant_count
        const next = Math.max(0, Math.min(max, Math.floor(count)))
        return {
          ...y,
          requestedCount: next,
          selectedVariants: y.info.variant_names.slice(0, next),
        }
      }),
    )
  }

  const toggleVariant = (path: string, variant: string) => {
    setSelectedYamls((prev) =>
      prev.map((y) => {
        if (y.path !== path) return y
        const has = y.selectedVariants.includes(variant)
        const next = has
          ? y.selectedVariants.filter((v) => v !== variant)
          : [...y.selectedVariants, variant]
        return { ...y, selectedVariants: next, requestedCount: next.length }
      }),
    )
  }

  const totalRuns = useMemo(
    () =>
      selectedYamls.reduce((acc, y) => {
        if (y.info?.has_variants && y.selectedVariants.length > 0) return acc + y.selectedVariants.length
        return acc + 1
      }, 0),
    [selectedYamls],
  )

  const refreshBatch = async () => {
    if (!batchId) return
    try {
      const detail = await api.getLegacyBatch(batchId)
      setBatchDetail(detail)
    } catch {
      // sessizce geç
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
      // Yüklenen dosyayı otomatik seç.
      void toggleSelect(res.yaml_path)
    } catch (e) {
      setUploadError(e instanceof ApiError ? e.message : 'YAML yüklenemedi')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const allRunsDone = useMemo(() => {
    if (!batchDetail) return false
    return batchDetail.runs.every((r) => r.status !== 'running')
  }, [batchDetail])

  usePolling(refreshBatch, Boolean(batchId) && !allRunsDone, 2500)

  const handleRun = async () => {
    if (!selectedKind) return
    if (selectedYamls.length === 0) {
      setRunError('En az bir YAML seç.')
      return
    }
    for (const y of selectedYamls) {
      if (y.info?.has_variants && y.selectedVariants.length === 0) {
        setRunError(`${y.path} için en az bir varyant seç (veya YAML'ı listeden çıkar).`)
        return
      }
    }
    setRunError('')
    setBatchDetail(null)
    setRunning(true)

    const streamKey = crypto.randomUUID()
    connect(streamKey)

    const items = selectedYamls.map((y) => {
      const params: Record<string, string | number | boolean> = {}
      if (selectedKind === 'geometry') {
        params.difficulty = difficulty
      }
      const variants = y.info?.has_variants ? y.selectedVariants : []
      return { yaml_path: y.path, params, variants }
    })

    try {
      const res = await api.runLegacyBatch(selectedKind, {
        items,
        parallelism,
        stream_key: streamKey,
      })
      setBatchId(res.batch_id)
      void refreshBatch()
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : 'Pipeline çalıştırılamadı')
    } finally {
      setRunning(false)
    }
  }

  const openDrawer = (path: string) => {
    setDrawerYaml(path)
    setDrawerOpen(true)
  }

  const handleDownloadAll = async (runId: string) => {
    try {
      const url = api.getLegacyRunDownloadUrl(runId)
      await downloadFromUrl(url, `${runId}.zip`)
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) console.error(e)
    }
  }

  const selectedDescriptor = useMemo(
    () => pipelines.find((p) => p.kind === selectedKind) ?? null,
    [pipelines, selectedKind],
  )

  return (
    <div className="p-8 max-w-6xl mx-auto">
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
            Eski Geometri ve Türkçe pipeline'larını çoklu YAML, paralel varyant ve klasör çıktıları ile çalıştır.
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
                    <p className="mt-1 text-xs text-muted-foreground">YAML kökü (repo): {p.yaml_root}/</p>
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
              {/* YAML çoklu seçim */}
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <FileCode className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                    YAML Dosyaları (çoklu seç)
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

                {uploadError && <p className="text-sm text-destructive">{uploadError}</p>}

                <div className="relative">
                  <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type="text"
                    value={yamlSearch}
                    onChange={(e) => setYamlSearch(e.target.value)}
                    placeholder="YAML ara..."
                    className="w-full pl-9 pr-3 py-2 rounded-xl border-2 bg-white text-sm focus:outline-none"
                    style={{ borderColor: 'var(--border)' }}
                  />
                </div>

                {currentYaml.loading ? (
                  <p className="text-sm text-muted-foreground">YAML listesi yükleniyor…</p>
                ) : currentYaml.error ? (
                  <p className="text-sm text-destructive">{currentYaml.error}</p>
                ) : filteredYamls.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {currentYaml.files.length === 0
                      ? "Bu pipeline için YAML bulunamadı. Yukarıdan kendi YAML'ını yükleyebilirsin."
                      : 'Aramayla eşleşen YAML yok.'}
                  </p>
                ) : (
                  <div className="max-h-72 overflow-auto border-2 rounded-xl bg-background" style={{ borderColor: 'var(--border)' }}>
                    {filteredYamls.map((f) => {
                      const checked = isSelected(f)
                      return (
                        <div
                          key={f}
                          className={`flex items-center gap-2 px-3 py-2 border-b last:border-b-0 hover:bg-accent ${
                            checked ? 'bg-accent/50' : ''
                          }`}
                          style={{ borderColor: 'var(--border)' }}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => void toggleSelect(f)}
                            className="w-4 h-4"
                          />
                          <code className="text-xs flex-1 truncate">{f}</code>
                          <button
                            type="button"
                            onClick={() => openDrawer(f)}
                            className="p-1 rounded hover:bg-background"
                            title="YAML'ı görüntüle / düzenle"
                          >
                            <Eye className="w-4 h-4 text-muted-foreground" />
                          </button>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              {/* Seçili YAML kartları + varyant kontrolleri */}
              {selectedYamls.length > 0 && (
                <div className="space-y-3">
                  <div className="text-sm font-medium text-foreground">
                    Seçilen YAML'lar ({selectedYamls.length}) — toplam {totalRuns} alt-run üretilecek
                  </div>
                  {selectedYamls.map((y) => (
                    <div
                      key={y.path}
                      className="rounded-xl border-2 p-4 bg-background"
                      style={{ borderColor: 'var(--border)' }}
                    >
                      <div className="flex items-start justify-between gap-3 mb-2">
                        <code className="text-xs break-all flex-1">{y.path}</code>
                        <button
                          type="button"
                          onClick={() => toggleSelect(y.path)}
                          className="p-1 rounded hover:bg-accent shrink-0"
                          aria-label="Listeden çıkar"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>

                      {y.loadingInfo && <p className="text-xs text-muted-foreground">Varyant bilgisi yükleniyor…</p>}
                      {y.infoError && <p className="text-xs text-destructive">{y.infoError}</p>}

                      {y.info?.has_variants ? (
                        <div className="mt-2 space-y-2">
                          <div className="flex items-center gap-3">
                            <label className="text-xs font-medium text-muted-foreground">
                              Üretilecek varyant sayısı
                            </label>
                            <input
                              type="number"
                              min={0}
                              max={y.info.variant_count}
                              value={y.requestedCount}
                              onChange={(e) => updateRequestedCount(y.path, Number(e.target.value))}
                              className="w-20 px-2 py-1 rounded border-2 text-sm bg-white"
                              style={{ borderColor: 'var(--border)' }}
                            />
                            <span className="text-xs text-muted-foreground">
                              / {y.info.variant_count} (autofill: ilk N varyant seçilir)
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {y.info.variant_names.map((name) => {
                              const sel = y.selectedVariants.includes(name)
                              return (
                                <button
                                  key={name}
                                  type="button"
                                  onClick={() => toggleVariant(y.path, name)}
                                  className={`text-xs px-2 py-1 rounded-full border-2 transition-colors ${
                                    sel
                                      ? 'bg-primary/10 border-primary text-foreground'
                                      : 'bg-muted border-border text-muted-foreground hover:bg-accent'
                                  }`}
                                >
                                  {name}
                                </button>
                              )
                            })}
                          </div>
                        </div>
                      ) : (
                        !y.loadingInfo && (
                          <p className="text-xs text-muted-foreground">
                            Bu YAML varyantsız — tek alt-run üretilir.
                          </p>
                        )
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Pipeline parametreleri */}
              <div className="grid gap-5 md:grid-cols-2">
                {selectedKind === 'geometry' && (
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
                )}
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <Hash className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                    Paralellik (max eşzamanlı alt-run)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={16}
                    value={parallelism}
                    onChange={(e) => setParallelism(Math.max(1, Number(e.target.value)))}
                    className="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none"
                    style={{ borderColor: 'var(--border)' }}
                  />
                </div>
              </div>
            </div>

            <div className="px-8 py-5 border-t border-border flex gap-3 bg-muted/20">
              <button
                type="button"
                onClick={() => void handleRun()}
                disabled={running || selectedYamls.length === 0}
                className="flex items-center gap-2 px-6 py-3 rounded-xl text-white font-medium shadow-lg hover:shadow-xl hover:scale-[1.02] transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                style={{ background: `linear-gradient(to right, var(--primary), var(--secondary))` }}
              >
                <Play className="w-4 h-4" fill="currentColor" />
                {running ? 'Başlatılıyor…' : `Çalıştır (${totalRuns} alt-run)`}
              </button>
              {batchId && (
                <button
                  type="button"
                  onClick={() => void refreshBatch()}
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

        {/* Batch sonuçları */}
        {batchDetail && batchDetail.runs.length > 0 && (
          <div className="bg-card rounded-2xl border border-border p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-medium" style={{ fontFamily: 'var(--font-display)' }}>
                Batch Sonuçları
              </h3>
              <code className="text-xs text-muted-foreground">batch: {batchDetail.batch_id}</code>
            </div>

            <div className="space-y-4">
              {batchDetail.runs.map((r) => (
                <div key={r.run_id} className="rounded-xl border border-border p-4 bg-background">
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <StatusBadge status={r.status} />
                        {r.variant_name && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-foreground border border-primary/20">
                            {r.variant_name}
                          </span>
                        )}
                      </div>
                      <code className="text-xs text-muted-foreground break-all">{r.yaml_path}</code>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleDownloadAll(r.run_id)}
                      disabled={r.outputs.length === 0}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg border-2 text-sm hover:bg-accent transition-colors disabled:opacity-40"
                      style={{ borderColor: 'var(--border)' }}
                    >
                      <Download className="w-4 h-4" />
                      Tümünü ZIP indir
                    </button>
                  </div>

                  {r.error && (
                    <div className="mb-3 px-3 py-2 rounded-lg text-xs bg-red-50 text-red-700 border border-red-200">
                      {r.error}
                    </div>
                  )}

                  {r.outputs.length > 0 && (
                    <div className="space-y-3">
                      <OutputPreviewGrid nodes={r.outputs} />
                      <OutputTree runId={r.run_id} nodes={r.outputs} />
                    </div>
                  )}
                </div>
              ))}
            </div>
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

      <YamlDrawer
        open={drawerOpen}
        kind={selectedKind}
        yamlPath={drawerYaml}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  )
}
