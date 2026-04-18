/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    exclude: ['onnxruntime-web'],  // Don't pre-bundle — has WASM deps
  },
  server: {
    port: 3000,
    proxy: {
      '/ws': { target: 'ws://localhost:8080', ws: true },
      '/api/rounds': 'http://localhost:8082',
      '/api': 'http://localhost:8000',
    },
  },
  preview: { port: 3000 },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    css: true,
  },
})
