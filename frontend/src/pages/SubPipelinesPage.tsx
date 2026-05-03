import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { Play, RefreshCw, FileCode, Hash } from 'lucide-react'

import { AgentRunsPanel } from '../components/AgentRunsPanel'
import { HtmlIterationsPanel } from '../components/HtmlIterationsPanel'
import { HtmlLayoutEditor } from '../components/HtmlLayoutEditor'
import { HtmlViewer } from '../components/HtmlViewer'
import { Modal } from '../components/Modal'
import { JsonPanel } from '../components/JsonPanel'
import { LayoutOutputDisplay } from '../components/LayoutOutputDisplay'
import { LogStreamPanel } from '../components/LogStreamPanel'
import { PipelineLogsPanel } from '../components/PipelineLogsPanel'
import { QuestionOutputDisplay } from '../components/QuestionOutputDisplay'
import { StatusBadge } from '../components/StatusBadge'
import { YamlInstanceCascadeSelector } from '../components/YamlInstanceCascadeSelector'
import { useLogStream } from '../hooks/useLogStream'
import { usePolling } from '../hooks/usePolling'
import { ApiError, api } from '../lib/api'
import { pickHtmlContent } from '../lib/html'
import type {
  ArtifactItem,
  CurriculumNodeItem,
  LayoutToHtmlRunResponse,
  PipelineLogEntryResponse,
  PipelineAgentLinkResponse,
  QuestionToLayoutRunResponse,
  RetryConfig,
  SubPipelineGetResponse,
  YamlInstanceItem,
  YamlTemplateItem,
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
  const [curriculumTree, setCurriculumTree] = useState<CurriculumNodeItem[]>([])
  const [yamlTemplates, setYamlTemplates] = useState<YamlTemplateItem[]>([])
  const [yamlInstances, setYamlInstances] = useState<YamlInstanceItem[]>([])
  const [yamlInstanceId, setYamlInstanceId] = useState('')
  const [questionArtifacts, setQuestionArtifacts] = useState<ArtifactItem[]>([])
  const [selectedQuestionArtifactId, setSelectedQuestionArtifactId] = useState('')
  const [selectedHtmlQuestionArtifactId, setSelectedHtmlQuestionArtifactId] = useState('')
  const [layoutArtifacts, setLayoutArtifacts] = useState<ArtifactItem[]>([])
  const [selectedLayoutArtifactId, setSelectedLayoutArtifactId] = useState('')
  const [retryConfig, setRetryConfig] = useState<RetryConfig>({
    question_max_retries: 3,
    layout_max_retries: 3,
    html_max_retries: 3,
    image_max_retries: 2,
    rule_eval_parallelism: 4,
  })

  const [yamlToQuestion, setYamlToQuestion] = useState<YamlToQuestionRunResponse | null>(null)
  const [questionToLayout, setQuestionToLayout] = useState<QuestionToLayoutRunResponse | null>(null)
  const [layoutToHtml, setLayoutToHtml] = useState<LayoutToHtmlRunResponse | null>(null)

  const [selectedQuestionArtifact, setSelectedQuestionArtifact] = useState<ArtifactItem | null>(null)
  const [selectedHtmlQuestionArtifact, setSelectedHtmlQuestionArtifact] = useState<ArtifactItem | null>(null)
  const [selectedLayoutArtifact, setSelectedLayoutArtifact] = useState<ArtifactItem | null>(null)

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
        const [tree, templates, yaml, questions, layouts] = await Promise.all([
          api.getCurriculumTree(),
          api.listYamlTemplates(),
          api.listYamlInstances(),
          api.listArtifacts('question'),
          api.listArtifacts('layout'),
        ])
        setCurriculumTree(tree)
        setYamlTemplates(templates)
        setYamlInstances(yaml)
        if (yaml.length > 0) setYamlInstanceId(yaml[0].id)
        setQuestionArtifacts(questions)
        if (questions.length > 0) {
          setSelectedQuestionArtifactId(questions[0].id)
          setSelectedHtmlQuestionArtifactId(questions[0].id)
        }
        setLayoutArtifacts(layouts)
        if (layouts.length > 0) setSelectedLayoutArtifactId(layouts[0].id)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'DB input listeleri alınamadı')
      }
    })()
  }, [])

  const refreshArtifacts = async () => {
    const [questions, layouts] = await Promise.all([
      api.listArtifacts('question'),
      api.listArtifacts('layout'),
    ])
    setQuestionArtifacts(questions)
    setLayoutArtifacts(layouts)
    if (!selectedQuestionArtifactId && questions.length > 0) setSelectedQuestionArtifactId(questions[0].id)
    if (!selectedHtmlQuestionArtifactId && questions.length > 0) setSelectedHtmlQuestionArtifactId(questions[0].id)
    if (!selectedLayoutArtifactId && layouts.length > 0) setSelectedLayoutArtifactId(layouts[0].id)
  }

  useEffect(() => {
    if (!questionArtifacts.some((item) => item.id === selectedQuestionArtifactId)) {
      setSelectedQuestionArtifactId(questionArtifacts[0]?.id ?? '')
    }
  }, [questionArtifacts, selectedQuestionArtifactId])

  useEffect(() => {
    if (!questionArtifacts.some((item) => item.id === selectedHtmlQuestionArtifactId)) {
      setSelectedHtmlQuestionArtifactId(questionArtifacts[0]?.id ?? '')
    }
  }, [questionArtifacts, selectedHtmlQuestionArtifactId])

  useEffect(() => {
    if (!layoutArtifacts.some((item) => item.id === selectedLayoutArtifactId)) {
      setSelectedLayoutArtifactId(layoutArtifacts[0]?.id ?? '')
    }
  }, [layoutArtifacts, selectedLayoutArtifactId])

  useEffect(() => {
    if (!selectedQuestionArtifactId) {
      setSelectedQuestionArtifact(null)
      return
    }
    void api.getArtifact(selectedQuestionArtifactId)
      .then(setSelectedQuestionArtifact)
      .catch(() => setSelectedQuestionArtifact(null))
  }, [selectedQuestionArtifactId])

  useEffect(() => {
    if (!selectedHtmlQuestionArtifactId) {
      setSelectedHtmlQuestionArtifact(null)
      return
    }
    void api.getArtifact(selectedHtmlQuestionArtifactId)
      .then(setSelectedHtmlQuestionArtifact)
      .catch(() => setSelectedHtmlQuestionArtifact(null))
  }, [selectedHtmlQuestionArtifactId])

  useEffect(() => {
    if (!selectedLayoutArtifactId) {
      setSelectedLayoutArtifact(null)
      return
    }
    void api.getArtifact(selectedLayoutArtifactId)
      .then(setSelectedLayoutArtifact)
      .catch(() => setSelectedLayoutArtifact(null))
  }, [selectedLayoutArtifactId])

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
    if (!yamlInstanceId) {
      setError('YAML instance seçilmedi')
      return
    }
    const key = crypto.randomUUID()
    connect(key)
    try {
      const result = await api.runSubYamlToQuestion({
        yaml_instance_id: yamlInstanceId,
        retry_config: toRetryConfig(retryConfig),
        stream_key: key,
      })
      setYamlToQuestion(result)
      setSelectedQuestionArtifactId(result.question_artifact_id)
      setSelectedHtmlQuestionArtifactId(result.question_artifact_id)
      await refreshStep('yaml', result.sub_pipeline_id)
      await refreshArtifacts()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'YAML → Question hatası')
    }
  }

  const runQuestionToLayout = async () => {
    setError('')
    if (!selectedQuestionArtifactId) {
      setError('Question artifact seçilmedi')
      return
    }
    const key = crypto.randomUUID()
    connect(key)
    try {
      const result = await api.runSubQuestionToLayout({
        question_artifact_id: selectedQuestionArtifactId,
        retry_config: toRetryConfig(retryConfig),
        stream_key: key,
      })
      setQuestionToLayout(result)
      setSelectedLayoutArtifactId(result.layout_artifact_id)
      await refreshStep('layout', result.sub_pipeline_id)
      await refreshArtifacts()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Question → Layout hatası')
    }
  }

  const runLayoutToHtml = async () => {
    setError('')
    setHtmlRunning(true)
    if (!selectedHtmlQuestionArtifactId || !selectedLayoutArtifactId) {
      setError('Question ve layout artifact seçimi gerekli')
      setHtmlRunning(false)
      return
    }
    const key = crypto.randomUUID()
    connect(key)
    try {
      const result = await api.runSubLayoutToHtml({
        question_artifact_id: selectedHtmlQuestionArtifactId,
        layout_artifact_id: selectedLayoutArtifactId,
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

  const [htmlOverride, setHtmlOverride] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)

  const htmlOutput = htmlOverride ?? pickHtmlContent(layoutToHtml?.question_html)
  const stepYamlOutput = asRecord(stepYaml.detail?.output_json)
  const stepLayoutOutput = asRecord(stepLayout.detail?.output_json)
  const yamlQuestionOutput = yamlToQuestion?.question_json ?? asRecord(stepYamlOutput?.question) ?? undefined
  const questionLayoutOutput = questionToLayout?.layout_plan_json ?? asRecord(stepLayoutOutput?.layout) ?? undefined
  const stepHtmlOutput = (stepHtml.detail?.output_json as Record<string, unknown> | undefined) ?? undefined
  const renderedImageArtifactId =
    layoutToHtml?.rendered_image_artifact_id ??
    (typeof stepHtmlOutput?.rendered_image_artifact_id === 'string' ? stepHtmlOutput.rendered_image_artifact_id : null)
  const renderedImageUrl = renderedImageArtifactId ? `/v1/assets/${encodeURIComponent(renderedImageArtifactId)}` : ''
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
                    <div className={labelClass}>
                      <FileCode className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                      YAML Instance
                    </div>
                    <YamlInstanceCascadeSelector
                      curriculumTree={curriculumTree}
                      templates={yamlTemplates}
                      instances={yamlInstances}
                      value={yamlInstanceId}
                      onChange={setYamlInstanceId}
                      selectClassName={selectClass}
                      inputClassName={selectClass}
                    />
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
                  <button type="button" onClick={() => void refreshArtifacts()}
                    className={btnSecondary} style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                    Artifact Listesini Yenile
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
                    <label className={labelClass}>Question Artifact</label>
                    <select
                      value={selectedQuestionArtifactId}
                      onChange={(e) => setSelectedQuestionArtifactId(e.target.value)}
                      className={selectClass}
                      style={{ borderColor: 'var(--border)' }}
                    >
                      {questionArtifacts.length === 0
                        ? <option value="">Question artifact yok</option>
                        : questionArtifacts.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.id}
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
                </div>
                <JsonPanel
                  title="Question Artifact İçeriği"
                  data={(selectedQuestionArtifact?.content_json as Record<string, unknown> | null) ?? null}
                />

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
                    <label className={labelClass}>Question Artifact</label>
                    <select
                      value={selectedHtmlQuestionArtifactId}
                      onChange={(e) => setSelectedHtmlQuestionArtifactId(e.target.value)}
                      className={selectClass}
                      style={{ borderColor: 'var(--border)' }}
                    >
                      {questionArtifacts.length === 0
                        ? <option value="">Question artifact yok</option>
                        : questionArtifacts.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.id}
                          </option>
                        ))
                      }
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className={labelClass}>Layout Artifact</label>
                    <select
                      value={selectedLayoutArtifactId}
                      onChange={(e) => setSelectedLayoutArtifactId(e.target.value)}
                      className={selectClass}
                      style={{ borderColor: 'var(--border)' }}
                    >
                      {layoutArtifacts.length === 0
                        ? <option value="">Layout artifact yok</option>
                        : layoutArtifacts.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.id}
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
                </div>
                <JsonPanel
                  title="Question Artifact İçeriği"
                  data={(selectedHtmlQuestionArtifact?.content_json as Record<string, unknown> | null) ?? null}
                />
                <JsonPanel
                  title="Layout Artifact İçeriği"
                  data={(selectedLayoutArtifact?.content_json as Record<string, unknown> | null) ?? null}
                />

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
