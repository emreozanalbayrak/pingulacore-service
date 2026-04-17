function isRelativeAssetRef(value: string): boolean {
  const token = value.trim().toLowerCase()
  if (!token) {
    return false
  }
  return !(
    token.startsWith('http://') ||
    token.startsWith('https://') ||
    token.startsWith('//') ||
    token.startsWith('/') ||
    token.startsWith('data:') ||
    token.startsWith('#') ||
    token.startsWith('mailto:')
  )
}

function encodePathPreservingSlashes(path: string): string {
  return path
    .split('/')
    .filter((part) => part.length > 0)
    .map((part) => encodeURIComponent(part))
    .join('/')
}

function extractRunsRelativePath(value: string): string | null {
  const normalized = value.trim().replace(/\\/g, '/')
  if (!normalized) {
    return null
  }
  const matched = normalized.match(/(?:^|\/)(runs\/.+)$/i)
  if (!matched) {
    return null
  }
  return matched[1].replace(/^\/+|\/+$/g, '')
}

function toServerAssetUrl(value: string): string {
  const runsPath = extractRunsRelativePath(value)
  if (runsPath) {
    return `/v1/assets/${encodePathPreservingSlashes(runsPath)}`
  }

  const file = value.replace(/\\/g, '/').split('/').pop()?.split('?')[0]?.trim()
  if (!file) {
    return ''
  }
  return `/v1/assets/${encodeURIComponent(file)}`
}

function splitAssetRef(value: string): { base: string; suffix: string } {
  const indexes = ['?', '#']
    .map((sep) => value.indexOf(sep))
    .filter((idx) => idx >= 0)
  const splitIdx = indexes.length > 0 ? Math.min(...indexes) : value.length
  return { base: value.slice(0, splitIdx), suffix: value.slice(splitIdx) }
}

export function rewriteRelativeAssetUrls(html: string): string {
  const attrRewritten = html.replace(/\b(src|href)=(['"])([^'"]+)\2/gi, (_match, attr, quote, value) => {
    if (!isRelativeAssetRef(value)) {
      return `${attr}=${quote}${value}${quote}`
    }

    const { base, suffix } = splitAssetRef(value)
    const replaced = toServerAssetUrl(base)
    if (!replaced) {
      return `${attr}=${quote}${value}${quote}`
    }
    return `${attr}=${quote}${replaced}${suffix}${quote}`
  })

  return attrRewritten.replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/gi, (_match, quote, value) => {
    const token = value.trim()
    if (!isRelativeAssetRef(token)) {
      return `url(${quote}${token}${quote})`
    }
    const { base, suffix } = splitAssetRef(token)
    const replaced = toServerAssetUrl(base)
    if (!replaced) {
      return `url(${quote}${token}${quote})`
    }
    return `url(${quote}${replaced}${suffix}${quote})`
  })
}

export function pickHtmlContent(payload: unknown): string {
  if (!payload || typeof payload !== 'object') {
    return ''
  }
  const maybe = payload as Record<string, unknown>
  const value = maybe.html_content
  return typeof value === 'string' ? value : ''
}

export function toAssetUrlFromPath(pathOrFilename: string | null | undefined): string {
  const token = (pathOrFilename ?? '').trim()
  if (!token) {
    return ''
  }
  return toServerAssetUrl(token)
}
