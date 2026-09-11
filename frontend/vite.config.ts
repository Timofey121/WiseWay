import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Единый конфиг Vite и Vitest. Alias-и и `server.fs.allow` разрешают импорт
// JSON из `fixtures/synthetic/**` и `contracts/examples/**` за пределами
// `frontend/` и в dev-сервере, и в production build, и в Vitest (WP-06/WP-07).
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@fixtures': fileURLToPath(new URL('../fixtures', import.meta.url)),
      '@examples': fileURLToPath(
        new URL('../contracts/examples', import.meta.url),
      ),
    },
  },
  server: {
    fs: {
      allow: [
        fileURLToPath(new URL('.', import.meta.url)),
        fileURLToPath(new URL('..', import.meta.url)),
      ],
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    setupFiles: ['./tests/setup.ts'],
  },
})
