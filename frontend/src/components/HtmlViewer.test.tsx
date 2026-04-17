import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { HtmlViewer } from './HtmlViewer'

describe('HtmlViewer', () => {
  it('varsayılan olarak Rendered gösterir ve Raw sekmesine geçebilir', () => {
    render(<HtmlViewer html={'<div><h1>Merhaba</h1><img src="demo.png" /></div>'} />)

    const iframe = screen.getByTitle('HTML Preview') as HTMLIFrameElement
    expect(iframe.srcdoc).toContain('/v1/assets/demo.png')

    fireEvent.click(screen.getByRole('button', { name: 'Raw' }))
    expect(screen.getByText(/<h1>Merhaba<\/h1>/)).toBeInTheDocument()
  })
})
