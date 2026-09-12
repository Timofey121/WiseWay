// React-хук bootstrap-проверки сессии.
//
// Монтирует store, запускает проверку `GET /session` и отдаёт снимок состояния
// вместе с явными действиями `retry`/`completeLogin`. Дополнительно хук
// устанавливает единый lifecycle-контекст сессии:
//
// - подписка `onUnauthorized` сбрасывает приватное состояние при
//   `401 UNAUTHENTICATED` (CSRF/idempotency/polls уже очищены транспортом);
// - переход сессии в `anonymous` после logout/401 отменяет поздние ответы
//   bootstrap-проверки и переводит снимок в `anonymous`, поэтому auth-гейт
//   показывает вход реактивно, без перезагрузки страницы.
//
// Хук не хранит пароль и не персистит состояние.

import { useEffect, useMemo, useSyncExternalStore } from 'react'

import type { WiseWayApiClient } from '@/api/transport'
import { getSessionStatus, subscribeSessionStatus } from '@/app/session-state'

import { installUnauthorizedReset } from './auth-lifecycle'
import {
  createSessionBootstrapStore,
  type SessionBootstrapSnapshot,
} from './session-bootstrap-store'
import type { Session } from './auth-api'

/** Значение хука bootstrap-проверки сессии. */
export interface UseSessionBootstrapResult {
  readonly snapshot: SessionBootstrapSnapshot
  readonly retry: () => void
  readonly completeLogin: (session: Session) => void
  readonly completeLogout: () => void
}

/** Запускает и отслеживает bootstrap-проверку сессии для переданного клиента. */
export function useSessionBootstrap(
  client: WiseWayApiClient,
): UseSessionBootstrapResult {
  const store = useMemo(() => createSessionBootstrapStore(client), [client])

  useEffect(() => {
    store.start()
    // `emitUnauthorized()` уже очистил CSRF/idempotency/polls; слушатель
    // добавляет только сброс приватного состояния.
    const unsubscribeUnauthorized = installUnauthorizedReset()
    // Реактивный переход authenticated → anonymous (logout/401/смена
    // пользователя) фиксирует снимок и отменяет поздний bootstrap-ответ.
    const unsubscribeSession = subscribeSessionStatus(() => {
      if (
        getSessionStatus() === 'anonymous' &&
        store.getSnapshot().status === 'authenticated'
      ) {
        store.completeLogout()
      }
    })
    return () => {
      unsubscribeSession()
      unsubscribeUnauthorized()
      store.stop()
    }
  }, [store])

  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot,
  )

  return {
    snapshot,
    retry: store.retry,
    completeLogin: store.completeLogin,
    completeLogout: store.completeLogout,
  }
}
