import { useEffect, useMemo, useRef, useState } from 'react'
import Moveable from 'react-moveable'
import { Undo2, Redo2, ArrowUpToLine, ArrowDownToLine, Save, X } from 'lucide-react'

import { rewriteRelativeAssetUrls } from '../lib/html'
import './HtmlLayoutEditor.css'

/* ─── Types ───────────────────────────────────────────────────── */

type NodeStylePatch = {
  position?: string
  left?: string
  top?: string
  width?: string
  height?: string
  zIndex?: string
  transform?: string
  right?: string
  bottom?: string
}

type Snapshot = Record<string, NodeStylePatch>

const PATCH_FIELDS: (keyof NodeStylePatch)[] = [
  'position', 'left', 'top', 'width', 'height', 'zIndex', 'transform', 'right', 'bottom',
]

const READ_ONLY_REASON_BY_TAG: Record<string, string> = {
  canvas: 'Canvas element — not editable in this editor.',
  iframe: 'Iframe content cannot be edited directly.',
  svg: 'SVG internals are read-only; the host element can be moved.',
}

const SKIP_TAGS = new Set(['script', 'style', 'meta', 'link', 'title', 'head', 'html'])

/* ─── Pure helpers ────────────────────────────────────────────── */

function scopeCss(css: string): string {
  return css.replace(/\bhtml\b/g, '[data-editor-scene-root]').replace(/\bbody\b/g, '[data-editor-scene-root]')
}

function unscopeCss(css: string): string {
  return css.replace(/\[data-editor-scene-root\]/g, 'body')
}

function extractSceneMarkup(rawHtml: string): string {
  const rewritten = rewriteRelativeAssetUrls(rawHtml)
  const doc = new DOMParser().parseFromString(rewritten, 'text/html')

  const styleBlocks = Array.from(doc.querySelectorAll('style'))
    .map((s) => `<style>${scopeCss(s.textContent ?? '')}</style>`)
    .join('\n')

  const bodyClass = doc.body.className ? ` class="${doc.body.className}"` : ''
  const bodyStyle = doc.body.getAttribute('style') ? ` style="${doc.body.getAttribute('style')}"` : ''

  return `${styleBlocks}\n<div data-editor-scene-root="true"${bodyClass}${bodyStyle}>${doc.body.innerHTML}</div>`
}

function findNodeById(stage: HTMLElement, id: string): HTMLElement | null {
  const eid = id.replaceAll('"', '\\"')
  return stage.querySelector(`[data-node-id="${eid}"][data-editor-editable="true"], [data-node-id="${eid}"][data-editor-readonly="true"]`)
}

function parsePx(value: string): number {
  const n = Number.parseFloat(value)
  return Number.isFinite(n) ? n : 0
}

function isVisualCandidate(el: HTMLElement): boolean {
  const s = window.getComputedStyle(el)
  if (s.display === 'none' || s.visibility === 'hidden') return false

  const tag = el.tagName.toLowerCase()
  if (['img', 'picture', 'video', 'button', 'input', 'textarea', 'canvas', 'iframe', 'svg'].includes(tag)) return true
  if (s.position === 'absolute' || s.position === 'fixed') return true

  const hasDirectText = Array.from(el.childNodes).some(
    (n) => n.nodeType === Node.TEXT_NODE && Boolean(n.textContent?.trim()),
  )
  if (hasDirectText) return true

  const hasOwnText = el.childElementCount === 0 && Boolean(el.textContent?.trim().length)
  const hasDecor =
    s.backgroundImage !== 'none' ||
    s.backgroundColor !== 'rgba(0, 0, 0, 0)' ||
    parsePx(s.borderTopWidth) > 0 ||
    parsePx(s.borderRightWidth) > 0 ||
    parsePx(s.borderBottomWidth) > 0 ||
    parsePx(s.borderLeftWidth) > 0

  if (hasOwnText || hasDecor) return true

  const r = el.getBoundingClientRect()
  return r.width >= 2 && r.height >= 2
}

