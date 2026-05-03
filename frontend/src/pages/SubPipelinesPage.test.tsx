import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { server } from '../test/server'
import type { ArtifactItem } from '../types'
import { SubPipelinesPage } from './SubPipelinesPage'

class EventSourceMock {
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  constructor(_url: string) {}
  addEventListener(_type: string, _listener: EventListenerOrEventListenerObject) {}
  close() {}
}

function installHandlers() {
  let questionArtifacts: ArtifactItem[] = [
    {
      id: 'question-seed',
      kind: 'question',
      content_json: { question_id: 'seed-q', stem: 'seed stem' },
      content_text: null,
      object_bucket: null,
      object_key: null,
      mime_type: null,
      is_favorite: false,
      source_pipeline_id: null,
      source_sub_pipeline_id: null,
      source_agent_name: null,
      source_agent_run_id: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
  ]

  let layoutArtifacts: ArtifactItem[] = [
    {
      id: 'layout-seed',
      kind: 'layout',
      content_json: { schema_version: 'layout-plan.v2', question_id: 'seed-q' },
      content_text: null,
      object_bucket: null,
      object_key: null,
      mime_type: null,
      is_favorite: false,
      source_pipeline_id: null,
      source_sub_pipeline_id: null,
      source_agent_name: null,
      source_agent_run_id: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
  ]

  server.use(
    http.get('/v1/curriculum/tree', () =>
      HttpResponse.json([
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
                      name: 'Sayılar',
                      slug: 'sayilar',
                      code: null,
                      grade: '2',
                      subject: 'matematik',
                      theme: 'sayilar',
                      sort_order: 0,
                      depth: 3,
                      path: 'root/grade-2/2-matematik/sayilar',
                      is_active: true,
                      children: [
                        {
                          id: 'folder-toplama',
                          parent_id: 'theme-ops',
                          node_type: 'folder',
                          scope: 'folder',
                          name: 'Toplama',
                          slug: 'toplama',
                          code: null,
                          grade: 'grade-2',
                          subject: '2-matematik',
                          theme: 'sayilar',
                          sort_order: 0,
                          depth: 4,
                          path: 'root/grade-2/2-matematik/sayilar/toplama',
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
      ]),
    ),
    http.get('/v1/yaml-templates', () =>
      HttpResponse.json([
        {
          id: 'tpl-1',
          curriculum_folder_node_id: 'folder-toplama',
          template_code: 'tpl-code',
          title: 'Template 1',
          description: null,
          field_schema: { type: 'object', properties: {} },
          schema_version: 'v1',
          status: 'active',
          created_by: 'seed',
        },
      ]),
    ),
    http.get('/v1/yaml-instances', () =>
      HttpResponse.json([
        {
          id: 'yaml-1',
          template_id: 'tpl-1',
          instance_name: 'o08_iki_adimli_toplama',
          status: 'final',
          values: { meta: { id: 'yaml-1' } },
          rendered_yaml_text: null,
          created_by: 'seed',
        },
      ]),
    ),
    http.get('/v1/artifacts', ({ request }) => {
      const kind = new URL(request.url).searchParams.get('kind')
      if (kind === 'question') return HttpResponse.json(questionArtifacts)
      if (kind === 'layout') return HttpResponse.json(layoutArtifacts)
      return HttpResponse.json([])
    }),
    http.get('/v1/artifacts/:artifactId', ({ params }) => {
      const artifact = [...questionArtifacts, ...layoutArtifacts].find((item) => item.id === params.artifactId)
      return HttpResponse.json(artifact)
    }),
    http.post('/v1/pipelines/sub/yaml-to-question/run', () => {
      questionArtifacts = [
        {
          id: 'qa-1',
          kind: 'question',
          content_json: { question_id: 'q-2', stem: 'deneme' },
          content_text: null,
          object_bucket: null,
          object_key: null,
          mime_type: null,
          is_favorite: false,
          source_pipeline_id: null,
          source_sub_pipeline_id: 'sq-1',
          source_agent_name: null,
          source_agent_run_id: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
        ...questionArtifacts,
      ]
      return HttpResponse.json({
        sub_pipeline_id: 'sq-1',
        question_artifact_id: 'qa-1',
        question_json: { question_id: 'q-2', stem: 'deneme' },
        rule_evaluation: {},
        attempts: 1,
      })
    }),
    http.post('/v1/pipelines/sub/question-to-layout/run', () => {
      layoutArtifacts = [
        {
          id: 'la-1',
          kind: 'layout',
          content_json: { schema_version: 'layout-plan.v2', question_id: 'q-2' },
          content_text: null,
          object_bucket: null,
          object_key: null,
          mime_type: null,
          is_favorite: false,
          source_pipeline_id: null,
          source_sub_pipeline_id: 'sl-1',
          source_agent_name: null,
          source_agent_run_id: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
        ...layoutArtifacts,
      ]
      return HttpResponse.json({
        sub_pipeline_id: 'sl-1',
        layout_artifact_id: 'la-1',
        layout_plan_json: { schema_version: 'layout-plan.v2', question_id: 'q-2' },
        validation: { overall_status: 'pass', issues: [], feedback: '' },
        attempts: 1,
      })
    }),
    http.post('/v1/pipelines/sub/layout-to-html/run', () =>
      HttpResponse.json({
        sub_pipeline_id: 'sh-1',
        html_artifact_id: 'ha-1',
        rendered_image_artifact_id: null,
        question_html: { html_content: '<div>render me</div>' },
        validation: { overall_status: 'pass', issues: [], feedback: '' },
        attempts: 1,
        generated_assets: {},
      }),
    ),
    http.get('/v1/sub-pipelines/:id', ({ params }) =>
      HttpResponse.json({
        id: params.id,
        pipeline_id: null,
        mode: 'sub',
        kind: 'any',
        status: 'success',
        input_json: {},
        output_json: {},
        error: null,
        created_at: '2026-01-01T00:00:00Z',
        finished_at: '2026-01-01T00:00:01Z',
      }),
    ),
    http.get('/v1/sub-pipelines/:id/agent-runs', () => HttpResponse.json([])),
    http.get('/v1/sub-pipelines/:id/logs', () => HttpResponse.json([])),
  )
}

describe('SubPipelinesPage', () => {
  beforeEach(() => {
    vi.stubGlobal('EventSource', EventSourceMock)
  })

  it('step çıktıları bir sonraki adıma otomatik taşınır', async () => {
    installHandlers()

    render(<SubPipelinesPage />)

    const runButtons = await screen.findAllByRole('button', { name: 'Çalıştır' })
    fireEvent.click(runButtons[0])

    await waitFor(() => {
      expect(screen.getAllByText(/q-2/).length).toBeGreaterThan(0)
    })

    fireEvent.click(screen.getByRole('button', { name: /Question → Layout/i }))
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'qa-1' })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Çalıştır' }))

    fireEvent.click(screen.getByRole('button', { name: /Layout → HTML/i }))
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'la-1' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Çalıştır' }))
    await waitFor(() => {
      expect(screen.getByText('Sub-Pipeline HTML Preview')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Raw' }))

    await waitFor(() => {
      expect(screen.getAllByText(/render me/).length).toBeGreaterThan(0)
    })
  })

  it('question ve layout artifact seçim akışı yeni DB input modeliyle çalışır', async () => {
    installHandlers()
    render(<SubPipelinesPage />)

    fireEvent.click(await screen.findByRole('button', { name: /Question → Layout/i }))
    expect(screen.queryByRole('button', { name: /Question Favorile/i })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'question-seed' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Layout → HTML/i }))
    expect(screen.getByRole('option', { name: 'layout-seed' })).toBeInTheDocument()
  })
})
