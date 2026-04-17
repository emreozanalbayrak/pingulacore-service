import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '../test/server'
import { FullPipelinePage } from './FullPipelinePage'

describe('FullPipelinePage', () => {
  it('full pipeline run sonrası summary ve ara çıktıları gösterir', async () => {
    server.use(
      http.get('/v1/yaml-files', () => HttpResponse.json({ files: ['o08_iki_adimli_toplama.yaml'] })),
      http.post('/v1/pipelines/full/run', () =>
        HttpResponse.json({
          pipeline_id: 'p-1',
          sub_pipeline_ids: {
            yaml_to_question: 's-1',
            question_to_layout: 's-2',
            layout_to_html: 's-3',
          },
          question_json: { question_id: 'q-1', stem: 'Soru metni' },
          layout_plan_json: { schema_version: 'layout-plan.v2' },
          question_html: { html_content: '<div>html-final</div>' },
        }),
      ),
      http.get('/v1/pipelines/p-1', () => HttpResponse.json({ id: 'p-1', mode: 'full', yaml_filename: 'o08_iki_adimli_toplama.yaml', status: 'success', retry_config: {}, created_at: '2026-01-01T00:00:00Z', finished_at: '2026-01-01T00:00:01Z' })),
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
      expect(screen.getByText('o08_iki_adimli_toplama.yaml')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Full Pipeline Çalıştır' }))

    await waitFor(() => {
      expect(screen.getByText('p-1')).toBeInTheDocument()
    })

    expect(screen.getByText(/\"stem\": \"Soru metni\"/)).toBeInTheDocument()
    expect(screen.getByText(/html-final/)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByText(/step-html/).length).toBeGreaterThan(0)
    })
  })
})
