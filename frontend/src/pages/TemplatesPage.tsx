import { useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { Plus, Save, Trash2 } from 'lucide-react'

const SUBJECTS = ['Türkçe', 'Matematik', 'Fen Bilgisi', 'Sosyal Bilgiler'] as const

type Subject = (typeof SUBJECTS)[number]
type FieldType = 'text' | 'integer' | 'bool'
type ScopeKind = 'global' | 'subject' | 'grade-subject' | 'theme' | 'subtopic'

const GRADES = Array.from({ length: 12 }, (_, index) => index + 1)

interface ThemeSeed {
  theme: string
  subtopics: [string, string]
}

interface ThemeItem {
  id: string
  title: string
  subtopics: [string, string]
}

interface TemplateField {
  id: string
  key: string
  type: FieldType
  description: string
  example: string
  children: TemplateField[]
}

interface TemplateScope {
  kind: ScopeKind
  subject?: Subject
  grade?: number
  themeIndex?: number
  subtopicIndex?: number
}

interface TemplateDefinition {
  id: string
  name: string
  parentId?: string
  scope: TemplateScope
  fields: TemplateField[]
}

interface TemplateDraft {
  name: string
  parentId: string
  scope: TemplateScope
  fields: TemplateField[]
  autoAttachSubtopicKey?: string
}

const SUBJECT_THEME_SEEDS: Record<Subject, ThemeSeed[]> = {
  'Türkçe': [
    { theme: 'Okuma ve Anlama Atölyesi', subtopics: ['Ana fikir ve yardımcı fikir', 'Metinden çıkarım yapma'] },
    { theme: 'Yazma Becerileri', subtopics: ['Planlı metin yazımı', 'Noktalama ve yazım kuralları'] },
    { theme: 'Sözcük Dünyası', subtopics: ['Eş anlamlı ve zıt anlamlı kelimeler', 'Söz varlığını geliştirme'] },
    { theme: 'Dinleme ve Konuşma', subtopics: ['Etkin dinleme stratejileri', 'Sunum ve konuşma pratiği'] },
    { theme: 'Metin Türleri', subtopics: ['Öyküleyici ve bilgilendirici metinler', 'Şiir okuma ve yorumlama'] },
    { theme: 'Medya Okuryazarlığı', subtopics: ['Görsel okuma becerileri', 'Dijital içerik değerlendirme'] },
  ],
  Matematik: [
    { theme: 'Sayı Duyusu', subtopics: ['Sayıları karşılaştırma ve sıralama', 'Basamak değeri ilişkileri'] },
    { theme: 'Dört İşlem ve Problemler', subtopics: ['İşlem önceliği ve stratejiler', 'Günlük yaşam problemleri'] },
    { theme: 'Geometri ve Şekiller', subtopics: ['Temel geometrik şekiller', 'Uzamsal düşünme etkinlikleri'] },
    { theme: 'Ölçme ve Veri', subtopics: ['Uzunluk, zaman ve kütle ölçme', 'Tablo ve grafik yorumlama'] },
    { theme: 'Mantık ve Akıl Yürütme', subtopics: ['Örüntü ve ilişkiler', 'Çok adımlı düşünme soruları'] },
    { theme: 'Finansal Okuryazarlık', subtopics: ['Para hesaplama ve bütçe', 'Tasarruf ve harcama planı'] },
  ],
  'Fen Bilgisi': [
    { theme: 'Canlılar ve Yaşam', subtopics: ['Canlıların temel ihtiyaçları', 'Yaşam döngüleri'] },
    { theme: 'Madde ve Değişim', subtopics: ['Maddenin halleri', 'Isı etkisiyle değişim'] },
    { theme: 'Kuvvet ve Hareket', subtopics: ['İtme ve çekme kuvvetleri', 'Hareket türleri'] },
    { theme: 'Işık, Ses ve Enerji', subtopics: ['Işık kaynakları ve gölge', 'Sesin yayılması'] },
    { theme: 'Dünya ve Evren', subtopics: ['Mevsimler ve iklim', 'Güneş sistemi keşfi'] },
    { theme: 'Bilimsel Süreç Becerileri', subtopics: ['Gözlem ve veri toplama', 'Hipotez kurma ve test etme'] },
  ],
  'Sosyal Bilgiler': [
    { theme: 'Birey ve Toplum', subtopics: ['Roller, sorumluluklar ve haklar', 'Toplumsal iletişim'] },
    { theme: 'Kültür ve Miras', subtopics: ['Yerel kültür ögeleri', 'Tarihsel mirası koruma'] },
    { theme: 'İnsanlar, Yerler ve Çevreler', subtopics: ['Harita okuma becerileri', 'Doğal ve beşeri çevre'] },
    { theme: 'Üretim, Dağıtım ve Tüketim', subtopics: ['Ekonomik faaliyetler', 'Bilinçli tüketim'] },
    { theme: 'Etkin Vatandaşlık', subtopics: ['Demokrasi ve katılım', 'Toplumsal dayanışma'] },
    { theme: 'Küresel Bağlantılar', subtopics: ['Farklı ülkeleri tanıma', 'Küresel iş birliği'] },
  ],
}

const INITIAL_TEMPLATES: TemplateDefinition[] = [
  {
    id: 'tpl-global',
    name: 'Genel Şablon Kuralları',
    scope: { kind: 'global' },
    fields: [
      {
        id: 'fld-global-security',
        key: 'güvenlik kuralları',
        type: 'text',
        description: 'Irkçı, cinsiyetçi veya siyasi içerik üretimini engeller.',
        example: 'Irkçı, cinsiyetçi, siyasi içerik üretme.',
        children: [],
      },
    ],
  },
  {
    id: 'tpl-math',
    name: 'Matematik Genel Kuralları',
    parentId: 'tpl-global',
    scope: { kind: 'subject', subject: 'Matematik' },
    fields: [
      {
        id: 'fld-math-question-root',
        key: 'soru kökü',
        type: 'text',
        description: 'Sorunun cevabı mutlaka sayısal bir değer olmalıdır.',
        example: 'Cevap 0-999 arasında tek bir sayıdır.',
        children: [],
      },
    ],
  },
  {
    id: 'tpl-math-grade-2',
    name: '2. Sınıf Matematik Kuralları',
    parentId: 'tpl-math',
    scope: { kind: 'grade-subject', subject: 'Matematik', grade: 2 },
    fields: [
      {
        id: 'fld-math-grade-2-visual',
        key: 'içerik',
        type: 'bool',
        description: 'Soruda en az bir görsel bulunmalıdır.',
        example: 'true',
        children: [],
      },
    ],
  },
]

function buildThemes(subject: Subject, grade: number): ThemeItem[] {
  return SUBJECT_THEME_SEEDS[subject].map((seed, index) => ({
    id: `${subject}-${grade}-${index + 1}`,
    title: `${seed.theme} (${grade}. Sınıf)`,
    subtopics: seed.subtopics,
  }))
}

function createId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function createEmptyField(): TemplateField {
  return {
    id: createId('fld'),
    key: '',
    type: 'text',
    description: '',
    example: '',
    children: [],
  }
}

function cloneFieldsWithNewIds(fields: TemplateField[]): TemplateField[] {
  return fields.map((field) => ({
    ...field,
    id: createId('fld'),
    children: cloneFieldsWithNewIds(field.children),
  }))
}

function normalizeKey(value: string): string {
  return value.trim().toLocaleLowerCase('tr-TR')
}

function mergeFieldArrays(base: TemplateField[], extension: TemplateField[]): TemplateField[] {
  const ordered: string[] = []
  const map = new Map<string, TemplateField>()

  for (const field of base) {
    const key = normalizeKey(field.key)
    if (!map.has(key)) ordered.push(key)
    map.set(key, {
      ...field,
      children: mergeFieldArrays(field.children, []),
    })
  }

  for (const field of extension) {
    const key = normalizeKey(field.key)
    const existing = map.get(key)
    if (!existing) {
      ordered.push(key)
      map.set(key, {
        ...field,
        children: mergeFieldArrays(field.children, []),
      })
      continue
    }

    map.set(key, {
      ...existing,
      ...field,
      key: field.key || existing.key,
      children: mergeFieldArrays(existing.children, field.children),
    })
  }

  return ordered
    .map((key) => map.get(key))
    .filter((field): field is TemplateField => Boolean(field))
}

function getTemplateChain(templates: TemplateDefinition[], templateId: string): TemplateDefinition[] {
  const byId = new Map(templates.map((template) => [template.id, template]))
  const chain: TemplateDefinition[] = []
  const visited = new Set<string>()

  let cursor = byId.get(templateId)
  while (cursor && !visited.has(cursor.id)) {
    visited.add(cursor.id)
    chain.unshift(cursor)
    cursor = cursor.parentId ? byId.get(cursor.parentId) : undefined
  }

  return chain
}

function getEffectiveFieldsFromChain(chain: TemplateDefinition[]): TemplateField[] {
  return chain.reduce<TemplateField[]>((acc, template) => mergeFieldArrays(acc, template.fields), [])
}

function getEffectiveFields(templates: TemplateDefinition[], templateId: string): TemplateField[] {
  return getEffectiveFieldsFromChain(getTemplateChain(templates, templateId))
}

function isApplicableToContext(
  template: TemplateDefinition,
  subject: Subject,
  grade: number,
  themeIndex: number,
  subtopicIndex: number,
): boolean {
  const scope = template.scope
  switch (scope.kind) {
    case 'global':
      return true
    case 'subject':
      return scope.subject === subject
    case 'grade-subject':
      return scope.subject === subject && scope.grade === grade
    case 'theme':
      return scope.subject === subject && scope.grade === grade && scope.themeIndex === themeIndex
    case 'subtopic':
      return (
        scope.subject === subject &&
        scope.grade === grade &&
        scope.themeIndex === themeIndex &&
        scope.subtopicIndex === subtopicIndex
      )
    default:
      return false
  }
}

function subtopicKey(subject: Subject, grade: number, themeIndex: number, subtopicIndex: number): string {
  return `${subject}::${grade}::${themeIndex}::${subtopicIndex}`
}

function getScopeLabel(scope: TemplateScope): string {
  switch (scope.kind) {
    case 'global':
      return 'Genel'
    case 'subject':
      return `${scope.subject ?? '-'} dersi`
    case 'grade-subject':
      return `${scope.grade ?? '-'}. sınıf ${scope.subject ?? '-'}`
    case 'theme':
      return `${scope.grade ?? '-'}. sınıf ${scope.subject ?? '-'} / Tema ${(scope.themeIndex ?? 0) + 1}`
    case 'subtopic':
      return `${scope.grade ?? '-'}. sınıf ${scope.subject ?? '-'} / Tema ${(scope.themeIndex ?? 0) + 1} / Alt ${(scope.subtopicIndex ?? 0) + 1}`
    default:
      return '-'
  }
}

function findLatestTemplate(
  templates: TemplateDefinition[],
  matcher: (template: TemplateDefinition) => boolean,
): TemplateDefinition | undefined {
  const reversed = [...templates].reverse()
  return reversed.find(matcher)
}

function suggestParentId(templates: TemplateDefinition[], scope: TemplateScope): string {
  if (scope.kind === 'global') return ''

  const globalTemplate = findLatestTemplate(templates, (template) => template.scope.kind === 'global')

  if (scope.kind === 'subject') {
    return globalTemplate?.id ?? ''
  }

  if (!scope.subject) return globalTemplate?.id ?? ''

  const subjectTemplate = findLatestTemplate(
    templates,
    (template) => template.scope.kind === 'subject' && template.scope.subject === scope.subject,
  )

  if (scope.kind === 'grade-subject') {
    return subjectTemplate?.id ?? globalTemplate?.id ?? ''
  }

  if (!scope.grade) return subjectTemplate?.id ?? globalTemplate?.id ?? ''

  const gradeTemplate = findLatestTemplate(
    templates,
    (template) =>
      template.scope.kind === 'grade-subject' &&
      template.scope.subject === scope.subject &&
      template.scope.grade === scope.grade,
  )

  if (scope.kind === 'theme') {
    return gradeTemplate?.id ?? subjectTemplate?.id ?? globalTemplate?.id ?? ''
  }

  if (typeof scope.themeIndex !== 'number') {
    return gradeTemplate?.id ?? subjectTemplate?.id ?? globalTemplate?.id ?? ''
  }

  const themeTemplate = findLatestTemplate(
    templates,
    (template) =>
      template.scope.kind === 'theme' &&
      template.scope.subject === scope.subject &&
      template.scope.grade === scope.grade &&
      template.scope.themeIndex === scope.themeIndex,
  )

  return themeTemplate?.id ?? gradeTemplate?.id ?? subjectTemplate?.id ?? globalTemplate?.id ?? ''
}

function sanitizeFields(fields: TemplateField[]): TemplateField[] {
  return fields
    .map((field) => ({
      ...field,
      key: field.key.trim(),
      description: field.description.trim(),
      example: field.example.trim(),
      children: sanitizeFields(field.children),
    }))
    .filter((field) => field.key.length > 0 && field.description.length > 0)
}

function mapFieldTree(
  fields: TemplateField[],
  targetId: string,
  updater: (field: TemplateField) => TemplateField,
): TemplateField[] {
  return fields.map((field) => {
    if (field.id === targetId) return updater(field)
    if (field.children.length === 0) return field
    return {
      ...field,
      children: mapFieldTree(field.children, targetId, updater),
    }
  })
}

function removeFieldFromTree(fields: TemplateField[], targetId: string): TemplateField[] {
  return fields
    .filter((field) => field.id !== targetId)
    .map((field) => ({
      ...field,
      children: removeFieldFromTree(field.children, targetId),
    }))
}

interface EditableFieldListProps {
  fields: TemplateField[]
  onChange: (fields: TemplateField[]) => void
  level?: number
}

function EditableFieldList({ fields, onChange, level = 0 }: EditableFieldListProps) {
  return (
    <div className="space-y-3">
      {fields.map((field) => (
        <div key={field.id} className="rounded-xl border border-border bg-background p-3" style={{ marginLeft: level * 12 }}>
          <div className="grid gap-2 md:grid-cols-2">
            <input
              value={field.key}
              onChange={(event) =>
                onChange(mapFieldTree(fields, field.id, (target) => ({ ...target, key: event.target.value })))
              }
              placeholder="Alan adı (örn: güvenlik kuralları)"
              className="rounded-lg border border-border bg-card px-3 py-2 text-sm"
            />
            <select
              value={field.type}
              onChange={(event) =>
                onChange(
                  mapFieldTree(fields, field.id, (target) => ({
                    ...target,
                    type: event.target.value as FieldType,
                  })),
                )
              }
              className="rounded-lg border border-border bg-card px-3 py-2 text-sm"
            >
              <option value="text">text</option>
              <option value="integer">integer</option>
              <option value="bool">bool</option>
            </select>
          </div>

          <textarea
            value={field.description}
            onChange={(event) =>
              onChange(mapFieldTree(fields, field.id, (target) => ({ ...target, description: event.target.value })))
            }
            placeholder="Açıklama (description)"
            rows={2}
            className="mt-2 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm"
          />

          <input
            value={field.example}
            onChange={(event) =>
              onChange(mapFieldTree(fields, field.id, (target) => ({ ...target, example: event.target.value })))
            }
            placeholder="Örnek değer (opsiyonel)"
            className="mt-2 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm"
          />

          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() =>
                onChange(
                  mapFieldTree(fields, field.id, (target) => ({
                    ...target,
                    children: [...target.children, createEmptyField()],
                  })),
                )
              }
              className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-accent"
            >
              <Plus className="h-3.5 w-3.5" />
              Child Alan
            </button>
            <button
              type="button"
              onClick={() => onChange(removeFieldFromTree(fields, field.id))}
              className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs text-destructive hover:bg-red-50"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Alanı Sil
            </button>
          </div>

          {field.children.length > 0 && (
            <div className="mt-3 border-l-2 border-accent pl-3">
              <EditableFieldList
                fields={field.children}
                onChange={(nextChildren) =>
                  onChange(mapFieldTree(fields, field.id, (target) => ({ ...target, children: nextChildren })))
                }
                level={level + 1}
              />
            </div>
          )}
        </div>
      ))}

      <button
        type="button"
        onClick={() => onChange([...fields, createEmptyField()])}
        className="inline-flex items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-sm hover:bg-accent"
      >
        <Plus className="h-4 w-4" />
        Alan Ekle
      </button>
    </div>
  )
}

