import '@testing-library/jest-dom/vitest'

import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import { server } from './server'

class EventSourceMock {
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  constructor() {}
  addEventListener() {}
  close() {}
}

beforeAll(() => {
  vi.stubGlobal('EventSource', EventSourceMock)
  server.listen({ onUnhandledRequest: 'error' })
})
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
