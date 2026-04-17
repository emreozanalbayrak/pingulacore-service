import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
        // Keep connections alive for SSE (text/event-stream) streams
        configure: (proxy) => {
          proxy.on('proxyReq', (_proxyReq, req) => {
            if (req.url?.startsWith('/v1/logs/stream')) {
              _proxyReq.setHeader('connection', 'keep-alive')
            }
          })
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
  },
})
