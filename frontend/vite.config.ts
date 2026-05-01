import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const v1Proxy = {
  '/v1': {
    target: process.env.BACKEND_URL ?? 'http://127.0.0.1:8000',
    changeOrigin: false,
    // Keep connections alive for SSE (text/event-stream) streams
    configure: (proxy: any) => {
      proxy.on('proxyReq', (proxyReq: any, req: any) => {
        if (req.url?.startsWith('/v1/logs/stream')) {
          proxyReq.setHeader('connection', 'keep-alive')
        }
      })
    },
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: v1Proxy },
  preview: { proxy: v1Proxy },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
  },
})
