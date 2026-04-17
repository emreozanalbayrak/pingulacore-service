import { useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Copy,
  FolderTree,
  Grid3X3,
  Image as ImageIcon,
  Layers,
} from 'lucide-react'

interface Props {
  data: unknown
  title?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function asText(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

interface TreeNode {
  slug: string
  node_type: string
  bindings: unknown[]
  children: TreeNode[]
}

function toTreeNode(value: unknown): TreeNode | null {
  if (!isRecord(value)) return null
  return {
    slug: asText(value.slug) || 'node',
    node_type: asText(value.node_type) || 'container',
    bindings: asArray(value.bindings),
    children: asArray(value.children).map((child) => toTreeNode(child)).filter((v): v is TreeNode => v !== null),
  }
}

function LayoutTree({ node, depth = 0 }: { node: TreeNode; depth?: number }) {
  const [open, setOpen] = useState(depth < 1)
  const hasChildren = node.children.length > 0

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left rounded-lg border border-border bg-white/70 hover:bg-accent/40 transition-colors px-3 py-2"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0">
            {hasChildren ? (
              open ? <ChevronDown className="w-4 h-4 shrink-0" /> : <ChevronRight className="w-4 h-4 shrink-0" />
            ) : (
              <span className="w-4 h-4 shrink-0" />
            )}
            <FolderTree className="w-4 h-4 text-primary shrink-0" />
            <span className="text-sm font-medium truncate">{node.slug}</span>
            <span className="text-xs text-muted-foreground">({node.node_type})</span>
          </div>
          <span className="text-xs px-2 py-1 rounded bg-muted text-muted-foreground shrink-0">
            bindings: {node.bindings.length}
          </span>
        </div>
      </button>

      {open && (
        <div className={`${depth > 0 ? 'ml-6' : 'ml-3'} space-y-2`}>
          {node.bindings.length > 0 && (
            <div className="rounded-lg border border-border bg-white/50 p-3 space-y-2">
              {node.bindings.map((binding, idx) => {
                const b = isRecord(binding) ? binding : {}
                return (
                  <div key={idx} className="text-xs rounded border border-border bg-accent/20 px-2 py-1.5 flex flex-wrap items-center gap-2">
                    <span className="font-medium">{asText(b.asset_slug) || 'asset'}</span>
                    <span className="text-muted-foreground">layer: {asText(b.layer) || 'content'}</span>
                    <span className="text-muted-foreground">z: {asText(b.z_index) || '0'}</span>
                    <span className="text-muted-foreground">repeat: {asText(b.repeat) || '1'}</span>
                  </div>
                )
              })}
            </div>
          )}

          {node.children.map((child, idx) => (
            <LayoutTree key={`${child.slug}-${idx}`} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

export function LayoutOutputDisplay({ data, title = 'Layout Output' }: Props) {
  const [showRawJson, setShowRawJson] = useState(false)
  const [copied, setCopied] = useState(false)
  const rawJson = useMemo(() => JSON.stringify(data ?? {}, null, 2), [data])
  const layout = isRecord(data) ? data : null

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(rawJson)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  if (!layout) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-base">{title}</h3>
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="px-4 py-2 rounded-lg bg-muted border border-border hover:border-primary hover:bg-accent transition-all duration-200 flex items-center gap-2"
          >
            <Copy className="w-4 h-4" />
            <span className="text-sm">{copied ? 'Kopyalandı!' : 'Kopyala'}</span>
          </button>
        </div>
        <div className="bg-white/50 rounded-xl border-2 border-border p-4">
          <pre className="text-sm text-muted-foreground whitespace-pre-wrap font-mono">
            {rawJson}
          </pre>
        </div>
      </div>
    )
  }

  const assetLibrary = isRecord(layout.asset_library) ? layout.asset_library : {}
  const assetEntries = Object.entries(assetLibrary)
  const treeRoot = toTreeNode(layout.html_layout)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-base">{title}</h3>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setShowRawJson((v) => !v)}
            className="px-4 py-2 rounded-lg bg-white border border-border hover:border-primary transition-all duration-200 flex items-center gap-2"
          >
            {showRawJson ? <ChevronRight className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            <span className="text-sm">Raw JSON</span>
          </button>
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="px-4 py-2 rounded-lg bg-muted border border-border hover:border-primary hover:bg-accent transition-all duration-200 flex items-center gap-2"
          >
            <Copy className="w-4 h-4" />
            <span className="text-sm">{copied ? 'Kopyalandı!' : 'Kopyala'}</span>
          </button>
        </div>
      </div>

      {showRawJson && (
        <div className="bg-white/50 rounded-xl border-2 border-border p-4">
          <pre className="text-sm text-muted-foreground whitespace-pre-wrap font-mono">
            {rawJson}
          </pre>
        </div>
      )}

      {!showRawJson && (
        <div className="bg-gradient-to-br from-white to-accent/20 rounded-xl border-2 border-border overflow-hidden">
          <div className="bg-gradient-to-r from-primary/10 to-secondary/10 px-6 py-4 border-b border-border">
            <div className="flex items-start justify-between">
              <div>
                <h4 className="text-lg mb-1" style={{ fontFamily: 'var(--font-display)' }}>
                  {asText(layout.question_id) || 'no_question_id'}
                </h4>
                <div className="flex gap-3 text-xs">
                  <span className="px-2 py-1 rounded bg-primary/20 text-primary">
                    {asText(layout.schema_version) || 'layout-plan.v2'}
                  </span>
                  <span className="px-2 py-1 rounded bg-secondary/20 text-secondary">
                    assets: {assetEntries.length}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="p-6 space-y-6">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <ImageIcon className="w-4 h-4 text-primary" />
                <h5 className="text-sm text-foreground">Asset Library</h5>
              </div>
              {assetEntries.length === 0 ? (
                <div className="text-sm text-muted-foreground bg-white/50 rounded-lg border border-border p-3">
                  Asset bulunamadı.
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {assetEntries.map(([slug, asset]) => {
                    const a = isRecord(asset) ? asset : {}
                    return (
                      <div key={slug} className="rounded-lg border border-border bg-white/70 p-3 space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium truncate">{slug}</span>
                          <span className="text-xs px-2 py-0.5 rounded bg-accent text-muted-foreground">
                            {asText(a.asset_type) || 'unknown'}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground space-y-1">
                          {asText(a.description) && <p>desc: {asText(a.description)}</p>}
                          {asText(a.source_filename) && <p>source: {asText(a.source_filename)}</p>}
                          {asText(a.output_filename) && <p>output: {asText(a.output_filename)}</p>}
                          {asText(a.render_shape) && <p>shape: {asText(a.render_shape)}</p>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            <div>
              <div className="flex items-center gap-2 mb-3">
                <Layers className="w-4 h-4 text-primary" />
                <h5 className="text-sm text-foreground">Layout Tree</h5>
              </div>
              <div className="rounded-lg border border-border bg-white/50 p-3">
                {treeRoot ? <LayoutTree node={treeRoot} /> : (
                  <div className="text-sm text-muted-foreground">html_layout bulunamadı.</div>
                )}
              </div>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-2">
                <Grid3X3 className="w-4 h-4 text-primary" />
                <h5 className="text-sm text-foreground">Summary</h5>
              </div>
              <div className="rounded-lg border border-border bg-white/70 p-3 text-sm text-muted-foreground">
                <p>Total assets: {assetEntries.length}</p>
                <p>Root bindings: {treeRoot?.bindings.length ?? 0}</p>
                <p>Root children: {treeRoot?.children.length ?? 0}</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
