import { useMemo, useState } from 'react'
import { Copy, ChevronDown, ChevronRight, Check } from 'lucide-react'

interface JsonPanelProps {
  title: string
  data: unknown
  emptyText?: string
  size?: 'default' | 'large'
}

export function JsonPanel({ title, data, emptyText = 'Veri yok', size = 'default' }: JsonPanelProps) {
  const [open, setOpen] = useState(true)
  const [copied, setCopied] = useState(false)

  const text = useMemo(() => {
    if (data === undefined || data === null) return ''
    try {
      return JSON.stringify(data, null, 2)
    } catch {
      return String(data)
    }
  }, [data])

  const handleCopy = () => {
    if (text) {
      void navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden mb-4">
      <div className="flex items-center justify-between px-5 py-3 border-b border-border"
        style={{ background: 'linear-gradient(to right, color-mix(in srgb, var(--accent) 40%, transparent), color-mix(in srgb, var(--muted) 40%, transparent))' }}>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 text-sm font-medium text-foreground hover:text-primary transition-colors bg-transparent border-0 p-0"
        >
          {open
            ? <ChevronDown className="w-4 h-4" />
            : <ChevronRight className="w-4 h-4" />
          }
          {title}
        </button>
        <button
          type="button"
          onClick={handleCopy}
          disabled={!text}
          className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs bg-white/70 border border-border hover:border-primary hover:bg-accent transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ color: 'var(--foreground)' }}
        >
          {copied ? <Check className="w-3 h-3 text-green-600" /> : <Copy className="w-3 h-3" />}
          {copied ? 'Kopyalandı!' : 'Kopyala'}
        </button>
      </div>

      {open && (
        <div className={`overflow-auto ${size === 'large' ? 'max-h-[640px] min-h-[460px]' : 'max-h-80'}`}>
          {text ? (
            <pre className="p-4 text-xs font-mono bg-gray-50 text-gray-800 m-0 whitespace-pre-wrap break-all leading-relaxed">
              {text}
            </pre>
          ) : (
            <div className="p-4 text-sm text-muted-foreground italic">{emptyText}</div>
          )}
        </div>
      )}
    </div>
  )
}
