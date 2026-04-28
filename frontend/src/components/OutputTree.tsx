import { useState } from 'react'
import { ChevronDown, ChevronRight, Download, FileIcon, Folder, FolderOpen, Image as ImageIcon } from 'lucide-react'

import { downloadFromUrl } from '../lib/download'
import { api } from '../lib/api'
import type { LegacyOutputNode } from '../types'

function isImage(name: string): boolean {
  return /\.(png|jpe?g|gif|webp|svg)$/i.test(name)
}

function formatBytes(size: number | null | undefined): string {
  if (!size) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(2)} MB`
}

interface OutputTreeProps {
  runId: string
  nodes: LegacyOutputNode[]
}

interface NodeRowProps {
  node: LegacyOutputNode
  runId: string
  depth: number
}

function NodeRow({ node, runId, depth }: NodeRowProps) {
  const [open, setOpen] = useState(depth < 1)
  const [downloading, setDownloading] = useState(false)

  const handleDownloadFile = async () => {
    if (!node.url) return
    setDownloading(true)
    try {
      await downloadFromUrl(node.url, node.name)
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) {
        console.error(e)
      }
    } finally {
      setDownloading(false)
    }
  }

  const handleDownloadFolder = async () => {
    setDownloading(true)
    try {
      const url = api.getLegacyRunDownloadUrl(runId, node.rel_path)
      await downloadFromUrl(url, `${node.name || 'klasor'}.zip`)
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) {
        console.error(e)
      }
    } finally {
      setDownloading(false)
    }
  }

  if (node.type === 'dir') {
    const Icon = open ? FolderOpen : Folder
    const Chevron = open ? ChevronDown : ChevronRight
    return (
      <div className="select-none">
        <div
          className="flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-accent group"
          style={{ paddingLeft: depth * 16 + 8 }}
        >
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-1.5 flex-1 min-w-0 text-left"
          >
            <Chevron className="w-4 h-4 text-muted-foreground shrink-0" />
            <Icon className="w-4 h-4 shrink-0" style={{ color: 'var(--primary)' }} />
            <span className="text-sm truncate font-medium">{node.name}</span>
            <span className="text-xs text-muted-foreground">{node.children?.length ?? 0} öğe</span>
          </button>
          <button
            type="button"
            onClick={() => void handleDownloadFolder()}
            disabled={downloading}
            className="opacity-0 group-hover:opacity-100 flex items-center gap-1 text-xs px-2 py-1 rounded border border-border hover:bg-background transition-opacity disabled:opacity-30"
            title="Klasörü ZIP olarak indir"
          >
            <Download className="w-3 h-3" /> ZIP
          </button>
        </div>
        {open && node.children && (
          <div>
            {node.children.map((child) => (
              <NodeRow key={child.rel_path} node={child} runId={runId} depth={depth + 1} />
            ))}
          </div>
        )}
      </div>
    )
  }

  const FileIco = isImage(node.name) ? ImageIcon : FileIcon
  return (
    <div
      className="flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-accent group"
      style={{ paddingLeft: depth * 16 + 8 }}
    >
      <span className="w-4 shrink-0" />
      <FileIco className="w-4 h-4 shrink-0 text-muted-foreground" />
      {node.url ? (
        <a
          href={node.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm truncate flex-1 min-w-0 text-foreground hover:text-primary"
        >
          {node.name}
        </a>
      ) : (
        <span className="text-sm truncate flex-1 min-w-0">{node.name}</span>
      )}
      <span className="text-xs text-muted-foreground shrink-0">{formatBytes(node.size)}</span>
      {node.url && (
        <button
          type="button"
          onClick={() => void handleDownloadFile()}
          disabled={downloading}
          className="opacity-0 group-hover:opacity-100 flex items-center gap-1 text-xs px-2 py-1 rounded border border-border hover:bg-background transition-opacity disabled:opacity-30"
          title="Dosyayı indir (kaydetme yolunu seçebilirsin)"
        >
          <Download className="w-3 h-3" />
        </button>
      )}
    </div>
  )
}

export function OutputTree({ runId, nodes }: OutputTreeProps) {
  if (nodes.length === 0) {
    return <p className="text-sm text-muted-foreground">Henüz çıktı yok.</p>
  }
  return (
    <div className="border border-border rounded-xl bg-background overflow-hidden">
      {nodes.map((n) => (
        <NodeRow key={n.rel_path} node={n} runId={runId} depth={0} />
      ))}
    </div>
  )
}

interface OutputPreviewGridProps {
  nodes: LegacyOutputNode[]
}

/** Top-level image preview grid — directly displays any image files at the top of the tree. */
export function OutputPreviewGrid({ nodes }: OutputPreviewGridProps) {
  const flatImages: LegacyOutputNode[] = []
  const walk = (list: LegacyOutputNode[]) => {
    for (const n of list) {
      if (n.type === 'file' && isImage(n.name) && n.url) flatImages.push(n)
      if (n.type === 'dir' && n.children) walk(n.children)
    }
  }
  walk(nodes)
  if (flatImages.length === 0) return null
  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {flatImages.slice(0, 12).map((img) => (
        <div key={img.rel_path} className="rounded-xl border border-border p-2 bg-background">
          <a href={img.url ?? '#'} target="_blank" rel="noopener noreferrer">
            <img
              src={img.url ?? ''}
              alt={img.name}
              className="w-full rounded-lg border border-border"
              loading="lazy"
            />
          </a>
          <div className="mt-2 text-xs text-muted-foreground truncate">{img.rel_path}</div>
        </div>
      ))}
    </div>
  )
}
