import { useEffect, useMemo, useState } from 'react'
import { motion } from 'motion/react'
import {
  BookOpen,
  Box,
  CircleHelp,
  FolderTree,
  Layers3,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  WandSparkles,
} from 'lucide-react'

import { CurriculumTreePicker } from '../components/CurriculumTreePicker'
import { DeleteConfirmModal } from '../components/DeleteConfirmModal'
import { JsonEditor } from '../components/JsonEditor'
import { JsonPanel } from '../components/JsonPanel'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, api } from '../lib/api'
import type {
  CurriculumNodeItem,
  PropertyDataType,
  PropertyDefinitionCreatePayload,
  PropertyDefinitionItem,
  PropertyDefinitionUpdatePayload,
  YamlInstanceCreatePayload,
  YamlInstanceItem,
  YamlInstanceUpdatePayload,
  YamlTemplateCreatePayload,
  YamlTemplateItem,
  YamlTemplateUpdatePayload,
} from '../types'

type ContentTab = 'properties' | 'templates' | 'instances'
type NoticeTone = 'success' | 'error' | 'info'
type SchemaFieldType = 'object' | 'array' | 'text' | 'number' | 'bool' | 'enum' | 'json'

interface NoticeState {
  tone: NoticeTone
  message: string
}

interface SchemaNode {
  type: SchemaFieldType
  label?: string
  description?: string
  required?: boolean
  properties?: Record<string, SchemaNode>
  items?: SchemaNode
  enum_values?: string[]
  options?: string[]
}

interface SchemaFieldDraft {
  id: string
  key: string
  label: string
  description: string
  type: SchemaFieldType
  required: boolean
  enumValues: string[]
  children: SchemaFieldDraft[]
  arrayItem: SchemaFieldDraft | null
}

interface PropertyFormState {
  definedAtCurriculumNodeId: string
  parentPropertyId: string
  label: string
  description: string
  propertyKey: string
  canonicalPath: string
  dataType: PropertyDataType
  defaultValue: string
  isRequired: boolean
  isActive: boolean
  constraintsText: string
}

interface TemplateFormState {
  curriculumFolderNodeId: string
  templateCode: string
  title: string
  description: string
  schemaVersion: string
  createdBy: string
  status: 'active' | 'archived'
  fields: SchemaFieldDraft[]
}

interface InstanceFormState {
  templateId: string
  instanceName: string
  status: 'draft' | 'final' | 'archived'
  createdBy: string
  values: Record<string, unknown>
}

const CONTENT_TABS: { id: ContentTab; label: string; Icon: typeof Layers3 }[] = [
  { id: 'properties', label: 'Property Definitions', Icon: Layers3 },
  { id: 'templates', label: 'YAML Templates', Icon: FolderTree },
  { id: 'instances', label: 'YAML Instances', Icon: Box },
]

const DATA_TYPE_OPTIONS: PropertyDataType[] = ['text', 'bool', 'number', 'json', 'array', 'enum', 'object']
const SCHEMA_FIELD_OPTIONS: SchemaFieldType[] = ['text', 'number', 'bool', 'enum', 'json', 'object', 'array']
const INSTANCE_STATUS_OPTIONS: Array<'draft' | 'final' | 'archived'> = ['draft', 'final', 'archived']

const inputClass = 'w-full rounded-xl border-2 border-border bg-white px-4 py-3 text-sm text-foreground focus:outline-none focus:border-primary transition-colors'
const textareaClass = `${inputClass} min-h-[110px] resize-y`
const selectClass = inputClass
const sectionCardClass = 'rounded-2xl border border-border bg-card shadow-sm overflow-hidden'

function createId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function parseError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) return error.message
  return fallback
}

function flattenCurriculumNodes(nodes: CurriculumNodeItem[], acc: CurriculumNodeItem[] = []): CurriculumNodeItem[] {
  for (const node of nodes) {
    acc.push(node)
    flattenCurriculumNodes(node.children, acc)
  }
  return acc
}

function formatNodeLabel(node: CurriculumNodeItem | null | undefined): string {
  if (!node) return '-'
  return `${node.name} · ${node.path}`
}

function normalizeJsonText(value: unknown): string {
  if (value === undefined || value === null || value === '') return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function toTitleCaseFromKey(key: string): string {
  return key
    .replace(/[._-]+/g, ' ')
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function toSchemaKey(value: string): string {
  return value
    .toLowerCase()
    .replace(/ı/g, 'i')
    .replace(/ş/g, 's')
    .replace(/ğ/g, 'g')
    .replace(/ü/g, 'u')
    .replace(/ö/g, 'o')
    .replace(/ç/g, 'c')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

function makeUniqueKey(base: string, used: Set<string>): string {
  let next = base || 'alan'
  let i = 2
  while (used.has(next)) {
    next = `${base || 'alan'}_${i}`
    i += 1
  }
  used.add(next)
  return next
}

function createDraftField(type: SchemaFieldType = 'text'): SchemaFieldDraft {
  return {
    id: createId('schema-field'),
    key: '',
    label: '',
    description: '',
    type,
    required: false,
    enumValues: type === 'enum' ? [''] : [],
    children: type === 'object' ? [] : [],
    arrayItem: type === 'array' ? createDraftField('text') : null,
  }
}

function normalizeSchemaNode(input: unknown): SchemaNode {
  if (!isRecord(input)) return { type: 'object', properties: {} }

  const rawType = typeof input.type === 'string' ? input.type : 'object'
  const type = (SCHEMA_FIELD_OPTIONS.includes(rawType as SchemaFieldType) ? rawType : 'object') as SchemaFieldType
  const label = typeof input.label === 'string' ? input.label : undefined
  const description = typeof input.description === 'string' ? input.description : undefined
  const required = Boolean(input.required)

  if (type === 'object') {
    const properties: Record<string, SchemaNode> = {}
    const rawProperties = isRecord(input.properties) ? input.properties : {}
    for (const [key, value] of Object.entries(rawProperties)) {
      properties[key] = normalizeSchemaNode(value)
    }
    return { type, label, description, required, properties }
  }

  if (type === 'array') {
    return {
      type,
      label,
      description,
      required,
      items: normalizeSchemaNode(input.items),
    }
  }

  if (type === 'enum') {
    const enumValues = Array.isArray(input.enum_values)
      ? input.enum_values.map(String)
      : Array.isArray(input.options)
        ? input.options.map(String)
        : []
    return { type, label, description, required, enum_values: enumValues }
  }

  return { type, label, description, required }
}

function schemaNodeToDraft(node: SchemaNode, key = ''): SchemaFieldDraft {
  return {
    id: createId('schema-field'),
    key,
    label: node.label ?? '',
    description: node.description ?? '',
    type: node.type,
    required: Boolean(node.required),
    enumValues: node.type === 'enum' ? [...(node.enum_values ?? node.options ?? [])] : [],
    children:
      node.type === 'object'
        ? Object.entries(node.properties ?? {}).map(([childKey, childNode]) => schemaNodeToDraft(childNode, childKey))
        : [],
    arrayItem: node.type === 'array' ? schemaNodeToDraft(node.items ?? { type: 'text' }, 'item') : null,
  }
}

function propertyToDraft(prop: PropertyDefinitionItem): SchemaFieldDraft {
  const type = (SCHEMA_FIELD_OPTIONS.includes(prop.data_type as SchemaFieldType) ? prop.data_type : 'text') as SchemaFieldType
  let enumValues: string[] = []
  if (type === 'enum' && isRecord(prop.constraints)) {
    const raw = (prop.constraints as Record<string, unknown>).enum_values
    if (Array.isArray(raw)) enumValues = raw.map(String)
  }
  return {
    id: createId('schema-field'),
    key: prop.property_key,
    label: prop.label || prop.property_key,
    description: prop.description ?? '',
    type,
    required: Boolean(prop.is_required),
    enumValues: type === 'enum' ? (enumValues.length > 0 ? enumValues : ['']) : [],
    children: type === 'object' ? [] : [],
    arrayItem: type === 'array' ? createDraftField('text') : null,
  }
}

function propertiesToDrafts(properties: PropertyDefinitionItem[]): SchemaFieldDraft[] {
  const draftById = new Map<string, SchemaFieldDraft>()
  for (const prop of properties) {
    draftById.set(prop.id, propertyToDraft(prop))
  }
  const roots: SchemaFieldDraft[] = []
  for (const prop of properties) {
    const draft = draftById.get(prop.id)
    if (!draft) continue
    const parentId = prop.parent_property_id ?? null
    if (parentId && draftById.has(parentId)) {
      const parentDraft = draftById.get(parentId)!
      if (parentDraft.type === 'object') {
        parentDraft.children.push(draft)
      } else if (parentDraft.type === 'array') {
        parentDraft.arrayItem = draft
      } else {
        roots.push(draft)
      }
    } else {
      roots.push(draft)
    }
  }
  return roots
}

function sanitizeDraftField(field: SchemaFieldDraft): SchemaFieldDraft | null {
  const label = field.label.trim()
  const key = field.key.trim() || toSchemaKey(label)
  if (!label && !key) return null
  const base: SchemaFieldDraft = {
    ...field,
    key: key || 'alan',
    label,
    description: field.description.trim(),
    enumValues: field.enumValues.map((item) => item.trim()).filter(Boolean),
    children: field.children.map(sanitizeDraftField).filter((item): item is SchemaFieldDraft => Boolean(item)),
    arrayItem: field.arrayItem ? sanitizeDraftField({ ...field.arrayItem, key: field.arrayItem.key || 'item' }) : null,
  }
  return base
}

function draftChildrenToProperties(fields: SchemaFieldDraft[]): Record<string, SchemaNode> {
  const usedKeys = new Set<string>()
  const entries: Array<[string, SchemaNode]> = []
  for (const field of fields) {
    const sanitized = sanitizeDraftField(field)
    if (!sanitized) continue
    const uniqueKey = makeUniqueKey(sanitized.key, usedKeys)
    entries.push([uniqueKey, draftFieldToSchemaNode({ ...sanitized, key: uniqueKey })])
  }
  return Object.fromEntries(entries)
}

function draftFieldToSchemaNode(field: SchemaFieldDraft): SchemaNode {
  const node: SchemaNode = {
    type: field.type,
  }

  if (field.label.trim()) node.label = field.label.trim()
  if (field.description.trim()) node.description = field.description.trim()
  if (field.required) node.required = true

  if (field.type === 'object') {
    node.properties = draftChildrenToProperties(field.children)
  }

  if (field.type === 'array') {
    const itemField = field.arrayItem ? sanitizeDraftField({ ...field.arrayItem, key: field.arrayItem.key || 'item' }) : null
    node.items = itemField ? draftFieldToSchemaNode(itemField) : { type: 'text' }
  }

  if (field.type === 'enum') {
    node.enum_values = field.enumValues.map((item) => item.trim()).filter(Boolean)
  }

  return node
}

function draftFieldsToSchema(fields: SchemaFieldDraft[]): Record<string, unknown> {
  const properties = draftChildrenToProperties(fields)
  return {
    type: 'object',
    properties,
  }
}

function deepMapDraftField(field: SchemaFieldDraft, targetId: string, updater: (field: SchemaFieldDraft) => SchemaFieldDraft): SchemaFieldDraft {
  if (field.id === targetId) return updater(field)
  return {
    ...field,
    children: field.children.map((child) => deepMapDraftField(child, targetId, updater)),
    arrayItem: field.arrayItem ? deepMapDraftField(field.arrayItem, targetId, updater) : null,
  }
}

function mapDraftTree(fields: SchemaFieldDraft[], targetId: string, updater: (field: SchemaFieldDraft) => SchemaFieldDraft): SchemaFieldDraft[] {
  return fields.map((field) => deepMapDraftField(field, targetId, updater))
}

function removeDraftField(fields: SchemaFieldDraft[], targetId: string): SchemaFieldDraft[] {
  return fields
    .filter((field) => field.id !== targetId)
    .map((field) => ({
      ...field,
      children: removeDraftField(field.children, targetId),
      arrayItem: field.arrayItem?.id === targetId ? null : field.arrayItem,
    }))
}

function resetDraftType(field: SchemaFieldDraft, nextType: SchemaFieldType): SchemaFieldDraft {
  return {
    ...field,
    type: nextType,
    enumValues: nextType === 'enum' ? field.enumValues.length > 0 ? field.enumValues : [''] : [],
    children: nextType === 'object' ? field.children : [],
    arrayItem: nextType === 'array' ? field.arrayItem ?? createDraftField('text') : null,
  }
}

function defaultValueForSchema(node: SchemaNode): unknown {
  if (node.type === 'object') {
    const result: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(node.properties ?? {})) {
      result[key] = defaultValueForSchema(value)
    }
    return result
  }
  if (node.type === 'array') return []
  if (node.type === 'number') return 0
  if (node.type === 'bool') return false
  if (node.type === 'enum') return (node.enum_values ?? node.options ?? [])[0] ?? ''
  if (node.type === 'json') return {}
  return ''
}

function collectDescendantPropertyIds(allProperties: PropertyDefinitionItem[], propertyId: string): Set<string> {
  const descendants = new Set<string>()
  const frontier = [propertyId]
  while (frontier.length > 0) {
    const current = frontier.pop()
    if (!current) continue
    for (const property of allProperties) {
      if (property.parent_property_id === current && !descendants.has(property.id)) {
        descendants.add(property.id)
        frontier.push(property.id)
      }
    }
  }
  return descendants
}

function ensureRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {}
}

function parseJsonValue(text: string): unknown {
  if (!text.trim()) return {}
  return JSON.parse(text)
}

function NoticeBanner({ notice, onClear }: { notice: NoticeState; onClear: () => void }) {
  const toneClass =
    notice.tone === 'success'
      ? 'border-green-200 bg-green-50 text-green-700'
      : notice.tone === 'error'
        ? 'border-red-200 bg-red-50 text-red-700'
        : 'border-blue-200 bg-blue-50 text-blue-700'

  return (
    <div className={`flex items-start justify-between gap-4 rounded-2xl border px-5 py-4 text-sm ${toneClass}`}>
      <span>{notice.message}</span>
      <button type="button" onClick={onClear} className="rounded-lg border border-current/20 px-3 py-1 text-xs hover:bg-white/50">
        Kapat
      </button>
    </div>
  )
}

interface CrudToolbarProps {
  title: string
  description: string
  searchValue: string
  searchPlaceholder: string
  onSearchChange: (value: string) => void
  onAdd: () => void
  onRefresh: () => void | Promise<void>
  filters?: React.ReactNode
}

function CrudToolbar({ title, description, searchValue, searchPlaceholder, onSearchChange, onAdd, onRefresh, filters }: CrudToolbarProps) {
  return (
    <div className={sectionCardClass}>
      <div
        className="border-b border-border px-6 py-5"
        style={{ background: 'linear-gradient(to right, color-mix(in srgb, var(--accent) 55%, transparent), color-mix(in srgb, var(--muted) 55%, transparent))' }}
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-xl text-foreground" style={{ fontFamily: 'var(--font-display)' }}>
              {title}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void onRefresh()}
              className="inline-flex items-center gap-2 rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-foreground hover:bg-accent"
            >
              <RefreshCw className="h-4 w-4" />
              Yenile
            </button>
            <button
              type="button"
              onClick={onAdd}
              className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium text-white shadow-sm"
              style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
            >
              <Plus className="h-4 w-4" />
              Yeni Kayıt
            </button>
          </div>
        </div>
      </div>
      <div className="grid gap-4 px-6 py-5 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Arama</label>
          <input
            value={searchValue}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={searchPlaceholder}
            aria-label={`${title} arama`}
            className={inputClass}
          />
        </div>
        {filters ? <div className="flex flex-wrap items-end gap-3">{filters}</div> : null}
      </div>
    </div>
  )
}

