import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { Play, RefreshCw, FileCode, Hash } from 'lucide-react'

import { AgentRunsPanel } from '../components/AgentRunsPanel'
import { HtmlIterationsPanel } from '../components/HtmlIterationsPanel'
import { HtmlLayoutEditor } from '../components/HtmlLayoutEditor'
import { HtmlViewer } from '../components/HtmlViewer'
import { Modal } from '../components/Modal'
import { JsonEditor } from '../components/JsonEditor'
import { LayoutOutputDisplay } from '../components/LayoutOutputDisplay'
import { LogStreamPanel } from '../components/LogStreamPanel'
import { PipelineLogsPanel } from '../components/PipelineLogsPanel'
import { QuestionOutputDisplay } from '../components/QuestionOutputDisplay'
import { StatusBadge } from '../components/StatusBadge'
import { useLogStream } from '../hooks/useLogStream'
import { usePolling } from '../hooks/usePolling'
import { ApiError, api } from '../lib/api'
import { pickHtmlContent, toAssetUrlFromPath } from '../lib/html'
import type {
  LayoutToHtmlRunResponse,
  PipelineLogEntryResponse,
  PipelineAgentLinkResponse,
  QuestionToLayoutRunResponse,
  RetryConfig,
  StoredJsonFileItem,
  SubPipelineGetResponse,
  YamlToQuestionRunResponse,
} from '../types'

interface StepState {
  id: string
  detail: SubPipelineGetResponse | null
  links: PipelineAgentLinkResponse[]
  logs: PipelineLogEntryResponse[]
}

type SubTab = 'yaml' | 'layout' | 'html'

const EMPTY_STEP: StepState = { id: '', detail: null, links: [], logs: [] }

function parseJson(text: string): Record<string, unknown> {
  return JSON.parse(text) as Record<string, unknown>
}