function readInlinePatch(el: HTMLElement): NodeStylePatch {
  const p: NodeStylePatch = {}
  for (const f of PATCH_FIELDS) {
    const v = el.style[f]
    if (v) p[f] = v
  }
  return p
}

function applyNodePatch(el: HTMLElement, patch: NodeStylePatch): void {
  for (const f of PATCH_FIELDS) el.style[f] = patch[f] ?? ''
  if ((patch.position ?? '').toLowerCase() === 'absolute') el.dataset.editorAbsolute = 'true'
}

function readZIndex(el: HTMLElement): number {
  const z = Number.parseInt(el.style.zIndex, 10)
  if (Number.isFinite(z)) return z
  const zc = Number.parseInt(window.getComputedStyle(el).zIndex, 10)
  return Number.isFinite(zc) ? zc : 0
}

function extractTranslate(v: string): { tx: number; ty: number } {
  if (!v || v === 'none') return { tx: 0, ty: 0 }
  try {
    const m = new DOMMatrixReadOnly(v)
    return { tx: m.m41, ty: m.m42 }
  } catch {
    return { tx: 0, ty: 0 }
  }
}

const EDITOR_ATTRS = [
  'data-editor-editable', 'data-editor-readonly', 'data-editor-selected',
  'data-node-id', 'data-editor-absolute', 'data-editor-scene-root',
]

function getFullHtml(stage: HTMLElement): string {
  const clone = stage.cloneNode(true) as HTMLElement
  const sceneRoot = clone.querySelector('[data-editor-scene-root]')
  if (!sceneRoot) return clone.innerHTML

  const styles = Array.from(clone.querySelectorAll('style'))
    .map((s) => `<style>${unscopeCss(s.textContent ?? '')}</style>`)
    .join('\n')

  for (const s of Array.from(clone.querySelectorAll('style'))) s.remove()

  const bodyClass = sceneRoot.className ? ` class="${sceneRoot.className}"` : ''
  const bodyStyle = (sceneRoot as HTMLElement).getAttribute('style')
    ? ` style="${(sceneRoot as HTMLElement).getAttribute('style')}"`
    : ''

  const allEls = sceneRoot.querySelectorAll('*')
  for (const el of allEls) {
    for (const a of EDITOR_ATTRS) el.removeAttribute(a)
  }
  for (const a of EDITOR_ATTRS) sceneRoot.removeAttribute(a)

  return `<!DOCTYPE html>\n<html lang="tr">\n<head>\n<meta charset="UTF-8">\n${styles}\n</head>\n<body${bodyClass}${bodyStyle}>\n${sceneRoot.innerHTML}\n</body>\n</html>`
}

/* ─── Props ───────────────────────────────────────────────────── */

interface HtmlLayoutEditorProps {
  html: string
  onSave: (html: string) => void
  onCancel: () => void
}

/* ─── Button helpers ──────────────────────────────────────────── */

const btnBase = 'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200'
const btnDefault = `${btnBase} bg-white/70 border-border hover:border-secondary/40 text-foreground disabled:opacity-40 disabled:cursor-not-allowed`
const btnPrimary = `${btnBase} bg-secondary text-white border-secondary shadow-sm hover:opacity-90`
const btnDanger = `${btnBase} bg-white/70 border-border hover:border-destructive/40 text-foreground`

/* ─── Component ───────────────────────────────────────────────── */

