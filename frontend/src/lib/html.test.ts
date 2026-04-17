import { describe, expect, it } from 'vitest'

import { rewriteRelativeAssetUrls, toAssetUrlFromPath } from './html'

describe('toAssetUrlFromPath', () => {
  it('keeps runs-relative path when building asset URL', () => {
    const url = toAssetUrlFromPath('runs/full/2026-04-16_12-00-00_g1_abc123/render_1.png')
    expect(url).toBe('/v1/assets/runs/full/2026-04-16_12-00-00_g1_abc123/render_1.png')
  })

  it('extracts runs path from absolute filesystem path', () => {
    const url = toAssetUrlFromPath('/Users/test/project/runs/sub/2026-04-16_12-00-00_geo_abc123/render_final.png')
    expect(url).toBe('/v1/assets/runs/sub/2026-04-16_12-00-00_geo_abc123/render_final.png')
  })

  it('falls back to basename for legacy plain filenames', () => {
    const url = toAssetUrlFromPath('render.png')
    expect(url).toBe('/v1/assets/render.png')
  })
})

describe('rewriteRelativeAssetUrls', () => {
  it('preserves runs path when rewriting relative URLs', () => {
    const html = '<img src="runs/full/2026-04-16_12-00-00_g1_abc123/render_2.png" />'
    const rewritten = rewriteRelativeAssetUrls(html)
    expect(rewritten).toContain('src="/v1/assets/runs/full/2026-04-16_12-00-00_g1_abc123/render_2.png"')
  })

  it('rewrites css url() background references for runs path', () => {
    const html = "<style>.scene{background-image:url('runs/sub/2026-04-16_12-00-00_geo_abc123/assets/classroom_scene.png')}</style>"
    const rewritten = rewriteRelativeAssetUrls(html)
    expect(rewritten).toContain("background-image:url('/v1/assets/runs/sub/2026-04-16_12-00-00_geo_abc123/assets/classroom_scene.png')")
  })
})
