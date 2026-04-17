import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import {
  File,
  FileJson,
  Folder,
  FolderOpen,
  Image as ImageIcon,
  RefreshCw,
  Search,
  Star,
  Trash2,
} from 'lucide-react'

import { HtmlViewer } from '../components/HtmlViewer'
import { JsonPanel } from '../components/JsonPanel'
import { ApiError, api } from '../lib/api'
import type { ExplorerFileReadResponse, ExplorerRoot, ExplorerTreeNode } from '../types'

type TreeMap = Record<ExplorerRoot, ExplorerTreeNode[]>

interface SelectedFile {
  root: ExplorerRoot
  path: string
  node: ExplorerTreeNode
}

function nodeKey(root: ExplorerRoot, path: string) {
  return `${root}:${path}`
}

function findNodeByPath(nodes: ExplorerTreeNode[], target: string): ExplorerTreeNode | null {
  for (const node of nodes) {
    if (node.path === target) return node
    const children = node.children ?? []
    const found = findNodeByPath(children, target)
    if (found) return found
  }
  return null
}

function collectExpandedKeys(root: ExplorerRoot, nodes: ExplorerTreeNode[]): string[] {
  const keys: string[] = []
  for (const node of nodes) {
    if (node.kind !== 'dir') continue
    keys.push(nodeKey(root, node.path))
    keys.push(...collectExpandedKeys(root, node.children ?? []))
  }
  return keys
}

function filterTree(nodes: ExplorerTreeNode[], search: string, favoritesOnly: boolean): ExplorerTreeNode[] {
  const term = search.trim().toLowerCase()
  const next: ExplorerTreeNode[] = []

  for (const node of nodes) {
    if (node.kind === 'dir') {
      const children = filterTree(node.children ?? [], search, favoritesOnly)
      const matchesSearch = term === '' || node.name.toLowerCase().includes(term)
      if (children.length > 0 || (matchesSearch && !favoritesOnly)) {
        next.push({ ...node, children })
      }
      continue
    }

    const matchesSearch = term === '' || node.name.toLowerCase().includes(term)
    const matchesFavorite = !favoritesOnly || node.is_favorite
    if (matchesSearch && matchesFavorite) next.push(node)
  }

  return next
}

function parseError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return fallback
}

