// Композиция auth-гейта: bootstrap-проверка сессии и выбор экрана.
//
// До ответа `GET /session` показывается русская загрузка; при `anonymous` —
// экран входа; при недоступности — безопасное сообщение и повтор; только при
// `authenticated` монтируется защищённая оболочка `AppShell`. Гейт не
// показывает вход при сетевой ошибке и не считает её выходом из сессии.

import type { WiseWayApiClient } from '@/api/transport'
import { AppShell } from '@/app/index'

import { LoginScreen } from './login-screen'
import {
  SessionCheckingScreen,
  SessionUnavailableScreen,
} from './session-states'
import { useSessionBootstrap } from './use-session-bootstrap'

export interface AuthGateProps {
  readonly client: WiseWayApiClient
}

export function AuthGate({ client }: AuthGateProps) {
  const { snapshot, retry, completeLogin } = useSessionBootstrap(client)

  if (snapshot.status === 'checking') {
    return <SessionCheckingScreen />
  }

  if (snapshot.status === 'unavailable') {
    return <SessionUnavailableScreen error={snapshot.error} onRetry={retry} />
  }

  if (snapshot.status === 'anonymous') {
    return <LoginScreen client={client} onAuthenticated={completeLogin} />
  }

  return <AppShell />
}