function ReadonlyFieldList({ fields }: { fields: TemplateField[] }) {
  if (fields.length === 0) {
    return <p className="text-sm text-muted-foreground">Alan yok.</p>
  }

  return (
    <div className="space-y-2">
      {fields.map((field) => (
        <div key={field.id} className="rounded-lg border border-border bg-background p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-foreground">{field.key}</span>
            <span className="rounded-md bg-accent px-2 py-0.5 text-xs text-muted-foreground">{field.type}</span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{field.description}</p>
          {field.example && <p className="mt-1 text-xs text-muted-foreground">Örnek: {field.example}</p>}
          {field.children.length > 0 && (
            <div className="mt-2 border-l-2 border-accent pl-3">
              <ReadonlyFieldList fields={field.children} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export function TemplatesPage() {
  const [selectedSubject, setSelectedSubject] = useState<Subject>('Türkçe')
  const [selectedGrade, setSelectedGrade] = useState(1)
  const [selectedThemeIndex, setSelectedThemeIndex] = useState(0)

  const [templates, setTemplates] = useState<TemplateDefinition[]>(INITIAL_TEMPLATES)
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('tpl-global')
  const [subtopicAssignments, setSubtopicAssignments] = useState<Record<string, string[]>>({})
  const [subtopicPicker, setSubtopicPicker] = useState<Record<string, string>>({})

  const [draft, setDraft] = useState<TemplateDraft | null>(null)
  const [draftError, setDraftError] = useState('')

  const themes = useMemo(() => buildThemes(selectedSubject, selectedGrade), [selectedSubject, selectedGrade])

  const safeThemeIndex = Math.min(selectedThemeIndex, themes.length - 1)
  const activeTheme = themes[safeThemeIndex]

  const templatesById = useMemo(
    () => new Map(templates.map((template) => [template.id, template])),
    [templates],
  )

  const relevantTemplates = useMemo(
    () =>
      templates.filter((template) =>
        isApplicableToContext(template, selectedSubject, selectedGrade, safeThemeIndex, 0),
      ),
    [templates, selectedSubject, selectedGrade, safeThemeIndex],
  )

  const selectedTemplate = templatesById.get(selectedTemplateId)
  const inheritanceChain = selectedTemplate ? getTemplateChain(templates, selectedTemplate.id) : []
  const effectiveFields = selectedTemplate ? getEffectiveFieldsFromChain(inheritanceChain) : []

  const resetDraftForScope = (scope: TemplateScope) => {
    const parentId = suggestParentId(templates, scope)
    setDraft({
      name: '',
      parentId,
      scope,
      fields: [],
    })
    setDraftError('')
  }

  const startChildDraft = (parentId: string) => {
    const parent = templatesById.get(parentId)
    if (!parent) return

    setDraft({
      name: `${parent.name} - Child`,
      parentId,
      scope: { ...parent.scope },
      fields: cloneFieldsWithNewIds(getEffectiveFields(templates, parentId)),
    })
    setDraftError('')
  }

  const startSubtopicDraft = (subtopicIndex: number) => {
    const subtopic = activeTheme.subtopics[subtopicIndex]
    const scope: TemplateScope = {
      kind: 'subtopic',
      subject: selectedSubject,
      grade: selectedGrade,
      themeIndex: safeThemeIndex,
      subtopicIndex,
    }
    const parentId = suggestParentId(templates, scope)

    setDraft({
      name: `${selectedSubject} ${selectedGrade}. Sınıf - ${activeTheme.title} / ${subtopic}`,
      parentId,
      scope,
      fields: parentId ? cloneFieldsWithNewIds(getEffectiveFields(templates, parentId)) : [],
      autoAttachSubtopicKey: subtopicKey(selectedSubject, selectedGrade, safeThemeIndex, subtopicIndex),
    })
    setDraftError('')
  }

  const attachTemplateToSubtopic = (key: string, templateId: string) => {
    if (!templateId) return

    setSubtopicAssignments((prev) => {
      const current = prev[key] ?? []
      if (current.includes(templateId)) return prev
      return {
        ...prev,
        [key]: [...current, templateId],
      }
    })
  }

  const removeTemplateFromSubtopic = (key: string, templateId: string) => {
    setSubtopicAssignments((prev) => ({
      ...prev,
      [key]: (prev[key] ?? []).filter((id) => id !== templateId),
    }))
  }

  const applyParentAutofill = () => {
    if (!draft?.parentId) return
    const inherited = cloneFieldsWithNewIds(getEffectiveFields(templates, draft.parentId))
    setDraft((prev) => (prev ? { ...prev, fields: inherited } : prev))
  }

  const saveDraft = () => {
    if (!draft) return

    const nextName = draft.name.trim()
    if (!nextName) {
      setDraftError('Şablon adı zorunlu.')
      return
    }

    const cleanedFields = sanitizeFields(draft.fields)
    if (cleanedFields.length === 0) {
      setDraftError('En az bir alan girmelisin (alan adı + açıklama).')
      return
    }

    const template: TemplateDefinition = {
      id: createId('tpl'),
      name: nextName,
      parentId: draft.parentId || undefined,
      scope: draft.scope,
      fields: cleanedFields,
    }

    setTemplates((prev) => [...prev, template])
    setSelectedTemplateId(template.id)

    if (draft.autoAttachSubtopicKey) {
      attachTemplateToSubtopic(draft.autoAttachSubtopicKey, template.id)
    }

    setDraft(null)
    setDraftError('')
  }

  const updateDraftScope = (nextScope: TemplateScope) => {
    setDraft((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        scope: nextScope,
        parentId: suggestParentId(templates, nextScope),
      }
    })
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <div className="rounded-2xl border border-border bg-card p-6 shadow-lg">
          <h1 className="text-3xl" style={{ fontFamily: 'var(--font-display)' }}>
            Şablonlar
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Şablonlar kalıtım (inheritance) ile kümülatif çalışır: Genel → Ders → Sınıf+Ders → Tema/Alt Başlık.
          </p>

          <div className="mt-6">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Dersler</p>
            <div className="flex flex-wrap gap-2">
              {SUBJECTS.map((subject) => {
                const active = subject === selectedSubject
                return (
                  <button
                    key={subject}
                    type="button"
                    onClick={() => {
                      setSelectedSubject(subject)
                      setSelectedThemeIndex(0)
                    }}
                    className={`rounded-xl border px-4 py-2 text-sm transition-all ${
                      active ? 'border-secondary bg-secondary text-secondary-foreground' : 'bg-background hover:bg-accent'
                    }`}
                  >
                    {subject}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="mt-5">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sınıflar</p>
            <div className="flex flex-wrap gap-2">
              {GRADES.map((grade) => {
                const active = grade === selectedGrade
                return (
                  <button
                    key={grade}
                    type="button"
                    onClick={() => {
                      setSelectedGrade(grade)
                      setSelectedThemeIndex(0)
                    }}
                    className={`min-w-11 rounded-xl border px-3 py-2 text-sm transition-all ${
                      active ? 'border-primary bg-primary text-primary-foreground' : 'bg-background hover:bg-accent'
                    }`}
                  >
                    {grade}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="mt-5">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Temalar</p>
            <div className="flex flex-wrap gap-2">
              {themes.map((theme, index) => {
                const active = index === safeThemeIndex
                return (
                  <button
                    key={theme.id}
                    type="button"
                    onClick={() => setSelectedThemeIndex(index)}
                    className={`rounded-xl border px-3 py-2 text-sm transition-all ${
                      active ? 'border-border bg-accent text-foreground' : 'bg-background hover:bg-accent'
                    }`}
                  >
                    {index + 1}. {theme.title}
                  </button>
                )}
              )}
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-12">
          <section className="space-y-4 xl:col-span-7">
            <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <h2 className="text-xl" style={{ fontFamily: 'var(--font-display)' }}>
                Alt Başlık Şablon Atamaları
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Her alt başlıkta birden fazla şablon kullanabilirsin. Yeni şablon açarken parent kuralları otomatik doldurulur.
              </p>

              <div className="mt-4 space-y-4">
                {activeTheme.subtopics.map((subtopic, subtopicIndex) => {
                  const key = subtopicKey(selectedSubject, selectedGrade, safeThemeIndex, subtopicIndex)
                  const assignedIds = subtopicAssignments[key] ?? []
                  const assignedTemplates = assignedIds
                    .map((id) => templatesById.get(id))
                    .filter((template): template is TemplateDefinition => Boolean(template))

                  const applicableTemplates = templates.filter((template) =>
                    isApplicableToContext(template, selectedSubject, selectedGrade, safeThemeIndex, subtopicIndex),
                  )

                  const pickerValue = subtopicPicker[key] ?? applicableTemplates[0]?.id ?? ''

                  return (
                    <article key={key} className="rounded-xl border border-border bg-background p-4">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Alt Başlık {subtopicIndex + 1}</p>
                      <h3 className="mt-1 text-base text-foreground">{subtopic}</h3>

                      <div className="mt-3 flex flex-wrap gap-2">
                        {assignedTemplates.length === 0 && (
                          <span className="rounded-lg bg-muted px-2 py-1 text-xs text-muted-foreground">
                            Atanmış şablon yok
                          </span>
                        )}
                        {assignedTemplates.map((template) => (
                          <span
                            key={`${key}:${template.id}`}
                            className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1 text-xs"
                          >
                            {template.name}
                            <button
                              type="button"
                              onClick={() => removeTemplateFromSubtopic(key, template.id)}
                              className="rounded px-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                              title="Atamayı kaldır"
                            >
                              x
                            </button>
                          </span>
                        ))}
                      </div>

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <select
                          value={pickerValue}
                          onChange={(event) =>
                            setSubtopicPicker((prev) => ({
                              ...prev,
                              [key]: event.target.value,
                            }))
                          }
                          className="min-w-64 rounded-lg border border-border bg-card px-3 py-2 text-sm"
                        >
                          {applicableTemplates.length === 0 && (
                            <option value="">Uygun şablon yok</option>
                          )}
                          {applicableTemplates.map((template) => (
                            <option key={template.id} value={template.id}>
                              {template.name} ({getScopeLabel(template.scope)})
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={() => attachTemplateToSubtopic(key, pickerValue)}
                          className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-accent"
                        >
                          Şablon Ekle
                        </button>
                        <button
                          type="button"
                          onClick={() => startSubtopicDraft(subtopicIndex)}
                          className="inline-flex items-center gap-1 rounded-lg border border-primary bg-primary px-3 py-2 text-sm text-primary-foreground"
                        >
                          <Plus className="h-4 w-4" />
                          Auto-fill ile Yeni Şablon
                        </button>
                      </div>
                    </article>
                  )
                })}
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-xl" style={{ fontFamily: 'var(--font-display)' }}>
                  Şablon Havuzu
                </h2>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      resetDraftForScope({
                        kind: 'global',
                      })
                    }
                    className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-accent"
                  >
                    Yeni Boş Şablon
                  </button>
                  {selectedTemplate && (
                    <button
                      type="button"
                      onClick={() => startChildDraft(selectedTemplate.id)}
                      className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-accent"
                    >
                      Seçilenden Child Oluştur
                    </button>
                  )}
                </div>
              </div>

              <div className="mt-4 grid gap-2 md:grid-cols-2">
                {templates.map((template) => {
                  const active = template.id === selectedTemplateId
                  return (
                    <button
                      key={template.id}
                      type="button"
                      onClick={() => setSelectedTemplateId(template.id)}
                      className={`rounded-xl border p-3 text-left transition-all ${
                        active ? 'border-primary bg-accent' : 'border-border bg-background hover:bg-accent'
                      }`}
                    >
                      <p className="text-sm font-medium text-foreground">{template.name}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{getScopeLabel(template.scope)}</p>
                    </button>
                  )
                })}
              </div>

              {selectedTemplate && (
                <div className="mt-4 rounded-xl border border-border bg-background p-4">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Inheritance Chain</p>
                  <p className="mt-1 text-sm text-foreground">
                    {inheritanceChain.map((template) => template.name).join(' -> ')}
                  </p>
                  <p className="mt-3 text-xs uppercase tracking-wide text-muted-foreground">Kümülatif Alanlar</p>
                  <div className="mt-2">
                    <ReadonlyFieldList fields={effectiveFields} />
                  </div>
                </div>
              )}
            </div>
          </section>

          <aside className="space-y-4 xl:col-span-5">
            <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <h2 className="text-xl" style={{ fontFamily: 'var(--font-display)' }}>
                Şablon Stüdyosu
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Alan adı, tip, description ve opsiyonel örnek değer gir. İstersen alanlara child ekle.
              </p>

              {!draft && (
                <div className="mt-4 rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                  Sağ üstten yeni şablon başlatabilir veya alt başlık kartından auto-fill ile form açabilirsin.
                </div>
              )}

              {draft && (
                <div className="mt-4 space-y-3">
                  <input
                    value={draft.name}
                    onChange={(event) => setDraft((prev) => (prev ? { ...prev, name: event.target.value } : prev))}
                    placeholder="Şablon adı"
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
                  />

                  <div className="grid gap-2 md:grid-cols-2">
                    <select
                      value={draft.scope.kind}
                      onChange={(event) => {
                        const nextKind = event.target.value as ScopeKind
                        updateDraftScope({
                          kind: nextKind,
                          subject: draft.scope.subject ?? selectedSubject,
                          grade: draft.scope.grade ?? selectedGrade,
                          themeIndex: draft.scope.themeIndex ?? safeThemeIndex,
                          subtopicIndex: draft.scope.subtopicIndex ?? 0,
                        })
                      }}
                      className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
                    >
                      <option value="global">global</option>
                      <option value="subject">subject</option>
                      <option value="grade-subject">grade-subject</option>
                      <option value="theme">theme</option>
                      <option value="subtopic">subtopic</option>
                    </select>

                    <select
                      value={draft.parentId}
                      onChange={(event) =>
                        setDraft((prev) => (prev ? { ...prev, parentId: event.target.value } : prev))
                      }
                      className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
                    >
                      <option value="">Parent yok</option>
                      {templates.map((template) => (
                        <option key={template.id} value={template.id}>
                          {template.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  {draft.scope.kind !== 'global' && (
                    <div className="grid gap-2 md:grid-cols-2">
                      <select
                        value={draft.scope.subject ?? selectedSubject}
                        onChange={(event) =>
                          updateDraftScope({
                            ...draft.scope,
                            subject: event.target.value as Subject,
                          })
                        }
                        className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
                      >
                        {SUBJECTS.map((subject) => (
                          <option key={subject} value={subject}>
                            {subject}
                          </option>
                        ))}
                      </select>

                      {(draft.scope.kind === 'grade-subject' ||
                        draft.scope.kind === 'theme' ||
                        draft.scope.kind === 'subtopic') && (
                        <select
                          value={draft.scope.grade ?? selectedGrade}
                          onChange={(event) =>
                            updateDraftScope({
                              ...draft.scope,
                              grade: Number(event.target.value),
                            })
                          }
                          className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
                        >
                          {GRADES.map((grade) => (
                            <option key={grade} value={grade}>
                              {grade}. sınıf
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  )}

                  {(draft.scope.kind === 'theme' || draft.scope.kind === 'subtopic') && (
                    <select
                      value={draft.scope.themeIndex ?? safeThemeIndex}
                      onChange={(event) =>
                        updateDraftScope({
                          ...draft.scope,
                          themeIndex: Number(event.target.value),
                        })
                      }
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
                    >
                      {buildThemes(draft.scope.subject ?? selectedSubject, draft.scope.grade ?? selectedGrade).map(
                        (theme, index) => (
                          <option key={theme.id} value={index}>
                            Tema {index + 1}: {theme.title}
                          </option>
                        ),
                      )}
                    </select>
                  )}

                  {draft.scope.kind === 'subtopic' && (
                    <select
                      value={draft.scope.subtopicIndex ?? 0}
                      onChange={(event) =>
                        updateDraftScope({
                          ...draft.scope,
                          subtopicIndex: Number(event.target.value),
                        })
                      }
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
                    >
                      {buildThemes(draft.scope.subject ?? selectedSubject, draft.scope.grade ?? selectedGrade)[
                        draft.scope.themeIndex ?? 0
                      ]?.subtopics.map((subtopic, index) => (
                        <option key={subtopic} value={index}>
                          Alt Başlık {index + 1}: {subtopic}
                        </option>
                      ))}
                    </select>
                  )}

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setDraft((prev) =>
                          prev
                            ? {
                                ...prev,
                                parentId: suggestParentId(templates, prev.scope),
                              }
                            : prev,
                        )
                      }
                      className="rounded-lg border border-border px-3 py-2 text-xs hover:bg-accent"
                    >
                      Parent Öner
                    </button>
                    <button
                      type="button"
                      onClick={applyParentAutofill}
                      disabled={!draft.parentId}
                      className="rounded-lg border border-border px-3 py-2 text-xs hover:bg-accent disabled:opacity-40"
                    >
                      Parent Alanları ile Auto-fill
                    </button>
                  </div>

                  <div className="rounded-xl border border-border bg-background p-3">
                    <EditableFieldList
                      fields={draft.fields}
                      onChange={(nextFields) => setDraft((prev) => (prev ? { ...prev, fields: nextFields } : prev))}
                    />
                  </div>

                  {draftError && <p className="text-sm text-destructive">{draftError}</p>}

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={saveDraft}
                      className="inline-flex items-center gap-2 rounded-lg border border-primary bg-primary px-3 py-2 text-sm text-primary-foreground"
                    >
                      <Save className="h-4 w-4" />
                      Şablonu Kaydet
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setDraft(null)
                        setDraftError('')
                      }}
                      className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-accent"
                    >
                      Vazgeç
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <h3 className="text-base" style={{ fontFamily: 'var(--font-display)' }}>
                Bu Kontekste Uygulanabilir Şablonlar
              </h3>
              <p className="mt-1 text-xs text-muted-foreground">
                {selectedSubject} / {selectedGrade}. sınıf / Tema {safeThemeIndex + 1}
              </p>
              <div className="mt-3 space-y-2">
                {relevantTemplates.map((template) => (
                  <div key={template.id} className="rounded-lg border border-border bg-background p-2.5">
                    <p className="text-sm text-foreground">{template.name}</p>
                    <p className="text-xs text-muted-foreground">{getScopeLabel(template.scope)}</p>
                  </div>
                ))}
                {relevantTemplates.length === 0 && (
                  <p className="text-sm text-muted-foreground">Uygun şablon bulunamadı.</p>
                )}
              </div>
            </div>
          </aside>
        </div>
      </motion.div>
    </div>
  )
}
