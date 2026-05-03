import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { server } from '../test/server'
import type { PropertyDefinitionItem, PropertyDataType, YamlInstanceItem, YamlTemplateItem } from '../types'
import { ContentManagementPage } from './ContentManagementPage'

function installHandlers() {
  const curriculumTree = [
    {
      id: 'root',
      parent_id: null,
      node_type: 'root',
      scope: 'constant',
      name: 'Root',
      slug: 'root',
      code: null,
      grade: null,
      subject: null,
      theme: null,
      sort_order: 0,
      depth: 0,
      path: 'root',
      is_active: true,
      children: [
        {
          id: 'grade-2',
          parent_id: 'root',
          node_type: 'grade',
          scope: 'constant',
          name: '2. Sınıf',
          slug: 'grade-2',
          code: null,
          grade: '2',
          subject: null,
          theme: null,
          sort_order: 0,
          depth: 1,
          path: 'root/grade-2',
          is_active: true,
          children: [
            {
              id: 'subject-math',
              parent_id: 'grade-2',
              node_type: 'subject',
              scope: 'constant',
              name: 'Matematik',
              slug: '2-matematik',
              code: null,
              grade: '2',
              subject: 'matematik',
              theme: null,
              sort_order: 0,
              depth: 2,
              path: 'root/grade-2/2-matematik',
              is_active: true,
              children: [
                {
                  id: 'theme-ops',
                  parent_id: 'subject-math',
                  node_type: 'theme',
                  scope: 'constant',
                  name: 'İşlemlerden Cebirsel Düşünmeye',
                  slug: 'islemlerden-cebirsel-dusunmeye',
                  code: null,
                  grade: '2',
                  subject: 'matematik',
                  theme: 'islemlerden-cebirsel-dusunmeye',
                  sort_order: 0,
                  depth: 3,
                  path: 'root/grade-2/2-matematik/islemlerden-cebirsel-dusunmeye',
                  is_active: true,
                  children: [
                    {
                      id: 'folder-ops',
                      parent_id: 'theme-ops',
                      node_type: 'folder',
                      scope: 'folder',
                      name: 'Import Operations',
                      slug: 'import-g2m-operations-common',
                      code: null,
                      grade: '2',
                      subject: 'matematik',
                      theme: 'islemlerden-cebirsel-dusunmeye',
                      sort_order: 0,
                      depth: 4,
                      path: 'root/grade-2/2-matematik/islemlerden-cebirsel-dusunmeye/import-g2m-operations-common',
                      is_active: true,
                      children: [],
                    },
                    {
                      id: 'folder-draft',
                      parent_id: 'theme-ops',
                      node_type: 'folder',
                      scope: 'folder',
                      name: 'Import Operations Draft',
                      slug: 'import-g2m-operations-draft',
                      code: null,
                      grade: '2',
                      subject: 'matematik',
                      theme: 'islemlerden-cebirsel-dusunmeye',
                      sort_order: 1,
                      depth: 4,
                      path: 'root/grade-2/2-matematik/islemlerden-cebirsel-dusunmeye/import-g2m-operations-draft',
                      is_active: true,
                      children: [],
                    },
                  ],
                },
              ],
            },
          ],
        },
      ],
    },
  ]

  let properties: PropertyDefinitionItem[] = [
    {
      id: 'prop-root-visual',
      defined_at_curriculum_node_id: 'root',
      parent_property_id: null,
      label: 'Görsel',
      description: 'Genel görsel kuralları',
      property_key: 'gorsel',
      canonical_path: 'visual',
      data_type: 'json',
      constraints: null,
      is_required: false,
      is_active: true,
    },
  ]

  let templates: YamlTemplateItem[] = [
    {
      id: 'template-1',
      curriculum_folder_node_id: 'folder-ops',
      template_code: 'g2m_operations_common_v1',
      title: 'Operations Common',
      description: 'Toplama ve çıkarma tabanlı template',
      field_schema: {
        type: 'object',
        properties: {
          meta: {
            type: 'object',
            properties: {
              id: { type: 'text', label: 'Question ID' },
            },
          },
          format: {
            type: 'object',
            properties: {
              count: { type: 'number', label: 'Şık Sayısı' },
            },
          },
        },
      },
      schema_version: 'v1',
      status: 'active',
      created_by: 'seed',
    },
  ]

  let instances: YamlInstanceItem[] = [
    {
      id: 'instance-1',
      template_id: 'template-1',
      instance_name: 'ornek-instance',
      status: 'draft',
      values: {
        meta: { id: 'q-100' },
        format: { count: 3 },
      },
      rendered_yaml_text: null,
      created_by: 'seed',
    },
  ]

  let latestTemplatePayload: Record<string, unknown> | null = null
  let latestInstancePayload: Record<string, unknown> | null = null

  server.use(
    http.get('/v1/curriculum/tree', () => HttpResponse.json(curriculumTree)),
    http.get('/v1/properties', () => HttpResponse.json(properties)),
    http.get('/v1/properties/effective/:nodeId', () => HttpResponse.json(properties)),
    http.post('/v1/properties', async ({ request }) => {
      const payload = (await request.json()) as Record<string, unknown>
      const row = {
        id: 'prop-created',
        defined_at_curriculum_node_id: String(payload.defined_at_curriculum_node_id),
        parent_property_id: payload.parent_property_id ? String(payload.parent_property_id) : null,
        label: String(payload.label),
        description: typeof payload.description === 'string' ? payload.description : null,
        property_key: String(payload.property_key),
        canonical_path: String(payload.canonical_path),
        data_type: String(payload.data_type) as PropertyDataType,
        constraints: payload.constraints ?? null,
        is_required: Boolean(payload.is_required),
        is_active: true,
      } satisfies PropertyDefinitionItem
      properties = [...properties, row]
      return HttpResponse.json(row, { status: 201 })
    }),
    http.patch('/v1/properties/:propertyId', async ({ params, request }) => {
      const payload = (await request.json()) as Record<string, unknown>
      properties = properties.map((item) =>
        item.id === params.propertyId
          ? {
              ...item,
              ...payload,
              description: typeof payload.description === 'string' ? payload.description : null,
              constraints: payload.constraints ?? null,
            }
          : item,
      )
      return HttpResponse.json(properties.find((item) => item.id === params.propertyId))
    }),
    http.delete('/v1/properties/:propertyId', ({ params }) => {
      properties = properties.filter((item) => item.id !== params.propertyId)
      return new HttpResponse(null, { status: 204 })
    }),
    http.get('/v1/yaml-templates', () => HttpResponse.json(templates)),
    http.post('/v1/yaml-templates', async ({ request }) => {
      latestTemplatePayload = (await request.json()) as Record<string, unknown>
      const row = {
        id: 'template-created',
        curriculum_folder_node_id: String(latestTemplatePayload.curriculum_folder_node_id),
        template_code: String(latestTemplatePayload.template_code),
        title: String(latestTemplatePayload.title),
        description: typeof latestTemplatePayload.description === 'string' ? latestTemplatePayload.description : null,
        field_schema: (latestTemplatePayload.field_schema ?? {}) as Record<string, unknown>,
        schema_version: String(latestTemplatePayload.schema_version ?? 'v1'),
        status: 'active',
        created_by: typeof latestTemplatePayload.created_by === 'string' ? latestTemplatePayload.created_by : null,
      } satisfies YamlTemplateItem
      templates = [...templates, row]
      return HttpResponse.json(row, { status: 201 })
    }),
    http.patch('/v1/yaml-templates/:templateId', async ({ params, request }) => {
      const payload = (await request.json()) as Record<string, unknown>
      templates = templates.map((item) =>
        item.id === params.templateId
          ? {
              ...item,
              ...payload,
              description: typeof payload.description === 'string' ? payload.description : null,
              field_schema: (payload.field_schema as Record<string, unknown>) ?? item.field_schema,
            }
          : item,
      )
      return HttpResponse.json(templates.find((item) => item.id === params.templateId))
    }),
    http.delete('/v1/yaml-templates/:templateId', ({ params }) => {
      templates = templates.filter((item) => item.id !== params.templateId)
      return new HttpResponse(null, { status: 204 })
    }),
    http.get('/v1/yaml-instances', () => HttpResponse.json(instances)),
    http.post('/v1/yaml-instances', async ({ request }) => {
      latestInstancePayload = (await request.json()) as Record<string, unknown>
      const row = {
        id: 'instance-created',
        template_id: String(latestInstancePayload.template_id),
        instance_name: String(latestInstancePayload.instance_name),
        status: String(latestInstancePayload.status ?? 'draft'),
        values: (latestInstancePayload.values ?? {}) as Record<string, unknown>,
        rendered_yaml_text: null,
        created_by: typeof latestInstancePayload.created_by === 'string' ? latestInstancePayload.created_by : null,
      } satisfies YamlInstanceItem
      instances = [row, ...instances]
      return HttpResponse.json(row, { status: 201 })
    }),
    http.patch('/v1/yaml-instances/:instanceId', async ({ params, request }) => {
      const payload = (await request.json()) as Record<string, unknown>
      instances = instances.map((item) =>
        item.id === params.instanceId
          ? {
              ...item,
              ...payload,
              values: (payload.values as Record<string, unknown>) ?? item.values,
            }
          : item,
      )
      return HttpResponse.json(instances.find((item) => item.id === params.instanceId))
    }),
    http.delete('/v1/yaml-instances/:instanceId', ({ params }) => {
      instances = instances.filter((item) => item.id !== params.instanceId)
      return new HttpResponse(null, { status: 204 })
    }),
    http.post('/v1/yaml-instances/:instanceId/render', ({ params }) => {
      instances = instances.map((item) =>
        item.id === params.instanceId
          ? {
              ...item,
              rendered_yaml_text: 'meta:\n  id: q-rendered\nformat:\n  count: 4\n',
            }
          : item,
      )
      return HttpResponse.json({
        instance_id: params.instanceId,
        artifact_id: 'artifact-rendered',
        yaml_content: { meta: { id: 'q-rendered' }, format: { count: 4 } },
        rendered_yaml_text: 'meta:\n  id: q-rendered\nformat:\n  count: 4\n',
      })
    }),
  )

  return {
    getLatestTemplatePayload: () => latestTemplatePayload,
    getLatestInstancePayload: () => latestInstancePayload,
  }
}

