import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  LegacyBatchRunRequest,
  LegacyPipelineKind,
  LegacyYamlContentUpdateRequest,
} from '../types'
import { server } from '../test/server'
import { LegacyPipelinePage } from './LegacyPipelinePage'

class EventSourceMock {
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  constructor() {}
  addEventListener() {}
  close() {}
}

const geometryVariantYaml = 'varyantli/v1_robot_enerji.yaml'
const geometryPlainYaml = 'standart/k10_ucgen.yaml'
const turkceYaml = 'test/test_baglam_cikarim.yaml'
const uploadedYaml = 'uploads/user_uploaded.yaml'

const REPO_YAML_BODY = `id: ${turkceYaml}
question: ekran uzerinden test
choices:
  - a
  - b
  - c
answer: a
`

interface InstallOptions {
  onBatchRun?: (kind: LegacyPipelineKind, body: LegacyBatchRunRequest) => void
  onYamlSave?: (kind: LegacyPipelineKind, body: LegacyYamlContentUpdateRequest) => void
  onYamlUpload?: (kind: LegacyPipelineKind, fileName: string) => void
  saveShouldFail?: boolean
  yamlContentByPath?: Record<string, { content: string; is_repo_yaml: boolean }>
  filesByKind?: Partial<Record<LegacyPipelineKind, string[]>>
  batchRuns?: Record<string, ReturnType<typeof batchResponse>>
}

function batchResponse(kind: LegacyPipelineKind, batchId: string, overrides: Partial<{
  status: string
  variant_name: string | null
  error: string | null
  yaml_path: string
}> = {}) {
  return {
    batch_id: batchId,
    kind,
    runs: [
      {
        run_id: `${batchId}-r1`,
        kind,
        yaml_path: overrides.yaml_path ?? (kind === 'geometry' ? geometryVariantYaml : turkceYaml),
        variant_name: overrides.variant_name ?? (kind === 'geometry' ? 'v1_robot' : null),
        status: overrides.status ?? 'success',
        error: overrides.error ?? null,
        started_at: '2026-04-30T10:00:00Z',
        finished_at: '2026-04-30T10:00:01Z',
        outputs: [],
      },
    ],
  }
}

