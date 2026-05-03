import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, MapPinned, Plus } from 'lucide-react'

import type { CurriculumNodeItem, CurriculumNodeScope, YamlTemplateItem } from '../types'

interface CurriculumTreePickerProps {
  nodes: CurriculumNodeItem[]
  selectedId?: string
  onSelect?: (node: CurriculumNodeItem) => void
  onClearSelection?: () => void
  selectableScopes?: CurriculumNodeScope[]
  title?: string
  emptyText?: string
  fullHeight?: boolean
  templates?: YamlTemplateItem[]
  selectedTemplateId?: string
  onSelectTemplate?: (template: YamlTemplateItem) => void
  onAddTemplate?: (node: CurriculumNodeItem) => void
  onManageProperties?: (node: CurriculumNodeItem) => void
}

// depth 0=Root, 1=Grade, 2=Subject, 3=Unit, 4+=Folder
const DEPTH_CONFIG: Record<number, { label: string; badge: string; indent: string; chevron: string }> = {
  0: {
    label: 'Root',
    badge: 'bg-slate-100 text-slate-700 border-slate-200',
    indent: 'border-slate-200',
    chevron: 'border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100',
  },
  1: {
    label: 'Sınıf',
    badge: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    indent: 'border-emerald-200',
    chevron: 'border-emerald-200 bg-emerald-50 text-emerald-600 hover:bg-emerald-100',
  },
  2: {
    label: 'Ders',
    badge: 'bg-blue-50 text-blue-700 border-blue-200',
    indent: 'border-blue-200',
    chevron: 'border-blue-200 bg-blue-50 text-blue-600 hover:bg-blue-100',
  },
  3: {
    label: 'Ünite',
    badge: 'bg-violet-50 text-violet-700 border-violet-200',
    indent: 'border-violet-200',
    chevron: 'border-violet-200 bg-violet-50 text-violet-600 hover:bg-violet-100',
  },
  4: {
    label: 'Klasör',
    badge: 'bg-amber-50 text-amber-700 border-amber-200',
    indent: 'border-amber-200',
    chevron: 'border-amber-200 bg-amber-50 text-amber-600 hover:bg-amber-100',
  },
}

function getDepthConfig(depth: number) {
  return DEPTH_CONFIG[Math.min(depth, 4)]
}

function collectDefaultExpanded(nodes: CurriculumNodeItem[], depthLimit = 2): string[] {
  const next: string[] = []
  for (const node of nodes) {
    if (node.depth <= depthLimit) next.push(node.id)
    next.push(...collectDefaultExpanded(node.children, depthLimit))
  }
  return next
}

function findNodeById(nodes: CurriculumNodeItem[], targetId?: string): CurriculumNodeItem | null {
  if (!targetId) return null
  for (const node of nodes) {
    if (node.id === targetId) return node
    const child = findNodeById(node.children, targetId)
    if (child) return child
  }
  return null
}

