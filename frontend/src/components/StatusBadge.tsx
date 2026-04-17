interface StatusBadgeProps {
  status: string
}

type Tone = 'ok' | 'fail' | 'running' | 'unknown'

const toneClasses: Record<Tone, string> = {
  ok: 'bg-green-100 text-green-700 border border-green-200',
  fail: 'bg-red-100 text-red-700 border border-red-200',
  running: 'bg-blue-100 text-blue-700 border border-blue-200',
  unknown: 'bg-gray-100 text-gray-600 border border-gray-200',
}

function normalize(status: string): Tone {
  const token = status.toLowerCase()
  if (token === 'success' || token === 'pass') return 'ok'
  if (token === 'failed' || token === 'fail') return 'fail'
  if (token === 'running') return 'running'
  return 'unknown'
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const tone = normalize(status)
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold ${toneClasses[tone]}`}>
      {tone === 'running' && (
        <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
      )}
      {status}
    </span>
  )
}