describe('ContentManagementPage', () => {
  beforeEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: () => Promise.resolve(),
      } as unknown as Clipboard,
    })
  })

  it('property, template ve instance CRUD akışlarının temelini çalıştırır', async () => {
    const accessors = installHandlers()

    render(<ContentManagementPage />)

    expect(await screen.findByText('İçerik Yönetimi')).toBeInTheDocument()
    expect(await screen.findByText('Görsel')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Yeni Kayıt' }))
    fireEvent.change(screen.getByLabelText('Property label'), { target: { value: 'Şık Sayısı' } })
    fireEvent.change(screen.getByLabelText('Property key'), { target: { value: 'sik_sayisi' } })
    fireEvent.change(screen.getByLabelText('Canonical path'), { target: { value: 'option.count' } })
    fireEvent.change(screen.getByLabelText('Property data type'), { target: { value: 'number' } })
    fireEvent.click(screen.getByRole('button', { name: 'Oluştur' }))

    await waitFor(() => {
      expect(screen.getAllByText('Şık Sayısı').length).toBeGreaterThan(0)
    })

    fireEvent.click(screen.getByRole('button', { name: /^YAML Templates/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Yeni Kayıt' }))
    fireEvent.change(screen.getByLabelText('Curriculum folder'), { target: { value: 'folder-draft' } })
    fireEvent.change(screen.getByLabelText('Template code'), { target: { value: 'new_template_v1' } })
    fireEvent.change(screen.getByLabelText('Template title'), { target: { value: 'Yeni Template' } })
    fireEvent.click(screen.getByRole('button', { name: 'Alan Ekle' }))
    const schemaKeys = screen.getAllByLabelText('Schema field key')
    fireEvent.change(schemaKeys[0], { target: { value: 'prompt' } })
    fireEvent.click(screen.getByRole('button', { name: 'Template Oluştur' }))

    await waitFor(() => {
      expect(screen.getAllByText('Yeni Template').length).toBeGreaterThan(0)
    })
    expect(accessors.getLatestTemplatePayload()?.field_schema).toMatchObject({
      type: 'object',
      properties: {
        prompt: { type: 'text' },
      },
    })

    fireEvent.click(screen.getByRole('button', { name: /^YAML Instances/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Yeni Kayıt' }))
    fireEvent.change(screen.getByLabelText('Instance template'), { target: { value: 'template-1' } })
    fireEvent.change(screen.getByLabelText('Instance name'), { target: { value: 'instance-yeni' } })
    fireEvent.change(screen.getByLabelText('Question ID'), { target: { value: 'q-new' } })
    fireEvent.change(screen.getByLabelText('Şık Sayısı'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Instance Oluştur' }))

    await waitFor(() => {
      expect(screen.getAllByText('instance-yeni').length).toBeGreaterThan(0)
    })
    expect(accessors.getLatestInstancePayload()?.values).toMatchObject({
      meta: { id: 'q-new' },
      format: { count: 5 },
    })

    fireEvent.click(screen.getByRole('button', { name: /instance-yeni/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Render YAML' }))

    await waitFor(() => {
      expect(screen.getByText(/q-rendered/)).toBeInTheDocument()
    })
  })
})