export function HtmlLayoutEditor({ html, onSave, onCancel }: HtmlLayoutEditorProps) {
  const stageViewportRef = useRef<HTMLDivElement | null>(null)
  const stageRef = useRef<HTMLDivElement | null>(null)
  const moveableRef = useRef<Moveable | null>(null)

  const [sceneMarkup, setSceneMarkup] = useState('')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [readOnlyByNodeId, setReadOnlyByNodeId] = useState<Record<string, string>>({})
  const [statusMessage, setStatusMessage] = useState('Loading...')
  const [domVersion, setDomVersion] = useState(0)
  const [inspectorDraft, setInspectorDraft] = useState({ left: '', top: '', width: '', height: '', zIndex: '' })

  const historyStackRef = useRef<Snapshot[]>([])
  const historyIndexRef = useRef(-1)
  const [historyVersion, setHistoryVersion] = useState(0)

  /* ── derived ───────────────────────────────────────────────── */

  const editableCount = useMemo(() => {
    const stage = stageRef.current
    if (!stage) return 0
    return stage.querySelectorAll('[data-editor-editable="true"]').length
  }, [domVersion, historyVersion])

  const readOnlyCount = useMemo(() => Object.keys(readOnlyByNodeId).length, [readOnlyByNodeId])

  const selectedTargets = useMemo(() => {
    const stage = stageRef.current
    if (!stage) return [] as HTMLElement[]
    return selectedIds.map((id) => findNodeById(stage, id)).filter((n): n is HTMLElement => n !== null)
  }, [selectedIds, domVersion])

  const activeTarget = selectedTargets.length === 1 ? selectedTargets[0] : null
  const canUndo = historyIndexRef.current > 0
  const canRedo = historyIndexRef.current >= 0 && historyIndexRef.current < historyStackRef.current.length - 1

  /* ── core functions ────────────────────────────────────────── */

  const buildSnapshot = (): Snapshot => {
    const stage = stageRef.current
    if (!stage) return {}
    const snap: Snapshot = {}
    for (const node of stage.querySelectorAll<HTMLElement>('[data-editor-editable="true"]')) {
      const id = node.dataset.nodeId
      if (id) snap[id] = readInlinePatch(node)
    }
    return snap
  }

  const applySnapshot = (snap: Snapshot): void => {
    const stage = stageRef.current
    if (!stage) return
    for (const node of stage.querySelectorAll<HTMLElement>('[data-editor-editable="true"]')) {
      const id = node.dataset.nodeId
      if (id) applyNodePatch(node, snap[id] ?? {})
    }
  }

  const pushHistory = (): void => {
    const snap = buildSnapshot()
    const stack = historyStackRef.current
    const cur = stack[historyIndexRef.current]
    if (cur && JSON.stringify(cur) === JSON.stringify(snap)) return
    let next = stack.slice(0, historyIndexRef.current + 1)
    next.push(snap)
    if (next.length > 21) next = next.slice(next.length - 21)
    historyStackRef.current = next
    historyIndexRef.current = next.length - 1
    setHistoryVersion((p) => p + 1)
  }

  const initializeHistory = (): void => {
    historyStackRef.current = [buildSnapshot()]
    historyIndexRef.current = 0
    setHistoryVersion((p) => p + 1)
  }

  const undo = (): void => {
    if (historyIndexRef.current <= 0) return
    historyIndexRef.current -= 1
    applySnapshot(historyStackRef.current[historyIndexRef.current] ?? {})
    setHistoryVersion((p) => p + 1)
  }

  const redo = (): void => {
    if (historyIndexRef.current >= historyStackRef.current.length - 1) return
    historyIndexRef.current += 1
    applySnapshot(historyStackRef.current[historyIndexRef.current] ?? {})
    setHistoryVersion((p) => p + 1)
  }

  const ensureAbsolute = (node: HTMLElement): boolean => {
    const stage = stageRef.current
    if (!stage) return false
    if (node.dataset.editorReadonly === 'true') return false
    if (node.dataset.editorAbsolute === 'true') return true

    const nodeRect = node.getBoundingClientRect()
    if (nodeRect.width < 1 || nodeRect.height < 1) return false

    const offsetParent = (node.offsetParent as HTMLElement) || stage
    const parentRect = offsetParent.getBoundingClientRect()
    const left = nodeRect.left - parentRect.left + offsetParent.scrollLeft
    const top = nodeRect.top - parentRect.top + offsetParent.scrollTop

    node.style.position = 'absolute'
    node.style.left = `${left}px`
    node.style.top = `${top}px`
    node.style.width = `${nodeRect.width}px`
    node.style.height = `${nodeRect.height}px`
    node.style.right = 'auto'
    node.style.bottom = 'auto'
    node.style.margin = '0'
    node.style.transform = 'none'
    node.dataset.editorAbsolute = 'true'
    return true
  }

  const commitTransform = (node: HTMLElement): void => {
    const t = extractTranslate(window.getComputedStyle(node).transform || node.style.transform)
    if (t.tx === 0 && t.ty === 0) { node.style.transform = 'none'; return }
    ensureAbsolute(node)
    node.style.left = `${parsePx(node.style.left) + t.tx}px`
    node.style.top = `${parsePx(node.style.top) + t.ty}px`
    node.style.transform = 'none'
  }

  const annotateDom = (emitStatus = false): void => {
    const stage = stageRef.current
    if (!stage) return

    type AR = { editableCount: number; readOnlyMap: Record<string, string>; mode: 'smart' | 'fallback' }
    const runPass = (mode: 'smart' | 'fallback'): AR => {
      const readOnlyMap: Record<string, string> = {}
      let counter = 0, editable = 0
      for (const node of stage.querySelectorAll<HTMLElement>('*')) {
        node.removeAttribute('data-editor-editable')
        node.removeAttribute('data-editor-readonly')
        node.removeAttribute('data-editor-selected')
        node.removeAttribute('data-node-id')
        delete node.dataset.editorAbsolute
        const tag = node.tagName.toLowerCase()
        if (SKIP_TAGS.has(tag)) continue
        if (mode === 'smart') {
          if (!isVisualCandidate(node)) continue
        } else {
          const s = window.getComputedStyle(node)
          if (s.display === 'none' || s.visibility === 'hidden') continue
          const r = node.getBoundingClientRect()
          if (r.width < 1 && r.height < 1 && !node.textContent?.trim() && !['img', 'picture', 'video', 'canvas', 'iframe', 'svg'].includes(tag)) continue
        }
        let reason: string | null = null
        if (tag in READ_ONLY_REASON_BY_TAG) reason = READ_ONLY_REASON_BY_TAG[tag]
        if (node.closest('svg') && tag !== 'svg') reason = READ_ONLY_REASON_BY_TAG.svg
        const nodeId = `node-${++counter}`
        node.dataset.nodeId = nodeId
        if (reason) { node.dataset.editorReadonly = 'true'; readOnlyMap[nodeId] = reason }
        else { node.dataset.editorEditable = 'true'; editable++ }
      }
      return { editableCount: editable, readOnlyMap, mode }
    }

    let result = runPass('smart')
    if (result.editableCount === 0 && Object.keys(result.readOnlyMap).length === 0) result = runPass('fallback')
    setReadOnlyByNodeId(result.readOnlyMap)
    setDomVersion((p) => p + 1)
    if (emitStatus) {
      const ro = Object.keys(result.readOnlyMap).length
      setStatusMessage(`${result.editableCount} editable, ${ro} read-only elements found.`)
    }
    requestAnimationFrame(() => initializeHistory())
  }

  const refreshInspector = (): void => {
    const stage = stageRef.current
    if (!activeTarget || !stage) { setInspectorDraft({ left: '', top: '', width: '', height: '', zIndex: '' }); return }
    const sr = stage.getBoundingClientRect(), r = activeTarget.getBoundingClientRect()
    setInspectorDraft({
      left: (r.left - sr.left + stage.scrollLeft).toFixed(1),
      top: (r.top - sr.top + stage.scrollTop).toFixed(1),
      width: r.width.toFixed(1),
      height: r.height.toFixed(1),
      zIndex: String(readZIndex(activeTarget)),
    })
  }

  const applyInspectorValues = (): void => {
    if (!activeTarget) return
    ensureAbsolute(activeTarget)
    const l = Number.parseFloat(inspectorDraft.left), t = Number.parseFloat(inspectorDraft.top)
    const w = Number.parseFloat(inspectorDraft.width), h = Number.parseFloat(inspectorDraft.height)
    const z = Number.parseInt(inspectorDraft.zIndex, 10)
    if (Number.isFinite(l)) activeTarget.style.left = `${l}px`
    if (Number.isFinite(t)) activeTarget.style.top = `${t}px`
    if (Number.isFinite(w)) activeTarget.style.width = `${Math.max(8, w)}px`
    if (Number.isFinite(h)) activeTarget.style.height = `${Math.max(8, h)}px`
    if (Number.isFinite(z)) activeTarget.style.zIndex = String(z)
    pushHistory(); refreshInspector()
  }

  const setLayer = (mode: 'front' | 'back'): void => {
    const stage = stageRef.current
    if (!stage || selectedTargets.length === 0) return
    const all = Array.from(stage.querySelectorAll<HTMLElement>('[data-editor-editable="true"]'))
    const zs = all.map(readZIndex)
    const max = zs.length ? Math.max(...zs) : 0, min = zs.length ? Math.min(...zs) : 0
    selectedTargets.forEach((n, i) => {
      ensureAbsolute(n)
      n.style.zIndex = mode === 'front' ? String(max + 1 + i) : String(min - 1 - i)
    })
    pushHistory(); refreshInspector()
  }

  const handleSave = (): void => {
    const stage = stageRef.current
    if (!stage) return
    onSave(getFullHtml(stage))
  }

  /* ── effects ───────────────────────────────────────────────── */

  useEffect(() => {
    setSceneMarkup(extractSceneMarkup(html))
  }, [html])

  useEffect(() => {
    const stage = stageRef.current
    if (!stage || !sceneMarkup) return
    stage.innerHTML = sceneMarkup
    annotateDom(true)
    const f = requestAnimationFrame(() => annotateDom(true))
    const t = setTimeout(() => annotateDom(true), 250)
    return () => { cancelAnimationFrame(f); clearTimeout(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneMarkup])

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    for (const node of stage.querySelectorAll<HTMLElement>('[data-editor-editable="true"]')) {
      const id = node.dataset.nodeId
      if (!id) continue
      if (selectedIds.includes(id)) node.dataset.editorSelected = 'true'
      else node.removeAttribute('data-editor-selected')
    }
    refreshInspector()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIds, domVersion, historyVersion])

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const onPointerDown = (e: PointerEvent): void => {
      if (!(e.target instanceof Element)) return
      const target = e.target.closest<HTMLElement>('[data-editor-editable="true"], [data-editor-readonly="true"]')
      if (!target) { if (!e.shiftKey) setSelectedIds([]); return }
      const id = target.dataset.nodeId
      if (!id) return
      if (target.dataset.editorReadonly === 'true') { setStatusMessage(readOnlyByNodeId[id] ?? 'This element is read-only.'); return }
      if (e.shiftKey) setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])
      else setSelectedIds([id])
    }
    stage.addEventListener('pointerdown', onPointerDown, true)
    return () => stage.removeEventListener('pointerdown', onPointerDown, true)
  }, [domVersion, readOnlyByNodeId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key.toLowerCase() === 'z' && (e.ctrlKey || e.metaKey) && e.shiftKey) { e.preventDefault(); redo(); return }
      if (e.key.toLowerCase() === 'z' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); undo() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  /* ── render ────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-muted/30 shrink-0 flex-wrap gap-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <button type="button" onClick={undo} disabled={!canUndo} className={btnDefault}><Undo2 className="w-3.5 h-3.5" /> Undo</button>
          <button type="button" onClick={redo} disabled={!canRedo} className={btnDefault}><Redo2 className="w-3.5 h-3.5" /> Redo</button>
          <div className="w-px h-5 bg-border mx-1" />
          <button type="button" onClick={() => setLayer('front')} disabled={selectedTargets.length === 0} className={btnDefault}>
            <ArrowUpToLine className="w-3.5 h-3.5" /> Front
          </button>
          <button type="button" onClick={() => setLayer('back')} disabled={selectedTargets.length === 0} className={btnDefault}>
            <ArrowDownToLine className="w-3.5 h-3.5" /> Back
          </button>
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button" onClick={onCancel} className={btnDanger}><X className="w-3.5 h-3.5" /> Cancel</button>
          <button type="button" onClick={handleSave} className={btnPrimary}><Save className="w-3.5 h-3.5" /> Save &amp; Apply</button>
        </div>
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-2 px-4 py-1.5 border-b border-border text-xs text-muted-foreground shrink-0 flex-wrap">
        <span>{statusMessage}</span>
        <span className="px-2 py-0.5 rounded-full bg-muted border border-border">Editable: {editableCount}</span>
        <span className="px-2 py-0.5 rounded-full bg-muted border border-border">Read-only: {readOnlyCount}</span>
        <span className="px-2 py-0.5 rounded-full bg-muted border border-border">Selected: {selectedTargets.length}</span>
      </div>

      {/* Workspace */}
      <div className="flex-1 min-h-0 flex">
        {/* Stage */}
        <div className="flex-1 min-w-0 overflow-auto">
          <div className="editor-stage-viewport h-full" ref={stageViewportRef}>
            {sceneMarkup ? (
              <div className="editor-stage-canvas" ref={stageRef} />
            ) : (
              <div className="flex items-center justify-center h-full text-muted-foreground">Loading editor...</div>
            )}

            {sceneMarkup && (
              <Moveable
                ref={moveableRef}
                target={selectedTargets}
                draggable
                resizable={selectedTargets.length === 1}
                keepRatio={false}
                throttleDrag={0}
                throttleResize={0}
                origin={false}
                snappable
                snapThreshold={6}
                bounds={{
                  left: 0, top: 0,
                  right: stageRef.current?.scrollWidth,
                  bottom: stageRef.current?.scrollHeight,
                }}
                onDragStart={(e) => { ensureAbsolute(e.target as HTMLElement); e.set([0, 0]) }}
                onDrag={(e) => { (e.target as HTMLElement).style.transform = e.transform }}
                onDragEnd={(e) => { if (!e.target) return; commitTransform(e.target as HTMLElement); pushHistory(); refreshInspector() }}
                onDragGroupStart={(e) => { e.events.forEach((ev) => { ensureAbsolute(ev.target as HTMLElement); ev.set([0, 0]) }) }}
                onDragGroup={(e) => { e.events.forEach((ev) => { (ev.target as HTMLElement).style.transform = ev.transform }) }}
                onDragGroupEnd={(e) => { e.events.forEach((ev) => commitTransform(ev.target as HTMLElement)); pushHistory(); refreshInspector() }}
                onResizeStart={(e) => { ensureAbsolute(e.target as HTMLElement); if (e.dragStart) e.dragStart.set([0, 0]) }}
                onResize={(e) => { const t = e.target as HTMLElement; t.style.width = `${Math.max(8, e.width)}px`; t.style.height = `${Math.max(8, e.height)}px`; t.style.transform = e.drag.transform }}
                onResizeEnd={(e) => { if (!e.target) return; commitTransform(e.target as HTMLElement); pushHistory(); refreshInspector() }}
              />
            )}
          </div>
        </div>

        {/* Inspector sidebar */}
        <div className="w-72 border-l border-border bg-card p-3 overflow-auto shrink-0">
          <h3 className="text-sm font-semibold text-foreground mb-2">Inspector</h3>
          <p className="text-xs text-muted-foreground mb-3">Shift + Click for multi-select.</p>

          {activeTarget ? (
            <div className="grid gap-2 mb-4">
              {(['left', 'top', 'width', 'height', 'zIndex'] as const).map((field) => (
                <label key={field} className="grid gap-1 text-xs text-foreground">
                  {field === 'zIndex' ? 'Z-Index' : field.charAt(0).toUpperCase() + field.slice(1)}
                  <input
                    type="number"
                    className="border border-border rounded-lg px-2 py-1 text-xs bg-input-background"
                    value={inspectorDraft[field]}
                    onChange={(e) => setInspectorDraft((p) => ({ ...p, [field]: e.currentTarget.value }))}
                  />
                </label>
              ))}
              <button type="button" onClick={applyInspectorValues} className={btnPrimary}>Apply</button>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Select a single element to edit numerically.</p>
          )}

          {readOnlyCount > 0 && (
            <>
              <h4 className="text-xs font-semibold text-foreground mt-4 mb-1">Read-only Elements</h4>
              <ul className="text-xs text-muted-foreground space-y-1">
                {Object.entries(readOnlyByNodeId).map(([id, reason]) => (
                  <li key={id}><strong>{id}:</strong> {reason}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
