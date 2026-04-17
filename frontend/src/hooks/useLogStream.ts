import { useCallback, useEffect, useRef, useState } from 'react'

export interface HtmlRenderEvent {
  attempt: number
  max_attempts: number
  rendered_image_path: string
}

export interface HtmlValidationEvent {
  attempt: number
  status: string
  feedback: string | null
  issues: string[]
}

export interface LogStreamState {
  lines: string[]
  connected: boolean
  done: boolean
  active: boolean
  renders: HtmlRenderEvent[]
  validations: HtmlValidationEvent[]
  connect: (key: string) => void
}

function upsertByAttempt<T extends { attempt: number }>(items: T[], next: T): T[] {
  const index = items.findIndex((item) => item.attempt === next.attempt)
  if (index === -1) return [...items, next]
  const copy = [...items]
  copy[index] = next
  return copy
}

export function useLogStream(): LogStreamState {
  const [lines, setLines] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [done, setDone] = useState(false)
  const [active, setActive] = useState(false)
  const [renders, setRenders] = useState<HtmlRenderEvent[]>([])
  const [validations, setValidations] = useState<HtmlValidationEvent[]>([])
  const esRef = useRef<EventSource | null>(null)

  const connect = useCallback((key: string) => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }

    setLines([])
    setConnected(false)
    setDone(false)
    setActive(true)
    setRenders([])
    setValidations([])

    const es = new EventSource(`/v1/logs/stream/${key}`)
    esRef.current = es

    es.onopen = () => setConnected(true)

    es.onmessage = (e: MessageEvent) => {
      try {
        const { line } = JSON.parse(e.data as string) as { line: string }
        setLines((prev) => [...prev, line])
      } catch {
        // ignore malformed
      }
    }

    es.addEventListener('done', () => {
      setConnected(false)
      setDone(true)
      es.close()
    })

    es.addEventListener('html_render', (e: MessageEvent) => {
      try {
        const render = JSON.parse(e.data as string) as HtmlRenderEvent
        setRenders((prev) => upsertByAttempt(prev, render))
      } catch {
        // ignore malformed
      }
    })

    es.addEventListener('html_validation', (e: MessageEvent) => {
      try {
        const validation = JSON.parse(e.data as string) as HtmlValidationEvent
        setValidations((prev) => upsertByAttempt(prev, validation))
      } catch {
        // ignore malformed
      }
    })

    es.onerror = () => {
      setConnected(false)
    }
  }, [])

  useEffect(() => {
    return () => {
      esRef.current?.close()
      esRef.current = null
    }
  }, [])

  return { lines, connected, done, active, renders, validations, connect }
}
