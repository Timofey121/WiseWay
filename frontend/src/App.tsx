import { useMemo } from 'react'

import { AppConfigProvider, AppShell, createAppApiClient } from './app/index'

export default function App() {
  // Единственное место создания app-level транспорта: режим real/mock
  // выбирается по `VITE_API_MODE` внутри `createAppApiClient()`.
  const api = useMemo(() => createAppApiClient(), [])

  return (
    <AppConfigProvider client={api}>
      <AppShell />
    </AppConfigProvider>
  )
}
