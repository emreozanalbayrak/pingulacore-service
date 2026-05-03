import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  size?: 'default' | 'wide' | 'full'
}

export function Modal({ open, onClose, title, children, size = 'default' }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  if (!open) return null

  const sizeClass = size === 'full'
    ? 'w-[95vw] h-[92vh]'
    : size === 'wide'
      ? 'w-[860px] max-h-[84vh]'
      : 'w-[640px] max-h-[80vh]'

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className={`relative z-[51] ${sizeClass} bg-card rounded-2xl border border-border shadow-2xl flex flex-col overflow-hidden`}>
        {title && (
          <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0"
            style={{ background: 'linear-gradient(to right, color-mix(in srgb, var(--accent) 40%, transparent), color-mix(in srgb, var(--muted) 40%, transparent))' }}>
            <h2 className="text-sm font-semibold text-foreground">{title}</h2>
            <button type="button" onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-black/10 transition-colors text-foreground/70 hover:text-foreground">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}
        <div className="flex-1 min-h-0 overflow-auto">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
