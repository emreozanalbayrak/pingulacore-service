import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '../test/server'
import { FullPipelinePage } from './FullPipelinePage'

describe('FullPipelinePage', () => {
  it('full pipeline run sonrası summary ve ara çıktıları gösterir', async () => {
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
      http.post('/v1/pipelines/full/run', () =>
        HttpResponse.json({
          pipeline_id: 'p-1',
          sub_pipeline_ids: {
            yaml_to_question: 's-1',
            question_to_layout: 's-2',
            layout_to_html: 's-3',
          },
          question_artifact_id: 'qa-1',
          layout_artifact_id: 'la-1',
          html_artifact_id: 'ha-1',
          rendered_image_artifact_id: null,
          question_json: { question_id: 'q-1', stem: 'Soru metni' },
          layout_plan_json: { schema_version: 'layout-plan.v2' },
          question_html: { html_content: '<div>html-final</div>' },
        }),
      ),
      http.get('/v1/pipelines/p-1', () => HttpResponse.json({ id: 'p-1', mode: 'full', yaml_instance_id: 'yaml-1', status: 'success', retry_config: {}, created_at: '2026-01-01T00:00:00Z', finished_at: '2026-01-01T00:00:01Z' })),
      http.get('/v1/pipelines/p-1/agent-runs', () =>
        HttpResponse.json([
          {
            id: 1,
            pipeline_id: 'p-1',
            sub_pipeline_id: 's-1',
            agent_name: 'main_generate_question',
            agent_table: 'agent_main_question_runs',
            agent_run_id: 'r-1',
            created_at: '2026-01-01T00:00:00Z',
          },
        ]),
      ),
      http.get('/v1/pipelines/p-1/logs', () =>
        HttpResponse.json([
          {
            id: 10,
            pipeline_id: 'p-1',
            sub_pipeline_id: null,
            mode: 'full',
            level: 'info',
            component: 'pipeline',
            message: 'Full pipeline başlatıldı.',
            details: { yaml: 'o08_iki_adimli_toplama.yaml' },
            created_at: '2026-01-01T00:00:00Z',
          },
        ]),
      ),
      http.get('/v1/sub-pipelines/s-1', () =>
        HttpResponse.json({
          id: 's-1',
          pipeline_id: 'p-1',
          mode: 'full',
          kind: 'yaml_to_question',
          status: 'success',
          input_json: {},
          output_json: { question: { question_id: 'q-1' } },
          error: null,
          created_at: '2026-01-01T00:00:00Z',
          finished_at: '2026-01-01T00:00:01Z',
        }),
      ),
      http.get('/v1/sub-pipelines/s-1/logs', () => HttpResponse.json([])),
      http.get('/v1/sub-pipelines/s-2', () =>
        HttpResponse.json({
          id: 's-2',
          pipeline_id: 'p-1',
          mode: 'full',
          kind: 'question_to_layout',
          status: 'success',
          input_json: {},
          output_json: { layout: { schema_version: 'layout-plan.v2' } },
          error: null,
          created_at: '2026-01-01T00:00:00Z',
          finished_at: '2026-01-01T00:00:01Z',
        }),
      ),
      http.get('/v1/sub-pipelines/s-2/logs', () => HttpResponse.json([])),
      http.get('/v1/sub-pipelines/s-3', () =>
        HttpResponse.json({
          id: 's-3',
          pipeline_id: 'p-1',
          mode: 'full',
          kind: 'layout_to_html',
          status: 'success',
          input_json: {},
          output_json: { html: { html_content: '<div>step-html</div>' } },
          error: null,
          created_at: '2026-01-01T00:00:00Z',
          finished_at: '2026-01-01T00:00:01Z',
        }),
      ),
      http.get('/v1/sub-pipelines/s-3/logs', () => HttpResponse.json([])),
    )

    render(<FullPipelinePage />)

    await waitFor(() => {
      expect(screen.getByText('o08_iki_adimli_toplama')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Full Pipeline Çalıştır' }))

    await waitFor(() => {
      expect(screen.getByText('Pipeline Özeti')).toBeInTheDocument()
    })

    expect(screen.getAllByText(/Soru metni/).length).toBeGreaterThan(0)
    fireEvent.click(screen.getAllByRole('button', { name: 'Raw' })[0])
    expect(screen.getByText(/html-final/)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByText(/step-html/).length).toBeGreaterThan(0)
    })
  })
})
