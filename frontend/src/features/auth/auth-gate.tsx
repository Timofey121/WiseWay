// Композиция auth-гейта: bootstrap-проверка сессии и выбор экрана.
//
// До ответа `GET /session` показывается русская загрузка; при `anonymous` —
// экран входа; при недоступности — безопасное сообщение и повтор; только при
// `authenticated` монтируется защищённая оболочка `AppShell`. Гейт не
// показывает вход при сетевой ошибке и не считает её выходом из сессии.
//
// Переход authenticated → anonymous (logout, `401 UNAUTHENTICATED`, блокировка,
// смена пользователя) происходит реактивно: гейт подписан на `session-state`,
// поэтому экран входа показывается без полной перезагрузки страницы.

import type { WiseWayApiClient } from '@/api/transport'
import { AppShell } from '@/app/index'
import { useSessionStatus } from '@/app/use-session'

import { LoginScreen } from './login-screen'
import { LogoutControl } from './logout-control'
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
  const sessionStatus = useSessionStatus()

  if (snapshot.status === 'checking') {
    return <SessionCheckingScreen />
  }

  if (snapshot.status === 'unavailable') {
    return <SessionUnavailableScreen error={snapshot.error} onRetry={retry} />
  }

  if (snapshot.status === 'anonymous' || sessionStatus === 'anonymous') {
    return <LoginScreen client={client} onAuthenticated={completeLogin} />
  }

  return <AppShell headerActions={<LogoutControl client={client} />} />
}
