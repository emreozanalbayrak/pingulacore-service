import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiFetch } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiFetch', () => {
  it('422 detail içinden message parse eder', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: { message: 'retry limiti aşıldı' } }), {
          status: 422,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(apiFetch('/v1/test')).rejects.toMatchObject({
      status: 422,
      message: 'retry limiti aşıldı',
    })
  })
})
