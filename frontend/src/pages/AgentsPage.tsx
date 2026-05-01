import { useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { Play, Bot, FileCode, Terminal, MessageSquare, RefreshCw, Code } from 'lucide-react'

import { HtmlViewer } from '../components/HtmlViewer'
import { JsonPanel } from '../components/JsonPanel'
import { LogStreamPanel } from '../components/LogStreamPanel'
import { StatusBadge } from '../components/StatusBadge'
import { useLogStream } from '../hooks/useLogStream'
import { ApiError, api } from '../lib/api'
import { pickHtmlContent } from '../lib/html'
import { randomUuid } from '../lib/uuid'
import type { AgentRunGetResponse, StandaloneAgentName, StandaloneAgentResponse } from '../types'

interface FieldConfig {
  key: string
  label: string
  kind: 'json' | 'text'
  defaultValue: string
}

interface AgentConfig {
  id: StandaloneAgentName
  label: string
  fields: FieldConfig[]
}

const AGENT_CONFIGS: AgentConfig[] = [
  {
    id: 'main_generate_question',
    label: 'Main / Generate Question',
    fields: [
      { key: 'yaml_content', label: 'YAML Content (JSON)', kind: 'json', defaultValue: '{\n  "meta": {"id": "q-demo"}\n}' },
      { key: 'feedback', label: 'Feedback', kind: 'text', defaultValue: '' },
    ],
  },
  {
    id: 'main_generate_layout',
    label: 'Main / Generate Layout',
    fields: [
      { key: 'question_json', label: 'Question JSON', kind: 'json', defaultValue: '{}' },
      { key: 'feedback', label: 'Feedback', kind: 'text', defaultValue: '' },
    ],
  },
  {
    id: 'main_generate_html',
    label: 'Main / Generate HTML',
    fields: [
      { key: 'question_json', label: 'Question JSON', kind: 'json', defaultValue: '{}' },
      { key: 'layout_plan_json', label: 'Layout Plan JSON', kind: 'json', defaultValue: '{}' },
      { key: 'asset_map', label: 'Asset Map JSON', kind: 'json', defaultValue: '{}' },
      { key: 'feedback', label: 'Feedback', kind: 'text', defaultValue: '' },
    ],
  },
  {
    id: 'validation_extract_rules',
    label: 'Validation / Extract Rules',
    fields: [{ key: 'yaml_content', label: 'YAML Content (JSON)', kind: 'json', defaultValue: '{}' }],
  },
  {
    id: 'validation_evaluate_rule',
    label: 'Validation / Evaluate Rule',
    fields: [
      { key: 'rule', label: 'Rule JSON', kind: 'json', defaultValue: '{"id": "R01", "category": "format", "text": "test"}' },
      { key: 'question_json', label: 'Question JSON', kind: 'json', defaultValue: '{}' },
    ],
  },
  {
    id: 'validation_question_layout',
    label: 'Validation / Question-Layout',
    fields: [
      { key: 'question_json', label: 'Question JSON', kind: 'json', defaultValue: '{}' },
      { key: 'layout_plan_json', label: 'Layout Plan JSON', kind: 'json', defaultValue: '{}' },
    ],
  },
  {
    id: 'validation_layout_html',
    label: 'Validation / Layout-HTML',
    fields: [
      { key: 'layout_plan_json', label: 'Layout Plan JSON', kind: 'json', defaultValue: '{}' },
      { key: 'html_content', label: 'HTML Content', kind: 'text', defaultValue: '<div>preview</div>' },
    ],
  },
  {
    id: 'helper_generate_composite_image',
    label: 'Helper / Composite Image',
    fields: [
      {
        key: 'asset',
        label: 'Asset JSON',
        kind: 'json',
        defaultValue:
          '{"slug": "demo_asset", "asset_type": "generated_composite", "description": "demo", "prompt": "demo", "output_filename": "demo_asset.png", "kind": "object", "transparent_background": false, "render_shape": "rectangle"}',
      },
    ],
  },
]

interface LocalRunItem {
  agent: StandaloneAgentName
  runId: string
  at: string
}

function buildDefaultValues(agent: AgentConfig): Record<string, string> {
  return Object.fromEntries(agent.fields.map((f) => [f.key, f.defaultValue]))
}

function buildPayload(agent: AgentConfig, values: Record<string, string>): Record<string, unknown> {
  return Object.fromEntries(
    agent.fields.map((f) => {
      const raw = values[f.key] ?? ''
      if (f.kind === 'json') return [f.key, JSON.parse(raw || '{}')]
      return [f.key, raw]
    }),
  )
}

export function AgentsPage() {
  const [agentId, setAgentId] = useState<StandaloneAgentName>('main_generate_question')
  const activeAgent = useMemo(() => AGENT_CONFIGS.find((r) => r.id === agentId) ?? AGENT_CONFIGS[0], [agentId])

  const [fieldValues, setFieldValues] = useState<Record<string, string>>(buildDefaultValues(activeAgent))
  const [advancedMode, setAdvancedMode] = useState(false)
  const [rawPayload, setRawPayload] = useState(JSON.stringify(buildPayload(activeAgent, fieldValues), null, 2))

  const [lastResponse, setLastResponse] = useState<StandaloneAgentResponse | null>(null)
  const [lastRunDetail, setLastRunDetail] = useState<AgentRunGetResponse | null>(null)
  const [runHistory, setRunHistory] = useState<LocalRunItem[]>([])
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [yamlFiles, setYamlFiles] = useState<string[]>([])
  const [selectedYamlFilename, setSelectedYamlFilename] = useState('')
  const { lines, connected, done, active, connect } = useLogStream()

  const selectAgent = (next: StandaloneAgentName) => {
    const config = AGENT_CONFIGS.find((item) => item.id === next) ?? AGENT_CONFIGS[0]
    const defaults = buildDefaultValues(config)
    setAgentId(next)
    setFieldValues(defaults)
    setRawPayload(JSON.stringify(buildPayload(config, defaults), null, 2))
    setError('')
  }

  const syncRawFromBasic = () => {
    try {
      setRawPayload(JSON.stringify(buildPayload(activeAgent, fieldValues), null, 2))
    } catch {
      setError('Basic form JSON alanlarında parse hatası var.')
    }
  }

  const refreshYamlFiles = async () => {
    setError('')
    try {
      const files = await api.listYamlFiles()
      setYamlFiles(files)
      if (files.length > 0) setSelectedYamlFilename(files[0])
      else setSelectedYamlFilename('')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'YAML dosya listesi alınamadı')
    }
  }

  const loadYamlContent = async () => {
    if (!selectedYamlFilename) {
      setError('YAML dosyası seçilmedi')
      return
    }
    setError('')
    try {
      const yamlData = await api.getYamlFileContent(selectedYamlFilename)
      const yamlText = JSON.stringify(yamlData, null, 2)
      setFieldValues((prev) => {
        const next = { ...prev, yaml_content: yamlText }
        if (!advancedMode) {
          try {
            setRawPayload(JSON.stringify(buildPayload(activeAgent, next), null, 2))
          } catch { /* keep raw as-is */ }
        }
        return next
      })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'YAML içeriği yüklenemedi')
    }
  }

  const run = async () => {
    setRunning(true)
    setError('')
    const key = randomUuid()
    connect(key)
    try {
      const payload = advancedMode
        ? (JSON.parse(rawPayload) as Record<string, unknown>)
        : buildPayload(activeAgent, fieldValues)
      const response = await api.runStandaloneAgent(activeAgent.id, { ...payload, stream_key: key })
      setLastResponse(response)
      const detail = await api.getAgentRun(activeAgent.id, response.run_id)
      setLastRunDetail(detail)
      setRunHistory((prev) => [{ agent: activeAgent.id, runId: response.run_id, at: new Date().toISOString() }, ...prev])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Agent çalıştırılamadı')
    } finally {
      setRunning(false)
    }
  }

  const openHistory = async (item: LocalRunItem) => {
    const detail = await api.getAgentRun(item.agent, item.runId)
    setLastRunDetail(detail)
  }

  const htmlOutput = pickHtmlContent(lastResponse?.result)

  const btnPrimary =
    'flex items-center gap-2 px-6 py-3 rounded-xl text-white font-medium shadow-lg hover:shadow-xl hover:scale-[1.02] transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100'
  const btnSecondary =
    'flex items-center gap-2 px-5 py-3 rounded-xl border-2 font-medium hover:bg-accent transition-all duration-200 text-sm'
  const labelClass = 'flex items-center gap-2 text-sm font-medium text-foreground'
  const inputClass = 'w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors font-mono text-sm resize-none'

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
            Standalone Agents
          </h1>
          <p className="text-muted-foreground">Run individual agents independently for testing</p>
        </div>

        {/* Error */}
        {error && (
          <div className="px-5 py-4 rounded-xl border text-sm bg-red-50 border-red-200 text-red-700">
            {error}
          </div>
        )}

        {/* Main Config Card */}
        <div className="bg-card rounded-2xl shadow-xl border border-border overflow-hidden">
          <div className="px-8 py-5 border-b border-border"
            style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}>
            <h2 className="text-xl" style={{ fontFamily: 'var(--font-display)' }}>
              Agent Configuration
            </h2>
          </div>

          <div className="p-8 space-y-6">
            {/* Agent Selector */}
            <div className="space-y-2">
              <label htmlFor="standalone-agent-select" className={labelClass}>
                <Bot className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                Agent
              </label>
              <select
                id="standalone-agent-select"
                value={agentId}
                onChange={(e) => selectAgent(e.target.value as StandaloneAgentName)}
                className="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors"
                style={{ borderColor: 'var(--border)' }}
              >
                {AGENT_CONFIGS.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
            </div>

            {/* Mode Toggle */}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => { setAdvancedMode((p) => !p); syncRawFromBasic() }}
                className={btnSecondary}
                style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
              >
                <Code className="w-4 h-4" />
                {advancedMode ? 'Basic Moda Dön' : 'Advanced JSON Aç'}
              </button>
            </div>

            {/* ── Basic Form ── */}
            {!advancedMode ? (
              <div className="rounded-xl border border-border p-6 space-y-5"
                style={{ background: 'linear-gradient(to bottom right, color-mix(in srgb, var(--accent) 30%, transparent), color-mix(in srgb, var(--muted) 30%, transparent))' }}>
                <h3 className="text-lg" style={{ fontFamily: 'var(--font-display)' }}>Basic Form</h3>

                {/* YAML loader — only for main_generate_question */}
                {activeAgent.id === 'main_generate_question' && (
                  <div className="space-y-3 pb-4 border-b border-border">
                    <div className="flex items-center justify-between">
                      <label className={labelClass}>
                        <FileCode className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                        Ortak YAML
                      </label>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => void refreshYamlFiles()}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg text-white shadow-sm"
                          style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
                        >
                          <RefreshCw className="w-3 h-3" />
                          YAML Listesini Yenile
                        </button>
                        <button
                          type="button"
                          onClick={() => void loadYamlContent()}
                          disabled={!selectedYamlFilename || yamlFiles.length === 0}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border-2 hover:bg-accent transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
                          style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
                        >
                          YAML İçeriğini Yükle
                        </button>
                      </div>
                    </div>
                    <select
                      value={selectedYamlFilename}
                      onChange={(e) => setSelectedYamlFilename(e.target.value)}
                      className="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors"
                      style={{ borderColor: 'var(--border)' }}
                    >
                      {yamlFiles.length === 0
                        ? <option value="">Önce listeyi yükleyin</option>
                        : yamlFiles.map((f) => <option key={f} value={f}>{f}</option>)
                      }
                    </select>
                  </div>
                )}

                {/* Dynamic Fields */}
                <div className="space-y-4">
                  {activeAgent.fields.map((field) => (
                    <div key={field.key} className="space-y-2">
                      <label className={labelClass}>
                        {field.kind === 'json'
                          ? <Terminal className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                          : <MessageSquare className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                        }
                        {field.label}
                      </label>
                      <textarea
                        rows={field.kind === 'json' ? 8 : 4}
                        spellCheck={false}
                        value={fieldValues[field.key] ?? ''}
                        onChange={(e) => setFieldValues((p) => ({ ...p, [field.key]: e.target.value }))}
                        className={inputClass}
                        style={{ borderColor: 'var(--border)' }}
                        placeholder={field.kind === 'json' ? '{}' : 'Optional...'}
                      />
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              /* ── Advanced JSON Mode ── */
              <div className="rounded-xl border border-border p-6 space-y-3"
                style={{ background: 'linear-gradient(to bottom right, color-mix(in srgb, var(--accent) 30%, transparent), color-mix(in srgb, var(--muted) 30%, transparent))' }}>
                <div className="flex items-center justify-between">
                  <h3 className="text-lg" style={{ fontFamily: 'var(--font-display)' }}>Advanced Raw JSON Payload</h3>
                  <button
                    type="button"
                    onClick={syncRawFromBasic}
                    className="text-xs px-3 py-1.5 rounded-lg border-2 hover:bg-accent transition-all duration-200"
                    style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
                  >
                    Raw Sync
                  </button>
                </div>
                <textarea
                  rows={16}
                  spellCheck={false}
                  value={rawPayload}
                  onChange={(e) => setRawPayload(e.target.value)}
                  className={inputClass}
                  style={{ borderColor: 'var(--border)' }}
                />
              </div>
            )}

            {/* Run Button */}
            <div>
              <button
                type="button"
                onClick={() => void run()}
                disabled={running}
                className={btnPrimary}
                style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
              >
                <Play className="w-4 h-4" fill="currentColor" />
                {running ? 'Çalışıyor...' : 'Agent Çalıştır'}
              </button>
            </div>
          </div>
        </div>

        {/* Results */}
        <div className="bg-card rounded-2xl border border-border overflow-hidden">
          <div className="px-8 py-5 border-b border-border"
            style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}>
            <h3 className="text-lg" style={{ fontFamily: 'var(--font-display)' }}>Agent Sonucu</h3>
          </div>
          <div className="p-6">
            {lastResponse ? (
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <span className="text-sm text-muted-foreground w-20">run_id</span>
                  <code className="text-xs bg-muted px-2 py-1 rounded-lg">{lastResponse.run_id}</code>
                  {lastRunDetail && <StatusBadge status={lastRunDetail.status} />}
                </div>
                <JsonPanel title="Result" data={lastResponse.result} size="large" />
                {lastRunDetail && <JsonPanel title="Run Detail" data={lastRunDetail} />}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground italic">Henüz sonuç yok.</p>
            )}
          </div>
        </div>

        {/* HTML Output */}
        {htmlOutput && <HtmlViewer title="Generated HTML" html={htmlOutput} />}

        {/* Log Stream */}
        <LogStreamPanel lines={lines} connected={connected} done={done} title="Agent Logs" active={active} />

        {/* Run History */}
        {runHistory.length > 0 && (
          <div className="bg-card rounded-2xl border border-border overflow-hidden">
            <div className="px-8 py-5 border-b border-border"
              style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}>
              <h3 className="text-lg" style={{ fontFamily: 'var(--font-display)' }}>Run Geçmişi</h3>
            </div>
            <div className="p-5 space-y-2">
              {runHistory.map((item) => (
                <button
                  key={`${item.agent}-${item.runId}`}
                  type="button"
                  onClick={() => void openHistory(item)}
                  className="w-full flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg border border-border bg-white/50 hover:border-primary hover:bg-accent transition-all duration-200 text-left"
                >
                  <span className="text-sm font-medium text-foreground">{item.agent}</span>
                  <code className="text-xs text-muted-foreground font-mono truncate max-w-[200px]">{item.runId}</code>
                  <span className="text-xs text-muted-foreground shrink-0">{item.at}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </motion.div>
    </div>
  )
}
