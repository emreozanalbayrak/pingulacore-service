import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { server } from '../test/server'
import { SubPipelinesPage } from './SubPipelinesPage'

class EventSourceMock {
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  constructor(_url: string) {}
  addEventListener(_type: string, _listener: EventListenerOrEventListenerObject) {}
  close() {}
}

interface StoredFileRow {
  filename: string
  is_favorite: boolean
}

interface HandlerOptions {
  questionFiles?: StoredFileRow[]
  layoutFiles?: StoredFileRow[]
}

function installHandlers(options: HandlerOptions = {}) {
  let questionFiles: StoredFileRow[] = [...(options.questionFiles ?? [])]
  let layoutFiles: StoredFileRow[] = [...(options.layoutFiles ?? [])]

  const payloadFor = (items: StoredFileRow[]) => ({
    files: items.map((item) => item.filename),
    items,
  })

  server.use(
    http.get('/v1/yaml-files', () => HttpResponse.json({ files: ['o08_iki_adimli_toplama.yaml'] })),
    http.get('/v1/sp-files/q_json', () => HttpResponse.json(payloadFor(questionFiles))),
    http.get('/v1/sp-files/layout', () => HttpResponse.json(payloadFor(layoutFiles))),
    http.post('/v1/pipelines/sub/yaml-to-question/run', () =>
      HttpResponse.json({
        sub_pipeline_id: 'sq-1',
        question_json: { question_id: 'q-2', stem: 'deneme' },
        rule_evaluation: {},
        attempts: 1,
      }),
    ),
    http.post('/v1/pipelines/sub/question-to-layout/run', () =>
      HttpResponse.json({
        sub_pipeline_id: 'sl-1',
        layout_plan_json: { schema_version: 'layout-plan.v2', question_id: 'q-2' },
        validation: { overall_status: 'pass', issues: [], feedback: '' },
        attempts: 1,
      }),
    ),
    http.post('/v1/pipelines/sub/layout-to-html/run', () =>
      HttpResponse.json({
        sub_pipeline_id: 'sh-1',
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

    const runYamlButton = await screen.findByRole('button', { name: 'Çalıştır' })
    fireEvent.click(runYamlButton)

    await waitFor(() => {
      expect(screen.getAllByText(/q-2/).length).toBeGreaterThan(0)
    })

    fireEvent.click(screen.getByRole('button', { name: /Question → Layout/i }))
    expect(screen.getByDisplayValue(/\"question_id\": \"q-2\"/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Çalıştır' }))

    fireEvent.click(screen.getByRole('button', { name: /Layout → HTML/i }))
    await waitFor(() => {
      expect(screen.getByDisplayValue(/\"schema_version\": \"layout-plan.v2\"/)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Çalıştır' }))

    await waitFor(() => {
      expect(screen.getAllByText(/render me/).length).toBeGreaterThan(0)
    })
  })

  it('favori kontrolleri kaldırılmış halde dosya seçim akışı çalışır', async () => {
    installHandlers({
      questionFiles: [{ filename: '20260417_q1.question.json', is_favorite: true }],
      layoutFiles: [{ filename: '20260417_l1.layout.json', is_favorite: true }],
    })
    render(<SubPipelinesPage />)

    fireEvent.click(await screen.findByRole('button', { name: /Question → Layout/i }))
    expect(screen.queryByRole('button', { name: /Question Favorile/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Kayıtlı Question: sadece favorileri göster')).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: /20260417_q1\.question\.json/ })).toBeInTheDocument()
  })
})
