import { defineConfig, devices } from '@playwright/test'

const PORT = 4173
// Явный IPv4-хост обязателен: `vite preview` по умолчанию слушает только
// loopback `::1` (IPv6), из-за чего probe Playwright по `127.0.0.1` получал
// connection refused. Привязка сервера и BASE_URL к одному хосту `127.0.0.1`
// делает проверку детерминированной в локальной среде и в CI.
const HOST = '127.0.0.1'
const BASE_URL = `http://${HOST}:${PORT}`

export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      // В текущей среде скачивание Chromium из CDN Playwright недоступно,
      // поэтому используется системный канал Microsoft Edge (Chromium-based).
      // См. README, раздел «Browser-тест и браузерный канал».
      name: 'msedge',
      use: { ...devices['Desktop Chrome'], channel: 'msedge' },
    },
  ],
  webServer: {
    command: `npm run preview -- --port ${PORT} --strictPort --host ${HOST}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
