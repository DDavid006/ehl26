import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api is proxied to the Flask app so the real endpoint can be used from `npm run dev`.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },
})
