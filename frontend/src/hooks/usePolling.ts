import { useEffect, useRef } from 'react'

export function usePolling(task: () => Promise<void> | void, enabled: boolean, intervalMs: number): void {
  const stableTask = useRef(task)
  stableTask.current = task

  useEffect(() => {
    if (!enabled) {
      return
    }

    const timer = window.setInterval(() => {
      void stableTask.current()
    }, intervalMs)

    return () => {
      window.clearInterval(timer)
    }
  }, [enabled, intervalMs])
}
