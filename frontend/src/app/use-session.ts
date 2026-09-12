// React-хук чтения аутентифицированной сессии из in-memory контейнера.
//
// Вынесен из `session-state.ts`, чтобы Fast Refresh видел файлы с состоянием и
// с хуком раздельно, и чтобы UI-компоненты не подписывались на контейнер вручную.

import { useSyncExternalStore } from 'react'

import {
  getAuthenticatedSession,
  subscribeSessionStatus,
  type AuthenticatedSession,
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