function toRetryConfig(input: RetryConfig): RetryConfig {
  const output: Record<string, number> = {}
  for (const [key, raw] of Object.entries(input)) {
    const value = Number(raw)
    if (Number.isFinite(value) && value > 0) output[key] = value
  }
  return output as RetryConfig
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

const tabs: { id: SubTab; label: string }[] = [
  { id: 'yaml', label: 'YAML → Question' },
  { id: 'layout', label: 'Question → Layout' },
  { id: 'html', label: 'Layout → HTML' },
]

export function SubPipelinesPage() {
  const [yamlFiles, setYamlFiles] = useState<string[]>([])
  const [yamlFilename, setYamlFilename] = useState('')
  const [storedQuestionFiles, setStoredQuestionFiles] = useState<StoredJsonFileItem[]>([])
  const [selectedQuestionFile, setSelectedQuestionFile] = useState('')
  const [selectedHtmlQuestionFile, setSelectedHtmlQuestionFile] = useState('')
  const [storedLayoutFiles, setStoredLayoutFiles] = useState<StoredJsonFileItem[]>([])
  const [selectedLayoutFile, setSelectedLayoutFile] = useState('')
  const [retryConfig, setRetryConfig] = useState<RetryConfig>({
    question_max_retries: 3,
    layout_max_retries: 3,
    html_max_retries: 3,
    image_max_retries: 2,
    rule_eval_parallelism: 4,
  })

  const [questionInput, setQuestionInput] = useState('{}')
  const [htmlQuestionInput, setHtmlQuestionInput] = useState('{}')
  const [layoutInput, setLayoutInput] = useState('{}')

  const [yamlToQuestion, setYamlToQuestion] = useState<YamlToQuestionRunResponse | null>(null)
  const [questionToLayout, setQuestionToLayout] = useState<QuestionToLayoutRunResponse | null>(null)
  const [layoutToHtml, setLayoutToHtml] = useState<LayoutToHtmlRunResponse | null>(null)

  const [stepYaml, setStepYaml] = useState<StepState>(EMPTY_STEP)
  const [stepLayout, setStepLayout] = useState<StepState>(EMPTY_STEP)
  const [stepHtml, setStepHtml] = useState<StepState>(EMPTY_STEP)
  const [activeTab, setActiveTab] = useState<SubTab>('yaml')
  const [error, setError] = useState('')
  const { lines, connected, done, active, renders, validations, connect } = useLogStream()
  const [htmlRunning, setHtmlRunning] = useState(false)

  useEffect(() => {
    void (async () => {
      try {
        const [yaml, questionFiles, layoutFiles] = await Promise.all([
          api.listYamlFiles(),
          api.listStoredQuestionFiles(),
          api.listStoredLayoutFiles(),
        ])
        setYamlFiles(yaml)
        if (yaml.length > 0) setYamlFilename(yaml[0])
        setStoredQuestionFiles(questionFiles)
        if (questionFiles.length > 0) {
          setSelectedQuestionFile(questionFiles[0].filename)
          setSelectedHtmlQuestionFile(questionFiles[0].filename)
        }
        setStoredLayoutFiles(layoutFiles)
        if (layoutFiles.length > 0) setSelectedLayoutFile(layoutFiles[0].filename)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Dosya listeleri alınamadı')
      }
    })()
  }, [])

  const refreshStoredFiles = async () => {
    const [questionFiles, layoutFiles] = await Promise.all([
      api.listStoredQuestionFiles(),
      api.listStoredLayoutFiles(),
    ])
    setStoredQuestionFiles(questionFiles)
    setStoredLayoutFiles(layoutFiles)
    if (!selectedQuestionFile && questionFiles.length > 0) setSelectedQuestionFile(questionFiles[0].filename)
    if (!selectedHtmlQuestionFile && questionFiles.length > 0) setSelectedHtmlQuestionFile(questionFiles[0].filename)
    if (!selectedLayoutFile && layoutFiles.length > 0) setSelectedLayoutFile(layoutFiles[0].filename)
  }

  useEffect(() => {
    if (!storedQuestionFiles.some((item) => item.filename === selectedQuestionFile)) {
      setSelectedQuestionFile(storedQuestionFiles[0]?.filename ?? '')
    }
  }, [storedQuestionFiles, selectedQuestionFile])

  useEffect(() => {
    if (!storedQuestionFiles.some((item) => item.filename === selectedHtmlQuestionFile)) {
      setSelectedHtmlQuestionFile(storedQuestionFiles[0]?.filename ?? '')
    }
  }, [storedQuestionFiles, selectedHtmlQuestionFile])

  useEffect(() => {
    if (!storedLayoutFiles.some((item) => item.filename === selectedLayoutFile)) {
      setSelectedLayoutFile(storedLayoutFiles[0]?.filename ?? '')
    }
  }, [storedLayoutFiles, selectedLayoutFile])

  const refreshStep = async (kind: 'yaml' | 'layout' | 'html', id: string) => {
    const [detail, links, logs] = await Promise.all([
      api.getSubPipeline(id),
      api.getSubPipelineAgentRuns(id),
      api.getSubPipelineLogs(id),
    ])
    if (kind === 'yaml') setStepYaml({ id, detail, links, logs })
    else if (kind === 'layout') setStepLayout({ id, detail, links, logs })
    else setStepHtml({ id, detail, links, logs })
  }

  const refreshAll = async () => {
    const jobs: Array<Promise<void>> = []
    if (stepYaml.id) jobs.push(refreshStep('yaml', stepYaml.id))
    if (stepLayout.id) jobs.push(refreshStep('layout', stepLayout.id))
    if (stepHtml.id) jobs.push(refreshStep('html', stepHtml.id))
    await Promise.all(jobs)
  }

  const hasRunningStep = [stepYaml, stepLayout, stepHtml].some((s) => s.detail?.status === 'running')
  usePolling(() => refreshAll(), hasRunningStep, 2500)

  const runYamlToQuestion = async () => {
    setError('')
    const key = crypto.randomUUID()
    connect(key)
    try {
      const result = await api.runSubYamlToQuestion({
        yaml_filename: yamlFilename,
        retry_config: toRetryConfig(retryConfig),
        stream_key: key,
      })
      setYamlToQuestion(result)
      const next = JSON.stringify(result.question_json, null, 2)
      setQuestionInput(next)
      setHtmlQuestionInput(next)
      await refreshStep('yaml', result.sub_pipeline_id)
      await refreshStoredFiles()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'YAML → Question hatası')
    }
  }

  const runQuestionToLayout = async () => {
    setError('')
    const key = crypto.randomUUID()
    connect(key)
    try {
      const questionJson = parseJson(questionInput)
      setHtmlQuestionInput(JSON.stringify(questionJson, null, 2))
      const result = await api.runSubQuestionToLayout({
        question_json: questionJson,
        retry_config: toRetryConfig(retryConfig),
        stream_key: key,
      })
      setQuestionToLayout(result)
      setLayoutInput(JSON.stringify(result.layout_plan_json, null, 2))
      await refreshStep('layout', result.sub_pipeline_id)
      await refreshStoredFiles()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Question → Layout hatası')
    }
  }

  const runLayoutToHtml = async () => {
    setError('')
    setHtmlRunning(true)
    const key = crypto.randomUUID()
    connect(key)
    try {
      const questionJson = parseJson(htmlQuestionInput)
      const layoutJson = parseJson(layoutInput)
      const result = await api.runSubLayoutToHtml({
        question_json: questionJson,
        layout_plan_json: layoutJson,
        retry_config: toRetryConfig(retryConfig),
        stream_key: key,
      })
      setLayoutToHtml(result)
      await refreshStep('html', result.sub_pipeline_id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Layout → HTML hatası')
    } finally {
      setHtmlRunning(false)
    }
  }

  const loadStoredQuestionInput = async () => {
    if (!selectedQuestionFile) return
    setError('')
    try {
      const data = await api.getStoredQuestionFile(selectedQuestionFile)
      setQuestionInput(JSON.stringify(data, null, 2))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Question dosyası yüklenemedi')
    }
  }

  const loadStoredQuestionInputForHtml = async () => {
    if (!selectedHtmlQuestionFile) return
    setError('')
    try {
      const data = await api.getStoredQuestionFile(selectedHtmlQuestionFile)
      setHtmlQuestionInput(JSON.stringify(data, null, 2))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Question dosyası yüklenemedi')
    }
  }

  const loadStoredLayoutInput = async () => {
    if (!selectedLayoutFile) return
    setError('')
    try {
      const data = await api.getStoredLayoutFile(selectedLayoutFile)
      setLayoutInput(JSON.stringify(data, null, 2))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Layout dosyası yüklenemedi')
    }
  }

  const [htmlOverride, setHtmlOverride] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)

  const htmlOutput = htmlOverride ?? pickHtmlContent(layoutToHtml?.question_html)
  const stepYamlOutput = asRecord(stepYaml.detail?.output_json)
  const stepLayoutOutput = asRecord(stepLayout.detail?.output_json)
  const yamlQuestionOutput = yamlToQuestion?.question_json ?? asRecord(stepYamlOutput?.question) ?? undefined
  const questionLayoutOutput = questionToLayout?.layout_plan_json ?? asRecord(stepLayoutOutput?.layout) ?? undefined
  const stepHtmlOutput = (stepHtml.detail?.output_json as Record<string, unknown> | undefined) ?? undefined
  const renderedImagePath =
    layoutToHtml?.rendered_image_path ??
    (typeof stepHtmlOutput?.rendered_image_path === 'string' ? stepHtmlOutput.rendered_image_path : null)
  const renderedImageUrl = toAssetUrlFromPath(renderedImagePath)

  const btnPrimary =
    'flex items-center gap-2 px-6 py-3 rounded-xl text-white font-medium shadow-lg hover:shadow-xl hover:scale-[1.02] transition-all duration-200'
  const btnSecondary =
    'flex items-center gap-2 px-5 py-3 rounded-xl border-2 font-medium hover:bg-accent transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed'
  const selectClass =
    'w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors'
  const labelClass = 'flex items-center gap-2 text-sm font-medium text-foreground'
  return (
    <div className="p-8 max-w-5xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="space-y-6"
      >
        {/* Header */}
        <div>
          <h1 className="text-3xl mb-1" style={{ fontFamily: 'var(--font-display)' }}>
            Sub-Pipelines
          </h1>
          <p className="text-muted-foreground">Individual pipeline stages for granular control</p>
        </div>

        {/* Error */}
        {error && (
          <div className="px-5 py-4 rounded-xl border text-sm bg-red-50 border-red-200 text-red-700">
            {error}
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-2 flex-wrap">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`px-6 py-3 rounded-xl text-sm font-medium transition-all duration-200 border-2 ${
                activeTab === tab.id
                  ? 'text-white shadow-lg border-transparent'
                  : 'bg-white border-border hover:border-primary text-foreground'
              }`}
              style={activeTab === tab.id
                ? { background: `linear-gradient(to right, var(--primary), var(--secondary))`, borderColor: 'transparent' }
                : {}
              }
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content Card */}
        <div className="bg-card rounded-2xl shadow-xl border border-border overflow-hidden">
          {/* Card Header */}
          <div className="px-8 py-5 border-b border-border"
            style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}>
            <div className="flex items-center gap-3">
              <h2 className="text-xl" style={{ fontFamily: 'var(--font-display)' }}>
                {activeTab === 'yaml' && '1) YAML → Question'}
                {activeTab === 'layout' && '2) Question → Layout'}
                {activeTab === 'html' && '3) Layout → HTML'}
              </h2>
              {activeTab === 'yaml' && stepYaml.detail && <StatusBadge status={stepYaml.detail.status} />}
              {activeTab === 'layout' && stepLayout.detail && <StatusBadge status={stepLayout.detail.status} />}
              {activeTab === 'html' && stepHtml.detail && <StatusBadge status={stepHtml.detail.status} />}
            </div>
          </div>

          <div className="p-8 space-y-6">

            {/* ── YAML → Question ─────────────────────────────── */}
            {activeTab === 'yaml' && (
              <>
                <div className="grid grid-cols-2 gap-5">
                  <div className="space-y-2">
                    <label className={labelClass}>
                      <FileCode className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                      YAML Dosyası
                    </label>
                    <select
                      value={yamlFilename}
                      onChange={(e) => setYamlFilename(e.target.value)}
                      className={selectClass}
                      style={{ borderColor: 'var(--border)' }}
                    >
                      {yamlFiles.map((f) => <option key={f} value={f}>{f}</option>)}
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className={labelClass}>
                      <Hash className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                      Question Retry
                    </label>
                    <input
                      type="number"
                      min={1}
                      value={retryConfig.question_max_retries ?? 3}
                      onChange={(e) => setRetryConfig((p) => ({ ...p, question_max_retries: Number(e.target.value) }))}
                      className={`${selectClass} text-center`}
                      style={{ borderColor: 'var(--border)' }}
                    />
                  </div>
                </div>

                <div className="flex gap-3 flex-wrap">
                  <button type="button" onClick={() => void refreshAll()}
                    className={btnSecondary} style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                    <RefreshCw className="w-4 h-4" /> Refresh now
                  </button>
                  <button type="button" onClick={() => void refreshStoredFiles()}
                    className={btnSecondary} style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                    Dosya Listesini Yenile
                  </button>
                  <button type="button" onClick={() => void runYamlToQuestion()}
                    className={btnPrimary}
                    style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}>
                    <Play className="w-4 h-4" fill="currentColor" /> Çalıştır
                  </button>
                </div>

                <QuestionOutputDisplay data={yamlQuestionOutput} title="Question Output" />

                {stepYaml.id && (
                  <>
                    <PipelineLogsPanel title="Step-1 Event Log" logs={stepYaml.logs}
                      onRefresh={() => refreshStep('yaml', stepYaml.id)} />
                    <AgentRunsPanel title="Step-1 Agent Runs" links={stepYaml.links}
                      onRefresh={() => refreshStep('yaml', stepYaml.id)} />
                  </>
                )}
              </>
            )}

            {/* ── Question → Layout ────────────────────────────── */}
            {activeTab === 'layout' && (
              <>
                <div className="grid grid-cols-3 gap-5">
                  <div className="space-y-2">
                    <label className={labelClass}>Kayıtlı Question</label>
                    <select
                      value={selectedQuestionFile}
                      onChange={(e) => setSelectedQuestionFile(e.target.value)}
                      className={selectClass}
                      style={{ borderColor: 'var(--border)' }}
                    >
                      {storedQuestionFiles.length === 0
                        ? <option value="">Kayıtlı dosya yok</option>
                        : storedQuestionFiles.map((f) => (
                          <option key={f.filename} value={f.filename}>
                            {f.filename}
                          </option>
                        ))
                      }
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className={labelClass}>
                      <Hash className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                      Layout Retry
                    </label>
                    <input
                      type="number"
                      min={1}
                      value={retryConfig.layout_max_retries ?? 3}
                      onChange={(e) => setRetryConfig((p) => ({ ...p, layout_max_retries: Number(e.target.value) }))}
                      className={`${selectClass} text-center`}
                      style={{ borderColor: 'var(--border)' }}
                    />
                  </div>
                </div>

                <div className="flex gap-3 flex-wrap">
                  <button type="button" onClick={() => void refreshAll()}
                    className={btnSecondary} style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                    <RefreshCw className="w-4 h-4" /> Refresh now
                  </button>
                  <button
                    type="button"
                    onClick={() => void loadStoredQuestionInput()}
                    disabled={!selectedQuestionFile || storedQuestionFiles.length === 0}
                    className={btnSecondary}
                    style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
                  >
                    Question Dosyasını Yükle
                  </button>
                </div>

                <JsonEditor label="Question JSON Input" value={questionInput} onChange={setQuestionInput} />

                <button type="button" onClick={() => void runQuestionToLayout()}
                  className={btnPrimary}
                  style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}>
                  <Play className="w-4 h-4" fill="currentColor" /> Çalıştır
                </button>

                <LayoutOutputDisplay data={questionLayoutOutput} title="Layout Output" />

                {stepLayout.id && (
                  <>
                    <PipelineLogsPanel title="Step-2 Event Log" logs={stepLayout.logs}
                      onRefresh={() => refreshStep('layout', stepLayout.id)} />
                    <AgentRunsPanel title="Step-2 Agent Runs" links={stepLayout.links}
                      onRefresh={() => refreshStep('layout', stepLayout.id)} />
                  </>
                )}
              </>
            )}

            {/* ── Layout → HTML ────────────────────────────────── */}
            {activeTab === 'html' && (
              <>
                <div className="grid grid-cols-3 gap-5">
                  <div className="space-y-2">
                    <label className={labelClass}>Kayıtlı Question</label>
                    <select
                      value={selectedHtmlQuestionFile}
                      onChange={(e) => setSelectedHtmlQuestionFile(e.target.value)}
                      className={selectClass}
                      style={{ borderColor: 'var(--border)' }}
                    >
                      {storedQuestionFiles.length === 0
                        ? <option value="">Kayıtlı dosya yok</option>
                        : storedQuestionFiles.map((f) => (
                          <option key={f.filename} value={f.filename}>
                            {f.filename}
                          </option>
                        ))
                      }
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className={labelClass}>Kayıtlı Layout</label>
                    <select
                      value={selectedLayoutFile}
                      onChange={(e) => setSelectedLayoutFile(e.target.value)}
                      className={selectClass}
                      style={{ borderColor: 'var(--border)' }}
                    >
                      {storedLayoutFiles.length === 0
                        ? <option value="">Kayıtlı dosya yok</option>
                        : storedLayoutFiles.map((f) => (
                          <option key={f.filename} value={f.filename}>
                            {f.filename}
                          </option>
                        ))
                      }
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className={labelClass}>
                      <Hash className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                      HTML Retry
                    </label>
                    <input
                      type="number"
                      min={1}
                      value={retryConfig.html_max_retries ?? 3}
                      onChange={(e) => setRetryConfig((p) => ({ ...p, html_max_retries: Number(e.target.value) }))}
                      className={`${selectClass} text-center`}
                      style={{ borderColor: 'var(--border)' }}
                    />
                  </div>
                </div>

                <div className="flex gap-3 flex-wrap">
                  <button type="button" onClick={() => void refreshAll()}
                    className={btnSecondary} style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                    <RefreshCw className="w-4 h-4" /> Refresh now
                  </button>
                  <button
                    type="button"
                    onClick={() => void loadStoredQuestionInputForHtml()}
                    disabled={!selectedHtmlQuestionFile || storedQuestionFiles.length === 0}
                    className={btnSecondary}
                    style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
                  >
                    Question Dosyasını Yükle
                  </button>
                  <button
                    type="button"
                    onClick={() => void loadStoredLayoutInput()}
                    disabled={!selectedLayoutFile || storedLayoutFiles.length === 0}
                    className={btnSecondary}
                    style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
                  >
                    Layout Dosyasını Yükle
                  </button>
                </div>

                <JsonEditor label="Question JSON Input" value={htmlQuestionInput} onChange={setHtmlQuestionInput} />
                <JsonEditor label="Layout JSON Input" value={layoutInput} onChange={setLayoutInput} />

                <button type="button" onClick={() => void runLayoutToHtml()}
                  className={btnPrimary}
                  style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}>
                  <Play className="w-4 h-4" fill="currentColor" /> Çalıştır
                </button>

                {/* HTML Iterations (real-time) */}
                <HtmlIterationsPanel renders={renders} validations={validations} running={htmlRunning} />

{htmlOutput && (
                  <>
                    <HtmlViewer html={htmlOutput} title="Sub-Pipeline HTML Preview" onEditClick={() => setEditorOpen(true)} />
                    <Modal open={editorOpen} onClose={() => setEditorOpen(false)} size="full" title="HTML Layout Editor">
                      <HtmlLayoutEditor
                        html={htmlOutput}
                        onSave={(edited) => { setHtmlOverride(edited); setEditorOpen(false) }}
                        onCancel={() => setEditorOpen(false)}
                      />
                    </Modal>
                  </>
                )}
                {renderedImageUrl && (
                  <div className="p-4 border border-border rounded-xl bg-white">
                    <h4 className="text-sm font-medium text-foreground mb-3">Final Render PNG</h4>
                    <img
                      src={renderedImageUrl}
                      alt="Final rendered question"
                      className="w-full rounded border border-border"
                      style={{ maxWidth: 960 }}
                    />
                  </div>
                )}

                {stepHtml.id && (
                  <>
                    <PipelineLogsPanel title="Step-3 Event Log" logs={stepHtml.logs}
                      onRefresh={() => refreshStep('html', stepHtml.id)} />
                    <AgentRunsPanel title="Step-3 Agent Runs" links={stepHtml.links}
                      onRefresh={() => refreshStep('html', stepHtml.id)} />
                  </>
                )}
              </>
            )}
          </div>
        </div>
        <LogStreamPanel lines={lines} connected={connected} done={done} title="Sub-Pipeline Logs" active={active} />
      </motion.div>
    </div>
  )
}
