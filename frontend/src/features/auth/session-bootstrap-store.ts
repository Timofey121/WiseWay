// In-memory store bootstrap-проверки сессии при старте приложения.
//
// При первом монтировании приложения store вызывает `GET /session` ДО показа
// защищённой оболочки и различает четыре состояния:
// - `checking` — запрос проверки сессии в полёте (показывается русская загрузка);
// - `anonymous` — сервер ответил 401 `UNAUTHENTICATED`: показывается вход;
// - `authenticated` — сервер вернул `Session`: actor/`expires_at` сохраняются в
//   `session-state`, CSRF-токен — в `session-context`, показывается оболочка;
// - `unavailable` — сетевой сбой или 5xx/иная ошибка: безопасное русское
//   сообщение и повтор. Это НЕ анонимное состояние и НЕ ложный logout.
//
// Store не хранит пароль и не персистит ничего в URL/history/storage/cookie.
// Поздний ответ устаревшего запроса отбрасывается по счётчику `sequence`.
// Успешный вход (`completeLogin`) фиксирует ту же серверную сессию, что и
// bootstrap, поэтому отдельного доверенного источника actor не появляется.

import { setCsrfToken } from '@/api/session-context'
import { toTransportError, type WiseWayApiClient } from '@/api/transport'
import {
  markAnonymous,
  markAuthenticated,
  type AuthenticatedSession,
} from '@/app/session-state'

import { fetchActiveSession, type Session } from './auth-api'

/** Состояние bootstrap-проверки сессии. */
export type SessionBootstrapStatus =
  | 'checking'
  | 'anonymous'
  | 'authenticated'
  | 'unavailable'

/** Безопасная ошибка bootstrap-проверки без тел/секретов. */
export interface SessionBootstrapError {
  readonly code: string
  readonly message: string
  readonly requestId: string | null
  readonly operationId: string | null
  readonly retryable: boolean
}

/** Неизменяемый снимок состояния store. */
export interface SessionBootstrapSnapshot {
  readonly status: SessionBootstrapStatus
  readonly error: SessionBootstrapError | null
}

/** Контракт store bootstrap-проверки сессии. */
export interface SessionBootstrapStore {
  /** Подписка на изменение снимка (для `useSyncExternalStore`). */
  subscribe: (listener: () => void) => () => void
  /** Текущий неизменяемый снимок. */
  getSnapshot: () => SessionBootstrapSnapshot
  /** Запускает однократную проверку сессии; идемпотентно. */
  start: () => void
  /** Прекращает слежение; идемпотентно. Поздний ответ отбрасывается. */
  stop: () => void
  /** Явная повторная проверка после состояния `unavailable`. */
  retry: () => void
  /** Фиксирует успешный вход: CSRF и серверный actor/`expires_at`. */
  completeLogin: (session: Session) => void
  /**
   * Фиксирует завершение сессии (logout/`401 UNAUTHENTICATED`): переводит
   * снимок в `anonymous` и отменяет поздний ответ устаревшей bootstrap-проверки
   * по счётчику `sequence`. Повторная очистка CSRF/idempotency/polls не
   * выполняется — это делает `auth-lifecycle`/`session-context`.
   */
  completeLogout: () => void
}

const CHECKING_SNAPSHOT: SessionBootstrapSnapshot = {
  status: 'checking',
  error: null,
}

const ANONYMOUS_SNAPSHOT: SessionBootstrapSnapshot = {
  status: 'anonymous',
  error: null,
}

const AUTHENTICATED_SNAPSHOT: SessionBootstrapSnapshot = {
  status: 'authenticated',
  error: null,
}

/**
 * Создаёт store bootstrap-проверки сессии поверх переданного API-клиента.
 * Store не выполняет запросов до `start()`.
 */
export function createSessionBootstrapStore(
  client: WiseWayApiClient,
): SessionBootstrapStore {
  const listeners = new Set<() => void>()
  let snapshot: SessionBootstrapSnapshot = CHECKING_SNAPSHOT
  let sequence = 0
  let started = false

  const update = (next: SessionBootstrapSnapshot): void => {
    snapshot = next
    for (const listener of [...listeners]) {
      listener()
    }
  }

  // Единая точка фиксации серверной сессии: CSRF уходит в session-context,
  // actor/expires_at — в session-state. Токен в session-state не дублируется.
  const applySession = (session: Session): void => {
    setCsrfToken(session.csrf_token)
    const authenticated: AuthenticatedSession = {
      actor: session.actor,
      expires_at: session.expires_at,
    }
    markAuthenticated(authenticated)
    update(AUTHENTICATED_SNAPSHOT)
  }

  const check = async (request: number): Promise<void> => {
    try {
      const session = await fetchActiveSession(client)
      if (sequence !== request) {
        return
      }
      applySession(session)
    } catch (error) {
      if (sequence !== request) {
        return
      }
      const transportError = toTransportError(error)
      // Только подтверждённый `401 UNAUTHENTICATED` означает анонимную сессию.
      // Любая другая ошибка (сеть/5xx/403/нечитаемый код) — недоступность, а не
      // ложный logout.
      if (
        transportError.status === 401 &&
        transportError.code === 'UNAUTHENTICATED'
      ) {
        markAnonymous()
        update(ANONYMOUS_SNAPSHOT)
        return
      }
      update({
        status: 'unavailable',
        error: {
          code: transportError.code,
          message: transportError.message,
          requestId: transportError.requestId,
          operationId: transportError.operationId,
          retryable: transportError.retryable,
        },
      })
    }
  }

  const beginCheck = (): void => {
    sequence += 1
    const request = sequence
    update(CHECKING_SNAPSHOT)
    void check(request)
  }

  return {
    subscribe(listener) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    getSnapshot() {
      return snapshot
    },
    start() {
      if (started) {
        return
      }
      started = true
      beginCheck()
    },
    stop() {
      if (!started) {
        return
      }
      started = false
      // Поздний ответ после остановки не должен менять снимок/сессию.
      sequence += 1
    },
    retry() {
      started = true
      beginCheck()
    },
    completeLogin(session) {
      // Отменяет возможный поздний ответ bootstrap-проверки.
      sequence += 1
      started = true
      applySession(session)
    },
    completeLogout() {
      // Поздний ответ прежней сессии (например, ещё летящий `GET /session`)
      // не должен вернуть пользователя в authenticated.
      sequence += 1
      started = true
      // Сначала фиксируем снимок, затем состояние сессии: подписчик
      // session-state увидит уже `anonymous`-снимок и не вызовет повтор.
      update(ANONYMOUS_SNAPSHOT)
      markAnonymous()
    },
  }
}