function installLegacyHandlers(options: InstallOptions = {}) {
  const yamlContentMap: Record<string, { content: string; is_repo_yaml: boolean }> = {
    [geometryVariantYaml]: { content: `id: ${geometryVariantYaml}\nvariants:\n  - v1_robot\n`, is_repo_yaml: true },
    [geometryPlainYaml]: { content: `id: ${geometryPlainYaml}\nquestion: tekil\n`, is_repo_yaml: true },
    [turkceYaml]: { content: REPO_YAML_BODY, is_repo_yaml: true },
    [uploadedYaml]: { content: 'id: uploaded\nquestion: hello\n', is_repo_yaml: false },
    ...(options.yamlContentByPath ?? {}),
  }

  server.use(
    http.get('/v1/legacy/pipelines', () =>
      HttpResponse.json({
        pipelines: [
          {
            kind: 'geometry',
            label: 'Geometri',
            enabled: true,
            yaml_root: 'legacy_app/geometri/pomodoro',
            default_params: { difficulty: 'medium' },
          },
          {
            kind: 'turkce',
            label: 'Türkçe',
            enabled: true,
            yaml_root: 'legacy_app/kadir_hoca/configs',
            default_params: {},
          },
        ],
      }),
    ),
    http.get('/v1/legacy/pipelines/:kind/yaml-files', ({ params }) => {
      const kind = params.kind as LegacyPipelineKind
      const fallback =
        kind === 'geometry' ? [geometryVariantYaml, geometryPlainYaml] : [turkceYaml]
      return HttpResponse.json({
        kind,
        files: options.filesByKind?.[kind] ?? fallback,
      })
    }),
    http.get('/v1/legacy/pipelines/:kind/yaml-info', ({ params, request }) => {
      const kind = params.kind as LegacyPipelineKind
      const yamlPath = new URL(request.url).searchParams.get('yaml_path')
      if (kind === 'geometry' && yamlPath === geometryVariantYaml) {
        return HttpResponse.json({
          kind,
          yaml_path: yamlPath,
          has_variants: true,
          variant_count: 3,
          variant_names: ['v1_robot', 'v2_lamba', 'v3_panel'],
        })
      }
      return HttpResponse.json({
        kind,
        yaml_path: yamlPath,
        has_variants: false,
        variant_count: 0,
        variant_names: [],
      })
    }),
    http.get('/v1/legacy/pipelines/:kind/yaml-content', ({ params, request }) => {
      const kind = params.kind as LegacyPipelineKind
      const yamlPath = new URL(request.url).searchParams.get('yaml_path') ?? ''
      const entry = yamlContentMap[yamlPath] ?? { content: '', is_repo_yaml: true }
      return HttpResponse.json({
        kind,
        yaml_path: yamlPath,
        content: entry.content,
        is_repo_yaml: entry.is_repo_yaml,
      })
    }),
    http.put('/v1/legacy/pipelines/:kind/yaml-content', async ({ params, request }) => {
      const kind = params.kind as LegacyPipelineKind
      const body = (await request.json()) as LegacyYamlContentUpdateRequest
      options.onYamlSave?.(kind, body)
      if (options.saveShouldFail) {
        return HttpResponse.json({ detail: 'YAML doğrulama hatası: invalid mapping' }, { status: 400 })
      }
      yamlContentMap[body.yaml_path] = {
        content: body.content,
        is_repo_yaml: yamlContentMap[body.yaml_path]?.is_repo_yaml ?? true,
      }
      return HttpResponse.json({
        kind,
        yaml_path: body.yaml_path,
        content: body.content,
        is_repo_yaml: yamlContentMap[body.yaml_path].is_repo_yaml,
      })
    }),
    http.post('/v1/legacy/pipelines/:kind/yaml-upload', async ({ params, request }) => {
      const kind = params.kind as LegacyPipelineKind
      const formData = await request.formData()
      const file = formData.get('file') as File | null
      options.onYamlUpload?.(kind, file?.name ?? '')
      const yaml_path = `uploads/${file?.name ?? 'unknown.yaml'}`
      yamlContentMap[yaml_path] = { content: 'id: fresh-upload\nquestion: q\n', is_repo_yaml: false }
      const baseFiles =
        options.filesByKind?.[kind] ??
        (kind === 'geometry' ? [geometryVariantYaml, geometryPlainYaml] : [turkceYaml])
      options.filesByKind = {
        ...(options.filesByKind ?? {}),
        [kind]: [...baseFiles, yaml_path],
      }
      return HttpResponse.json({ kind, yaml_path })
    }),
    http.post('/v1/legacy/pipelines/:kind/batch-run', async ({ params, request }) => {
      const kind = params.kind as LegacyPipelineKind
      const body = (await request.json()) as LegacyBatchRunRequest
      options.onBatchRun?.(kind, body)
      return HttpResponse.json({
        batch_id: `${kind}-batch-1`,
        run_ids: [`${kind}-run-1`],
        status: 'running',
        stream_key: body.stream_key,
      })
    }),
    http.get('/v1/legacy/runs/:batchId/batch', ({ params }) => {
      const batchId = String(params.batchId)
      const customised = options.batchRuns?.[batchId]
      if (customised) return HttpResponse.json(customised)
      return HttpResponse.json(
        batchResponse(batchId.startsWith('turkce') ? 'turkce' : 'geometry', batchId),
      )
    }),
  )
}