interface PropertyFormModalProps {
  open: boolean
  mode: 'create' | 'edit'
  initialProperty: PropertyDefinitionItem | null
  defaultNodeId: string
  allNodes: CurriculumNodeItem[]
  allProperties: PropertyDefinitionItem[]
  onClose: () => void
  onSubmit: (payload: PropertyDefinitionCreatePayload | PropertyDefinitionUpdatePayload, propertyId?: string) => Promise<void>
}

function PropertyFormModal({
  open,
  mode,
  initialProperty,
  defaultNodeId,
  allNodes,
  allProperties,
  onClose,
  onSubmit,
}: PropertyFormModalProps) {
  const flatNodes = useMemo(() => flattenCurriculumNodes(allNodes), [allNodes])
  const [form, setForm] = useState<PropertyFormState>({
    definedAtCurriculumNodeId: defaultNodeId,
    parentPropertyId: '',
    label: '',
    description: '',
    propertyKey: '',
    canonicalPath: '',
    dataType: 'text',
    defaultValue: '',
    isRequired: false,
    isActive: true,
    constraintsText: '',
  })
  const [effectiveProperties, setEffectiveProperties] = useState<PropertyDefinitionItem[]>([])
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    if (mode === 'edit' && initialProperty) {
      setForm({
        definedAtCurriculumNodeId: initialProperty.defined_at_curriculum_node_id,
        parentPropertyId: initialProperty.parent_property_id ?? '',
        label: initialProperty.label,
        description: initialProperty.description ?? '',
        propertyKey: initialProperty.property_key,
        canonicalPath: initialProperty.canonical_path,
        dataType: initialProperty.data_type,
        defaultValue: initialProperty.default_value ?? '',
        isRequired: initialProperty.is_required,
        isActive: initialProperty.is_active,
        constraintsText: normalizeJsonText(initialProperty.constraints),
      })
    } else {
      setForm({
        definedAtCurriculumNodeId: defaultNodeId,
        parentPropertyId: '',
        label: '',
        description: '',
        propertyKey: '',
        canonicalPath: '',
        dataType: 'text',
        defaultValue: '',
        isRequired: false,
        isActive: true,
        constraintsText: '',
      })
    }
    setError('')
  }, [defaultNodeId, initialProperty, mode, open])

  useEffect(() => {
    if (!open || !form.definedAtCurriculumNodeId) return
    void api.getEffectiveProperties(form.definedAtCurriculumNodeId)
      .then((rows) => setEffectiveProperties(rows))
      .catch((err) => setError(parseError(err, 'Effective property listesi alınamadı')))
  }, [form.definedAtCurriculumNodeId, open])

  const invalidIds = useMemo(() => {
    if (!initialProperty) return new Set<string>()
    const descendants = collectDescendantPropertyIds(allProperties, initialProperty.id)
    descendants.add(initialProperty.id)
    return descendants
  }, [allProperties, initialProperty])

  const parentOptions = useMemo(() => {
    const rows = [...effectiveProperties]
    if (mode === 'edit' && initialProperty?.parent_property_id) {
      const currentParent = allProperties.find((item) => item.id === initialProperty.parent_property_id)
      if (currentParent && !rows.some((item) => item.id === currentParent.id)) {
        rows.push(currentParent)
      }
    }
    return rows.filter((item) => !invalidIds.has(item.id))
  }, [allProperties, effectiveProperties, initialProperty, invalidIds, mode])

  const handleSubmit = async () => {
    setSubmitting(true)
    setError('')
    try {
      const constraints = form.constraintsText.trim() ? parseJsonValue(form.constraintsText) : null
      if (!form.definedAtCurriculumNodeId) {
        throw new Error('Defined at curriculum node seçilmedi')
      }
      if (!form.label.trim() || !form.propertyKey.trim() || !form.canonicalPath.trim()) {
        throw new Error('Label, property key ve canonical path zorunlu')
      }

      if (mode === 'create') {
        const payload: PropertyDefinitionCreatePayload = {
          defined_at_curriculum_node_id: form.definedAtCurriculumNodeId,
          parent_property_id: form.parentPropertyId || null,
          label: form.label.trim(),
          description: form.description.trim() || null,
          property_key: form.propertyKey.trim(),
          canonical_path: form.canonicalPath.trim(),
          data_type: form.dataType,
          default_value: form.dataType === 'object' ? null : (form.defaultValue.trim() || null),
          constraints,
          is_required: form.isRequired,
        }
        await onSubmit(payload)
      } else if (initialProperty) {
        const payload: PropertyDefinitionUpdatePayload = {
          label: form.label.trim(),
          description: form.description.trim() || null,
          property_key: form.propertyKey.trim(),
          canonical_path: form.canonicalPath.trim(),
          data_type: form.dataType,
          default_value: form.dataType === 'object' ? null : (form.defaultValue.trim() || null),
          constraints,
          is_required: form.isRequired,
          is_active: form.isActive,
        }
        await onSubmit(payload, initialProperty.id)
      }
      onClose()
    } catch (err) {
      setError(parseError(err, 'Property kaydedilemedi'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={mode === 'create' ? 'Property Definition Oluştur' : 'Property Definition Düzenle'}>
      <div className="space-y-5 p-6">
        {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2 md:col-span-2">
            <label className="text-sm font-medium text-foreground">Defined At Curriculum Node</label>
            <select
              value={form.definedAtCurriculumNodeId}
              onChange={(event) => setForm((prev) => ({ ...prev, definedAtCurriculumNodeId: event.target.value, parentPropertyId: '' }))}
              className={selectClass}
              disabled={mode === 'edit'}
              aria-label="Defined at curriculum node"
            >
              {flatNodes.map((node) => (
                <option key={node.id} value={node.id}>{node.path}</option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Label</label>
            <input aria-label="Property label" value={form.label} onChange={(event) => setForm((prev) => ({ ...prev, label: event.target.value }))} className={inputClass} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Property Key</label>
            <input aria-label="Property key" value={form.propertyKey} onChange={(event) => setForm((prev) => ({ ...prev, propertyKey: event.target.value }))} className={inputClass} />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Canonical Path</label>
            <input aria-label="Canonical path" value={form.canonicalPath} onChange={(event) => setForm((prev) => ({ ...prev, canonicalPath: event.target.value }))} className={inputClass} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Data Type</label>
            <select
              aria-label="Property data type"
              value={form.dataType}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  dataType: event.target.value as PropertyDataType,
                  defaultValue: event.target.value === 'object' ? '' : prev.defaultValue,
                }))
              }
              className={selectClass}
            >
              {DATA_TYPE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Default Value</label>
            <input
              aria-label="Property default value"
              value={form.defaultValue}
              onChange={(event) => setForm((prev) => ({ ...prev, defaultValue: event.target.value }))}
              className={inputClass}
              disabled={form.dataType === 'object'}
              placeholder={form.dataType === 'array' ? 'deger1;deger2;deger3' : 'Varsayılan değer'}
            />
            {form.dataType === 'array' ? (
              <div className="text-xs text-muted-foreground">Array tipinde öğeleri `;` ile ayır.</div>
            ) : null}
          </div>

          <div className="space-y-2 md:col-span-2">
            <label className="text-sm font-medium text-foreground">Description</label>
            <textarea aria-label="Property description" value={form.description} onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))} className={textareaClass} />
          </div>

          <div className="space-y-2 md:col-span-2">
            <label className="text-sm font-medium text-foreground">Parent Property</label>
            <select aria-label="Parent property" value={form.parentPropertyId} onChange={(event) => setForm((prev) => ({ ...prev, parentPropertyId: event.target.value }))} className={selectClass}>
              <option value="">Parent yok</option>
              {parentOptions.map((item) => (
                <option key={item.id} value={item.id}>{item.label} · {item.canonical_path}</option>
              ))}
            </select>
          </div>

          <div className="space-y-2 md:col-span-2">
            <JsonEditor
              label="Constraints (JSON)"
              value={form.constraintsText}
              onChange={(value) => setForm((prev) => ({ ...prev, constraintsText: value }))}
              rows={8}
              placeholder='{"min": 1, "max": 4}'
            />
          </div>

          <label className="inline-flex items-center gap-2 rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground">
            <input type="checkbox" checked={form.isRequired} onChange={(event) => setForm((prev) => ({ ...prev, isRequired: event.target.checked }))} />
            Zorunlu alan
          </label>

          {mode === 'edit' && (
            <label className="inline-flex items-center gap-2 rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground">
              <input type="checkbox" checked={form.isActive} onChange={(event) => setForm((prev) => ({ ...prev, isActive: event.target.checked }))} />
              Aktif
            </label>
          )}
        </div>

        <div className="flex items-center justify-end gap-3">
          <button type="button" onClick={onClose} className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-foreground hover:bg-accent">Vazgeç</button>
          <button type="button" onClick={() => void handleSubmit()} disabled={submitting} className="rounded-xl px-4 py-2.5 text-sm font-medium text-white" style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}>
            {submitting ? 'Kaydediliyor...' : mode === 'create' ? 'Oluştur' : 'Kaydet'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

function SchemaFieldListEditor({
  fields,
  onChange,
}: {
  fields: SchemaFieldDraft[]
  onChange: (fields: SchemaFieldDraft[]) => void
}) {
  const [expandedById, setExpandedById] = useState<Record<string, boolean>>({})

  return (
    <div className="space-y-2">
      {fields.map((field) => {
        const expanded = expandedById[field.id] ?? !field.label.trim()

        return (
        <div key={field.id} className="space-y-1">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-2">
            <span className="text-xs text-muted-foreground">{field.children.length > 0 ? '▾' : '•'}</span>
            <input
              value={field.label}
              onChange={(event) => onChange(mapDraftTree(fields, field.id, (target) => ({ ...target, label: event.target.value })))}
              className="min-w-0 flex-1 border-0 bg-transparent p-0 text-sm text-foreground focus:outline-none"
              placeholder="Alan adı"
              aria-label="Schema field label"
            />
            <span className="rounded-md border border-border bg-card px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {field.type}
            </span>

            {field.description.trim() ? (
              <div className="group relative">
                <CircleHelp className="h-4 w-4 cursor-help text-muted-foreground" />
                <div className="pointer-events-none absolute right-0 top-6 z-10 w-72 rounded-xl border border-border bg-white p-3 text-xs text-foreground opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                  {field.description}
                </div>
              </div>
            ) : null}

            <button
              type="button"
              onClick={() => setExpandedById((prev) => ({ ...prev, [field.id]: !expanded }))}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-foreground hover:bg-accent"
              title="Alan ayarları"
              aria-label="Alan ayarları"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>

            {field.type === 'object' ? (
              <button
                type="button"
                onClick={() =>
                  onChange(
                    mapDraftTree(fields, field.id, (target) => ({
                      ...target,
                      children: [...target.children, createDraftField('text')],
                    })),
                  )
                }
                className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-foreground hover:bg-accent"
                title="Alt alan ekle"
                aria-label="Alt alan ekle"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            ) : null}

            <button
              type="button"
              onClick={() => onChange(removeDraftField(fields, field.id))}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-red-200 text-red-700 hover:bg-red-50"
              title="Alanı sil"
              aria-label="Alanı sil"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>

          {expanded ? (
            <div className="ml-4 rounded-lg border border-border/70 bg-card p-3">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">Data Type</label>
                  <select
                    value={field.type}
                    onChange={(event) =>
                      onChange(mapDraftTree(fields, field.id, (target) => resetDraftType(target, event.target.value as SchemaFieldType)))
                    }
                    className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-foreground focus:outline-none focus:border-primary"
                    aria-label="Schema field type"
                  >
                    {SCHEMA_FIELD_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </div>
                <div className="space-y-1 md:col-span-2">
                  <label className="text-xs font-medium text-muted-foreground">Description</label>
                  <textarea
                    value={field.description}
                    onChange={(event) => onChange(mapDraftTree(fields, field.id, (target) => ({ ...target, description: event.target.value })))}
                    className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-foreground focus:outline-none focus:border-primary"
                    rows={2}
                    aria-label="Schema field description"
                    placeholder="Açıklama"
                  />
                </div>
              </div>
            </div>
          ) : null}

          {field.children.length > 0 ? (
            <div className="ml-4 border-l border-border/70 pl-3">
              <SchemaFieldListEditor
                fields={field.children}
                onChange={(nextChildren) => onChange(mapDraftTree(fields, field.id, (target) => ({ ...target, children: nextChildren })))}
              />
            </div>
          ) : null}
        </div>
      )})}

      <button
        type="button"
        onClick={() => onChange([...fields, createDraftField('text')])}
        className="inline-flex items-center gap-2 rounded-xl border border-dashed border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-accent"
      >
        <Plus className="h-4 w-4" />
        Alan Ekle
      </button>
    </div>
  )
}

interface TemplateFormModalProps {
  open: boolean
  mode: 'create' | 'edit'
  initialTemplate: YamlTemplateItem | null
  folderNodes: CurriculumNodeItem[]
  defaultFolderId: string
  onClose: () => void
  onSubmit: (payload: YamlTemplateCreatePayload | YamlTemplateUpdatePayload, templateId?: string) => Promise<void>
  prefilledFields?: SchemaFieldDraft[]
  lockFolder?: boolean
}

function TemplateFormModal({ open, mode, initialTemplate, folderNodes, defaultFolderId, onClose, onSubmit, prefilledFields, lockFolder }: TemplateFormModalProps) {
  const [form, setForm] = useState<TemplateFormState>({
    curriculumFolderNodeId: defaultFolderId,
    templateCode: '',
    title: '',
    description: '',
    schemaVersion: 'v1',
    createdBy: '',
    status: 'active',
    fields: [],
  })
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    if (mode === 'edit' && initialTemplate) {
      const schema = normalizeSchemaNode(initialTemplate.field_schema)
      setForm({
        curriculumFolderNodeId: initialTemplate.curriculum_folder_node_id,
        templateCode: initialTemplate.template_code,
        title: initialTemplate.title,
        description: initialTemplate.description ?? '',
        schemaVersion: initialTemplate.schema_version,
        createdBy: initialTemplate.created_by ?? '',
        status: initialTemplate.status === 'archived' ? 'archived' : 'active',
        fields: Object.entries(schema.properties ?? {}).map(([key, node]) => schemaNodeToDraft(node, key)),
      })
    } else {
      setForm({
        curriculumFolderNodeId: defaultFolderId,
        templateCode: '',
        title: '',
        description: '',
        schemaVersion: 'v1',
        createdBy: '',
        status: 'active',
        fields: prefilledFields ?? [],
      })
    }
    setError('')
  }, [defaultFolderId, initialTemplate, mode, open, prefilledFields])

  const selectedFolder = folderNodes.find((node) => node.id === form.curriculumFolderNodeId) ?? null
  const schemaPreview = useMemo(() => draftFieldsToSchema(form.fields), [form.fields])

  const handleSubmit = async () => {
    setSubmitting(true)
    setError('')
    try {
      if (!form.curriculumFolderNodeId) throw new Error('Curriculum folder seçilmedi')
      if (!form.templateCode.trim() || !form.title.trim()) {
        throw new Error('Template code ve title zorunlu')
      }

      if (mode === 'create') {
        const payload: YamlTemplateCreatePayload = {
          curriculum_folder_node_id: form.curriculumFolderNodeId,
          template_code: form.templateCode.trim(),
          title: form.title.trim(),
          description: form.description.trim() || null,
          field_schema: schemaPreview,
          schema_version: form.schemaVersion.trim() || 'v1',
          created_by: form.createdBy.trim() || null,
        }
        await onSubmit(payload)
      } else if (initialTemplate) {
        const payload: YamlTemplateUpdatePayload = {
          template_code: form.templateCode.trim(),
          title: form.title.trim(),
          description: form.description.trim() || null,
          field_schema: schemaPreview,
          schema_version: form.schemaVersion.trim() || 'v1',
          status: form.status,
        }
        await onSubmit(payload, initialTemplate.id)
      }
      onClose()
    } catch (err) {
      setError(parseError(err, 'Template kaydedilemedi'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={mode === 'create' ? 'YAML Template Oluştur' : 'YAML Template Düzenle'} size="wide">
      <div className="space-y-6 p-6">
        {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        <div className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium text-foreground">Curriculum Folder</label>
              <select
                value={form.curriculumFolderNodeId}
                onChange={(event) => setForm((prev) => ({ ...prev, curriculumFolderNodeId: event.target.value }))}
                className={selectClass}
                disabled={mode === 'edit' || Boolean(lockFolder)}
                aria-label="Curriculum folder"
              >
                {folderNodes.map((node) => (
                  <option key={node.id} value={node.id}>{node.path}</option>
                ))}
              </select>
              {selectedFolder && <p className="text-xs text-muted-foreground">{selectedFolder.path}</p>}
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Template Code</label>
              <input aria-label="Template code" value={form.templateCode} onChange={(event) => setForm((prev) => ({ ...prev, templateCode: event.target.value }))} className={inputClass} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Schema Version</label>
              <input aria-label="Schema version" value={form.schemaVersion} onChange={(event) => setForm((prev) => ({ ...prev, schemaVersion: event.target.value }))} className={inputClass} />
            </div>

            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium text-foreground">Title</label>
              <input aria-label="Template title" value={form.title} onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))} className={inputClass} />
            </div>

            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium text-foreground">Description</label>
              <textarea aria-label="Template description" value={form.description} onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))} className={textareaClass} rows={4} />
            </div>

            {mode === 'create' ? (
              <div className="space-y-2 md:col-span-2">
                <label className="text-sm font-medium text-foreground">Created By</label>
                <input aria-label="Template created by" value={form.createdBy} onChange={(event) => setForm((prev) => ({ ...prev, createdBy: event.target.value }))} className={inputClass} />
              </div>
            ) : (
              <div className="space-y-2 md:col-span-2">
                <label className="text-sm font-medium text-foreground">Status</label>
                <select aria-label="Template status" value={form.status} onChange={(event) => setForm((prev) => ({ ...prev, status: event.target.value as 'active' | 'archived' }))} className={selectClass}>
                  <option value="active">active</option>
                  <option value="archived">archived</option>
                </select>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-border bg-card p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h4 className="text-lg text-foreground" style={{ fontFamily: 'var(--font-display)' }}>Field Schema Builder</h4>
                <p className="text-sm text-muted-foreground">Root her zaman object kabul edilir. Alt alanları aşağıdan yönet.</p>
              </div>
            </div>
            {mode === 'create' && prefilledFields && prefilledFields.length > 0 && (
              <div className="mb-4 rounded-xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-800">
                {prefilledFields.length} property kalıtsal olarak yüklendi. Silebilir veya yeni ekleyebilirsin.
              </div>
            )}
            <SchemaFieldListEditor fields={form.fields} onChange={(fields) => setForm((prev) => ({ ...prev, fields }))} />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3">
          <button type="button" onClick={onClose} className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-foreground hover:bg-accent">Vazgeç</button>
          <button type="button" onClick={() => void handleSubmit()} disabled={submitting} className="rounded-xl px-4 py-2.5 text-sm font-medium text-white" style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}>
            {submitting ? 'Kaydediliyor...' : mode === 'create' ? 'Template Oluştur' : 'Template Kaydet'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

interface FolderNamePromptModalProps {
  open: boolean
  uniteName: string
  unitePath: string
  busy: boolean
  onClose: () => void
  onConfirm: (name: string, slug: string) => Promise<void>
}

function FolderNamePromptModal({ open, uniteName, unitePath, busy, onClose, onConfirm }: FolderNamePromptModalProps) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) {
      setName('')
      setSlug('')
      setError('')
    }
  }, [open])

  const slugify = (value: string) =>
    value
      .toLowerCase()
      .replace(/ı/g, 'i')
      .replace(/ş/g, 's')
      .replace(/ğ/g, 'g')
      .replace(/ü/g, 'u')
      .replace(/ö/g, 'o')
      .replace(/ç/g, 'c')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')

  const handleConfirm = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Folder ismi zorunlu')
      return
    }
    const finalSlug = slug.trim() || slugify(trimmed)
    if (!finalSlug) {
      setError('Geçerli bir slug üretilemedi, manuel gir')
      return
    }
    try {
      await onConfirm(trimmed, finalSlug)
    } catch (err) {
      setError(parseError(err, 'Folder oluşturulamadı'))
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Yeni Folder Oluştur">
      <div className="space-y-4 p-6">
        <div className="rounded-xl border border-border bg-background px-4 py-3 text-sm">
          <div className="text-muted-foreground">Üst Ünite:</div>
          <div className="font-medium text-foreground">{uniteName}</div>
          <div className="text-xs text-muted-foreground">{unitePath}</div>
        </div>
        {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Folder İsmi</label>
          <input
            value={name}
            onChange={(e) => {
              setName(e.target.value)
              if (!slug) setSlug(slugify(e.target.value))
            }}
            className={inputClass}
            placeholder="Ör: Toplama"
            autoFocus
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Slug</label>
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            className={inputClass}
            placeholder="otomatik üretilir"
          />
        </div>
        <div className="flex items-center justify-end gap-3">
          <button type="button" onClick={onClose} className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-foreground hover:bg-accent">Vazgeç</button>
          <button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={busy}
            className="rounded-xl px-4 py-2.5 text-sm font-medium text-white"
            style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
          >
            {busy ? 'Oluşturuluyor...' : 'Folder Oluştur ve Devam Et'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

function JsonValueEditor({ value, onChange, label }: { value: unknown; onChange: (next: unknown) => void; label?: string }) {
  const [text, setText] = useState(normalizeJsonText(value))

  useEffect(() => {
    setText(normalizeJsonText(value))
  }, [value])

  return (
    <div className="space-y-2">
      {label ? <label className="text-sm font-medium text-foreground">{label}</label> : null}
      <JsonEditor
        value={text}
        onChange={(next) => {
          setText(next)
          try {
            onChange(parseJsonValue(next))
          } catch {
            // Invalid JSON stays local until user fixes it.
          }
        }}
        rows={8}
      />
    </div>
  )
}

function DynamicValueEditor({
  schema,
  value,
  onChange,
  fieldKey,
  depth = 0,
}: {
  schema: SchemaNode
  value: unknown
  onChange: (next: unknown) => void
  fieldKey?: string
  depth?: number
}) {
  const title = schema.label?.trim() || (fieldKey ? toTitleCaseFromKey(fieldKey) : 'Alan')
  const description = schema.description?.trim()

  if (schema.type === 'object') {
    const safeValue = ensureRecord(value)
    const properties = Object.entries(schema.properties ?? {})
    return (
      <div className="space-y-3 rounded-2xl border border-border bg-background p-4" style={{ marginLeft: depth * 8 }}>
        <div>
          <div className="text-sm font-semibold text-foreground">{title}</div>
          {description ? <div className="text-xs text-muted-foreground">{description}</div> : null}
        </div>
        {properties.length === 0 ? (
          <JsonValueEditor value={safeValue} onChange={onChange} />
        ) : (
          <div className="space-y-3">
            {properties.map(([key, node]) => (
              <DynamicValueEditor
                key={key}
                schema={node}
                value={safeValue[key]}
                fieldKey={key}
                depth={depth + 1}
                onChange={(next) => onChange({ ...safeValue, [key]: next })}
              />
            ))}
          </div>
        )}
      </div>
    )
  }

  if (schema.type === 'array') {
    const safeItems = Array.isArray(value) ? value : []
    const itemSchema = schema.items ?? { type: 'text' }
    return (
      <div className="space-y-3 rounded-2xl border border-border bg-background p-4" style={{ marginLeft: depth * 8 }}>
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-foreground">{title}</div>
            {description ? <div className="text-xs text-muted-foreground">{description}</div> : null}
          </div>
          <button
            type="button"
            onClick={() => onChange([...safeItems, defaultValueForSchema(itemSchema)])}
            className="rounded-xl border border-border px-3 py-2 text-xs font-medium text-foreground hover:bg-accent"
          >
            Eleman Ekle
          </button>
        </div>

        {safeItems.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-card px-4 py-5 text-sm text-muted-foreground">Dizi boş.</div>
        ) : (
          <div className="space-y-3">
            {safeItems.map((item, index) => (
              <div key={`${fieldKey ?? 'item'}-${index}`} className="rounded-xl border border-border bg-card p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Öğe {index + 1}</div>
                  <button
                    type="button"
                    onClick={() => onChange(safeItems.filter((_, itemIndex) => itemIndex !== index))}
                    className="rounded-lg border border-red-200 px-2.5 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50"
                  >
                    Sil
                  </button>
                </div>
                <DynamicValueEditor
                  schema={itemSchema}
                  value={item}
                  depth={depth + 1}
                  onChange={(next) => onChange(safeItems.map((existing, itemIndex) => (itemIndex === index ? next : existing)))}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  if (schema.type === 'bool') {
    return (
      <div className="space-y-2" style={{ marginLeft: depth * 8 }}>
        <label className="text-sm font-medium text-foreground">{title}</label>
        {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
        <select aria-label={title} value={String(Boolean(value))} onChange={(event) => onChange(event.target.value === 'true')} className={selectClass}>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      </div>
    )
  }

  if (schema.type === 'number') {
    return (
      <div className="space-y-2" style={{ marginLeft: depth * 8 }}>
        <label className="text-sm font-medium text-foreground">{title}</label>
        {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
        <input
          type="number"
          value={typeof value === 'number' ? value : 0}
          onChange={(event) => onChange(Number(event.target.value))}
          aria-label={title}
          className={inputClass}
        />
      </div>
    )
  }

  if (schema.type === 'enum') {
    const options = schema.enum_values ?? schema.options ?? []
    return (
      <div className="space-y-2" style={{ marginLeft: depth * 8 }}>
        <label className="text-sm font-medium text-foreground">{title}</label>
        {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
        <select aria-label={title} value={typeof value === 'string' ? value : options[0] ?? ''} onChange={(event) => onChange(event.target.value)} className={selectClass}>
          {options.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      </div>
    )
  }

  if (schema.type === 'json') {
    return <JsonValueEditor label={title} value={value} onChange={onChange} />
  }

  const multiline = typeof value === 'string' && value.length > 80
  return (
    <div className="space-y-2" style={{ marginLeft: depth * 8 }}>
      <label className="text-sm font-medium text-foreground">{title}</label>
      {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
      {multiline ? (
        <textarea aria-label={title} value={typeof value === 'string' ? value : ''} onChange={(event) => onChange(event.target.value)} className={textareaClass} rows={4} />
      ) : (
        <input aria-label={title} value={typeof value === 'string' ? value : ''} onChange={(event) => onChange(event.target.value)} className={inputClass} />
      )}
    </div>
  )
}

interface InstanceFormModalProps {
  open: boolean
  mode: 'create' | 'edit'
  initialInstance: YamlInstanceItem | null
  templates: YamlTemplateItem[]
  defaultTemplateId: string
  onClose: () => void
  onSubmit: (payload: YamlInstanceCreatePayload | YamlInstanceUpdatePayload, instanceId?: string) => Promise<void>
}

function InstanceFormModal({ open, mode, initialInstance, templates, defaultTemplateId, onClose, onSubmit }: InstanceFormModalProps) {
  const [form, setForm] = useState<InstanceFormState>({
    templateId: defaultTemplateId,
    instanceName: '',
    status: 'draft',
    createdBy: '',
    values: {},
  })
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === form.templateId) ?? null,
    [form.templateId, templates],
  )
  const normalizedSchema = useMemo(
    () => normalizeSchemaNode(selectedTemplate?.field_schema ?? { type: 'object', properties: {} }),
    [selectedTemplate?.field_schema],
  )

  useEffect(() => {
    if (!open) return
    if (mode === 'edit' && initialInstance) {
      setForm({
        templateId: initialInstance.template_id,
        instanceName: initialInstance.instance_name,
        status: (INSTANCE_STATUS_OPTIONS.includes(initialInstance.status as 'draft') ? initialInstance.status : 'draft') as 'draft' | 'final' | 'archived',
        createdBy: initialInstance.created_by ?? '',
        values: initialInstance.values,
      })
    } else {
      const template = templates.find((item) => item.id === defaultTemplateId) ?? templates[0] ?? null
      const schema = normalizeSchemaNode(template?.field_schema ?? { type: 'object', properties: {} })
      setForm({
        templateId: template?.id ?? '',
        instanceName: '',
        status: 'draft',
        createdBy: '',
        values: ensureRecord(defaultValueForSchema(schema)),
      })
    }
    setError('')
  }, [defaultTemplateId, initialInstance, mode, open, templates])

  const changeTemplate = (templateId: string) => {
    const template = templates.find((item) => item.id === templateId) ?? null
    const schema = normalizeSchemaNode(template?.field_schema ?? { type: 'object', properties: {} })
    setForm((prev) => ({
      ...prev,
      templateId,
      values: ensureRecord(defaultValueForSchema(schema)),
    }))
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setError('')
    try {
      if (!form.templateId) throw new Error('Template seçilmedi')
      if (!form.instanceName.trim()) throw new Error('Instance name zorunlu')

      if (mode === 'create') {
        const payload: YamlInstanceCreatePayload = {
          template_id: form.templateId,
          instance_name: form.instanceName.trim(),
          status: form.status,
          created_by: form.createdBy.trim() || null,
          values: form.values,
        }
        await onSubmit(payload)
      } else if (initialInstance) {
        const payload: YamlInstanceUpdatePayload = {
          instance_name: form.instanceName.trim(),
          status: form.status,
          values: form.values,
        }
        await onSubmit(payload, initialInstance.id)
      }
      onClose()
    } catch (err) {
      setError(parseError(err, 'Instance kaydedilemedi'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={mode === 'create' ? 'YAML Instance Oluştur' : 'YAML Instance Düzenle'} size="full">
      <div className="space-y-6 p-6">
        {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
          <div className="space-y-5">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2 md:col-span-2">
                <label className="text-sm font-medium text-foreground">Template</label>
                <select
                  value={form.templateId}
                  onChange={(event) => changeTemplate(event.target.value)}
                  className={selectClass}
                  disabled={mode === 'edit'}
                  aria-label="Instance template"
                >
                  {templates.map((template) => (
                    <option key={template.id} value={template.id}>{template.title} · {template.template_code}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Instance Name</label>
                <input aria-label="Instance name" value={form.instanceName} onChange={(event) => setForm((prev) => ({ ...prev, instanceName: event.target.value }))} className={inputClass} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Status</label>
                <select aria-label="Instance status" value={form.status} onChange={(event) => setForm((prev) => ({ ...prev, status: event.target.value as 'draft' | 'final' | 'archived' }))} className={selectClass}>
                  {INSTANCE_STATUS_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </div>

              {mode === 'create' && (
                <div className="space-y-2 md:col-span-2">
                  <label className="text-sm font-medium text-foreground">Created By</label>
                  <input aria-label="Instance created by" value={form.createdBy} onChange={(event) => setForm((prev) => ({ ...prev, createdBy: event.target.value }))} className={inputClass} />
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-border bg-card p-5">
              <div className="mb-4">
                <h4 className="text-lg text-foreground" style={{ fontFamily: 'var(--font-display)' }}>Template Values</h4>
                <p className="text-sm text-muted-foreground">Schema’ya göre otomatik üretilen form.</p>
              </div>
              {Object.keys(normalizedSchema.properties ?? {}).length === 0 ? (
                <JsonValueEditor value={form.values} onChange={(next) => setForm((prev) => ({ ...prev, values: ensureRecord(next) }))} label="Values JSON" />
              ) : (
                <DynamicValueEditor
                  schema={normalizedSchema}
                  value={form.values}
                  onChange={(next) => setForm((prev) => ({ ...prev, values: ensureRecord(next) }))}
                />
              )}
            </div>
          </div>

          <div className="space-y-4">
            <JsonPanel title="Raw Values JSON" data={form.values} size="large" />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3">
          <button type="button" onClick={onClose} className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-foreground hover:bg-accent">Vazgeç</button>
          <button type="button" onClick={() => void handleSubmit()} disabled={submitting} className="rounded-xl px-4 py-2.5 text-sm font-medium text-white" style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}>
            {submitting ? 'Kaydediliyor...' : mode === 'create' ? 'Instance Oluştur' : 'Instance Kaydet'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

function PropertiesTab({
  curriculumTree,
  allProperties,
  refreshProperties,
  setNotice,
}: {
  curriculumTree: CurriculumNodeItem[]
  allProperties: PropertyDefinitionItem[]
  refreshProperties: () => Promise<PropertyDefinitionItem[]>
  setNotice: (notice: NoticeState) => void
}) {
  const flatNodes = useMemo(() => flattenCurriculumNodes(curriculumTree), [curriculumTree])
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [selectedPropertyId, setSelectedPropertyId] = useState('')
  const [search, setSearch] = useState('')
  const [activeOnly, setActiveOnly] = useState(false)
  const [modalMode, setModalMode] = useState<'create' | 'edit' | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<PropertyDefinitionItem | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)

  useEffect(() => {
    if (!selectedNodeId && flatNodes.length > 0) {
      setSelectedNodeId(flatNodes[0].id)
    }
  }, [flatNodes, selectedNodeId])

  const filteredProperties = useMemo(() => {
    const term = search.trim().toLowerCase()
    return allProperties.filter((item) => {
      if (selectedNodeId && item.defined_at_curriculum_node_id !== selectedNodeId) return false
      if (activeOnly && !item.is_active) return false
      if (!term) return true
      return [item.label, item.property_key, item.canonical_path].some((value) => value.toLowerCase().includes(term))
    })
  }, [activeOnly, allProperties, search, selectedNodeId])

  useEffect(() => {
    if (!filteredProperties.some((item) => item.id === selectedPropertyId)) {
      setSelectedPropertyId(filteredProperties[0]?.id ?? '')
    }
  }, [filteredProperties, selectedPropertyId])

  const selectedNode = flatNodes.find((node) => node.id === selectedNodeId) ?? null
  const selectedProperty = filteredProperties.find((item) => item.id === selectedPropertyId) ?? null

  const handleSubmit = async (payload: PropertyDefinitionCreatePayload | PropertyDefinitionUpdatePayload, propertyId?: string) => {
    const response = propertyId ? await api.updateProperty(propertyId, payload as PropertyDefinitionUpdatePayload) : await api.createProperty(payload as PropertyDefinitionCreatePayload)
    await refreshProperties()
    setSelectedNodeId(response.defined_at_curriculum_node_id)
    setSelectedPropertyId(response.id)
    setNotice({ tone: 'success', message: propertyId ? 'Property definition güncellendi.' : 'Yeni property definition oluşturuldu.' })
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleteBusy(true)
    try {
      await api.deleteProperty(deleteTarget.id)
      await refreshProperties()
      setNotice({ tone: 'success', message: `Property silindi: ${deleteTarget.label}` })
      setDeleteTarget(null)
    } catch (error) {
      setNotice({ tone: 'error', message: parseError(error, 'Property silinemedi') })
    } finally {
      setDeleteBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <CurriculumTreePicker
          nodes={curriculumTree}
          selectedId={selectedNodeId}
          onSelect={(node) => setSelectedNodeId(node.id)}
          title="Curriculum Node"
        />

        <div className="space-y-6">
          <CrudToolbar
            title="Property Definitions"
            description="Curriculum node bazlı property tanımlarını görüntüle, oluştur ve yönet."
            searchValue={search}
            searchPlaceholder="Label, property key veya canonical path ara"
            onSearchChange={setSearch}
            onAdd={() => setModalMode('create')}
            onRefresh={() => void refreshProperties()}
            filters={(
              <label className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 text-sm text-foreground">
                <input type="checkbox" checked={activeOnly} onChange={(event) => setActiveOnly(event.target.checked)} />
                Sadece aktifler
              </label>
            )}
          />

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]">
            <div className={sectionCardClass}>
              <div className="border-b border-border px-5 py-4">
                <div className="text-sm font-medium text-foreground">Liste</div>
                <div className="text-xs text-muted-foreground">{formatNodeLabel(selectedNode)}</div>
              </div>
              <div className="max-h-[720px] overflow-auto p-4 space-y-3">
                {filteredProperties.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-sm text-muted-foreground">Bu filtre için property bulunamadı.</div>
                ) : filteredProperties.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedPropertyId(item.id)}
                    className={`w-full rounded-2xl border p-4 text-left transition-all ${selectedPropertyId === item.id ? 'border-primary bg-accent shadow-sm' : 'border-border bg-background hover:bg-accent/60'}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-foreground">{item.label}</div>
                        <div className="mt-1 text-xs text-muted-foreground">{item.canonical_path}</div>
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusBadge status={item.is_active ? 'active' : 'archived'} />
                        <span className="rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground">{item.data_type}</span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className={sectionCardClass}>
              <div className="border-b border-border px-5 py-4 flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-foreground">Detay</div>
                  <div className="text-xs text-muted-foreground">Seçili property bilgileri</div>
                </div>
                {selectedProperty && (
                  <div className="flex gap-2">
                    <button type="button" onClick={() => setModalMode('edit')} className="rounded-xl border border-border px-3 py-2 text-xs font-medium text-foreground hover:bg-accent inline-flex items-center gap-2"><Pencil className="h-3.5 w-3.5" />Düzenle</button>
                    <button type="button" onClick={() => setDeleteTarget(selectedProperty)} className="rounded-xl border border-red-200 px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-50 inline-flex items-center gap-2"><Trash2 className="h-3.5 w-3.5" />Sil</button>
                  </div>
                )}
              </div>
              <div className="p-5">
                {selectedProperty ? (
                  <div className="space-y-4">
                    <div>
                      <div className="text-xl text-foreground" style={{ fontFamily: 'var(--font-display)' }}>{selectedProperty.label}</div>
                      <div className="mt-1 text-sm text-muted-foreground">{selectedProperty.description || 'Açıklama yok'}</div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <DetailChip label="Property Key" value={selectedProperty.property_key} />
                      <DetailChip label="Canonical Path" value={selectedProperty.canonical_path} />
                      <DetailChip label="Data Type" value={selectedProperty.data_type} />
                      <DetailChip label="Default Value" value={selectedProperty.default_value || '-'} />
                      <DetailChip label="Defined At" value={selectedProperty.defined_at_curriculum_node_id} />
                      <DetailChip label="Parent Property" value={selectedProperty.parent_property_id || '-'} />
                      <DetailChip label="Required" value={selectedProperty.is_required ? 'true' : 'false'} />
                    </div>
                    <JsonPanel title="Constraints" data={selectedProperty.constraints} emptyText="Constraint yok" />
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-sm text-muted-foreground">Listeden bir property seç.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <PropertyFormModal
        open={modalMode !== null}
        mode={modalMode ?? 'create'}
        initialProperty={modalMode === 'edit' ? selectedProperty : null}
        defaultNodeId={selectedNodeId}
        allNodes={curriculumTree}
        allProperties={allProperties}
        onClose={() => setModalMode(null)}
        onSubmit={handleSubmit}
      />

      <DeleteConfirmModal
        open={Boolean(deleteTarget)}
        title="Property Definition Sil"
        message={deleteTarget ? `${deleteTarget.label} kaydını silmek istediğine emin misin?` : ''}
        busy={deleteBusy}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </div>
  )
}

function TemplatesTab({
  curriculumTree,
  templates,
  refreshTemplates,
  setNotice,
}: {
  curriculumTree: CurriculumNodeItem[]
  templates: YamlTemplateItem[]
  refreshTemplates: () => Promise<YamlTemplateItem[]>
  setNotice: (notice: NoticeState) => void
}) {
  const allFlatNodes = useMemo(() => flattenCurriculumNodes(curriculumTree), [curriculumTree])
  const flatNodes = useMemo(() => allFlatNodes.filter((node) => node.scope === 'folder'), [allFlatNodes])
  const nodePathMap = useMemo(() => new Map(allFlatNodes.map((n) => [n.id, n.path])), [allFlatNodes])
  const [selectedFolderId, setSelectedFolderId] = useState('')
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [search, setSearch] = useState('')
  const [modalMode, setModalMode] = useState<'create' | 'edit' | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<YamlTemplateItem | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)

  const filteredTemplates = useMemo(() => {
    const term = search.trim().toLowerCase()
    const selectedPath = selectedFolderId ? (nodePathMap.get(selectedFolderId) ?? null) : null
    return templates.filter((item) => {
      if (selectedPath) {
        const itemPath = nodePathMap.get(item.curriculum_folder_node_id) ?? ''
        if (!itemPath.startsWith(selectedPath)) return false
      }
      if (!term) return true
      return [item.template_code, item.title, item.description ?? ''].some((value) => value.toLowerCase().includes(term))
    })
  }, [nodePathMap, search, selectedFolderId, templates])

  useEffect(() => {
    if (!filteredTemplates.some((item) => item.id === selectedTemplateId)) {
      setSelectedTemplateId(filteredTemplates[0]?.id ?? '')
    }
  }, [filteredTemplates, selectedTemplateId])

  const selectedFolder = allFlatNodes.find((node) => node.id === selectedFolderId) ?? null
  const selectedTemplate = filteredTemplates.find((item) => item.id === selectedTemplateId) ?? null

  const handleSubmit = async (payload: YamlTemplateCreatePayload | YamlTemplateUpdatePayload, templateId?: string) => {
    const response = templateId
      ? await api.updateYamlTemplate(templateId, payload as YamlTemplateUpdatePayload)
      : await api.createYamlTemplate(payload as YamlTemplateCreatePayload)
    await refreshTemplates()
    setSelectedFolderId(response.curriculum_folder_node_id)
    setSelectedTemplateId(response.id)
    setNotice({ tone: 'success', message: templateId ? 'YAML template güncellendi.' : 'Yeni YAML template oluşturuldu.' })
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleteBusy(true)
    try {
      await api.deleteYamlTemplate(deleteTarget.id)
      await refreshTemplates()
      setNotice({ tone: 'success', message: `Template silindi: ${deleteTarget.title}` })
      setDeleteTarget(null)
    } catch (error) {
      setNotice({ tone: 'error', message: parseError(error, 'Template silinemedi') })
    } finally {
      setDeleteBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <CurriculumTreePicker
          nodes={curriculumTree}
          selectedId={selectedFolderId}
          onSelect={(node) => setSelectedFolderId(node.id)}
          onClearSelection={() => setSelectedFolderId('')}
          title="Template Folder Seçimi"
        />

        <div className="space-y-6">
          <CrudToolbar
            title="YAML Templates"
            description="Curriculum folder node altındaki gerçek template kayıtlarını yönet."
            searchValue={search}
            searchPlaceholder="Template code, title veya description ara"
            onSearchChange={setSearch}
            onAdd={() => setModalMode('create')}
            onRefresh={() => void refreshTemplates()}
          />

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]">
            <div className={sectionCardClass}>
              <div className="border-b border-border px-5 py-4">
                <div className="text-sm font-medium text-foreground">Liste</div>
                <div className="text-xs text-muted-foreground">{selectedFolder ? formatNodeLabel(selectedFolder) : 'Tüm folderlar'}</div>
              </div>
              <div className="max-h-[720px] overflow-auto p-4 space-y-3">
                {filteredTemplates.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-sm text-muted-foreground">Bu filtre için template bulunamadı.</div>
                ) : filteredTemplates.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedTemplateId(item.id)}
                    className={`w-full rounded-2xl border p-4 text-left transition-all ${selectedTemplateId === item.id ? 'border-primary bg-accent shadow-sm' : 'border-border bg-background hover:bg-accent/60'}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-foreground">{item.title}</div>
                        <div className="mt-1 text-xs text-muted-foreground">{item.template_code}</div>
                      </div>
                      <StatusBadge status={item.status} />
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className={sectionCardClass}>
              <div className="border-b border-border px-5 py-4 flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-foreground">Detay</div>
                  <div className="text-xs text-muted-foreground">Seçili template özeti</div>
                </div>
                {selectedTemplate && (
                  <div className="flex gap-2">
                    <button type="button" onClick={() => setModalMode('edit')} className="rounded-xl border border-border px-3 py-2 text-xs font-medium text-foreground hover:bg-accent inline-flex items-center gap-2"><Pencil className="h-3.5 w-3.5" />Düzenle</button>
                    <button type="button" onClick={() => setDeleteTarget(selectedTemplate)} className="rounded-xl border border-red-200 px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-50 inline-flex items-center gap-2"><Trash2 className="h-3.5 w-3.5" />Sil</button>
                  </div>
                )}
              </div>
              <div className="p-5">
                {selectedTemplate ? (
                  <div className="space-y-4">
                    <div>
                      <div className="text-xl text-foreground" style={{ fontFamily: 'var(--font-display)' }}>{selectedTemplate.title}</div>
                      <div className="mt-1 text-sm text-muted-foreground">{selectedTemplate.description || 'Açıklama yok'}</div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <DetailChip label="Template Code" value={selectedTemplate.template_code} />
                      <DetailChip label="Schema Version" value={selectedTemplate.schema_version} />
                      <DetailChip label="Status" value={selectedTemplate.status} />
                      <DetailChip label="Created By" value={selectedTemplate.created_by || '-'} />
                    </div>
                    <JsonPanel title="Field Schema" data={selectedTemplate.field_schema} size="large" />
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-sm text-muted-foreground">Listeden bir template seç.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <TemplateFormModal
        open={modalMode !== null}
        mode={modalMode ?? 'create'}
        initialTemplate={modalMode === 'edit' ? selectedTemplate : null}
        folderNodes={flatNodes}
        defaultFolderId={selectedFolderId}
        onClose={() => setModalMode(null)}
        onSubmit={handleSubmit}
      />

      <DeleteConfirmModal
        open={Boolean(deleteTarget)}
        title="YAML Template Sil"
        message={deleteTarget ? `${deleteTarget.title} kaydını silmek istediğine emin misin?` : ''}
        busy={deleteBusy}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </div>
  )
}

function InstancesTab({
  templates,
  instances,
  refreshInstances,
  setNotice,
}: {
  templates: YamlTemplateItem[]
  instances: YamlInstanceItem[]
  refreshInstances: () => Promise<YamlInstanceItem[]>
  setNotice: (notice: NoticeState) => void
}) {
  const [templateFilterId, setTemplateFilterId] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [search, setSearch] = useState('')
  const [selectedInstanceId, setSelectedInstanceId] = useState('')
  const [modalMode, setModalMode] = useState<'create' | 'edit' | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<YamlInstanceItem | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [renderBusyId, setRenderBusyId] = useState('')

  const filteredInstances = useMemo(() => {
    const term = search.trim().toLowerCase()
    return instances.filter((item) => {
      if (templateFilterId && item.template_id !== templateFilterId) return false
      if (statusFilter && item.status !== statusFilter) return false
      if (!term) return true
      return item.instance_name.toLowerCase().includes(term)
    })
  }, [instances, search, statusFilter, templateFilterId])

  useEffect(() => {
    if (!filteredInstances.some((item) => item.id === selectedInstanceId)) {
      setSelectedInstanceId(filteredInstances[0]?.id ?? '')
    }
  }, [filteredInstances, selectedInstanceId])

  const selectedInstance = filteredInstances.find((item) => item.id === selectedInstanceId) ?? null
  const selectedTemplate = templates.find((item) => item.id === selectedInstance?.template_id) ?? null

  const handleSubmit = async (payload: YamlInstanceCreatePayload | YamlInstanceUpdatePayload, instanceId?: string) => {
    const response = instanceId
      ? await api.updateYamlInstance(instanceId, payload as YamlInstanceUpdatePayload)
      : await api.createYamlInstance(payload as YamlInstanceCreatePayload)
    await refreshInstances()
    setSelectedInstanceId(response.id)
    setTemplateFilterId(response.template_id)
    setNotice({ tone: 'success', message: instanceId ? 'YAML instance güncellendi.' : 'Yeni YAML instance oluşturuldu.' })
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleteBusy(true)
    try {
      await api.deleteYamlInstance(deleteTarget.id)
      await refreshInstances()
      setNotice({ tone: 'success', message: `Instance silindi: ${deleteTarget.instance_name}` })
      setDeleteTarget(null)
    } catch (error) {
      setNotice({ tone: 'error', message: parseError(error, 'Instance silinemedi') })
    } finally {
      setDeleteBusy(false)
    }
  }

  const handleRender = async (instanceId: string) => {
    setRenderBusyId(instanceId)
    try {
      const response = await api.renderYamlInstance(instanceId)
      await refreshInstances()
      setNotice({ tone: 'success', message: `Rendered YAML güncellendi. Artifact: ${response.artifact_id}` })
    } catch (error) {
      setNotice({ tone: 'error', message: parseError(error, 'YAML render edilemedi') })
    } finally {
      setRenderBusyId('')
    }
  }

  return (
    <div className="space-y-6">
      <CrudToolbar
        title="YAML Instances"
        description="Template kayıtlarından türetilmiş doldurulmuş YAML instance’larını yönet."
        searchValue={search}
        searchPlaceholder="Instance name ara"
        onSearchChange={setSearch}
        onAdd={() => setModalMode('create')}
        onRefresh={() => void refreshInstances()}
        filters={(
          <>
            <select value={templateFilterId} onChange={(event) => setTemplateFilterId(event.target.value)} className={selectClass}>
              <option value="">Tüm template'ler</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>{template.title}</option>
              ))}
            </select>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className={selectClass}>
              <option value="">Tüm statüler</option>
              {INSTANCE_STATUS_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </>
        )}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
        <div className={sectionCardClass}>
          <div className="border-b border-border px-5 py-4">
            <div className="text-sm font-medium text-foreground">Liste</div>
            <div className="text-xs text-muted-foreground">Template ve status filtreleri uygulanır.</div>
          </div>
          <div className="max-h-[760px] overflow-auto p-4 space-y-3">
            {filteredInstances.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-sm text-muted-foreground">Bu filtre için instance bulunamadı.</div>
            ) : filteredInstances.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setSelectedInstanceId(item.id)}
                className={`w-full rounded-2xl border p-4 text-left transition-all ${selectedInstanceId === item.id ? 'border-primary bg-accent shadow-sm' : 'border-border bg-background hover:bg-accent/60'}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-foreground">{item.instance_name}</div>
                    <div className="mt-1 text-xs text-muted-foreground">template_id: {item.template_id}</div>
                  </div>
                  <StatusBadge status={item.status} />
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className={sectionCardClass}>
          <div className="border-b border-border px-5 py-4 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-foreground">Detay</div>
              <div className="text-xs text-muted-foreground">Seçili YAML instance</div>
            </div>
            {selectedInstance && (
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setModalMode('edit')} className="rounded-xl border border-border px-3 py-2 text-xs font-medium text-foreground hover:bg-accent inline-flex items-center gap-2"><Pencil className="h-3.5 w-3.5" />Düzenle</button>
                <button type="button" onClick={() => void handleRender(selectedInstance.id)} disabled={renderBusyId === selectedInstance.id} className="rounded-xl border border-border px-3 py-2 text-xs font-medium text-foreground hover:bg-accent inline-flex items-center gap-2"><WandSparkles className="h-3.5 w-3.5" />{renderBusyId === selectedInstance.id ? 'Render...' : 'Render YAML'}</button>
                <button type="button" onClick={() => setDeleteTarget(selectedInstance)} className="rounded-xl border border-red-200 px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-50 inline-flex items-center gap-2"><Trash2 className="h-3.5 w-3.5" />Sil</button>
              </div>
            )}
          </div>
          <div className="p-5">
            {selectedInstance ? (
              <div className="space-y-4">
                <div>
                  <div className="text-xl text-foreground" style={{ fontFamily: 'var(--font-display)' }}>{selectedInstance.instance_name}</div>
                  <div className="mt-1 text-sm text-muted-foreground">{selectedTemplate ? `${selectedTemplate.title} · ${selectedTemplate.template_code}` : 'Template bilgisi bulunamadı'}</div>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <DetailChip label="Status" value={selectedInstance.status} />
                  <DetailChip label="Created By" value={selectedInstance.created_by || '-'} />
                  <DetailChip label="Instance ID" value={selectedInstance.id} />
                  <DetailChip label="Template ID" value={selectedInstance.template_id} />
                </div>
                <div className="rounded-2xl border border-border bg-background p-4">
                  <div className="mb-2 text-sm font-medium text-foreground">Rendered YAML Preview</div>
                  <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap break-words rounded-xl bg-white p-4 text-xs text-gray-800">{selectedInstance.rendered_yaml_text || 'Henüz render edilmemiş.'}</pre>
                </div>
                <JsonPanel title="Raw Values JSON" data={selectedInstance.values} size="large" />
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-sm text-muted-foreground">Listeden bir instance seç.</div>
            )}
          </div>
        </div>
      </div>

      <InstanceFormModal
        open={modalMode !== null}
        mode={modalMode ?? 'create'}
        initialInstance={modalMode === 'edit' ? selectedInstance : null}
        templates={templates}
        defaultTemplateId={templateFilterId || templates[0]?.id || ''}
        onClose={() => setModalMode(null)}
        onSubmit={handleSubmit}
      />

      <DeleteConfirmModal
        open={Boolean(deleteTarget)}
        title="YAML Instance Sil"
        message={deleteTarget ? `${deleteTarget.instance_name} kaydını silmek istediğine emin misin?` : ''}
        busy={deleteBusy}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </div>
  )
}

function DetailChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-background px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 break-all text-sm text-foreground">{value}</div>
    </div>
  )
}

interface NodePropertyManagerModalProps {
  open: boolean
  node: CurriculumNodeItem | null
  allProperties: PropertyDefinitionItem[]
  onClose: () => void
  refreshProperties: () => Promise<PropertyDefinitionItem[]>
  setNotice: (notice: NoticeState) => void
}

function NodePropertyManagerModal({
  open,
  node,
  allProperties,
  onClose,
  refreshProperties,
  setNotice,
}: NodePropertyManagerModalProps) {
  const [label, setLabel] = useState('')
  const [propertyKey, setPropertyKey] = useState('')
  const [canonicalPath, setCanonicalPath] = useState('')
  const [dataType, setDataType] = useState<PropertyDataType>('text')
  const [defaultValue, setDefaultValue] = useState('')
  const [description, setDescription] = useState('')
  const [parentPropertyId, setParentPropertyId] = useState('')
  const [isRequired, setIsRequired] = useState(false)
  const [effectiveParents, setEffectiveParents] = useState<PropertyDefinitionItem[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [keyTouched, setKeyTouched] = useState(false)
  const [pathTouched, setPathTouched] = useState(false)

  useEffect(() => {
    if (!open || !node) return
    setLabel('')
    setPropertyKey('')
    setCanonicalPath('')
    setDataType('text')
    setDefaultValue('')
    setDescription('')
    setParentPropertyId('')
    setIsRequired(false)
    setError('')
    setBusy(false)
    setKeyTouched(false)
    setPathTouched(false)
    void api.getEffectiveProperties(node.id)
      .then((rows) => setEffectiveParents(rows))
      .catch((err) => setError(parseError(err, 'Parent property listesi alınamadı')))
  }, [open, node])

  const nodeProperties = useMemo(
    () => allProperties
      .filter((item) => item.defined_at_curriculum_node_id === node?.id)
      .sort((a, b) => a.canonical_path.localeCompare(b.canonical_path)),
    [allProperties, node?.id],
  )

  const propertyMap = useMemo(() => new Map(allProperties.map((item) => [item.id, item])), [allProperties])

  const parentLabel = (propertyId?: string | null) => {
    if (!propertyId) return '-'
    const parent = propertyMap.get(propertyId)
    if (!parent) return `Silinmiş parent (${propertyId})`
    return `${parent.label} · ${parent.canonical_path}`
  }

  const parentChain = (item: PropertyDefinitionItem): string => {
    const names: string[] = []
    let cursor = item.parent_property_id
    let guard = 0
    while (cursor && guard < 20) {
      const parent = propertyMap.get(cursor)
      if (!parent) break
      names.unshift(parent.label || parent.property_key)
      cursor = parent.parent_property_id
      guard += 1
    }
    return names.length > 0 ? names.join(' > ') : '-'
  }

  const handleLabelChange = (value: string) => {
    setLabel(value)
    const generated = toSchemaKey(value)
    if (!keyTouched) setPropertyKey(generated)
    if (!pathTouched) setCanonicalPath(generated)
  }

  const handleCreate = async () => {
    if (!node) return
    setBusy(true)
    setError('')
    try {
      const trimmedLabel = label.trim()
      const trimmedKey = propertyKey.trim()
      const trimmedPath = canonicalPath.trim()
      if (!trimmedLabel || !trimmedKey || !trimmedPath) {
        throw new Error('Label, property key ve canonical path zorunlu')
      }
      await api.createProperty({
        defined_at_curriculum_node_id: node.id,
        parent_property_id: parentPropertyId || null,
        label: trimmedLabel,
        description: description.trim() || null,
        property_key: trimmedKey,
        canonical_path: trimmedPath,
        data_type: dataType,
        default_value: dataType === 'object' ? null : (defaultValue.trim() || null),
        is_required: isRequired,
      })
      await refreshProperties()
      setNotice({ tone: 'success', message: `${node.name} için yeni property eklendi.` })
      setLabel('')
      setPropertyKey('')
      setCanonicalPath('')
      setDefaultValue('')
      setDescription('')
      setParentPropertyId('')
      setIsRequired(false)
      setKeyTouched(false)
      setPathTouched(false)
    } catch (err) {
      setError(parseError(err, 'Property oluşturulamadı'))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (item: PropertyDefinitionItem) => {
    setBusy(true)
    setError('')
    try {
      await api.deleteProperty(item.id)
      await refreshProperties()
      setNotice({ tone: 'success', message: `Property silindi: ${item.label}` })
      if (parentPropertyId === item.id) setParentPropertyId('')
    } catch (err) {
      setError(parseError(err, 'Property silinemedi'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={node ? `${node.name} · Alanları Yönet` : 'Alanları Yönet'} size="wide">
      <div className="space-y-5 p-6">
        {node ? <div className="text-xs text-muted-foreground">{node.path}</div> : null}
        {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

        <div className="rounded-2xl border border-border bg-card p-4">
          <div className="mb-3 text-sm font-medium text-foreground">Yeni Property Ekle</div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Label</label>
              <input value={label} onChange={(e) => handleLabelChange(e.target.value)} className={inputClass} />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Data Type</label>
              <select
                value={dataType}
                onChange={(e) => {
                  const nextType = e.target.value as PropertyDataType
                  setDataType(nextType)
                  if (nextType === 'object') setDefaultValue('')
                }}
                className={selectClass}
              >
                {DATA_TYPE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Property Key</label>
              <input
                value={propertyKey}
                onChange={(e) => {
                  setKeyTouched(true)
                  setPropertyKey(e.target.value)
                }}
                className={inputClass}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Canonical Path</label>
              <input
                value={canonicalPath}
                onChange={(e) => {
                  setPathTouched(true)
                  setCanonicalPath(e.target.value)
                }}
                className={inputClass}
              />
            </div>
            <div className="space-y-1 md:col-span-2">
              <label className="text-xs font-medium text-muted-foreground">Description</label>
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} className={textareaClass} rows={3} />
            </div>
            <div className="space-y-1 md:col-span-2">
              <label className="text-xs font-medium text-muted-foreground">Default Value</label>
              <input
                value={defaultValue}
                onChange={(e) => setDefaultValue(e.target.value)}
                className={inputClass}
                disabled={dataType === 'object'}
                placeholder={dataType === 'array' ? 'deger1;deger2;deger3' : 'Varsayılan değer'}
              />
              {dataType === 'array' ? (
                <div className="text-xs text-muted-foreground">Array tipinde öğeleri `;` ile ayır.</div>
              ) : null}
            </div>
            <div className="space-y-1 md:col-span-2">
              <label className="text-xs font-medium text-muted-foreground">Parent Property</label>
              <select value={parentPropertyId} onChange={(e) => setParentPropertyId(e.target.value)} className={selectClass}>
                <option value="">Parent yok</option>
                {effectiveParents.map((item) => (
                  <option key={item.id} value={item.id}>{item.label} · {item.canonical_path}</option>
                ))}
              </select>
            </div>
            <label className="inline-flex items-center gap-2 rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground">
              <input type="checkbox" checked={isRequired} onChange={(e) => setIsRequired(e.target.checked)} />
              Zorunlu alan
            </label>
          </div>
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={busy || !node}
              className="rounded-xl px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
              style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
            >
              {busy ? 'Kaydediliyor...' : 'Property Ekle'}
            </button>
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-card">
          <div className="border-b border-border px-4 py-3 text-sm font-medium text-foreground">Bu Node'da Tanımlı Property'ler ({nodeProperties.length})</div>
          <div className="max-h-[380px] space-y-3 overflow-auto p-4">
            {nodeProperties.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-sm text-muted-foreground">Bu node'da tanımlı property yok.</div>
            ) : nodeProperties.map((item) => (
              <div key={item.id} className="rounded-xl border border-border bg-background p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-foreground">{item.label}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{item.canonical_path}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground">{item.data_type}</span>
                    <button
                      type="button"
                      onClick={() => void handleDelete(item)}
                      disabled={busy}
                      className="rounded-lg border border-red-200 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
                    >
                      Sil
                    </button>
                  </div>
                </div>
                <div className="mt-3 grid gap-2 text-xs text-muted-foreground">
                  <div><span className="font-medium text-foreground">Parent:</span> {parentLabel(item.parent_property_id)}</div>
                  <div><span className="font-medium text-foreground">Parent Zinciri:</span> {parentChain(item)}</div>
                  <div><span className="font-medium text-foreground">Default:</span> {item.default_value || '-'}</div>
                  <div><span className="font-medium text-foreground">Required:</span> {item.is_required ? 'true' : 'false'}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  )
}

export function ContentManagementPage() {
  const [activeTab, setActiveTab] = useState<ContentTab>('properties')
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [curriculumTree, setCurriculumTree] = useState<CurriculumNodeItem[]>([])
  const [properties, setProperties] = useState<PropertyDefinitionItem[]>([])
  const [templates, setTemplates] = useState<YamlTemplateItem[]>([])
  const [instances, setInstances] = useState<YamlInstanceItem[]>([])
  const [loading, setLoading] = useState(true)

  const [treeCreateFolderId, setTreeCreateFolderId] = useState<string | null>(null)
  const [treeCreatePrefilledFields, setTreeCreatePrefilledFields] = useState<SchemaFieldDraft[]>([])
  const [folderPromptUnite, setFolderPromptUnite] = useState<CurriculumNodeItem | null>(null)
  const [folderPromptBusy, setFolderPromptBusy] = useState(false)
  const [propertyManagerNode, setPropertyManagerNode] = useState<CurriculumNodeItem | null>(null)

  const loadCurriculumTree = async () => {
    const rows = await api.getCurriculumTree()
    setCurriculumTree(rows)
    return rows
  }

  const loadProperties = async () => {
    const rows = await api.listProperties()
    setProperties(rows)
    return rows
  }

  const loadTemplates = async () => {
    const rows = await api.listYamlTemplates()
    setTemplates(rows)
    return rows
  }

  const loadInstances = async () => {
    const rows = await api.listYamlInstances()
    setInstances(rows)
    return rows
  }

  useEffect(() => {
    void (async () => {
      setLoading(true)
      try {
        await Promise.all([loadCurriculumTree(), loadProperties(), loadTemplates(), loadInstances()])
      } catch (error) {
        setNotice({ tone: 'error', message: parseError(error, 'İçerik yönetimi verileri yüklenemedi') })
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const openTemplateCreateForFolder = async (folderId: string) => {
    try {
      const props = await api.getEffectiveProperties(folderId)
      const drafts = propertiesToDrafts(props)
      setTreeCreatePrefilledFields(drafts)
      setTreeCreateFolderId(folderId)
    } catch (error) {
      setNotice({ tone: 'error', message: parseError(error, 'Effective property listesi alınamadı') })
    }
  }

  const handleAddTemplate = (node: CurriculumNodeItem) => {
    if (node.scope === 'folder') {
      void openTemplateCreateForFolder(node.id)
    } else {
      setFolderPromptUnite(node)
    }
  }

  const handleFolderPromptConfirm = async (name: string, slug: string) => {
    if (!folderPromptUnite) return
    setFolderPromptBusy(true)
    try {
      const parts = folderPromptUnite.path.split('/')
      const grade = parts[1]
      const subject = parts[2]
      const theme = parts[3]
      if (!grade || !subject || !theme) {
        throw new Error('Ünite path geçersiz; grade/subject/theme çıkarılamadı')
      }
      const newNode = await api.createCurriculumNode({
        parent_id: null,
        name,
        slug,
        grade,
        subject,
        theme,
      })
      await loadCurriculumTree()
      setFolderPromptUnite(null)
      await openTemplateCreateForFolder(newNode.id)
      setNotice({ tone: 'success', message: `Yeni folder oluşturuldu: ${newNode.name}` })
    } catch (error) {
      setNotice({ tone: 'error', message: parseError(error, 'Folder oluşturulamadı') })
      throw error
    } finally {
      setFolderPromptBusy(false)
    }
  }

  const handleTreeTemplateSubmit = async (
    payload: YamlTemplateCreatePayload | YamlTemplateUpdatePayload,
    templateId?: string,
  ) => {
    if (templateId) {
      await api.updateYamlTemplate(templateId, payload as YamlTemplateUpdatePayload)
    } else {
      await api.createYamlTemplate(payload as YamlTemplateCreatePayload)
    }
    await loadTemplates()
    setTreeCreateFolderId(null)
    setTreeCreatePrefilledFields([])
    setNotice({ tone: 'success', message: templateId ? 'YAML template güncellendi.' : 'Yeni YAML template oluşturuldu.' })
  }

  const folderNodes = useMemo(() => flattenCurriculumNodes(curriculumTree).filter((n) => n.scope === 'folder'), [curriculumTree])

  return (
    <div className="p-8 max-w-[1680px] mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="space-y-6"
      >
        <div className="rounded-[28px] border border-border bg-card px-8 py-7 shadow-xl">
          <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-2xl text-white shadow-lg" style={{ background: 'linear-gradient(to bottom right, var(--primary), var(--secondary))' }}>
                <Sparkles className="h-7 w-7" />
              </div>
              <h1 className="text-4xl text-foreground" style={{ fontFamily: 'var(--font-display)' }}>
                Müfredat Yönetimi
              </h1>
              <p className="mt-2 text-lg text-muted-foreground">
                Property definitions, YAML templates ve YAML instances kayıtlarını tek bir ekrandan görüntüle, ekle, düzenle ve sil.
              </p>
            </div>
            <div className="rounded-2xl border border-border bg-background px-5 py-4 text-sm text-muted-foreground shadow-sm">
              <div className="flex items-center gap-2 font-medium text-foreground">
                <BookOpen className="h-4 w-4" />
                DB-backed CRUD
              </div>
              <div className="mt-1">Backend endpointleri doğrudan kullanılıyor; işlem sonrası ilgili liste yeniden yüklenir.</div>
            </div>
          </div>
        </div>

        {notice ? <NoticeBanner notice={notice} onClear={() => setNotice(null)} /> : null}

        {loading ? (
          <div className="rounded-2xl border border-border bg-card px-6 py-12 text-center text-sm text-muted-foreground shadow-sm">
            İçerik yönetimi verileri yükleniyor...
          </div>
        ) : (
          <CurriculumTreePicker
            nodes={curriculumTree}
            selectedId={selectedNodeId}
            onSelect={(node) => setSelectedNodeId(node.id)}
            title="Müfredat Ağacı"
            fullHeight
            templates={templates}
            onAddTemplate={handleAddTemplate}
            onManageProperties={(node) => setPropertyManagerNode(node)}
          />
        )}

        <NodePropertyManagerModal
          open={propertyManagerNode !== null}
          node={propertyManagerNode}
          allProperties={properties}
          onClose={() => setPropertyManagerNode(null)}
          refreshProperties={loadProperties}
          setNotice={setNotice}
        />

        <TemplateFormModal
          open={treeCreateFolderId !== null}
          mode="create"
          initialTemplate={null}
          folderNodes={folderNodes}
          defaultFolderId={treeCreateFolderId ?? ''}
          onClose={() => {
            setTreeCreateFolderId(null)
            setTreeCreatePrefilledFields([])
          }}
          onSubmit={handleTreeTemplateSubmit}
          prefilledFields={treeCreatePrefilledFields}
          lockFolder
        />

        <FolderNamePromptModal
          open={folderPromptUnite !== null}
          uniteName={folderPromptUnite?.name ?? ''}
          unitePath={folderPromptUnite?.path ?? ''}
          busy={folderPromptBusy}
          onClose={() => {
            if (!folderPromptBusy) setFolderPromptUnite(null)
          }}
          onConfirm={handleFolderPromptConfirm}
        />
      </motion.div>
    </div>
  )
}
