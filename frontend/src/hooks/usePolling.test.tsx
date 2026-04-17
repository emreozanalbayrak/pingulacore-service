import { act, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { usePolling } from './usePolling'

function Probe() {
  const [count, setCount] = useState(0)
  usePolling(() => setCount((prev) => prev + 1), true, 200)
  return <div>{count}</div>
}

describe('usePolling', () => {
  it('enabled iken periyodik çağrı yapar', () => {
    vi.useFakeTimers()
    render(<Probe />)

    act(() => {
      vi.advanceTimersByTime(650)
    })
    expect(screen.getByText('3')).toBeInTheDocument()

    vi.useRealTimers()
  })
})
