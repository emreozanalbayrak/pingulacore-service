import { useMemo, useState } from 'react'
import { RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'

import { api } from '../lib/api'
import type { AgentRunGetResponse, PipelineAgentLinkResponse } from '../types'
import { JsonPanel } from './JsonPanel'
import { StatusBadge } from './StatusBadge'

interface AgentRunsPanelProps {
  title: string
  links: PipelineAgentLinkResponse[]
  onRefresh: () => Promise<void>
}

type DetailedRun = AgentRunGetResponse & { agent_name: string; created_at: string }

export function AgentRunsPanel({ title, links, onRefresh }: AgentRunsPanelProps) {
  const [selected, setSelected] = useState<DetailedRun | null>(null)
  const [details, setDetails] = useState<DetailedRun[]>([])
  const [loadingAll, setLoadingAll] = useState(false)
  const [open, setOpen] = useState(false)

  const groupedByAttempt = useMemo(() => {
    const groups = new Map<number, DetailedRun[]>()
    for (const row of details) {
      const existing = groups.get(row.attempt_no) ?? []
      existing.push(row)
      groups.set(row.attempt_no, existing)
    }
    return [...groups.entries()].sort((a, b) => a[0] - b[0])
  }, [details])

  const openDetail = async (link: PipelineAgentLinkResponse) => {
    const detail = await api.getAgentRun(link.agent_name, link.agent_run_id)
    setSelected({ ...detail, agent_name: link.agent_name, created_at: link.created_at })
    setOpen(true)
  }

  const loadAllDetails = async () => {
    setLoadingAll(true)
    try {
      const rows = await Promise.all(
        links.map(async (link) => {
          const detail = await api.getAgentRun(link.agent_name, link.agent_run_id)
          return { ...detail, agent_name: link.agent_name, created_at: link.created_at }
        }),
      )
      setDetails(rows)
    } finally {
      setLoadingAll(false)
    }
  }

  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden mb-4">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-border"
        style={{ background: 'linear-gradient(to right, color-mix(in srgb, var(--accent) 40%, transparent), color-mix(in srgb, var(--muted) 40%, transparent))' }}>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 text-sm font-medium text-foreground hover:text-primary transition-colors bg-transparent border-0 p-0"
        >
          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          {title}
          {links.length > 0 && (
            <span className="ml-1 px-2 py-0.5 rounded-full text-xs bg-white/60 border border-border text-muted-foreground">
              {links.length}
            </span>
          )}
        </button>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void onRefresh()}
            className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs bg-white/70 border border-border hover:border-primary hover:bg-accent transition-all duration-200 text-foreground"
          >
            <RefreshCw className="w-3 h-3" />
            Yenile
          </button>
          <button
            type="button"
            onClick={() => void loadAllDetails()}
            disabled={loadingAll || links.length === 0}
            className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs bg-white/70 border border-border hover:border-primary hover:bg-accent transition-all duration-200 text-foreground disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loadingAll ? 'Yükleniyor...' : 'Detayları Yükle'}
          </button>
        </div>
      </div>

      {open && (
        <div className="p-4 space-y-3">
          {links.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">Henüz agent run yok.</p>
          ) : (
            <div className="space-y-2">
              {links.map((link) => (
                <button
                  key={`${link.agent_name}-${link.agent_run_id}`}
                  type="button"
                  onClick={() => void openDetail(link)}
                  className="w-full flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg border border-border bg-white/50 hover:border-primary hover:bg-accent transition-all duration-200 text-left"
                >
                  <span className="text-sm font-medium text-foreground">{link.agent_name}</span>
                  <span className="text-xs font-mono text-muted-foreground truncate max-w-[200px]">{link.agent_run_id}</span>
                  <span className="text-xs text-muted-foreground shrink-0">{link.created_at}</span>
                </button>
              ))}
            </div>
          )}

          {groupedByAttempt.length > 0 && (
            <div className="mt-4 space-y-3">
              <h4 className="text-sm font-medium text-foreground">Attempt Grupları</h4>
              {groupedByAttempt.map(([attempt, rows]) => (
                <div key={attempt} className="border border-dashed border-border rounded-xl p-4">
                  <h5 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
                    Attempt {attempt}
                  </h5>
                  <div className="space-y-1.5">
                    {rows.map((row) => (
                      <div key={`${row.agent_name}-${row.id}`}
                        className="flex items-center justify-between gap-3 px-3 py-1.5 rounded-lg bg-muted/50">
                        <span className="text-sm text-foreground">{row.agent_name}</span>
                        <StatusBadge status={row.status} />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {selected && (
            <JsonPanel title={`Run Detayı: ${selected.agent_name}`} data={selected} />
          )}
        </div>
      )}
    </div>
  )
}
