import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Terminal } from 'lucide-react'

interface Props {
  lines: string[]
  connected: boolean
  done: boolean
  title: string
  active?: boolean
}

function levelClass(line: string): string {
  if (line.includes('[ERROR]')) return 'text-red-400'
  if (line.includes('[WARNING]')) return 'text-amber-400'
  if (line.includes('[DEBUG]')) return 'text-gray-500'
  return 'text-gray-300'
}

export function LogStreamPanel({ lines, connected, done, title, active = false }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const isAtBottomRef = useRef(true)
  const prevLinesLen = useRef(0)

  // Track unread when collapsed
  useEffect(() => {
    if (!expanded) {
      setUnreadCount(lines.length)
    }
  }, [lines.length, expanded])

  // Clear unread when expanded
  useEffect(() => {
    if (expanded) setUnreadCount(0)
  }, [expanded])

  // Auto-scroll to bottom when new lines arrive and user is at bottom
  useEffect(() => {
    if (!expanded) return
    if (lines.length === prevLinesLen.current) return
    prevLinesLen.current = lines.length
    if (isAtBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [lines.length, expanded])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }

  if (!active && lines.length === 0 && !connected) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
      {expanded && (
        <div
          className="w-[680px] max-h-[480px] flex flex-col rounded-2xl shadow-2xl border border-white/10 overflow-hidden"
          style={{ background: '#0f1117' }}
        >
          {/* Header */}
          <div
            className="flex items-center justify-between px-4 py-3 border-b border-white/10 shrink-0"
            style={{ background: '#1a1d27' }}
          >
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-gray-400" />
              <span className="text-sm font-medium text-gray-200">{title}</span>
              <span className="text-xs text-gray-500">({lines.length} lines)</span>
            </div>
            <div className="flex items-center gap-3">
              {connected && (
                <span className="flex items-center gap-1.5 text-xs text-green-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  live
                </span>
              )}
              {done && <span className="text-xs text-gray-500">done</span>}
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="text-gray-500 hover:text-gray-300 transition-colors"
              >
                <ChevronDown className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Log lines */}
          <div
            ref={containerRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto font-mono text-xs leading-5 p-3 space-y-px"
          >
            {lines.map((line, i) => (
              <div key={i} className={`whitespace-pre-wrap break-all ${levelClass(line)}`}>
                {line}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>
      )}

      {/* Toggle button */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 px-4 py-2 rounded-xl shadow-lg text-sm font-medium transition-all duration-200 hover:scale-[1.02]"
        style={{ background: connected ? '#1a2f1a' : '#1a1d27', border: '1px solid rgba(255,255,255,0.12)' }}
      >
        <Terminal className="w-4 h-4" style={{ color: connected ? '#4ade80' : active && !done ? '#f59e0b' : '#6b7280' }} />
        <span style={{ color: connected ? '#4ade80' : active && !done ? '#f59e0b' : '#9ca3af' }}>
          {connected ? 'Live Logs' : active && !done ? 'Connecting…' : 'Logs'}
        </span>
        {connected && <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />}
        {active && !connected && !done && (
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
        )}
        {!expanded && unreadCount > 0 && (
          <span className="px-1.5 py-0.5 text-xs rounded-full bg-white/10 text-gray-300">
            {unreadCount}
          </span>
        )}
        {expanded ? <ChevronDown className="w-3 h-3 text-gray-500" /> : <ChevronUp className="w-3 h-3 text-gray-500" />}
      </button>
    </div>
  )
}
