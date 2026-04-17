import { useMemo, useState } from 'react'
import {
  BookOpen,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Copy,
  Image as ImageIcon,
  Type,
  Users,
  XCircle,
} from 'lucide-react'

interface Props {
  data: unknown
  title?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function asText(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

export function QuestionOutputDisplay({ data, title = 'Question Output' }: Props) {
  const [showRawJson, setShowRawJson] = useState(false)
  const [copied, setCopied] = useState(false)

  const rawJson = useMemo(() => JSON.stringify(data ?? {}, null, 2), [data])
  const question = isRecord(data) ? data : null

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(rawJson)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  if (!question) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-base">{title}</h3>
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="px-4 py-2 rounded-lg bg-muted border border-border hover:border-primary hover:bg-accent transition-all duration-200 flex items-center gap-2"
          >
            <Copy className="w-4 h-4" />
            <span className="text-sm">{copied ? 'Kopyalandı!' : 'Kopyala'}</span>
          </button>
        </div>
        <div className="bg-white/50 rounded-xl border-2 border-border p-4">
          <pre className="text-sm text-muted-foreground whitespace-pre-wrap font-mono">
            {rawJson}
          </pre>
        </div>
      </div>
    )
  }

  const scenario = isRecord(question.scenario) ? question.scenario : null
  const entities = asArray(scenario?.entities)
  const characters = asArray(scenario?.characters)
  const scenes = asArray(scenario?.scenes)
  const options = asArray(question.options)
  const solution = asArray(question.solution)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-base">{title}</h3>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setShowRawJson((v) => !v)}
            className="px-4 py-2 rounded-lg bg-white border border-border hover:border-primary transition-all duration-200 flex items-center gap-2"
          >
            {showRawJson ? <ChevronRight className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            <span className="text-sm">Raw JSON</span>
          </button>
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="px-4 py-2 rounded-lg bg-muted border border-border hover:border-primary hover:bg-accent transition-all duration-200 flex items-center gap-2"
          >
            <Copy className="w-4 h-4" />
            <span className="text-sm">{copied ? 'Kopyalandı!' : 'Kopyala'}</span>
          </button>
        </div>
      </div>

      {showRawJson && (
        <div className="bg-white/50 rounded-xl border-2 border-border p-4">
          <pre className="text-sm text-muted-foreground whitespace-pre-wrap font-mono">
            {rawJson}
          </pre>
        </div>
      )}

      {!showRawJson && (
        <div className="bg-gradient-to-br from-white to-accent/20 rounded-xl border-2 border-border overflow-hidden">
          <div className="bg-gradient-to-r from-primary/10 to-secondary/10 px-6 py-4 border-b border-border">
            <div className="flex items-start justify-between">
              <div>
                <h4 className="text-lg mb-1" style={{ fontFamily: 'var(--font-display)' }}>
                  {asText(question.question_id) || 'N/A'}
                </h4>
                <div className="flex gap-3 text-xs">
                  <span className="px-2 py-1 rounded bg-primary/20 text-primary">
                    Grade {asText(question.grade) || 'N/A'}
                  </span>
                  <span className="px-2 py-1 rounded bg-secondary/20 text-secondary capitalize">
                    {asText(question.difficulty) || 'N/A'}
                  </span>
                  <span className="px-2 py-1 rounded bg-muted text-muted-foreground">
                    {asText(question.schema_version) || 'N/A'}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="p-6 space-y-6">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <BookOpen className="w-4 h-4 text-primary" />
                <h5 className="text-sm text-foreground">Question Stem</h5>
              </div>
              <p className="text-sm bg-white/50 rounded-lg p-3 border border-border">
                {asText(question.stem) || 'N/A'}
              </p>
            </div>

            {scenario && (
              <div>
                <h5 className="text-sm text-foreground mb-2">Scenario</h5>
                <div className="bg-white/50 rounded-lg p-4 border border-border space-y-3">
                  {asText(scenario.story) && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Story</p>
                      <p className="text-sm">{asText(scenario.story)}</p>
                    </div>
                  )}

                  {entities.length > 0 && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-2">Entities</p>
                      <div className="space-y-2">
                        {entities.map((entity, idx) => {
                          const item = isRecord(entity) ? entity : {}
                          return (
                            <div key={idx} className="flex items-start gap-2 text-sm bg-accent/30 rounded p-2">
                              <ImageIcon className="w-4 h-4 text-primary mt-0.5" />
                              <div>
                                <span className="font-medium">{asText(item.name)}</span>
                                {asText(item.quantity) && <span className="text-muted-foreground"> (×{asText(item.quantity)})</span>}
                                {asText(item.description) && (
                                  <p className="text-xs text-muted-foreground">{asText(item.description)}</p>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {characters.length > 0 && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-2">Characters</p>
                      <div className="space-y-2">
                        {characters.map((char, idx) => {
                          const item = isRecord(char) ? char : {}
                          return (
                            <div key={idx} className="flex items-start gap-2 text-sm bg-accent/30 rounded p-2">
                              <Users className="w-4 h-4 text-primary mt-0.5" />
                              <div>
                                <span className="font-medium">{asText(item.name)}</span>
                                {asText(item.description) && (
                                  <p className="text-xs text-muted-foreground">{asText(item.description)}</p>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {scenes.length > 0 && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-2">Scenes</p>
                      <div className="space-y-2">
                        {scenes.map((scene, idx) => {
                          const item = isRecord(scene) ? scene : {}
                          const enabled = Boolean(item.enabled)
                          return (
                            <div key={idx} className="text-sm bg-accent/30 rounded p-2">
                              <div className="flex items-center gap-2 mb-1">
                                <span className={`w-2 h-2 rounded-full ${enabled ? 'bg-green-500' : 'bg-gray-400'}`} />
                                <span className="text-xs text-muted-foreground">
                                  {enabled ? 'Enabled' : 'Disabled'}
                                </span>
                              </div>
                              {asText(item.description_prompt) && (
                                <p className="text-xs text-muted-foreground">{asText(item.description_prompt)}</p>
                              )}
                              {asText(item.color_scheme) && (
                                <p className="text-xs text-muted-foreground">Color: {asText(item.color_scheme)}</p>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {options.length > 0 && (
              <div>
                <h5 className="text-sm text-foreground mb-2">Options</h5>
                <div className="space-y-2">
                  {options.map((option, idx) => {
                    const item = isRecord(option) ? option : {}
                    const modality = asText(item.modality)
                    const isCorrect = Boolean(item.is_correct)
                    return (
                      <div
                        key={idx}
                        className={`rounded-lg p-3 border-2 ${
                          isCorrect ? 'bg-green-50 border-green-300' : 'bg-white/50 border-border'
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <div className="flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-white border-2 border-primary flex items-center justify-center text-sm">
                              {asText(item.label)}
                            </span>
                            {isCorrect ? (
                              <CheckCircle className="w-4 h-4 text-green-600" />
                            ) : (
                              <XCircle className="w-4 h-4 text-muted-foreground" />
                            )}
                          </div>

                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1">
                              {modality === 'text' ? (
                                <Type className="w-4 h-4 text-muted-foreground" />
                              ) : (
                                <ImageIcon className="w-4 h-4 text-muted-foreground" />
                              )}
                              <span className="text-xs text-muted-foreground capitalize">{modality || 'unknown'}</span>
                            </div>

                            {modality === 'text' ? (
                              <p className="text-sm">{asText(item.content)}</p>
                            ) : (
                              <div className="space-y-1">
                                {asArray(item.content).map((entity, eidx) => {
                                  const e = isRecord(entity) ? entity : {}
                                  return (
                                    <div key={eidx} className="text-xs bg-accent/30 rounded p-2">
                                      <span className="font-medium">{asText(e.name)}</span>
                                      {asText(e.quantity) && <span className="text-muted-foreground"> (×{asText(e.quantity)})</span>}
                                    </div>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {solution.length > 0 && (
              <div>
                <h5 className="text-sm text-foreground mb-2">Solution</h5>
                <div className="bg-blue-50 rounded-lg p-3 border border-blue-200">
                  {solution.map((step, idx) => (
                    <p key={idx} className="text-sm text-blue-900">
                      {idx + 1}. {asText(step)}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
