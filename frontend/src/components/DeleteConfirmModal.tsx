import { AlertTriangle } from 'lucide-react'

import { Modal } from './Modal'

interface DeleteConfirmModalProps {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  busy?: boolean
  onClose: () => void
  onConfirm: () => void | Promise<void>
}

export function DeleteConfirmModal({
  open,
  title,
  message,
  confirmLabel = 'Sil',
  busy = false,
  onClose,
  onConfirm,
}: DeleteConfirmModalProps) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="space-y-5 p-6">
        <div className="flex items-start gap-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-4 text-red-700">
          <div className="rounded-xl bg-white p-2 shadow-sm">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div>
            <p className="text-sm font-medium">Bu işlem geri alınamaz.</p>
            <p className="mt-1 text-sm leading-6">{message}</p>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-foreground hover:bg-accent"
          >
            Vazgeç
          </button>
          <button
            type="button"
            onClick={() => void onConfirm()}
            disabled={busy}
            className="rounded-xl bg-destructive px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:opacity-95 disabled:opacity-50"
          >
            {busy ? 'Siliniyor...' : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}
