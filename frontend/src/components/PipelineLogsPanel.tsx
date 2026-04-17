import { useState } from 'react'
import { RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'

import type { PipelineLogEntryResponse } from '../types'
import { JsonPanel } from './JsonPanel'

interface PipelineLogsPanelProps {
  title: string
  logs: PipelineLogEntryResponse[]
  onRefresh: () => Promise<void>
}

const levelClasses: Record<string, string> = {
  error: 'bg-red-50 border-red-200 text-red-700',
  warning: 'bg-amber-50 border-amber-200 text-amber-700',
  warn: 'bg-amber-50 border-amber-200 text-amber-700',
  info: 'bg-blue-50 border-blue-200 text-blue-700',
  debug: 'bg-gray-50 border-gray-200 text-gray-600',
}

function getLevelClasses(level: string) {
  return levelClasses[level.toLowerCase()] ?? 'bg-gray-50 border-gray-200 text-gray-600'
}

export function PipelineLogsPanel({ title, logs, onRefresh }: PipelineLogsPanelProps) {
  const [open, setOpen] = useState(false)

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
          {logs.length > 0 && (
            <span className="ml-1 px-2 py-0.5 rounded-full text-xs bg-white/60 border border-border text-muted-foreground">
              {logs.length}
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={() => void onRefresh()}
          className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs bg-white/70 border border-border hover:border-primary hover:bg-accent transition-all duration-200 text-foreground"
        >
          <RefreshCw className="w-3 h-3" />
          Yenile
        </button>
      </div>

      {open && (
        <div className="p-4 space-y-2 max-h-[480px] overflow-auto">
          {logs.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">Henüz log yok.</p>
          ) : (
            logs.map((row) => (
              <div key={row.id} className="space-y-1">
                <div className={`flex flex-wrap items-start gap-2 px-3 py-2 rounded-lg border text-xs ${getLevelClasses(row.level)}`}>
                  <span className="font-mono shrink-0 opacity-70">{row.created_at}</span>
                  <span className="font-semibold shrink-0 uppercase">[{row.component}]</span>
                  <span className="flex-1">{row.message}</span>
                </div>
                {row.details != null && (
                  <JsonPanel title={`Detay #${row.id}`} data={row.details} />
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
