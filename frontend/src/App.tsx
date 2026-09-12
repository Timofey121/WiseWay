import { useMemo } from 'react'

import { AppConfigProvider, createAppApiClient } from './app/index'
import { AuthGate } from './features/auth/index'

export default function App() {
  // Единственное место создания app-level транспорта: режим real/mock
  // выбирается по `VITE_API_MODE` внутри `createAppApiClient()`.
  const api = useMemo(() => createAppApiClient(), [])

  return (
    <AppConfigProvider client={api}>
      <AuthGate client={api} />
    </AppConfigProvider>
  )
}