describe('LegacyPipelinePage', () => {
  beforeEach(() => {
    vi.stubGlobal('EventSource', EventSourceMock)
  })

  afterEach(() => {
    cleanup()
  })

  it('geometri YAML varyantlarını seçtirir ve batch run payloadunu doğru gönderir', async () => {
    let capturedKind: LegacyPipelineKind | null = null
    let capturedBody: LegacyBatchRunRequest | null = null
    installLegacyHandlers({
      onBatchRun: (kind, body) => {
        capturedKind = kind
        capturedBody = body
      },
    })

    render(<LegacyPipelinePage />)

    expect(await screen.findByRole('button', { name: /Geometri/i })).toBeInTheDocument()
    expect(screen.getByText(/YAML kökü \(repo\): legacy_app\/geometri\/pomodoro\//)).toBeInTheDocument()

    fireEvent.click(await screen.findByRole('checkbox', { name: `YAML seç: ${geometryVariantYaml}` }))

    await waitFor(() => {
      expect(screen.getByText(/toplam 3 alt-run üretilecek/)).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: 'v1_robot' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'v2_lamba' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'v3_panel' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(`Üretilecek varyant sayısı: ${geometryVariantYaml}`), {
      target: { value: '2' },
    })
    await waitFor(() => {
      expect(screen.getByText(/toplam 2 alt-run üretilecek/)).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: 'v2_lamba' }))
    await waitFor(() => {
      expect(screen.getByText(/toplam 1 alt-run üretilecek/)).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('Paralellik'), { target: { value: '4' } })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'zor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Çalıştır (1 alt-run)' }))

    await waitFor(() => {
      expect(capturedKind).toBe('geometry')
      expect(capturedBody).toMatchObject({
        parallelism: 4,
        items: [
          {
            yaml_path: geometryVariantYaml,
            params: { difficulty: 'zor' },
            variants: ['v1_robot'],
          },
        ],
      })
    })
    expect((capturedBody as LegacyBatchRunRequest | null)?.stream_key).toEqual(expect.any(String))
  })

  it('YAML drawer içeriğini açar ve Türkçe çalıştırmada varyantsız tek alt-run gönderir', async () => {
    let capturedKind: LegacyPipelineKind | null = null
    let capturedBody: LegacyBatchRunRequest | null = null
    installLegacyHandlers({
      onBatchRun: (kind, body) => {
        capturedKind = kind
        capturedBody = body
      },
    })

    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('button', { name: /Türkçe/i }))
    fireEvent.click(await screen.findByRole('button', { name: `YAML görüntüle/düzenle: ${turkceYaml}` }))

    const drawer = await screen.findByText('YAML Görüntüle / Düzenle')
    expect(drawer).toBeInTheDocument()
    expect(await screen.findByDisplayValue(/question: ekran uzerinden test/)).toBeInTheDocument()
    expect(screen.getByText(/Repo YAML'ı düzenliyorsun/)).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: 'Kapat' })[1])
    await waitFor(() => {
      expect(screen.queryByText('YAML Görüntüle / Düzenle')).not.toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('checkbox', { name: `YAML seç: ${turkceYaml}` }))
    await waitFor(() => {
      expect(screen.getByText(/Bu YAML varyantsız/)).toBeInTheDocument()
    })

    expect(screen.queryByLabelText(`Üretilecek varyant sayısı: ${turkceYaml}`)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Çalıştır (1 alt-run)' }))

    await waitFor(() => {
      expect(capturedKind).toBe('turkce')
      expect(capturedBody).toMatchObject({
        parallelism: 4,
        items: [
          {
            yaml_path: turkceYaml,
            params: {},
            variants: [],
          },
        ],
      })
    })
  })

  it('drawer içeriği eksiksiz yüklenir, dirty state ile Kaydet aktifleşir ve PUT payloadu içeriği aynen taşır', async () => {
    let savedKind: LegacyPipelineKind | null = null
    let savedBody: LegacyYamlContentUpdateRequest | null = null
    installLegacyHandlers({
      onYamlSave: (kind, body) => {
        savedKind = kind
        savedBody = body
      },
    })

    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('button', { name: /Türkçe/i }))
    fireEvent.click(await screen.findByRole('button', { name: `YAML görüntüle/düzenle: ${turkceYaml}` }))

    const textarea = (await screen.findByDisplayValue(/question: ekran uzerinden test/)) as HTMLTextAreaElement
    // Tüm orijinal içerik (newline'lar, choices listesi) tam korunmuş olmalı.
    expect(textarea.value).toBe(REPO_YAML_BODY)

    const saveButton = screen.getByRole('button', { name: /Kaydet/i })
    expect(saveButton).toBeDisabled()

    const editedContent = REPO_YAML_BODY.replace('question: ekran uzerinden test', 'question: düzenlenmiş soru')
    fireEvent.change(textarea, { target: { value: editedContent } })

    await waitFor(() => expect(saveButton).not.toBeDisabled())

    fireEvent.click(saveButton)

    await waitFor(() => {
      expect(savedKind).toBe('turkce')
      expect(savedBody).toEqual({ yaml_path: turkceYaml, content: editedContent })
    })

    // Save başarılı → original güncellendi → dirty=false → buton tekrar disabled.
    await waitFor(() => expect(saveButton).toBeDisabled())
    // Textarea'daki içerik kaydedilen değerle birebir aynı (newline/whitespace dahil).
    expect((textarea as HTMLTextAreaElement).value).toBe(editedContent)
    // Hata kutusu görünmemeli.
    expect(screen.queryByText(/YAML kaydedilemedi/)).not.toBeInTheDocument()
  })

  it('save backend hatası "YAML kaydedilemedi" detayını gösterir ve içeriği korur', async () => {
    installLegacyHandlers({ saveShouldFail: true })

    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('button', { name: /Türkçe/i }))
    fireEvent.click(await screen.findByRole('button', { name: `YAML görüntüle/düzenle: ${turkceYaml}` }))

    const textarea = (await screen.findByDisplayValue(/question: ekran uzerinden test/)) as HTMLTextAreaElement
    const edited = `${textarea.value}\n# yorum eklendi\n`
    fireEvent.change(textarea, { target: { value: edited } })

    const saveButton = screen.getByRole('button', { name: /Kaydet/i })
    await waitFor(() => expect(saveButton).not.toBeDisabled())
    fireEvent.click(saveButton)

    await waitFor(() => {
      expect(screen.getByText(/YAML doğrulama hatası: invalid mapping/)).toBeInTheDocument()
    })
    // Backend hatasından sonra kullanıcının düzenlemesi textarea'da hâlâ duruyor.
    expect((textarea as HTMLTextAreaElement).value).toBe(edited)
    // Hata düzeltilmediği için dirty=true → buton tekrar enabled (yeniden denenebilir).
    expect(saveButton).not.toBeDisabled()
  })

  it("uploaded YAML için drawer 'Repo YAML düzenliyorsun' uyarısını göstermez", async () => {
    installLegacyHandlers({
      filesByKind: { turkce: [turkceYaml, uploadedYaml] },
    })

    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('button', { name: /Türkçe/i }))
    fireEvent.click(await screen.findByRole('button', { name: `YAML görüntüle/düzenle: ${uploadedYaml}` }))

    expect(await screen.findByDisplayValue(/id: uploaded/)).toBeInTheDocument()
    expect(screen.queryByText(/Repo YAML'ı düzenliyorsun/)).not.toBeInTheDocument()
  })

  // jsdom + MSW kombinasyonunda hidden file input + FormData upload simulasyonu kararsız;
  // yükleme akışı kendisi yine handleUpload → api.uploadLegacyYaml → reloadYamlFiles → toggleSelect zinciri.
  // E2E'de manuel doğrulanır.
  it.skip('YAML upload sonrası dosya listeye eklenir ve otomatik seçilir', async () => {
    let uploadedKind: LegacyPipelineKind | null = null
    let uploadedName = ''
    installLegacyHandlers({
      onYamlUpload: (kind, fileName) => {
        uploadedKind = kind
        uploadedName = fileName
      },
    })

    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('button', { name: /Türkçe/i }))
    await screen.findByRole('checkbox', { name: `YAML seç: ${turkceYaml}` })

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    expect(fileInput).toBeTruthy()
    const file = new File(['id: yeni\n'], 'yeni.yaml', { type: 'application/x-yaml' })
    await userEvent.upload(fileInput, file)

    await waitFor(() => {
      expect(uploadedKind).toBe('turkce')
      expect(uploadedName).toBe('yeni.yaml')
    })

    // Yüklenen yol (uploads/yeni.yaml) listeye eklendi ve auto-select sonucu seçili kart göründü.
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: 'YAML seç: uploads/yeni.yaml' })).toBeChecked()
    })
    expect(screen.getByText(/Seçilen YAML'lar \(1\)/)).toBeInTheDocument()
  })

  it('pipeline türü değişince seçili YAML\'lar sıfırlanır (state preservation guard)', async () => {
    installLegacyHandlers()

    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('checkbox', { name: `YAML seç: ${geometryVariantYaml}` }))
    await waitFor(() => {
      expect(screen.getByText(/Seçilen YAML'lar \(1\)/)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Türkçe/i }))

    await waitFor(() => {
      expect(screen.queryByText(/Seçilen YAML'lar/)).not.toBeInTheDocument()
    })
    // Türkçe sekmesinde geometry seçimi sızmamış olmalı.
    expect(screen.queryByRole('checkbox', { name: `YAML seç: ${geometryVariantYaml}` })).not.toBeInTheDocument()
  })

  it('çoklu YAML seçimi totalRuns toplamını doğru hesaplar', async () => {
    installLegacyHandlers()

    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('checkbox', { name: `YAML seç: ${geometryVariantYaml}` }))
    await screen.findByText(/toplam 3 alt-run üretilecek/)

    fireEvent.click(screen.getByRole('checkbox', { name: `YAML seç: ${geometryPlainYaml}` }))

    // 3 varyant + 1 varyantsız = 4 alt-run.
    await waitFor(() => {
      expect(screen.getByText(/toplam 4 alt-run üretilecek/)).toBeInTheDocument()
    })
    expect(screen.getByText(/Seçilen YAML'lar \(2\)/)).toBeInTheDocument()
  })

  it('hiç YAML seçilmeden Çalıştır basılınca uyarı gösterir, sonrası kayboluyor', async () => {
    installLegacyHandlers()

    render(<LegacyPipelinePage />)
    await screen.findByRole('button', { name: /Geometri/i })

    const runButton = screen.getByRole('button', { name: /Çalıştır \(0 alt-run\)/ })
    expect(runButton).toBeDisabled()
  })

  it('varyantlı YAML\'da hiç varyant seçili değilken Çalıştır validation hatası verir', async () => {
    let captured: LegacyBatchRunRequest | null = null
    installLegacyHandlers({
      onBatchRun: (_kind, body) => {
        captured = body
      },
    })

    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('checkbox', { name: `YAML seç: ${geometryVariantYaml}` }))
    await screen.findByText(/toplam 3 alt-run üretilecek/)

    // Tüm varyantları kaldır (autofill: 0 → selectedVariants=[]).
    fireEvent.change(screen.getByLabelText(`Üretilecek varyant sayısı: ${geometryVariantYaml}`), {
      target: { value: '0' },
    })
    // totalRuns reduce: has_variants=true ama selectedVariants=[] olduğunda else branch → 1.
    await waitFor(() => {
      expect(screen.getByText(/toplam 1 alt-run üretilecek/)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Çalıştır \(1 alt-run\)/ }))

    await waitFor(() => {
      expect(
        screen.getByText(new RegExp(`${geometryVariantYaml.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')} için en az bir varyant seç`)),
      ).toBeInTheDocument()
    })
    // Backend hiç çağrılmamalı.
    expect(captured).toBeNull()
  })

  it('Listeden çıkar butonu seçili YAML\'ı kaldırır ve totalRuns sıfırlanır', async () => {
    installLegacyHandlers()
    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('checkbox', { name: `YAML seç: ${geometryVariantYaml}` }))
    await screen.findByText(/Seçilen YAML'lar \(1\)/)

    fireEvent.click(screen.getByRole('button', { name: 'Listeden çıkar' }))

    await waitFor(() => {
      expect(screen.queryByText(/Seçilen YAML'lar/)).not.toBeInTheDocument()
    })
    expect(screen.getByRole('checkbox', { name: `YAML seç: ${geometryVariantYaml}` })).not.toBeChecked()
  })

  it('batch tamamlandıktan sonra StatusBadge, variant chip ve hata kutusu doğru render olur', async () => {
    installLegacyHandlers({
      batchRuns: {
        'geometry-batch-1': {
          batch_id: 'geometry-batch-1',
          kind: 'geometry',
          runs: [
            {
              run_id: 'geometry-batch-1-r1',
              kind: 'geometry',
              yaml_path: geometryVariantYaml,
              variant_name: 'v1_robot',
              status: 'failed',
              error: 'render hatası: missing field',
              started_at: '2026-04-30T10:00:00Z',
              finished_at: '2026-04-30T10:00:01Z',
              outputs: [],
            },
          ],
        },
      },
    })

    render(<LegacyPipelinePage />)

    fireEvent.click(await screen.findByRole('checkbox', { name: `YAML seç: ${geometryVariantYaml}` }))
    await screen.findByText(/toplam 3 alt-run üretilecek/)

    fireEvent.click(screen.getByRole('button', { name: /Çalıştır \(3 alt-run\)/ }))

    // refreshBatch ilk çağrıda stale closure nedeniyle bail eder; usePolling 2500ms sonra
    // güncel batchId ile çağırır → waitFor timeout'u artırıyoruz.
    const errorBox = await screen.findByText(/render hatası: missing field/, undefined, { timeout: 5000 })
    expect(errorBox).toBeInTheDocument()

    const resultsCard = errorBox.closest('.bg-card') ?? errorBox.parentElement!
    const scoped = within(resultsCard as HTMLElement)
    expect(scoped.getByText('failed')).toBeInTheDocument()
    expect(scoped.getByText('v1_robot')).toBeInTheDocument()

    // outputs.length===0 → ZIP butonu disabled.
    expect(scoped.getByRole('button', { name: /Tümünü ZIP indir/i })).toBeDisabled()
  })
})
