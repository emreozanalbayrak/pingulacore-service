import { useMemo, useRef, type KeyboardEvent, type ChangeEvent } from 'react'

interface JsonEditorProps {
  label?: string
  value: string
  onChange: (next: string) => void
  rows?: number
  placeholder?: string
}

export function JsonEditor({ label, value, onChange, rows = 8, placeholder }: JsonEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const isValid = useMemo(() => {
    if (!value.trim()) return false
    try {
      JSON.parse(value)
      return true
    } catch {
      return false
    }
  }, [value])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const textarea = e.currentTarget
    const { selectionStart, selectionEnd } = textarea
    const current = textarea.value

    if (e.key === 'Tab') {
      e.preventDefault()
      const next = current.substring(0, selectionStart) + '  ' + current.substring(selectionEnd)
      onChange(next)
      setTimeout(() => {
        textarea.selectionStart = textarea.selectionEnd = selectionStart + 2
      }, 0)
      return
    }

    if (e.key === 'Enter') {
      e.preventDefault()
      const beforeCursor = current.substring(0, selectionStart)
      const afterCursor = current.substring(selectionEnd)
      const lineStart = beforeCursor.lastIndexOf('\n') + 1
      const currentLine = beforeCursor.substring(lineStart)
      const indentMatch = currentLine.match(/^(\s*)/)
      const indent = indentMatch ? indentMatch[1] : ''
      const charBefore = beforeCursor.charAt(selectionStart - 1)
      const charAfter = afterCursor.charAt(0)

      if ((charBefore === '{' || charBefore === '[') && (charAfter === '}' || charAfter === ']')) {
        const next = beforeCursor + '\n' + indent + '  ' + '\n' + indent + afterCursor
        onChange(next)
        setTimeout(() => {
          textarea.selectionStart = textarea.selectionEnd = selectionStart + indent.length + 3
        }, 0)
      } else if (charBefore === '{' || charBefore === '[' || charBefore === ',') {
        const next = beforeCursor + '\n' + indent + '  ' + afterCursor
        onChange(next)
        setTimeout(() => {
          textarea.selectionStart = textarea.selectionEnd = selectionStart + indent.length + 3
        }, 0)
      } else {
        const next = beforeCursor + '\n' + indent + afterCursor
        onChange(next)
        setTimeout(() => {
          textarea.selectionStart = textarea.selectionEnd = selectionStart + indent.length + 1
        }, 0)
      }
      return
    }

    const pairs: Record<string, string> = { '{': '}', '[': ']', '"': '"' }
    if (pairs[e.key] && selectionStart === selectionEnd) {
      const charAfter = current.charAt(selectionEnd)
      if ((e.key === '"') && charAfter === '"') return
      if (/[a-zA-Z0-9]/.test(charAfter)) return
      e.preventDefault()
      const closing = pairs[e.key]
      const next = current.substring(0, selectionStart) + e.key + closing + current.substring(selectionEnd)
      onChange(next)
      setTimeout(() => {
        textarea.selectionStart = textarea.selectionEnd = selectionStart + 1
      }, 0)
    }

    const closing = ['}', ']', '"']
    if (closing.includes(e.key) && selectionStart === selectionEnd) {
      if (current.charAt(selectionEnd) === e.key) {
        e.preventDefault()
        textarea.selectionStart = textarea.selectionEnd = selectionStart + 1
      }
    }
  }

  return (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-sm font-medium text-foreground">{label}</label>
      )}
      <textarea
        ref={textareaRef}
        value={value}
        rows={rows}
        spellCheck={false}
        placeholder={placeholder}
        onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        className="w-full px-4 py-3 rounded-xl border-2 border-border bg-white focus:border-primary focus:outline-none transition-colors font-mono text-sm resize-none"
        style={{ borderColor: 'var(--border)' }}
      />
      <span className={`text-xs font-medium ${isValid ? 'text-green-600' : 'text-amber-600'}`}>
        {isValid ? '✓ Geçerli JSON' : '⚠ JSON doğrulanamadı'}
      </span>
    </div>
  )
}