export function CurriculumTreePicker({
  nodes,
  selectedId,
  onSelect,
  onClearSelection,
  selectableScopes,
  title = 'Curriculum Ağacı',
  emptyText = 'Node bulunamadı.',
  fullHeight = false,
  templates,
  selectedTemplateId,
  onSelectTemplate,
  onAddTemplate,
  onManageProperties,
}: CurriculumTreePickerProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(collectDefaultExpanded(nodes)))

  const selectableSet = useMemo(() => new Set(selectableScopes ?? ['constant', 'folder']), [selectableScopes])
  const selectedNode = useMemo(() => findNodeById(nodes, selectedId), [nodes, selectedId])
  const templatesByFolder = useMemo(() => {
    const map = new Map<string, YamlTemplateItem[]>()
    for (const t of templates ?? []) {
      const list = map.get(t.curriculum_folder_node_id) ?? []
      list.push(t)
      map.set(t.curriculum_folder_node_id, list)
    }
    return map
  }, [templates])

  const toggle = (nodeId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(nodeId)) next.delete(nodeId)
      else next.add(nodeId)
      return next
    })
  }

  const renderNode = (node: CurriculumNodeItem) => {
    const isSelected = node.id === selectedId
    const isSelectable = !!onSelect && selectableSet.has(node.scope)
    const folderTemplates = templatesByFolder.get(node.id) ?? []
    const hasChildren = node.children.length > 0
    const hasTemplates = folderTemplates.length > 0
    const hasBranchChildren = hasChildren || hasTemplates
    const isOpen = expanded.has(node.id)
    const cfg = getDepthConfig(node.depth)
    const canAddTemplate =
      !!onAddTemplate &&
      ((node.depth === 3 && node.scope === 'constant') || (node.depth === 4 && node.scope === 'folder'))
    const canManageProperties = !!onManageProperties

    return (
      <div key={node.id} className="space-y-1">
        <div className="flex items-center gap-2">
          {hasBranchChildren ? (
            <button
              type="button"
              onClick={() => toggle(node.id)}
              className={`h-7 w-7 shrink-0 rounded-lg border ${cfg.chevron}`}
              aria-label={isOpen ? 'Dal kapat' : 'Dal aç'}
            >
              {isOpen ? <ChevronDown className="mx-auto h-4 w-4" /> : <ChevronRight className="mx-auto h-4 w-4" />}
            </button>
          ) : (
            <span className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${cfg.chevron}`}>
              <span className="text-xs font-semibold">•</span>
            </span>
          )}

          <button
            type="button"
            onClick={() => isSelectable && onSelect?.(node)}
            disabled={!isSelectable}
            className={[
              'flex-1 rounded-xl border px-3 py-2 text-left transition-all',
              isSelected
                ? 'border-primary bg-accent shadow-sm'
                : 'border-border bg-white hover:bg-accent/60',
              !isSelectable ? 'cursor-not-allowed opacity-55' : '',
            ].join(' ')}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-foreground">{node.name}</div>
                <div className="truncate text-xs text-muted-foreground">{node.path}</div>
              </div>
              <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${cfg.badge}`}>
                {cfg.label}
              </span>
            </div>
          </button>
          {canAddTemplate && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onAddTemplate?.(node)
              }}
              className={`h-7 w-7 shrink-0 rounded-lg border ${cfg.chevron}`}
              aria-label="Yeni template oluştur"
              title="Yeni template oluştur"
            >
              <Plus className="mx-auto h-4 w-4" />
            </button>
          )}
          {canManageProperties && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onManageProperties?.(node)
              }}
              className="shrink-0 rounded-lg border border-border bg-white px-2.5 py-1.5 text-[11px] font-medium text-foreground hover:bg-accent"
              aria-label="Alanları Yönet"
              title="Alanları Yönet"
            >
              Alanları Yönet
            </button>
          )}
        </div>

        {isOpen && hasBranchChildren && (
          <div className={`ml-4 border-l pl-3 ${cfg.indent}`}>
            {hasChildren && node.children.map((child) => renderNode(child))}
            {folderTemplates.map((tpl) => (
              <div key={tpl.id} className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-orange-200 bg-orange-50 text-[11px] font-bold text-orange-700">
                    Y
                  </span>
                  <button
                    type="button"
                    onClick={() => onSelectTemplate?.(tpl)}
                    disabled={!onSelectTemplate}
                    className={[
                      'flex-1 rounded-xl border px-3 py-2 text-left transition-all',
                      selectedTemplateId === tpl.id
                        ? 'border-primary bg-accent shadow-sm'
                        : 'border-border bg-white hover:bg-accent/60',
                      !onSelectTemplate ? 'cursor-default' : '',
                    ].join(' ')}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-foreground">{tpl.title}</div>
                        <div className="truncate text-xs text-muted-foreground">{tpl.template_code}</div>
                      </div>
                      <span className="shrink-0 rounded-full border border-orange-200 bg-orange-50 px-2 py-0.5 text-[11px] font-medium text-orange-700">
                        Template
                      </span>
                    </div>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-border bg-card shadow-sm overflow-hidden">
      <div
        className="border-b border-border px-5 py-4"
        style={{ background: 'linear-gradient(to right, color-mix(in srgb, var(--accent) 45%, transparent), color-mix(in srgb, var(--muted) 45%, transparent))' }}
      >
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-base font-medium text-foreground">{title}</h3>
          {onClearSelection && (
            <button
              type="button"
              onClick={onClearSelection}
              className={[
                'rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors',
                !selectedId
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-white text-muted-foreground hover:bg-accent',
              ].join(' ')}
            >
              Tümü
            </button>
          )}
        </div>
        {selectedNode && (
          <div className="mt-2 inline-flex items-center gap-2 rounded-full border border-border bg-white px-3 py-1 text-xs text-muted-foreground">
            <MapPinned className="h-3.5 w-3.5" />
            <span className="truncate max-w-[260px]">{selectedNode.path}</span>
          </div>
        )}
      </div>

      <div className={`${fullHeight ? '' : 'max-h-[640px] '}overflow-auto p-4`}>
        {nodes.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-sm text-muted-foreground">
            {emptyText}
          </div>
        ) : (
          <div className="space-y-2">{nodes.map((node) => renderNode(node))}</div>
        )}
      </div>
    </div>
  )
}
