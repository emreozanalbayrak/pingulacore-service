import { useEffect, useMemo, useState } from 'react'

import type { CurriculumNodeItem, YamlInstanceItem, YamlTemplateItem } from '../types'

function flattenCurriculumNodes(nodes: CurriculumNodeItem[], acc: CurriculumNodeItem[] = []): CurriculumNodeItem[] {
  for (const node of nodes) {
    acc.push(node)
    flattenCurriculumNodes(node.children, acc)
  }
  return acc
}

function normalizeText(value: string): string {
  return value.trim().toLowerCase()
}

interface YamlInstanceCascadeSelectorProps {
  curriculumTree: CurriculumNodeItem[]
  templates: YamlTemplateItem[]
  instances: YamlInstanceItem[]
  value: string
  onChange: (instanceId: string) => void
  label?: string
  selectClassName: string
  inputClassName: string
}

export function YamlInstanceCascadeSelector({
  curriculumTree,
  templates,
  instances,
  value,
  onChange,
  label = 'YAML Instance',
  selectClassName,
  inputClassName,
}: YamlInstanceCascadeSelectorProps) {
  const flatNodes = useMemo(() => flattenCurriculumNodes(curriculumTree), [curriculumTree])
  const nodeById = useMemo(() => new Map(flatNodes.map((node) => [node.id, node])), [flatNodes])
  const folderChildrenByParent = useMemo(() => {
    const mapping = new Map<string, CurriculumNodeItem[]>()
    for (const node of flatNodes) {
      if (node.scope !== 'folder' || !node.parent_id) continue
      const rows = mapping.get(node.parent_id) ?? []
      rows.push(node)
      mapping.set(node.parent_id, rows)
    }
    for (const rows of mapping.values()) {
      rows.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name))
    }
    return mapping
  }, [flatNodes])

  const gradeNodes = useMemo(
    () => flatNodes.filter((node) => node.scope === 'constant' && node.node_type === 'grade'),
    [flatNodes],
  )
  const [selectedGradeId, setSelectedGradeId] = useState('')
  const subjectNodes = useMemo(
    () => flatNodes.filter((node) => node.scope === 'constant' && node.node_type === 'subject' && node.parent_id === selectedGradeId),
    [flatNodes, selectedGradeId],
  )
  const [selectedSubjectId, setSelectedSubjectId] = useState('')
  const unitNodes = useMemo(
    () => flatNodes.filter((node) => node.scope === 'constant' && node.node_type === 'theme' && node.parent_id === selectedSubjectId),
    [flatNodes, selectedSubjectId],
  )
  const [selectedUnitId, setSelectedUnitId] = useState('')
  const [selectedFolderPath, setSelectedFolderPath] = useState<string[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [search, setSearch] = useState('')

  const isDescendantOf = (nodeId: string, ancestorId: string): boolean => {
    let cursor: CurriculumNodeItem | undefined = nodeById.get(nodeId)
    let guard = 0
    while (cursor && guard < 64) {
      if (cursor.id === ancestorId) return true
      cursor = cursor.parent_id ? nodeById.get(cursor.parent_id) : undefined
      guard += 1
    }
    return false
  }

  const folderLevels = useMemo(() => {
    if (!selectedUnitId) return [] as Array<{ parentId: string; options: CurriculumNodeItem[]; selectedId: string }>
    const levels: Array<{ parentId: string; options: CurriculumNodeItem[]; selectedId: string }> = []
    let parentId = selectedUnitId
    let idx = 0
    while (idx < 16) {
      const options = folderChildrenByParent.get(parentId) ?? []
      if (options.length === 0) break
      const selectedId = selectedFolderPath[idx] ?? ''
      levels.push({ parentId, options, selectedId })
      if (!selectedId || !options.some((item) => item.id === selectedId)) break
      parentId = selectedId
      idx += 1
    }
    return levels
  }, [folderChildrenByParent, selectedFolderPath, selectedUnitId])

  const deepestSelectedFolderId = useMemo(() => {
    const validSelections = folderLevels
      .filter((level) => level.selectedId && level.options.some((item) => item.id === level.selectedId))
      .map((level) => level.selectedId)
    return validSelections.length > 0 ? validSelections[validSelections.length - 1] : ''
  }, [folderLevels])

  const filteredTemplates = useMemo(() => {
    return templates.filter((template) => {
      const folder = nodeById.get(template.curriculum_folder_node_id)
      if (!folder || folder.scope !== 'folder') return false
      if (selectedGradeId && !isDescendantOf(folder.id, selectedGradeId)) return false
      if (selectedSubjectId && !isDescendantOf(folder.id, selectedSubjectId)) return false
      if (selectedUnitId && !isDescendantOf(folder.id, selectedUnitId)) return false
      if (deepestSelectedFolderId && !isDescendantOf(folder.id, deepestSelectedFolderId)) return false
      return true
    })
  }, [deepestSelectedFolderId, selectedGradeId, selectedSubjectId, selectedUnitId, templates, nodeById])

  const selectedTemplate = useMemo(
    () => filteredTemplates.find((template) => template.id === selectedTemplateId) ?? null,
    [filteredTemplates, selectedTemplateId],
  )

  const globalSearchedInstances = useMemo(() => {
    const term = normalizeText(search)
    if (!term) return instances
    return instances.filter((item) =>
      [item.instance_name, item.id, item.status, item.created_by ?? '']
        .some((token) => normalizeText(token).includes(term)),
    )
  }, [instances, search])

  const baseInstances = useMemo(
    () => instances.filter((item) => item.template_id === selectedTemplateId),
    [instances, selectedTemplateId],
  )

  const filteredInstances = useMemo(
    () => (search.trim() ? globalSearchedInstances : baseInstances),
    [baseInstances, globalSearchedInstances, search],
  )

  const selectedInstance = useMemo(
    () => instances.find((item) => item.id === value) ?? null,
    [instances, value],
  )

  useEffect(() => {
    if (!selectedTemplateId || filteredTemplates.some((item) => item.id === selectedTemplateId)) return
    setSelectedTemplateId(filteredTemplates[0]?.id ?? '')
  }, [filteredTemplates, selectedTemplateId])

  useEffect(() => {
    if (search.trim()) return
    if (!selectedTemplateId) return
    if (value && baseInstances.some((item) => item.id === value)) return
    const nextId = filteredInstances[0]?.id ?? ''
    if (nextId !== value) onChange(nextId)
  }, [baseInstances, filteredInstances, onChange, search, selectedTemplateId, value])

  useEffect(() => {
    if (!value) return
    const selected = instances.find((item) => item.id === value)
    if (!selected) return
    const template = templates.find((item) => item.id === selected.template_id)
    if (!template) return
    const folder = nodeById.get(template.curriculum_folder_node_id)
    if (!folder) return

    let gradeId = ''
    let subjectId = ''
    let unitId = ''
    const folderChain: string[] = []

    let cursor: CurriculumNodeItem | undefined = folder
    let guard = 0
    while (cursor && guard < 64) {
      if (cursor.scope === 'folder') folderChain.unshift(cursor.id)
      if (cursor.scope === 'constant' && cursor.node_type === 'theme') unitId = cursor.id
      if (cursor.scope === 'constant' && cursor.node_type === 'subject') subjectId = cursor.id
      if (cursor.scope === 'constant' && cursor.node_type === 'grade') gradeId = cursor.id
      cursor = cursor.parent_id ? nodeById.get(cursor.parent_id) : undefined
      guard += 1
    }

    setSelectedGradeId(gradeId)
    setSelectedSubjectId(subjectId)
    setSelectedUnitId(unitId)
    setSelectedFolderPath(folderChain)
    setSelectedTemplateId(template.id)
  }, [instances, nodeById, templates, value])

  const onGradeChange = (nextId: string) => {
    setSelectedGradeId(nextId)
    setSelectedSubjectId('')
    setSelectedUnitId('')
    setSelectedFolderPath([])
    setSelectedTemplateId('')
    onChange('')
  }

  const onSubjectChange = (nextId: string) => {
    setSelectedSubjectId(nextId)
    setSelectedUnitId('')
    setSelectedFolderPath([])
    setSelectedTemplateId('')
    onChange('')
  }

  const onUnitChange = (nextId: string) => {
    setSelectedUnitId(nextId)
    setSelectedFolderPath([])
    setSelectedTemplateId('')
    onChange('')
  }

  const onFolderLevelChange = (levelIndex: number, nextId: string) => {
    setSelectedFolderPath((prev) => {
      const next = prev.slice(0, levelIndex)
      next[levelIndex] = nextId
      return next
    })
    setSelectedTemplateId('')
    onChange('')
  }

  const onTemplateChange = (nextTemplateId: string) => {
    setSelectedTemplateId(nextTemplateId)
    const nextInstance = instances.find((item) => item.template_id === nextTemplateId)
    onChange(nextInstance?.id ?? '')
  }

  return (
    <div className="space-y-3">
      <label className="text-sm font-medium text-foreground">{label}</label>

      <input
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Tüm instance'larda ara (ad, id, durum...)"
        className={inputClassName}
      />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <select value={selectedGradeId} onChange={(event) => onGradeChange(event.target.value)} className={selectClassName}>
          <option value="">Sınıf seç</option>
          {gradeNodes.map((node) => (
            <option key={node.id} value={node.id}>{node.name}</option>
          ))}
        </select>

        <select value={selectedSubjectId} onChange={(event) => onSubjectChange(event.target.value)} className={selectClassName} disabled={!selectedGradeId}>
          <option value="">Ders seç</option>
          {subjectNodes.map((node) => (
            <option key={node.id} value={node.id}>{node.name}</option>
          ))}
        </select>

        <select value={selectedUnitId} onChange={(event) => onUnitChange(event.target.value)} className={selectClassName} disabled={!selectedSubjectId}>
          <option value="">Ünite seç</option>
          {unitNodes.map((node) => (
            <option key={node.id} value={node.id}>{node.name}</option>
          ))}
        </select>
      </div>

      {folderLevels.map((level, index) => (
        <div key={`${level.parentId}-${index}`} className="grid gap-3 md:grid-cols-2">
          <select
            value={level.selectedId}
            onChange={(event) => onFolderLevelChange(index, event.target.value)}
            className={selectClassName}
            disabled={!selectedUnitId}
          >
            <option value="">{index === 0 ? 'Konu / klasör seç' : `Alt klasör ${index + 1} seç`}</option>
            {level.options.map((node) => (
              <option key={node.id} value={node.id}>{node.name}</option>
            ))}
          </select>
        </div>
      ))}

      <div className="grid gap-3 md:grid-cols-2">
        <select
          value={selectedTemplateId}
          onChange={(event) => onTemplateChange(event.target.value)}
          className={selectClassName}
          disabled={filteredTemplates.length === 0}
        >
          <option value="">Template seç</option>
          {filteredTemplates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.title} · {template.template_code}
            </option>
          ))}
        </select>
      </div>

      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={selectClassName}
        disabled={filteredInstances.length === 0}
      >
        {filteredInstances.length === 0 ? (
          <option value="">Instance bulunamadı</option>
        ) : (
          filteredInstances.map((item) => (
            <option key={item.id} value={item.id}>{item.instance_name}</option>
          ))
        )}
      </select>

      {selectedInstance ? (
        <p className="text-xs text-muted-foreground">
          id: <code>{selectedInstance.id}</code> · status: {selectedInstance.status}
          {selectedTemplate ? ` · template: ${selectedTemplate.template_code}` : ''}
        </p>
      ) : null}
    </div>
  )
}
