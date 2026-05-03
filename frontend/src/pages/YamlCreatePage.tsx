import { useEffect, useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { BookOpen, Plus, Sparkles, Trash2 } from 'lucide-react'

import { api, ApiError } from '../lib/api'
import type { CurriculumNodeItem, PropertyDefinitionItem, YamlTemplateItem } from '../types'

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

const inputClass = 'w-full rounded-xl border-2 border-border bg-white px-4 py-3 text-sm text-foreground focus:outline-none focus:border-primary transition-colors'
const textareaClass = `${inputClass} min-h-[110px] resize-y`
const selectClass = inputClass

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

function normalizeSchemaNode(input: unknown): SchemaNode {
  if (!isRecord(input)) return { type: 'object', properties: {} }

  const rawType = typeof input.type === 'string' ? input.type : 'object'
  const type = (['text', 'number', 'bool', 'enum', 'json', 'object', 'array'].includes(rawType) ? rawType : 'object') as SchemaFieldType
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

function parseBoolText(value: string): boolean {
  const normalized = value.trim().toLowerCase()
  return ['true', '1', 'yes', 'evet', 'on'].includes(normalized)
}

function parsePrimitiveDefault(node: SchemaNode, rawValue: string): unknown {
  const text = rawValue.trim()
  if (!text) return defaultValueForSchema(node)
  if (node.type === 'number') {
    const asNumber = Number(text)
    return Number.isNaN(asNumber) ? 0 : asNumber
  }
  if (node.type === 'bool') return parseBoolText(text)
  if (node.type === 'json') {
    try {
      return JSON.parse(text)
    } catch {
      return defaultValueForSchema(node)
    }
  }
  return text
}

function parseArrayDefault(node: SchemaNode, rawValue: string): unknown[] {
  const itemSchema = node.items ?? { type: 'text' }
  const tokens = rawValue
    .split(';')
    .map((chunk) => chunk.trim())
    .filter(Boolean)
  if (itemSchema.type === 'object' || itemSchema.type === 'array') return []
  return tokens.map((token) => parsePrimitiveDefault(itemSchema, token))
}

function buildDefaultsFromSchemaAndProperties(
  node: SchemaNode,
  propertyByPath: Map<string, PropertyDefinitionItem>,
  pathSegments: string[] = [],
): unknown {
  const canonicalPath = pathSegments.join('.')
  const matchingProperty = canonicalPath ? propertyByPath.get(canonicalPath) : undefined
  const rawDefault = matchingProperty?.default_value?.trim()

  if (node.type === 'object') {
    const output: Record<string, unknown> = {}
    for (const [key, child] of Object.entries(node.properties ?? {})) {
      output[key] = buildDefaultsFromSchemaAndProperties(child, propertyByPath, [...pathSegments, key])
    }
    return output
  }

  if (rawDefault) {
    if (node.type === 'array') return parseArrayDefault(node, rawDefault)
    return parsePrimitiveDefault(node, rawDefault)
  }

  return defaultValueForSchema(node)
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

function JsonValueEditor({ value, onChange, label }: { value: unknown; onChange: (next: unknown) => void; label?: string }) {
  const [text, setText] = useState('')

  useEffect(() => {
    try {
      setText(JSON.stringify(value ?? {}, null, 2))
    } catch {
      setText('{}')
    }
  }, [value])

  return (
    <div className="space-y-2">
      {label ? <label className="text-sm font-medium text-foreground">{label}</label> : null}
      <textarea
        value={text}
        onChange={(event) => {
          const next = event.target.value
          setText(next)
          try {
            onChange(JSON.parse(next))
          } catch {
            // invalid JSON remains local
          }
        }}
        className={textareaClass}
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
  compact = false,
}: {
  schema: SchemaNode
  value: unknown
  onChange: (next: unknown) => void
  fieldKey?: string
  depth?: number
  compact?: boolean
}) {
  const title = schema.label?.trim() || fieldKey || ''
  const description = schema.description?.trim()

  if (schema.type === 'object') {
    const safeValue = isRecord(value) ? value : {}
    const properties = Object.entries(schema.properties ?? {})

    if (depth === 0) {
      return (
        <div className="space-y-3">
          {properties.length === 0 ? (
            <JsonValueEditor value={safeValue} onChange={onChange} />
          ) : (
            properties.map(([key, node]) => (
              <DynamicValueEditor
                key={key}
                schema={node}
                value={safeValue[key]}
                fieldKey={key}
                depth={depth + 1}
                onChange={(next) => onChange({ ...safeValue, [key]: next })}
              />
            ))
          )}
        </div>
      )
    }

    return (
      <div className="space-y-2" style={{ marginLeft: depth * 8 }}>
        {title ? <div className="text-sm font-semibold text-foreground">{title}</div> : null}
        {description ? <div className="text-xs text-muted-foreground">{description}</div> : null}
        <div className="space-y-2 border-l border-border pl-3">
          {properties.length === 0 ? (
            <JsonValueEditor value={safeValue} onChange={onChange} />
          ) : (
            properties.map(([key, node]) => (
              <DynamicValueEditor
                key={key}
                schema={node}
                value={safeValue[key]}
                fieldKey={key}
                depth={depth + 1}
                onChange={(next) => onChange({ ...safeValue, [key]: next })}
              />
            ))
          )}
        </div>
      </div>
    )
  }

  if (schema.type === 'array') {
    const safeItems = Array.isArray(value) ? value : []
    const itemSchema = schema.items ?? { type: 'text' }
    return (
      <div className="space-y-2" style={{ marginLeft: depth * 8 }}>
        <div className="flex items-center justify-between gap-3">
          <div>
            {title ? <div className="text-sm font-semibold text-foreground">{title}</div> : null}
            {description ? <div className="text-xs text-muted-foreground">{description}</div> : null}
          </div>
          <button
            type="button"
            onClick={() => onChange([...safeItems, defaultValueForSchema(itemSchema)])}
            className="rounded-xl border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent inline-flex items-center gap-1.5"
          >
            <Plus className="h-3.5 w-3.5" />
            Öğe Ekle
          </button>
        </div>
        {safeItems.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-card px-4 py-3 text-sm text-muted-foreground">Henüz öğe yok.</div>
        ) : (
          <div className="space-y-2 border-l border-border pl-3">
            {safeItems.map((item, index) => (
              <div key={`item-${index}`} className="flex items-start gap-2">
                <div className="pt-2 text-xs text-muted-foreground">-</div>
                <div className="min-w-0 flex-1">
                  <DynamicValueEditor
                    schema={itemSchema}
                    value={item}
                    depth={depth + 1}
                    compact={itemSchema.type !== 'object' && itemSchema.type !== 'array'}
                    onChange={(next) => onChange(safeItems.map((curr, i) => (i === index ? next : curr)))}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => onChange(safeItems.filter((_, i) => i !== index))}
                  className="mt-1 rounded-lg border border-red-200 px-2 py-1 text-xs text-red-700 hover:bg-red-50 inline-flex items-center gap-1"
                >
                  <Trash2 className="h-3 w-3" />
                  Sil
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  if (schema.type === 'bool') {
    if (compact) {
      return (
        <label className="inline-flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />
          {Boolean(value) ? 'Evet' : 'Hayır'}
        </label>
      )
    }
    return (
      <div className="space-y-1" style={{ marginLeft: depth * 8 }}>
        {title ? <div className="text-sm font-semibold text-foreground">{title}</div> : null}
        {description ? <div className="mb-3 text-xs text-muted-foreground">{description}</div> : null}
        <label className="inline-flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />
          {Boolean(value) ? 'Evet' : 'Hayır'}
        </label>
      </div>
    )
  }

  if (schema.type === 'number') {
    if (compact) {
      return (
        <input
          type="number"
          value={typeof value === 'number' ? value : 0}
          onChange={(event) => onChange(Number(event.target.value))}
          className={inputClass}
        />
      )
    }
    return (
      <div className="space-y-1" style={{ marginLeft: depth * 8 }}>
        {title ? <div className="text-sm font-semibold text-foreground">{title}</div> : null}
        {description ? <div className="mb-3 text-xs text-muted-foreground">{description}</div> : null}
        <input
          type="number"
          value={typeof value === 'number' ? value : 0}
          onChange={(event) => onChange(Number(event.target.value))}
          className={inputClass}
        />
      </div>
    )
  }

  if (schema.type === 'enum') {
    const options = schema.enum_values ?? schema.options ?? []
    if (compact) {
      return (
        <select value={typeof value === 'string' ? value : ''} onChange={(event) => onChange(event.target.value)} className={selectClass}>
          {options.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
      )
    }
    return (
      <div className="space-y-1" style={{ marginLeft: depth * 8 }}>
        {title ? <div className="text-sm font-semibold text-foreground">{title}</div> : null}
        {description ? <div className="mb-3 text-xs text-muted-foreground">{description}</div> : null}
        <select value={typeof value === 'string' ? value : ''} onChange={(event) => onChange(event.target.value)} className={selectClass}>
          {options.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
      </div>
    )
  }

  if (schema.type === 'json') {
    if (compact) {
      return <JsonValueEditor value={value} onChange={onChange} />
    }
    return (
      <div className="space-y-1" style={{ marginLeft: depth * 8 }}>
        <JsonValueEditor value={value} onChange={onChange} label={title || undefined} />
        {description ? <div className="text-xs text-muted-foreground">{description}</div> : null}
      </div>
    )
  }

  if (compact) {
    return (
      <input
        value={typeof value === 'string' ? value : ''}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      />
    )
  }

  return (
    <div className="space-y-1" style={{ marginLeft: depth * 8 }}>
      {title ? <div className="text-sm font-semibold text-foreground">{title}</div> : null}
      {description ? <div className="mb-3 text-xs text-muted-foreground">{description}</div> : null}
      <input
        value={typeof value === 'string' ? value : ''}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      />
    </div>
  )
}

export function YamlCreatePage() {
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [loading, setLoading] = useState(true)

  const [curriculumTree, setCurriculumTree] = useState<CurriculumNodeItem[]>([])
  const [templates, setTemplates] = useState<YamlTemplateItem[]>([])

  const [yamlName, setYamlName] = useState('')
  const [yamlDescription, setYamlDescription] = useState('')
  const [createdBy, setCreatedBy] = useState('')
  const [status, setStatus] = useState<'draft' | 'final' | 'archived'>('draft')

  const [selectedGradeId, setSelectedGradeId] = useState('')
  const [selectedSubjectId, setSelectedSubjectId] = useState('')
  const [selectedUnitId, setSelectedUnitId] = useState('')
  const [selectedTemplateId, setSelectedTemplateId] = useState('')

  const [openedTemplateId, setOpenedTemplateId] = useState('')
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    void (async () => {
      setLoading(true)
      try {
        const [tree, templateRows] = await Promise.all([
          api.getCurriculumTree(),
          api.listYamlTemplates(),
        ])
        setCurriculumTree(tree)
        setTemplates(templateRows)
      } catch (error) {
        setNotice({ tone: 'error', message: parseError(error, 'YAML oluşturma verileri yüklenemedi') })
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const flatNodes = useMemo(() => flattenCurriculumNodes(curriculumTree), [curriculumTree])
  const nodeById = useMemo(() => new Map(flatNodes.map((node) => [node.id, node])), [flatNodes])
  const folderNodes = useMemo(() => flatNodes.filter((node) => node.scope === 'folder'), [flatNodes])

  const gradeNodes = useMemo(
    () => flatNodes.filter((node) => node.scope === 'constant' && node.node_type === 'grade'),
    [flatNodes],
  )
  const subjectNodes = useMemo(
    () => flatNodes.filter((node) => node.scope === 'constant' && node.node_type === 'subject' && node.parent_id === selectedGradeId),
    [flatNodes, selectedGradeId],
  )
  const unitNodes = useMemo(
    () => flatNodes.filter((node) => node.scope === 'constant' && node.node_type === 'theme' && node.parent_id === selectedSubjectId),
    [flatNodes, selectedSubjectId],
  )

  const selectedGrade = gradeNodes.find((node) => node.id === selectedGradeId) ?? null
  const selectedSubject = subjectNodes.find((node) => node.id === selectedSubjectId) ?? null
  const selectedUnit = unitNodes.find((node) => node.id === selectedUnitId) ?? null

  const filteredFolderIds = useMemo(() => {
    return folderNodes
      .filter((folder) => {
        if (selectedGrade && folder.grade !== selectedGrade.slug) return false
        if (selectedSubject && folder.subject !== selectedSubject.slug) return false
        if (selectedUnit && folder.theme !== selectedUnit.slug) return false
        return true
      })
      .map((folder) => folder.id)
  }, [folderNodes, selectedGrade, selectedSubject, selectedUnit])

  const templateOptions = useMemo(
    () => templates.filter((template) => filteredFolderIds.includes(template.curriculum_folder_node_id)),
    [templates, filteredFolderIds],
  )

  const openedTemplate = useMemo(
    () => templates.find((template) => template.id === openedTemplateId) ?? null,
    [templates, openedTemplateId],
  )

  const openedSchema = useMemo(
    () => normalizeSchemaNode(openedTemplate?.field_schema ?? { type: 'object', properties: {} }),
    [openedTemplate?.field_schema],
  )

  const loadTemplateDefaults = async (template: YamlTemplateItem) => {
    const schema = normalizeSchemaNode(template.field_schema)
    const fallbackDefaults = defaultValueForSchema(schema)
    try {
      const effectiveProperties = await api.getEffectiveProperties(template.curriculum_folder_node_id)
      const propertyByPath = new Map(effectiveProperties.map((item) => [item.canonical_path, item]))
      const hydrated = buildDefaultsFromSchemaAndProperties(schema, propertyByPath)
      setValues(isRecord(hydrated) ? hydrated : (isRecord(fallbackDefaults) ? fallbackDefaults : {}))
    } catch {
      setValues(isRecord(fallbackDefaults) ? fallbackDefaults : {})
    }
  }

  const handleOpenTemplate = async () => {
    const selected = templateOptions.find((template) => template.id === selectedTemplateId)
    if (!selected) {
      setNotice({ tone: 'error', message: 'Önce bir YAML Template seçmelisin.' })
      return
    }
    setOpenedTemplateId(selected.id)
    await loadTemplateDefaults(selected)
  }

  useEffect(() => {
    if (!openedTemplateId) return
    const selected = templates.find((template) => template.id === openedTemplateId)
    if (!selected) {
      setOpenedTemplateId('')
      setValues({})
      return
    }
    void loadTemplateDefaults(selected)
  }, [openedTemplateId, templates])

  const handleCreateInstance = async () => {
    if (!openedTemplate) {
      setNotice({ tone: 'error', message: 'Önce bir template açmalısın.' })
      return
    }
    if (!yamlName.trim()) {
      setNotice({ tone: 'error', message: 'YAML Name zorunlu.' })
      return
    }
    setSubmitting(true)
    try {
      const payloadValues: Record<string, unknown> = { ...values }
      if (yamlDescription.trim()) {
        payloadValues.__meta = {
          ...(isRecord(payloadValues.__meta) ? payloadValues.__meta : {}),
          description: yamlDescription.trim(),
        }
      }
      const response = await api.createYamlInstance({
        template_id: openedTemplate.id,
        instance_name: yamlName.trim(),
        status,
        created_by: createdBy.trim() || null,
        values: payloadValues,
      })
      setNotice({ tone: 'success', message: `YAML instance oluşturuldu: ${response.instance_name}` })
    } catch (error) {
      setNotice({ tone: 'error', message: parseError(error, 'YAML instance oluşturulamadı') })
    } finally {
      setSubmitting(false)
    }
  }

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
                YAML Oluştur
              </h1>
              <p className="mt-2 text-lg text-muted-foreground">
                Dinamik müfredat filtrelerinden template seç, property değerlerini doldur ve YAML instance üret.
              </p>
            </div>
            <div className="rounded-2xl border border-border bg-background px-5 py-4 text-sm text-muted-foreground shadow-sm">
              <div className="flex items-center gap-2 font-medium text-foreground">
                <BookOpen className="h-4 w-4" />
                Template’den Instance
              </div>
              <div className="mt-1">Sınıf → Ders → Ünite → Template akışı ile YAML instance oluştur.</div>
            </div>
          </div>
        </div>

        {notice ? <NoticeBanner notice={notice} onClear={() => setNotice(null)} /> : null}

        {loading ? (
          <div className="rounded-2xl border border-border bg-card px-6 py-12 text-center text-sm text-muted-foreground shadow-sm">
            YAML oluşturma verileri yükleniyor...
          </div>
        ) : (
          <div className="space-y-6">
            <div className="rounded-2xl border border-border bg-card p-6">
              <h2 className="text-lg text-foreground" style={{ fontFamily: 'var(--font-display)' }}>Metadata</h2>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div className="space-y-2 md:col-span-2">
                  <label className="text-sm font-medium text-foreground">YAML Name</label>
                  <input value={yamlName} onChange={(event) => setYamlName(event.target.value)} className={inputClass} />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <label className="text-sm font-medium text-foreground">YAML Description</label>
                  <textarea value={yamlDescription} onChange={(event) => setYamlDescription(event.target.value)} className={textareaClass} rows={3} />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Created By</label>
                  <input value={createdBy} onChange={(event) => setCreatedBy(event.target.value)} className={inputClass} />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Status</label>
                  <select value={status} onChange={(event) => setStatus(event.target.value as 'draft' | 'final' | 'archived')} className={selectClass}>
                    <option value="draft">draft</option>
                    <option value="final">final</option>
                    <option value="archived">archived</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-card p-6">
              <h2 className="text-lg text-foreground" style={{ fontFamily: 'var(--font-display)' }}>Template Seçimi</h2>
              <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Sınıf</label>
                  <select
                    value={selectedGradeId}
                    onChange={(event) => {
                      setSelectedGradeId(event.target.value)
                      setSelectedSubjectId('')
                      setSelectedUnitId('')
                      setSelectedTemplateId('')
                      setOpenedTemplateId('')
                    }}
                    className={selectClass}
                  >
                    <option value="">Seçiniz</option>
                    {gradeNodes.map((item) => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Ders</label>
                  <select
                    value={selectedSubjectId}
                    onChange={(event) => {
                      setSelectedSubjectId(event.target.value)
                      setSelectedUnitId('')
                      setSelectedTemplateId('')
                      setOpenedTemplateId('')
                    }}
                    className={selectClass}
                    disabled={!selectedGradeId}
                  >
                    <option value="">Seçiniz</option>
                    {subjectNodes.map((item) => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Ünite</label>
                  <select
                    value={selectedUnitId}
                    onChange={(event) => {
                      setSelectedUnitId(event.target.value)
                      setSelectedTemplateId('')
                      setOpenedTemplateId('')
                    }}
                    className={selectClass}
                    disabled={!selectedSubjectId}
                  >
                    <option value="">Seçiniz</option>
                    {unitNodes.map((item) => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">YAML Template</label>
                  <select
                    value={selectedTemplateId}
                    onChange={(event) => setSelectedTemplateId(event.target.value)}
                    className={selectClass}
                    disabled={templateOptions.length === 0}
                  >
                    <option value="">Seçiniz</option>
                    {templateOptions.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.title} · {template.template_code}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="mt-4 flex justify-end">
                <button
                  type="button"
                  onClick={handleOpenTemplate}
                  disabled={!selectedTemplateId}
                  className="rounded-xl px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                  style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
                >
                  Aç
                </button>
              </div>
            </div>

            {openedTemplate ? (
              <div className="rounded-2xl border border-border bg-card p-6">
                <div className="mb-4">
                  <h2 className="text-lg text-foreground" style={{ fontFamily: 'var(--font-display)' }}>Template Property'leri</h2>
                  <p className="text-sm text-muted-foreground">
                    {openedTemplate.title} · {openedTemplate.template_code} · {nodeById.get(openedTemplate.curriculum_folder_node_id)?.path ?? '-'}
                  </p>
                </div>
                <div className="space-y-3">
                  <DynamicValueEditor schema={openedSchema} value={values} onChange={(next) => setValues(isRecord(next) ? next : {})} />
                </div>
                <div className="mt-6 flex justify-end">
                  <button
                    type="button"
                    onClick={() => void handleCreateInstance()}
                    disabled={submitting}
                    className="rounded-xl px-5 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                    style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
                  >
                    {submitting ? 'Oluşturuluyor...' : 'Oluştur'}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </motion.div>
    </div>
  )
}
