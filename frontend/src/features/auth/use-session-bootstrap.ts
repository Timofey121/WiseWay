// React-хук bootstrap-проверки сессии.
//
// Монтирует store, запускает проверку `GET /session` и отдаёт снимок состояния
// вместе с явными действиями `retry`/`completeLogin`. Хук не хранит пароль и
// не персистит состояние.

import { useEffect, useMemo, useSyncExternalStore } from 'react'

import type { WiseWayApiClient } from '@/api/transport'

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
}

/** Запускает и отслеживает bootstrap-проверку сессии для переданного клиента. */
export function useSessionBootstrap(
  client: WiseWayApiClient,
): UseSessionBootstrapResult {
  const store = useMemo(() => createSessionBootstrapStore(client), [client])

  useEffect(() => {
    store.start()
    return () => {
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
  }
}
