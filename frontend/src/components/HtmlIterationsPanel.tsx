import { useEffect, useMemo, useRef } from 'react'
import { CheckCircle, XCircle, Loader2 } from 'lucide-react'

import { toAssetUrlFromPath } from '../lib/html'
import type { HtmlRenderEvent, HtmlValidationEvent } from '../hooks/useLogStream'

interface Props {
  renders: HtmlRenderEvent[]
  validations: HtmlValidationEvent[]
  running?: boolean
}

export function HtmlIterationsPanel({ renders, validations, running = false }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const attempts = useMemo(() => {
    const renderByAttempt = new Map<number, HtmlRenderEvent>(renders.map((render) => [render.attempt, render]))
    const validationByAttempt = new Map<number, HtmlValidationEvent>(validations.map((validation) => [validation.attempt, validation]))
    const numbers = [...new Set([...renderByAttempt.keys(), ...validationByAttempt.keys()])].sort((a, b) => a - b)

    return numbers.map((attempt) => ({
      attempt,
      render: renderByAttempt.get(attempt),
      validation: validationByAttempt.get(attempt),
    }))
  }, [renders, validations])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [renders.length, validations.length])

  if (attempts.length === 0 && !running) return null
  const lastAttempt = attempts[attempts.length - 1]
  const waitingForNextRender =
    running && Boolean(lastAttempt?.validation) && lastAttempt.validation?.status !== 'pass'

  return (
    <div className="bg-card rounded-2xl border border-border overflow-hidden">
      <div
        className="px-6 py-4 border-b border-border flex items-center gap-3"
        style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}
      >
        <h3 className="text-lg" style={{ fontFamily: 'var(--font-display)' }}>
          HTML Iterations
        </h3>
        {running && attempts.length === 0 && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="w-3 h-3 animate-spin" />
            Waiting for first render...
          </span>
        )}
      </div>

      <div className="p-6 space-y-6">
        {attempts.map((entry, idx) => {
          const imageUrl = entry.render ? toAssetUrlFromPath(entry.render.rendered_image_path) : ''
          const passed = entry.validation?.status === 'pass'
          const failed = Boolean(entry.validation) && !passed

          return (
            <div key={entry.attempt} className="space-y-3">
              {/* Iteration header */}
              <div className="flex items-center gap-2">
                {entry.validation ? (
                  passed ? (
                    <CheckCircle className="w-5 h-5 text-green-500" />
                  ) : (
                    <XCircle className="w-5 h-5 text-amber-500" />
                  )
                ) : (
                  <Loader2 className="w-5 h-5 text-muted-foreground animate-spin" />
                )}
                <span className="font-medium text-foreground">
                  Iteration {entry.attempt}
                  {entry.render ? `/${entry.render.max_attempts}` : ''}
                </span>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    passed
                      ? 'bg-green-100 text-green-700'
                      : failed
                        ? 'bg-amber-100 text-amber-700'
                        : 'bg-muted text-muted-foreground'
                  }`}
                >
                  {passed ? 'Passed' : failed ? 'Failed' : 'Evaluating...'}
                </span>
              </div>

              {/* Rendered image */}
              {imageUrl && (
                <img
                  src={imageUrl}
                  alt={`Iteration ${entry.attempt} render`}
                  className="w-full rounded-lg border border-border"
                  style={{ maxWidth: 960 }}
                />
              )}

              {/* Per-attempt evaluating state */}
              {!entry.validation && entry.render && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground px-1">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Evaluating...
                </div>
              )}

              {/* Feedback */}
              {failed && entry.validation?.feedback && (
                <div className="px-4 py-3 rounded-lg bg-amber-50 border border-amber-200 text-sm text-amber-800">
                  <span className="font-medium">Feedback:</span>{' '}
                  {entry.validation.feedback}
                </div>
              )}

              {/* Issues list */}
              {failed && entry.validation?.issues && entry.validation.issues.length > 0 && (
                <ul className="px-4 space-y-1 text-sm text-amber-700">
                  {entry.validation.issues.map((issue, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="shrink-0">-</span>
                      <span>{issue}</span>
                    </li>
                  ))}
                </ul>
              )}

              {/* Divider between iterations (not after last) */}
              {idx < attempts.length - 1 && (
                <div className="border-t border-border pt-2" />
              )}
            </div>
          )
        })}

        {/* Spinner while waiting for next iteration render */}
        {waitingForNextRender && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            Generating next iteration...
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
