import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { server } from '../test/server'
import { FilesPage } from './FilesPage'

interface NodeRow {
  name: string
  path: string
  kind: 'file' | 'dir'
  is_favorite: boolean
  favoritable: boolean
  children?: NodeRow[]
}

function installHandlers() {
  let runsTree: NodeRow[] = [
    {
      name: 'sub',
      path: 'sub',
      kind: 'dir',
      is_favorite: false,
      favoritable: false,
      children: [
        {
          name: 'render_final.png',
          path: 'sub/render_final.png',
          kind: 'file',
          is_favorite: false,
          favoritable: true,
          children: [],
        },
        {
          name: 'scene.png',
          path: 'sub/scene.png',
          kind: 'file',
          is_favorite: false,
          favoritable: false,
          children: [],
        },
      ],
    },
  ]
  let spFilesTree: NodeRow[] = [
    {
      name: 'q_json',
      path: 'q_json',
      kind: 'dir',
      is_favorite: false,
      favoritable: false,
      children: [
        {
          name: 'demo.question.json',
          path: 'q_json/demo.question.json',
          kind: 'file',
          is_favorite: false,
          favoritable: true,
          children: [],
        },
      ],
    },
  ]

  const favoriteCalls: Array<{ root: string; path: string; is_favorite: boolean }> = []
  const deleteCalls: Array<{ root: string; path: string }> = []

  server.use(
    http.get('/v1/explorer/tree', ({ request }) => {
      const url = new URL(request.url)
      const root = url.searchParams.get('root')
      if (root === 'runs') return HttpResponse.json({ root, items: runsTree, path: null })
      if (root === 'sp_files') return HttpResponse.json({ root, items: spFilesTree, path: null })
      return HttpResponse.json({ detail: 'invalid root' }, { status: 422 })
    }),
    http.get('/v1/explorer/file', ({ request }) => {
      const url = new URL(request.url)
      const root = url.searchParams.get('root')
      const path = url.searchParams.get('path')
      if (root === 'sp_files' && path === 'q_json/demo.question.json') {
        return HttpResponse.json({
          root,
          path,
          filename: 'demo.question.json',
          content_type: 'json',
          content: { question_id: 'q-demo' },
          mime_type: 'application/json',
          asset_url: null,
        })
      }
      if (root === 'runs' && (path === 'sub/render_final.png' || path === 'sub/scene.png')) {
        const filename = path.split('/').pop() ?? 'image.png'
        return HttpResponse.json({
          root,
          path,
          filename,
          content_type: 'image',
          content: 'ZmFrZQ==',
          mime_type: 'image/png',
          asset_url: null,
        })
      }
      return HttpResponse.json({ detail: 'not found' }, { status: 404 })
    }),
    http.patch('/v1/explorer/file/favorite', async ({ request }) => {
      const body = (await request.json()) as { root: string; path: string; is_favorite: boolean }
      favoriteCalls.push(body)
      if (body.root === 'runs' && body.path === 'sub/render_final.png') {
        runsTree = runsTree.map((dir) => ({
          ...dir,
          children: (dir.children ?? []).map((file) =>
            file.path === body.path ? { ...file, is_favorite: body.is_favorite } : file,
          ),
        }))
      }
      return HttpResponse.json(body)
    }),
    http.delete('/v1/explorer/file', ({ request }) => {
      const url = new URL(request.url)
      const root = url.searchParams.get('root') ?? ''
      const path = url.searchParams.get('path') ?? ''
      deleteCalls.push({ root, path })
      if (root === 'sp_files' && path === 'q_json/demo.question.json') {
        spFilesTree = [
          {
            name: 'q_json',
            path: 'q_json',
            kind: 'dir',
            is_favorite: false,
            favoritable: false,
            children: [],
          },
        ]
      }
      return new HttpResponse(null, { status: 204 })
    }),
  )

  return { favoriteCalls, deleteCalls }
}

describe('FilesPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('tree gösterir ve dosyaya tıklayınca json preview otomatik açar', async () => {
    installHandlers()
    render(<FilesPage />)

    const fileButton = await screen.findByRole('button', { name: /demo\.question\.json/ })
    expect(fileButton).toHaveAttribute('title', 'demo.question.json')
    fireEvent.click(fileButton)

    await waitFor(() => {
      expect(screen.getByText('JSON Preview')).toBeInTheDocument()
      expect(screen.getByText(/q-demo/)).toBeInTheDocument()
    })
  })

  it('delete akışı node’u ağaçtan kaldırır', async () => {
    const { deleteCalls } = installHandlers()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<FilesPage />)

    fireEvent.click(await screen.findByRole('button', { name: /demo\.question\.json/ }))
    await screen.findByText('JSON Preview')
    fireEvent.click(screen.getByRole('button', { name: 'Sil' }))

    await waitFor(() => {
      expect(deleteCalls).toEqual([{ root: 'sp_files', path: 'q_json/demo.question.json' }])
      expect(screen.queryByText('demo.question.json')).not.toBeInTheDocument()
    })
  })

  it('favorite toggle çağrılır ve non-favoritable dosyada buton disabled olur', async () => {
    const { favoriteCalls } = installHandlers()
    render(<FilesPage />)

    fireEvent.click(await screen.findByRole('button', { name: /render_final\.png/ }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Favorile' })).not.toBeDisabled()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Favorile' }))

    await waitFor(() => {
      expect(favoriteCalls).toEqual([{ root: 'runs', path: 'sub/render_final.png', is_favorite: true }])
    })

    fireEvent.click(screen.getByRole('button', { name: /scene\.png/ }))
    expect(screen.getByRole('button', { name: 'Favorile' })).toBeDisabled()
  })
})
