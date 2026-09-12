// React-хуки чтения in-memory состояния сессии.
//
// Вынесены из `session-state.ts`, чтобы Fast Refresh видел файлы с состоянием и
// с хуками раздельно, и чтобы UI-компоненты не подписывались на контейнер вручную.

import { useSyncExternalStore } from 'react'

import {
  getAuthenticatedSession,
  getSessionStatus,
  subscribeSessionStatus,
  type AuthenticatedSession,
  type SessionStatus,
} from './session-state'

/**
 * Возвращает аутентифицированную сессию (`actor`/`expires_at`) или `null`.
 * Ссылка стабильна до изменения сессии, поэтому хук безопасен для
 * `useSyncExternalStore`.
 */
export function useAuthenticatedSession(): AuthenticatedSession | null {
  return useSyncExternalStore(
    subscribeSessionStatus,
    getAuthenticatedSession,
    getAuthenticatedSession,
  )
}

/**
 * Возвращает `anonymous | authenticated`. Нужен auth-гейту, чтобы реактивно
 * переключаться на экран входа при logout/`401 UNAUTHENTICATED`/смене
 * пользователя без перезагрузки страницы.
 */
export function useSessionStatus(): SessionStatus {
  return useSyncExternalStore(
    subscribeSessionStatus,
    getSessionStatus,
    getSessionStatus,
  )
}
