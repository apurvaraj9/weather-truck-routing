import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the Django API runs on :8000; Vite forwards /api calls to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
