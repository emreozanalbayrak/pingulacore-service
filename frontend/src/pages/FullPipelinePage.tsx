import { useEffect, useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { Play, RefreshCw, FileCode, Hash } from 'lucide-react'

import { AgentRunsPanel } from '../components/AgentRunsPanel'
import { HtmlIterationsPanel } from '../components/HtmlIterationsPanel'
import { HtmlLayoutEditor } from '../components/HtmlLayoutEditor'
import { HtmlViewer } from '../components/HtmlViewer'
import { Modal } from '../components/Modal'
import { JsonPanel } from '../components/JsonPanel'
import { LogStreamPanel } from '../components/LogStreamPanel'
import { PipelineLogsPanel } from '../components/PipelineLogsPanel'
import { StatusBadge } from '../components/StatusBadge'
import { useLogStream } from '../hooks/useLogStream'
import { usePolling } from '../hooks/usePolling'
import { ApiError, api } from '../lib/api'
import { pickHtmlContent, toAssetUrlFromPath } from '../lib/html'
import type {
  FullPipelineRunResponse,
  PipelineAgentLinkResponse,
  PipelineGetResponse,
  PipelineLogEntryResponse,
  RetryConfig,
  SubPipelineGetResponse,
} from '../types'

const EMPTY_RETRY: RetryConfig = {
  question_max_retries: 3,
  layout_max_retries: 3,
  html_max_retries: 3,
  image_max_retries: 2,
  rule_eval_parallelism: 4,
}

function toRetryConfig(input: RetryConfig): RetryConfig {
  const output: Record<string, number> = {}
  for (const [key, raw] of Object.entries(input)) {
    const value = Number(raw)
    if (Number.isFinite(value) && value > 0) {
      output[key] = value
    }
  }
  return output as RetryConfig
}

export function FullPipelinePage() {
  const [yamlFiles, setYamlFiles] = useState<string[]>([])
  const [yamlFilename, setYamlFilename] = useState('')
  const [retryConfig, setRetryConfig] = useState<RetryConfig>(EMPTY_RETRY)

  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const { lines, connected, done, active, renders, validations, connect } = useLogStream()

  const [response, setResponse] = useState<FullPipelineRunResponse | null>(null)
  const [pipeline, setPipeline] = useState<PipelineGetResponse | null>(null)
  const [pipelineRuns, setPipelineRuns] = useState<PipelineAgentLinkResponse[]>([])
  const [pipelineLogs, setPipelineLogs] = useState<PipelineLogEntryResponse[]>([])
  const [subPipelines, setSubPipelines] = useState<Record<string, SubPipelineGetResponse>>({})
  const [subPipelineLogs, setSubPipelineLogs] = useState<Record<string, PipelineLogEntryResponse[]>>({})

  useEffect(() => {
    void (async () => {
      try {
        const files = await api.listYamlFiles()
        setYamlFiles(files)
        if (!yamlFilename && files.length > 0) {
          setYamlFilename(files[0])
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'YAML listesi alınamadı')
      }
    })()
  }, [yamlFilename])

  const refreshAll = async (snapshot?: FullPipelineRunResponse | null): Promise<void> => {
    const source = snapshot ?? response
    if (!source) return

    const pipelineId = source.pipeline_id
    const entries = Object.entries(source.sub_pipeline_ids)

    const [pipelineData, links, logs] = await Promise.all([
      api.getPipeline(pipelineId),
      api.getPipelineAgentRuns(pipelineId),
      api.getPipelineLogs(pipelineId),
    ])

    const subRows = await Promise.all(
      entries.map(async ([name, id]) => {
        const [row, subLogs] = await Promise.all([api.getSubPipeline(id), api.getSubPipelineLogs(id)])
        return [name, { row, logs: subLogs }] as const
      }),
    )

    setPipeline(pipelineData)
    setPipelineRuns(links)
    setPipelineLogs(logs)
    setSubPipelines(Object.fromEntries(subRows.map(([name, payload]) => [name, payload.row])))
    setSubPipelineLogs(Object.fromEntries(subRows.map(([name, payload]) => [name, payload.logs])))
  }

  usePolling(
    () => refreshAll(),
    Boolean(response?.pipeline_id) && (pipeline?.status ?? 'running') === 'running',
    2500,
  )

  useEffect(() => {
    if (!response) return
    void refreshAll(response).catch((e) => {
      setError(e instanceof Error ? e.message : 'Pipeline durumu yenilenemedi')
    })
  }, [response?.pipeline_id])

  const run = async () => {
    if (!yamlFilename) {
      setError('YAML dosyası seçilmedi.')
      return
    }
    setRunning(true)
    setError('')
    const key = crypto.randomUUID()
    connect(key)
    try {
      const result = await api.runFullPipeline({
        yaml_filename: yamlFilename,
        retry_config: toRetryConfig(retryConfig),
        stream_key: key,
      })
      setResponse(result)
      await refreshAll(result)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Pipeline çalıştırılırken beklenmeyen bir hata oluştu.')
    } finally {
      setRunning(false)
    }
  }

  const [htmlOverrideMain, setHtmlOverrideMain] = useState<string | null>(null)
  const [editorOpenMain, setEditorOpenMain] = useState(false)
  const [subHtmlOverrides, setSubHtmlOverrides] = useState<Record<string, string>>({})
  const [editorOpenSub, setEditorOpenSub] = useState<string | null>(null)

  const rawHtmlFromResponse = useMemo(() => pickHtmlContent(response?.question_html), [response])
  const htmlFromResponse = htmlOverrideMain ?? rawHtmlFromResponse
  const fullRenderedImageUrl = useMemo(
    () => toAssetUrlFromPath(response?.rendered_image_path),
    [response?.rendered_image_path],
  )

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="space-y-6"
      >
        {/* Page Header */}
        <div>
          <h1 className="text-3xl mb-1" style={{ fontFamily: 'var(--font-display)' }}>
            Full Pipeline
          </h1>
          <p className="text-muted-foreground">Complete pipeline from YAML to HTML output</p>
        </div>

        {/* Configuration Card */}
        <div className="bg-card rounded-2xl shadow-xl border border-border overflow-hidden">
          <div className="px-8 py-5 border-b border-border"
            style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}>
            <h2 className="text-xl" style={{ fontFamily: 'var(--font-display)' }}>
              Pipeline Configuration
            </h2>
          </div>

          <div className="p-8 space-y-6">
            {/* YAML File */}
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                <FileCode className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                YAML Dosyası
              </label>
              <select
                value={yamlFilename}
                onChange={(e) => setYamlFilename(e.target.value)}
                className="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors"
                style={{ borderColor: 'var(--border)' }}
              >
                {yamlFiles.map((file) => (
                  <option key={file} value={file}>{file}</option>
                ))}
              </select>
            </div>

            {/* Retry Grid */}
            <div className="grid grid-cols-3 gap-5">
              {(
                [
                  { key: 'question_max_retries', label: 'Question Retry' },
                  { key: 'layout_max_retries', label: 'Layout Retry' },
                  { key: 'html_max_retries', label: 'HTML Retry' },
                ] as const
              ).map(({ key, label }) => (
                <div key={key} className="space-y-2">
                  <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <Hash className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                    {label}
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={retryConfig[key] ?? 3}
                    onChange={(e) => setRetryConfig((prev) => ({ ...prev, [key]: Number(e.target.value) }))}
                    className="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors text-center"
                    style={{ borderColor: 'var(--border)' }}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Footer Actions */}
          <div className="px-8 py-5 border-t border-border flex gap-3 bg-muted/20">
            <button
              type="button"
              onClick={() => void run()}
              disabled={running}
              className="flex items-center gap-2 px-6 py-3 rounded-xl text-white font-medium shadow-lg hover:shadow-xl hover:scale-[1.02] transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
              style={{ background: `linear-gradient(to right, var(--primary), var(--secondary))` }}
            >
              <Play className="w-4 h-4" fill="currentColor" />
              {running ? 'Çalışıyor...' : 'Full Pipeline Çalıştır'}
            </button>
            <button
              type="button"
              onClick={() => void refreshAll()}
              disabled={!response}
              className="flex items-center gap-2 px-6 py-3 rounded-xl border-2 font-medium hover:bg-accent transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
            >
              <RefreshCw className="w-4 h-4" />
              Refresh now
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="px-5 py-4 rounded-xl border text-sm bg-red-50 border-red-200 text-red-700">
            {error}
          </div>
        )}

        {/* HTML Iterations (real-time, visible even before pipeline finishes) */}
        <HtmlIterationsPanel renders={renders} validations={validations} running={running} />

        {/* Results Section */}
        {response && (
          <div className="space-y-4">
            {/* Pipeline Status */}
            <div className="bg-card rounded-2xl border border-border p-6">
              <h3 className="text-lg font-medium mb-3" style={{ fontFamily: 'var(--font-display)' }}>
                Pipeline Özeti
              </h3>
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-3">
                  <span className="text-muted-foreground w-28 shrink-0">pipeline_id</span>
                  <code className="text-xs bg-muted px-2 py-1 rounded-lg truncate">{response.pipeline_id}</code>
                </div>
                {pipeline && (
                  <div className="flex items-center gap-3">
                    <span className="text-muted-foreground w-28 shrink-0">Durum</span>
                    <StatusBadge status={pipeline.status} />
                  </div>
                )}
              </div>
            </div>

            {/* JSON Outputs */}
            <JsonPanel title="Question JSON" data={response.question_json} />
            <JsonPanel title="Layout Plan JSON" data={response.layout_plan_json} />

            {/* HTML Output */}
            {htmlFromResponse && (
              <>
                <HtmlViewer title="Full Pipeline HTML" html={htmlFromResponse} onEditClick={() => setEditorOpenMain(true)} />
                <Modal open={editorOpenMain} onClose={() => setEditorOpenMain(false)} size="full" title="HTML Layout Editor">
                  <HtmlLayoutEditor
                    html={htmlFromResponse}
                    onSave={(edited) => { setHtmlOverrideMain(edited); setEditorOpenMain(false) }}
                    onCancel={() => setEditorOpenMain(false)}
                  />
                </Modal>
              </>
            )}

            {/* Rendered Image */}
            {fullRenderedImageUrl && (
              <div className="bg-card rounded-xl border border-border p-5">
                <h3 className="text-sm font-medium text-foreground mb-3">Full Pipeline Final Render PNG</h3>
                <img
                  src={fullRenderedImageUrl}
                  alt="Full pipeline final render"
                  className="w-full rounded-lg border border-border"
                  style={{ maxWidth: 960 }}
                />
              </div>
            )}

            {/* Sub-Pipeline Cards */}
            <div className="bg-card rounded-2xl border border-border overflow-hidden">
              <div className="px-6 py-4 border-b border-border"
                style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}>
                <h3 className="text-lg" style={{ fontFamily: 'var(--font-display)' }}>
                  Sub-Pipeline Ara Çıktılar
                </h3>
              </div>
              <div className="p-6 space-y-6">
                {Object.entries(response.sub_pipeline_ids).map(([name, id]) => {
                  const row = subPipelines[name]
                  const rawHtml = pickHtmlContent((row?.output_json as Record<string, unknown> | undefined)?.html)
                  const html = subHtmlOverrides[name] ?? rawHtml
                  const subRenderedImagePath = (row?.output_json as Record<string, unknown> | undefined)?.rendered_image_path
                  const subRenderedImageUrlRaw =
                    typeof subRenderedImagePath === 'string' ? toAssetUrlFromPath(subRenderedImagePath) : ''
                  // Fall back to the parent pipeline's final render when the sub-pipeline output didn't store one.
                  const subRenderedImageUrl = subRenderedImageUrlRaw || fullRenderedImageUrl
                  return (
                    <div key={id} className="border border-border rounded-xl p-5">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="font-medium text-foreground">{name}</h4>
                        {row ? <StatusBadge status={row.status} /> : (
                          <span className="text-xs text-muted-foreground">Yükleniyor...</span>
                        )}
                      </div>
                      <code className="text-xs text-muted-foreground font-mono">{id}</code>
                      <div className="mt-3 space-y-2">
                        <JsonPanel title={`${name} Output`} data={row?.output_json} />
                        {name === 'layout_to_html' && html && (
                          <>
                            <HtmlViewer title="Ara Adım HTML" html={html} onEditClick={() => setEditorOpenSub(name)} />
                            <Modal open={editorOpenSub === name} onClose={() => setEditorOpenSub(null)} size="full" title="HTML Layout Editor">
                              <HtmlLayoutEditor
                                html={html}
                                onSave={(edited) => { setSubHtmlOverrides((prev) => ({ ...prev, [name]: edited })); setEditorOpenSub(null) }}
                                onCancel={() => setEditorOpenSub(null)}
                              />
                            </Modal>
                          </>
                        )}
                        {name === 'layout_to_html' && subRenderedImageUrl && (
                          <div className="p-4 border border-border rounded-lg">
                            <h5 className="text-xs font-medium text-foreground mb-2">Ara Adım Final Render PNG</h5>
                            <img
                              src={subRenderedImageUrl}
                              alt="Sub pipeline final render"
                              className="w-full rounded border border-border"
                              style={{ maxWidth: 960 }}
                            />
                          </div>
                        )}
                        <PipelineLogsPanel
                          title={`${name} Event Log`}
                          logs={subPipelineLogs[name] ?? []}
                          onRefresh={refreshAll}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Pipeline Logs & Agent Runs */}
            <PipelineLogsPanel title="Pipeline Event Logları" logs={pipelineLogs} onRefresh={refreshAll} />
            <AgentRunsPanel title="Pipeline Agent Runs" links={pipelineRuns} onRefresh={refreshAll} />
          </div>
        )}
        <LogStreamPanel lines={lines} connected={connected} done={done} title="Full Pipeline Logs" active={active} />
      </motion.div>
    </div>
  )
}
