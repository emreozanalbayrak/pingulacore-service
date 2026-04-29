import { useEffect, useMemo, useRef, useState } from 'react'
import Moveable from 'react-moveable'
import {
  Undo2, Redo2, ArrowUpToLine, ArrowDownToLine, Save, X, ChevronUp,
} from 'lucide-react'

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
  margin?: string
}

type Snapshot = Record<string, NodeStylePatch>

const PATCH_FIELDS: (keyof NodeStylePatch)[] = [
  'position', 'left', 'top', 'width', 'height', 'zIndex', 'transform', 'right', 'bottom', 'margin',
]

const READ_ONLY_REASON_BY_TAG: Record<string, string> = {
  canvas: 'Canvas elemanı düzenlenemez.',
  iframe: 'Iframe içeriği düzenlenemez.',
  svg: 'SVG iç yapısı düzenlenemez; dış kabuk taşınabilir.',
}

const SKIP_TAGS = new Set(['script', 'style', 'meta', 'link', 'title', 'head', 'html'])
const HISTORY_LIMIT = 50

/* ─── Pure helpers ────────────────────────────────────────────── */

function scopeCss(css: string): string {
  // Replace `html` and `body` selector tokens with the scene root attribute
  // selector. Word-boundary regex avoids matching identifiers that contain
  // those substrings (e.g. `.body-card`, `.html-content`).
  return css
    .replace(/(^|[\s,>+~{};])html(?=[\s,>+~{}.\[:])/g, '$1[data-editor-scene-root]')
    .replace(/(^|[\s,>+~{};])body(?=[\s,>+~{}.\[:])/g, '$1[data-editor-scene-root]')
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
  return stage.querySelector(`[data-node-id="${eid}"]`)
}

function parsePx(value: string): number {
  const n = Number.parseFloat(value)
  return Number.isFinite(n) ? n : 0
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
  const stageRef = useRef<HTMLDivElement | null>(null)
  const moveableRef = useRef<Moveable | null>(null)

  const [sceneMarkup, setSceneMarkup] = useState('')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [readOnlyByNodeId, setReadOnlyByNodeId] = useState<Record<string, string>>({})
  const [parentByNodeId, setParentByNodeId] = useState<Record<string, string>>({})
  const [statusMessage, setStatusMessage] = useState('Hazırlanıyor...')
  const [layoutReady, setLayoutReady] = useState(false)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domVersion, historyVersion, layoutReady])

  const readOnlyCount = useMemo(() => Object.keys(readOnlyByNodeId).length, [readOnlyByNodeId])

  const selectedTargets = useMemo(() => {
    const stage = stageRef.current
    if (!stage) return [] as HTMLElement[]
    return selectedIds
      .map((id) => findNodeById(stage, id))
      .filter((n): n is HTMLElement => n !== null && n.dataset.editorEditable === 'true')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIds, domVersion, layoutReady])

  const activeTarget = selectedTargets.length === 1 ? selectedTargets[0] : null
  const activeNodeId = activeTarget?.dataset.nodeId ?? null
  const canUndo = historyIndexRef.current > 0
  const canRedo = historyIndexRef.current >= 0 && historyIndexRef.current < historyStackRef.current.length - 1
  const canGoToParent = Boolean(activeNodeId && parentByNodeId[activeNodeId])

  /* ── core: snapshot/history ────────────────────────────────── */

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
    if (next.length > HISTORY_LIMIT) next = next.slice(next.length - HISTORY_LIMIT)
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

  /* ── core: annotation, freeze, transform commit ────────────── */

  const annotateDom = (): { editable: number; readOnly: Record<string, string>; parents: Record<string, string> } => {
    const stage = stageRef.current
    if (!stage) return { editable: 0, readOnly: {}, parents: {} }

    // Single pass over all descendants. Always assigns a node-id to every
    // non-skip element. Then decides readonly vs editable based on tag/context.
    // Permissive: an element is editable unless it's hard-readonly (canvas/iframe/inside-svg)
    // or completely empty AND zero-sized.
    const readOnly: Record<string, string> = {}
    let counter = 0
    let editable = 0

    for (const node of stage.querySelectorAll<HTMLElement>('*')) {
      node.removeAttribute('data-editor-editable')
      node.removeAttribute('data-editor-readonly')
      node.removeAttribute('data-editor-selected')
      node.removeAttribute('data-node-id')
      delete node.dataset.editorAbsolute

      const tag = node.tagName.toLowerCase()
      if (SKIP_TAGS.has(tag)) continue
      if (node.hasAttribute('data-editor-scene-root')) continue

      const cs = window.getComputedStyle(node)
      if (cs.display === 'none') continue

      const rect = node.getBoundingClientRect()
      const hasText = Boolean(node.textContent?.trim())
      const isMedia = ['img', 'picture', 'video', 'canvas', 'iframe', 'svg'].includes(tag)
      const hasSize = rect.width > 0 || rect.height > 0
      // Skip only if truly empty: no text, not media, no size, no children
      if (!hasText && !isMedia && !hasSize && node.childElementCount === 0) continue

      let reason: string | null = null
      if (tag in READ_ONLY_REASON_BY_TAG) reason = READ_ONLY_REASON_BY_TAG[tag]
      if (node.closest('svg') && tag !== 'svg') reason = READ_ONLY_REASON_BY_TAG.svg

      const id = `node-${++counter}`
      node.dataset.nodeId = id
      if (reason) {
        node.dataset.editorReadonly = 'true'
        readOnly[id] = reason
      } else {
        node.dataset.editorEditable = 'true'
        editable += 1
      }
    }

    // Build parent relationships (nearest annotated ancestor)
    const parents: Record<string, string> = {}
    for (const node of stage.querySelectorAll<HTMLElement>('[data-node-id]')) {
      const id = node.dataset.nodeId
      if (!id) continue
      let cursor = node.parentElement
      while (cursor && cursor !== stage) {
        if (cursor.dataset.nodeId) { parents[id] = cursor.dataset.nodeId; break }
        cursor = cursor.parentElement
      }
    }

    setReadOnlyByNodeId(readOnly)
    setParentByNodeId(parents)
    setDomVersion((p) => p + 1)
    return { editable, readOnly, parents }
  }

  const freezeLayout = (): void => {
    const stage = stageRef.current
    if (!stage) return

    // Lock scene root dimensions so it doesn't collapse when children leave flow
    const sceneRoot = stage.querySelector<HTMLElement>('[data-editor-scene-root]')
    if (sceneRoot) {
      const r = sceneRoot.getBoundingClientRect()
      if (r.width > 0) sceneRoot.style.width = `${r.width}px`
      if (r.height > 0) sceneRoot.style.height = `${r.height}px`
    }

    const editableEls = Array.from(stage.querySelectorAll<HTMLElement>('[data-editor-editable="true"]'))
    const editableSet = new Set<HTMLElement>(editableEls)

    // Future positioning ancestor: nearest editable, or pre-positioned, or scene root
    const findAnchor = (el: HTMLElement): HTMLElement => {
      let cursor = el.parentElement
      while (cursor && cursor !== stage) {
        if (editableSet.has(cursor)) return cursor
        if (cursor.hasAttribute('data-editor-scene-root')) return cursor
        const p = window.getComputedStyle(cursor).position
        if (p !== 'static') return cursor
        cursor = cursor.parentElement
      }
      return sceneRoot ?? stage
    }

    // PHASE 1: read all positions BEFORE any writes
    const positions = editableEls.map((el) => {
      const rect = el.getBoundingClientRect()
      const anchor = findAnchor(el)
      const ancRect = anchor.getBoundingClientRect()
      return {
        el,
        left: rect.left - ancRect.left + anchor.scrollLeft,
        top: rect.top - ancRect.top + anchor.scrollTop,
        width: rect.width,
        height: rect.height,
      }
    })

    // PHASE 2: apply writes
    for (const p of positions) {
      if (p.width < 1 || p.height < 1) continue
      p.el.style.position = 'absolute'
      p.el.style.left = `${p.left}px`
      p.el.style.top = `${p.top}px`
      p.el.style.width = `${p.width}px`
      p.el.style.height = `${p.height}px`
      p.el.style.right = 'auto'
      p.el.style.bottom = 'auto'
      p.el.style.margin = '0'
      p.el.style.transform = 'none'
      p.el.dataset.editorAbsolute = 'true'
    }
  }

  const commitTransform = (node: HTMLElement): void => {
    const t = extractTranslate(window.getComputedStyle(node).transform || node.style.transform)
    if (t.tx === 0 && t.ty === 0) { node.style.transform = 'none'; return }
    node.style.left = `${parsePx(node.style.left) + t.tx}px`
    node.style.top = `${parsePx(node.style.top) + t.ty}px`
    node.style.transform = 'none'
  }

  /* ── inspector ─────────────────────────────────────────────── */

  const refreshInspector = (): void => {
    const stage = stageRef.current
    if (!activeTarget || !stage) {
      setInspectorDraft({ left: '', top: '', width: '', height: '', zIndex: '' })
      return
    }
    setInspectorDraft({
      left: parsePx(activeTarget.style.left).toFixed(1),
      top: parsePx(activeTarget.style.top).toFixed(1),
      width: parsePx(activeTarget.style.width).toFixed(1),
      height: parsePx(activeTarget.style.height).toFixed(1),
      zIndex: String(readZIndex(activeTarget)),
    })
  }

  const applyInspectorValues = (): void => {
    if (!activeTarget) return
    const l = Number.parseFloat(inspectorDraft.left)
    const t = Number.parseFloat(inspectorDraft.top)
    const w = Number.parseFloat(inspectorDraft.width)
    const h = Number.parseFloat(inspectorDraft.height)
    const z = Number.parseInt(inspectorDraft.zIndex, 10)
    if (Number.isFinite(l)) activeTarget.style.left = `${l}px`
    if (Number.isFinite(t)) activeTarget.style.top = `${t}px`
    if (Number.isFinite(w)) activeTarget.style.width = `${Math.max(8, w)}px`
    if (Number.isFinite(h)) activeTarget.style.height = `${Math.max(8, h)}px`
    if (Number.isFinite(z)) activeTarget.style.zIndex = String(z)
    pushHistory()
    refreshInspector()
  }

  /* ── layer ─────────────────────────────────────────────────── */

  const setLayer = (mode: 'front' | 'back'): void => {
    const stage = stageRef.current
    if (!stage || selectedTargets.length === 0) return
    const all = Array.from(stage.querySelectorAll<HTMLElement>('[data-editor-editable="true"]'))
    const zs = all.map(readZIndex)
    const max = zs.length ? Math.max(...zs) : 0
    const min = zs.length ? Math.min(...zs) : 0
    selectedTargets.forEach((n, i) => {
      n.style.zIndex = mode === 'front' ? String(max + 1 + i) : String(min - 1 - i)
    })
    pushHistory()
    refreshInspector()
  }

  /* ── hierarchy navigation ─────────────────────────────────── */

  const goToParent = (): void => {
    if (!activeNodeId) return
    const parent = parentByNodeId[activeNodeId]
    if (!parent) return
    setSelectedIds([parent])
  }

  /* ── save ──────────────────────────────────────────────────── */

  const handleSave = (): void => {
    const stage = stageRef.current
    if (!stage) return
    onSave(getFullHtml(stage))
  }

  /* ── effects: scene markup ────────────────────────────────── */

  useEffect(() => {
    setLayoutReady(false)
    setSelectedIds([])
    setSceneMarkup(extractSceneMarkup(html))
  }, [html])

  /* ── effects: mount markup, annotate, freeze ──────────────── */

  useEffect(() => {
    const stage = stageRef.current
    if (!stage || !sceneMarkup) return

    stage.innerHTML = sceneMarkup
    let cancelled = false

    const init = () => {
      if (cancelled) return
      const result = annotateDom()
      freezeLayout()
      setStatusMessage(`${result.editable} düzenlenebilir, ${Object.keys(result.readOnly).length} salt-okunur eleman bulundu.`)
      initializeHistory()
      setLayoutReady(true)
    }

    // Wait for fonts and images to settle, then init via double rAF
    const waitForReady = async () => {
      try {
        if (document.fonts && typeof document.fonts.ready?.then === 'function') {
          await document.fonts.ready
        }
        const imgs = Array.from(stage.querySelectorAll<HTMLImageElement>('img'))
        await Promise.all(
          imgs.map((img) => {
            if (img.complete) return Promise.resolve()
            return new Promise<void>((resolve) => {
              const done = () => resolve()
              img.addEventListener('load', done, { once: true })
              img.addEventListener('error', done, { once: true })
              setTimeout(done, 1500)
            })
          }),
        )
      } catch { /* noop */ }
      if (cancelled) return
      requestAnimationFrame(() => requestAnimationFrame(init))
    }
    void waitForReady()

    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneMarkup])

  /* ── effects: apply selected attribute + refresh inspector ── */

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    for (const node of stage.querySelectorAll<HTMLElement>('[data-node-id]')) {
      const id = node.dataset.nodeId
      if (!id) continue
      if (selectedIds.includes(id)) node.dataset.editorSelected = 'true'
      else node.removeAttribute('data-editor-selected')
    }
    refreshInspector()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIds, domVersion, historyVersion, layoutReady])

  /* ── effects: pointer-down on stage (selection) ───────────── */

  useEffect(() => {
    const stage = stageRef.current
    if (!stage || !layoutReady) return

    const onPointerDown = (e: PointerEvent): void => {
      if (!(e.target instanceof Element)) return

      // Ignore clicks on Moveable handles/lines (they have their own controls)
      if (e.target.closest('.moveable-control-box, .moveable-control, .moveable-line')) return

      const target = e.target.closest<HTMLElement>('[data-node-id]')
      if (!target) {
        if (!e.shiftKey) setSelectedIds([])
        return
      }

      const id = target.dataset.nodeId
      if (!id) return

      if (target.dataset.editorReadonly === 'true') {
        setStatusMessage(readOnlyByNodeId[id] ?? 'Bu eleman düzenlenemez.')
        return
      }

      if (e.shiftKey) {
        setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])
      } else {
        setSelectedIds([id])
      }
    }

    stage.addEventListener('pointerdown', onPointerDown)
    return () => stage.removeEventListener('pointerdown', onPointerDown)
  }, [layoutReady, readOnlyByNodeId])

  /* ── effects: keyboard shortcuts ──────────────────────────── */

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const k = e.key.toLowerCase()
      if (k === 'z' && (e.ctrlKey || e.metaKey) && e.shiftKey) { e.preventDefault(); redo(); return }
      if (k === 'z' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); undo(); return }
      if (k === 'escape' && selectedIds.length > 0) {
        e.preventDefault()
        if (canGoToParent) goToParent()
        else setSelectedIds([])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIds, canGoToParent])

  /* ── render ────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-muted/30 shrink-0 flex-wrap gap-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <button type="button" onClick={undo} disabled={!canUndo} className={btnDefault}><Undo2 className="w-3.5 h-3.5" /> Geri Al</button>
          <button type="button" onClick={redo} disabled={!canRedo} className={btnDefault}><Redo2 className="w-3.5 h-3.5" /> Yinele</button>
          <div className="w-px h-5 bg-border mx-1" />
          <button type="button" onClick={() => setLayer('front')} disabled={selectedTargets.length === 0} className={btnDefault}>
            <ArrowUpToLine className="w-3.5 h-3.5" /> Öne
          </button>
          <button type="button" onClick={() => setLayer('back')} disabled={selectedTargets.length === 0} className={btnDefault}>
            <ArrowDownToLine className="w-3.5 h-3.5" /> Arkaya
          </button>
          <div className="w-px h-5 bg-border mx-1" />
          <button type="button" onClick={goToParent} disabled={!canGoToParent} className={btnDefault} title="Üst elemana çık (Esc)">
            <ChevronUp className="w-3.5 h-3.5" /> Üst
          </button>
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button" onClick={onCancel} className={btnDanger}><X className="w-3.5 h-3.5" /> İptal</button>
          <button type="button" onClick={handleSave} disabled={!layoutReady} className={btnPrimary}><Save className="w-3.5 h-3.5" /> Kaydet</button>
        </div>
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-2 px-4 py-1.5 border-b border-border text-xs text-muted-foreground shrink-0 flex-wrap">
        <span>{statusMessage}</span>
        <span className="px-2 py-0.5 rounded-full bg-muted border border-border">Düzenlenebilir: {editableCount}</span>
        <span className="px-2 py-0.5 rounded-full bg-muted border border-border">Salt-okunur: {readOnlyCount}</span>
        <span className="px-2 py-0.5 rounded-full bg-muted border border-border">Seçili: {selectedTargets.length}</span>
        {activeTarget && (
          <span className="px-2 py-0.5 rounded-full bg-primary/10 border border-primary/30 text-primary">
            &lt;{activeTarget.tagName.toLowerCase()}&gt; {activeNodeId}
          </span>
        )}
      </div>

      {/* Workspace */}
      <div className="flex-1 min-h-0 flex">
        {/* Stage */}
        <div className="flex-1 min-w-0 overflow-auto bg-[var(--muted)]">
          <div className="editor-stage-viewport">
            {sceneMarkup ? (
              <div
                className="editor-stage-canvas"
                ref={stageRef}
                style={{ visibility: layoutReady ? 'visible' : 'hidden' }}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-muted-foreground">Yükleniyor...</div>
            )}
            {sceneMarkup && !layoutReady && (
              <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">Hazırlanıyor...</div>
            )}

            {layoutReady && selectedTargets.length > 0 && (
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
                onDragStart={(e) => { e.set([0, 0]) }}
                onDrag={(e) => { (e.target as HTMLElement).style.transform = e.transform }}
                onDragEnd={(e) => { if (!e.target) return; commitTransform(e.target as HTMLElement); pushHistory(); refreshInspector() }}
                onDragGroupStart={(e) => { e.events.forEach((ev) => ev.set([0, 0])) }}
                onDragGroup={(e) => { e.events.forEach((ev) => { (ev.target as HTMLElement).style.transform = ev.transform }) }}
                onDragGroupEnd={(e) => { e.events.forEach((ev) => commitTransform(ev.target as HTMLElement)); pushHistory(); refreshInspector() }}
                onResizeStart={(e) => { if (e.dragStart) e.dragStart.set([0, 0]) }}
                onResize={(e) => {
                  const t = e.target as HTMLElement
                  t.style.width = `${Math.max(8, e.width)}px`
                  t.style.height = `${Math.max(8, e.height)}px`
                  t.style.transform = e.drag.transform
                }}
                onResizeEnd={(e) => { if (!e.target) return; commitTransform(e.target as HTMLElement); pushHistory(); refreshInspector() }}
              />
            )}
          </div>
        </div>

        {/* Inspector sidebar */}
        <div className="w-72 border-l border-border bg-card p-3 overflow-auto shrink-0">
          <h3 className="text-sm font-semibold text-foreground mb-2">Özellikler</h3>
          <p className="text-xs text-muted-foreground mb-3">
            Çoklu seçim için Shift+Click. Esc ile parent'a çık.
          </p>

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
              <button type="button" onClick={applyInspectorValues} className={btnPrimary}>Uygula</button>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Sayısal düzenleme için tek bir eleman seçin.</p>
          )}

          {readOnlyCount > 0 && (
            <>
              <h4 className="text-xs font-semibold text-foreground mt-4 mb-1">Salt-Okunur Elemanlar</h4>
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
