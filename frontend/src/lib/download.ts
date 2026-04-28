type SaveFilePickerOptions = {
  suggestedName?: string
  types?: Array<{
    description?: string
    accept: Record<string, string[]>
  }>
}

type FileSystemWritableFileStream = {
  write: (data: BufferSource | Blob | string) => Promise<void>
  close: () => Promise<void>
}

type FileSystemFileHandle = {
  createWritable: () => Promise<FileSystemWritableFileStream>
}

declare global {
  interface Window {
    showSaveFilePicker?: (options?: SaveFilePickerOptions) => Promise<FileSystemFileHandle>
  }
}

export function isFileSystemAccessSupported(): boolean {
  return typeof window !== 'undefined' && typeof window.showSaveFilePicker === 'function'
}

function inferAcceptType(filename: string): SaveFilePickerOptions['types'] {
  const ext = filename.toLowerCase().match(/\.[a-z0-9]+$/)?.[0] ?? ''
  if (ext === '.zip') return [{ description: 'ZIP', accept: { 'application/zip': ['.zip'] } }]
  if (ext === '.png') return [{ description: 'PNG image', accept: { 'image/png': ['.png'] } }]
  if (ext === '.jpg' || ext === '.jpeg')
    return [{ description: 'JPEG image', accept: { 'image/jpeg': ['.jpg', '.jpeg'] } }]
  if (ext === '.html') return [{ description: 'HTML', accept: { 'text/html': ['.html'] } }]
  if (ext === '.json') return [{ description: 'JSON', accept: { 'application/json': ['.json'] } }]
  if (ext === '.yaml' || ext === '.yml')
    return [{ description: 'YAML', accept: { 'application/x-yaml': ['.yaml', '.yml'] } }]
  if (ext === '.pdf') return [{ description: 'PDF', accept: { 'application/pdf': ['.pdf'] } }]
  return undefined
}

/**
 * Save a Blob to disk. Uses File System Access API when available so the user
 * picks the destination path; otherwise falls back to a classic anchor download.
 */
export async function saveBlobAs(blob: Blob, suggestedName: string): Promise<'picker' | 'fallback'> {
  if (isFileSystemAccessSupported()) {
    try {
      const handle = await window.showSaveFilePicker!({
        suggestedName,
        types: inferAcceptType(suggestedName),
      })
      const writable = await handle.createWritable()
      await writable.write(blob)
      await writable.close()
      return 'picker'
    } catch (err) {
      // User aborted — don't fall back.
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err
      }
      // Fall through to classic download on other errors.
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = suggestedName
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return 'fallback'
}

/**
 * Fetch a URL and save its body. Used for ZIP endpoints and asset URLs.
 */
export async function downloadFromUrl(url: string, suggestedName: string): Promise<'picker' | 'fallback'> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`İndirme hatası (${res.status})`)
  }
  const blob = await res.blob()
  return saveBlobAs(blob, suggestedName)
}
