import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ['dashboard.pradnyasiwi.web.id'],
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true,
      },
      '/docs': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true,
      },
      '/openapi.json': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true,
      },
    },
  },
})
