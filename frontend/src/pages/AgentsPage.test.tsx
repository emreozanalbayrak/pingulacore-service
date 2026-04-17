import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '../test/server'
import { AgentsPage } from './AgentsPage'

describe('AgentsPage', () => {
  it('hybrid form ile standalone agent run ve run detayını gösterir', async () => {
    server.use(
      http.post('/v1/agents/main/generate-html/run', () =>
        HttpResponse.json({
          run_id: 'r-1',
          result: { selected_template: 'stub', html_content: '<section>agent-html</section>' },
        }),
      ),
      http.get('/v1/agent-runs/main_generate_html/r-1', () =>
        HttpResponse.json({
          id: 'r-1',
          mode: 'standalone',
          pipeline_id: null,
          sub_pipeline_id: null,
          attempt_no: 1,
          status: 'success',
          input_json: {},
          output_json: { html_content: '<section>agent-html</section>' },
          feedback_text: '',
          error: null,
          model_name: 'stub',
          question_id: null,
          schema_version: null,
          started_at: '2026-01-01T00:00:00Z',
          finished_at: '2026-01-01T00:00:01Z',
        }),
      ),
    )

    render(<AgentsPage />)

    fireEvent.change(screen.getByLabelText('Agent'), {
      target: { value: 'main_generate_html' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Agent Çalıştır' }))

    await waitFor(() => {
      expect(screen.getAllByText('r-1').length).toBeGreaterThan(0)
    })

    expect(screen.getAllByText(/agent-html/).length).toBeGreaterThan(0)
    expect(screen.getByText('success')).toBeInTheDocument()
  })

  it('main generate question için ortak YAML dosyasını inputa yükler', async () => {
    server.use(
      http.get('/v1/yaml-files', () => HttpResponse.json({ files: ['o08_iki_adimli_toplama.yaml'] })),
      http.get('/v1/yaml-files/o08_iki_adimli_toplama.yaml', () =>
        HttpResponse.json({
          filename: 'o08_iki_adimli_toplama.yaml',
          data: { meta: { id: 'q-from-yaml' }, context: { topic: 'toplama' } },
        }),
      ),
    )

    render(<AgentsPage />)

    fireEvent.click(screen.getByRole('button', { name: 'YAML Listesini Yenile' }))
    await waitFor(() => {
      expect(screen.getByDisplayValue('o08_iki_adimli_toplama.yaml')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'YAML İçeriğini Yükle' }))

    await waitFor(() => {
      expect(screen.getByDisplayValue(/"q-from-yaml"/)).toBeInTheDocument()
    })
  })
})
