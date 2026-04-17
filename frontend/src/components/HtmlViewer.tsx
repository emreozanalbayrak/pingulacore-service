import { useMemo, useState } from 'react'
import { Code, Eye } from 'lucide-react'

import { rewriteRelativeAssetUrls } from '../lib/html'

interface HtmlViewerProps {
  html: string
  title?: string
  fillHeight?: boolean
}

export function HtmlViewer({ html, title = 'HTML Çıktısı', fillHeight = false }: HtmlViewerProps) {
  const [tab, setTab] = useState<'raw' | 'rendered'>('rendered')
  const rewritten = useMemo(() => rewriteRelativeAssetUrls(html), [html])

  return (
    <div className={`bg-card rounded-xl border border-border overflow-hidden ${fillHeight ? 'h-full flex flex-col' : 'mb-4'}`}>
      <div className="flex items-center justify-between px-5 py-3 border-b border-border"
        style={{ background: 'linear-gradient(to right, color-mix(in srgb, var(--accent) 40%, transparent), color-mix(in srgb, var(--muted) 40%, transparent))' }}>
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setTab('raw')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 border ${
              tab === 'raw'
                ? 'bg-secondary text-white border-secondary shadow-sm'
                : 'bg-white/70 border-border hover:border-secondary/40 text-foreground'
            }`}
          >
            <Code className="w-3 h-3" />
            Raw
          </button>
          <button
            type="button"
            onClick={() => setTab('rendered')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 border ${
              tab === 'rendered'
                ? 'bg-secondary text-white border-secondary shadow-sm'
                : 'bg-white/70 border-border hover:border-secondary/40 text-foreground'
            }`}
          >
            <Eye className="w-3 h-3" />
            Rendered
          </button>
        </div>
      </div>

      <div className={fillHeight ? 'flex-1 min-h-0' : ''}>
        {tab === 'raw' ? (
          <pre className={`p-4 text-xs font-mono text-gray-800 bg-gray-50 overflow-auto m-0 whitespace-pre-wrap ${fillHeight ? 'h-full max-h-none' : 'max-h-96'}`}>
            {html || 'Henüz HTML yok'}
          </pre>
        ) : (
          <iframe
            className={`w-full border-0 bg-white ${fillHeight ? 'h-full' : ''}`}
            style={fillHeight ? { minHeight: '320px' } : { minHeight: '320px' }}
            sandbox="allow-same-origin"
            title="HTML Preview"
            srcDoc={rewritten}
          />
        )}
      </div>
    </div>
  )
}