export function FilesPage() {
  const [trees, setTrees] = useState<TreeMap>({ runs: [], sp_files: [] })
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['runs:', 'sp_files:']))
  const [selected, setSelected] = useState<SelectedFile | null>(null)
  const [preview, setPreview] = useState<ExplorerFileReadResponse | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [showOnlyFavorites, setShowOnlyFavorites] = useState(false)
  const [treePanelWidth, setTreePanelWidth] = useState(420)
  const [isResizing, setIsResizing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const splitContainerRef = useRef<HTMLDivElement | null>(null)

  const btnPrimary =
    'flex items-center gap-2 px-5 py-3 rounded-xl text-white font-medium shadow-lg hover:shadow-xl hover:scale-[1.02] transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed'
  const btnSecondary =
    'flex items-center gap-2 px-4 py-2.5 rounded-xl border-2 font-medium hover:bg-accent transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed'

  const refreshTrees = async (): Promise<TreeMap> => {
    setError('')
    const [runs, spFiles] = await Promise.all([api.getExplorerTree('runs'), api.getExplorerTree('sp_files')])
    const next = { runs: runs.items, sp_files: spFiles.items }
    setTrees(next)
    setExpanded(
      new Set([
        'runs:',
        'sp_files:',
        ...collectExpandedKeys('runs', next.runs),
        ...collectExpandedKeys('sp_files', next.sp_files),
      ]),
    )
    return next
  }

  useEffect(() => {
    void (async () => {
      setBusy(true)
      try {
        await refreshTrees()
      } catch (e) {
        setError(parseError(e, 'Dosya ağacı yüklenemedi'))
      } finally {
        setBusy(false)
      }
    })()
  }, [])

  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (event: MouseEvent) => {
      const container = splitContainerRef.current
      if (!container) return
      const rect = container.getBoundingClientRect()
      const nextWidth = Math.max(280, Math.min(760, event.clientX - rect.left))
      setTreePanelWidth(nextWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [isResizing])

  const filteredTrees = useMemo(
    () => ({
      runs: filterTree(trees.runs, searchTerm, showOnlyFavorites),
      sp_files: filterTree(trees.sp_files, searchTerm, showOnlyFavorites),
    }),
    [trees, searchTerm, showOnlyFavorites],
  )

  const toggleExpanded = (root: ExplorerRoot, path: string) => {
    const key = nodeKey(root, path)
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const handleSelectFile = async (root: ExplorerRoot, node: ExplorerTreeNode) => {
    const nextSelected: SelectedFile = { root, path: node.path, node }
    setSelected(nextSelected)
    setPreview(null)
    setBusy(true)
    setError('')
    try {
      const data = await api.getExplorerFile(root, node.path)
      setPreview(data)
    } catch (e) {
      setError(parseError(e, 'Dosya açılamadı'))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!selected) return
    const ok = window.confirm(`"${selected.path}" dosyası silinsin mi?`)
    if (!ok) return

    setBusy(true)
    setError('')
    try {
      await api.deleteExplorerFile(selected.root, selected.path)
      await refreshTrees()
      setSelected(null)
      setPreview(null)
    } catch (e) {
      setError(parseError(e, 'Dosya silinemedi'))
    } finally {
      setBusy(false)
    }
  }

  const handleFavoriteToggle = async () => {
    if (!selected || !selected.node.favoritable) return
    setBusy(true)
    setError('')
    try {
      await api.setExplorerFavorite({
        root: selected.root,
        path: selected.path,
        is_favorite: !selected.node.is_favorite,
      })
      const nextTrees = await refreshTrees()
      setSelected((prev) => {
        if (!prev) return null
        const node = findNodeByPath((prev.root === 'runs' ? nextTrees.runs : nextTrees.sp_files), prev.path)
        if (!node) return prev
        return { ...prev, node }
      })
    } catch (e) {
      setError(parseError(e, 'Favori durumu güncellenemedi'))
    } finally {
      setBusy(false)
    }
  }

  const renderNode = (root: ExplorerRoot, node: ExplorerTreeNode, depth = 0) => {
    const selectedKey = selected ? nodeKey(selected.root, selected.path) : ''
    const key = nodeKey(root, node.path)
    const isSelected = selectedKey === key
    const isOpen = expanded.has(key)

    if (node.kind === 'dir') {
      return (
        <div key={key}>
          <button
            type="button"
            onClick={() => toggleExpanded(root, node.path)}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-accent text-left"
            style={{ paddingLeft: `${8 + depth * 16}px` }}
          >
            {isOpen ? <FolderOpen className="w-4 h-4 text-primary" /> : <Folder className="w-4 h-4 text-primary" />}
            <span className="text-sm text-foreground">{node.name}</span>
          </button>
          {isOpen && (
            <div>
              {(node.children ?? []).map((child) => renderNode(root, child, depth + 1))}
            </div>
          )}
        </div>
      )
    }

    const icon = node.name.endsWith('.json')
      ? <FileJson className="w-4 h-4 text-secondary" />
      : node.name.endsWith('.png')
        ? <ImageIcon className="w-4 h-4 text-secondary" />
        : <File className="w-4 h-4 text-secondary" />

    return (
      <button
        key={key}
        type="button"
        onClick={() => void handleSelectFile(root, node)}
        title={node.name}
        className={`w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg text-left ${
          isSelected ? 'bg-accent border border-primary/30' : 'hover:bg-accent/60'
        }`}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        <span className="flex items-center gap-2 min-w-0">
          {icon}
          <span className="text-sm text-foreground truncate">{node.name}</span>
        </span>
        {node.is_favorite && <Star className="w-3.5 h-3.5 text-amber-500 fill-amber-400 shrink-0" />}
      </button>
    )
  }

  const previewPanel = (() => {
    if (!selected) return <div className="text-sm text-muted-foreground">Soldan bir dosya seç.</div>
    if (!preview || preview.path !== selected.path || preview.root !== selected.root) {
      return <div className="text-sm text-muted-foreground">Önizleme yükleniyor...</div>
    }

    if (preview.content_type === 'json') {
      return <JsonPanel title="JSON Preview" data={preview.content} size="large" />
    }
    if (preview.content_type === 'html') {
      return <HtmlViewer html={String(preview.content ?? '')} title="HTML Preview" fillHeight />
    }
    if (preview.content_type === 'text') {
      return (
        <pre className="p-4 text-xs font-mono bg-gray-50 text-gray-800 rounded-xl border border-border overflow-auto max-h-[640px] whitespace-pre-wrap">
          {String(preview.content ?? '')}
        </pre>
      )
    }
    if (preview.content_type === 'image') {
      const src = preview.asset_url
        ? preview.asset_url
        : `data:${preview.mime_type ?? 'application/octet-stream'};base64,${String(preview.content ?? '')}`
      return (
        <div className="p-4 border border-border rounded-xl bg-white">
          <img src={src} alt={preview.filename} className="w-full rounded border border-border" style={{ maxWidth: 960 }} />
        </div>
      )
    }
    return <div className="text-sm text-muted-foreground">Bu dosya türü için önizleme desteklenmiyor.</div>
  })()

  return (
    <div className="p-8 max-w-[1700px] mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="space-y-6"
      >
        <div>
          <h1 className="text-3xl mb-1" style={{ fontFamily: 'var(--font-display)' }}>
            Files & Favorites
          </h1>
          <p className="text-muted-foreground">runs ve sp_files içeriklerini ağaç görünümünde yönet.</p>
        </div>

        {error && (
          <div className="px-5 py-4 rounded-xl border text-sm bg-red-50 border-red-200 text-red-700">
            {error}
          </div>
        )}

        <div ref={splitContainerRef} className="flex flex-col gap-6 lg:flex-row lg:items-stretch">
          <div
            className="bg-card rounded-2xl border border-border p-4 space-y-4 w-full lg:shrink-0"
            style={{ width: `min(100%, ${treePanelWidth}px)` }}
          >
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative flex-1 min-w-[180px]">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <input
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  placeholder="Dosya ara..."
                  className="w-full pl-9 pr-3 py-2 rounded-xl border border-border bg-white text-sm"
                />
              </div>
              <button
                type="button"
                onClick={() => void refreshTrees()}
                disabled={busy}
                className={btnSecondary}
                style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
              >
                <RefreshCw className="w-4 h-4" /> Yenile
              </button>
            </div>

            <label className="inline-flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={showOnlyFavorites}
                onChange={(e) => setShowOnlyFavorites(e.target.checked)}
              />
              Sadece favoriler
            </label>

            <div className="space-y-4 max-h-[70vh] overflow-auto pr-1">
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">runs</div>
                <div className="space-y-0.5">
                  {filteredTrees.runs.map((node) => renderNode('runs', node))}
                  {filteredTrees.runs.length === 0 && <div className="text-xs text-muted-foreground px-2">Kayıt yok</div>}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">sp_files</div>
                <div className="space-y-0.5">
                  {filteredTrees.sp_files.map((node) => renderNode('sp_files', node))}
                  {filteredTrees.sp_files.length === 0 && <div className="text-xs text-muted-foreground px-2">Kayıt yok</div>}
                </div>
              </div>
            </div>
          </div>

          <button
            type="button"
            aria-label="Tree panelini yeniden boyutlandır"
            onMouseDown={() => setIsResizing(true)}
            className={`hidden lg:block w-1 rounded-full cursor-col-resize transition-colors ${
              isResizing ? 'bg-primary/70' : 'bg-border hover:bg-primary/50'
            }`}
          />

          <div className="bg-card rounded-2xl border border-border p-5 min-w-0 flex-1 flex flex-col gap-4 min-h-[72vh]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg text-foreground" style={{ fontFamily: 'var(--font-display)' }}>
                  Preview
                </h2>
                <p className="text-xs text-muted-foreground">
                  {selected ? `${selected.root}/${selected.path}` : 'Dosya seçilmedi'}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void handleDelete()}
                  disabled={!selected || busy}
                  className={btnSecondary}
                  style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
                >
                  <Trash2 className="w-4 h-4" /> Sil
                </button>
                <button
                  type="button"
                  onClick={() => void handleFavoriteToggle()}
                  disabled={!selected || !selected.node.favoritable || busy}
                  title={!selected?.node?.favoritable ? 'Sadece question/layout JSON ve render*.png favorilenebilir.' : undefined}
                  className={btnPrimary}
                  style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
                >
                  <Star className={`w-4 h-4 ${selected?.node?.is_favorite ? 'fill-white' : ''}`} />
                  {selected?.node?.is_favorite ? 'Favoriden Çıkar' : 'Favorile'}
                </button>
              </div>
            </div>
            <div className="flex-1 min-h-0">
              {previewPanel}
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
