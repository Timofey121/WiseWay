// In-memory store загрузки `AppConfig` (`GET /app-config`).
//
// Store намеренно отделён от React-компонента: синхронизация с внешним API —
// это внешнее состояние, поэтому оно читается через `useSyncExternalStore`.
// Такая модель:
// - грузит конфигурацию ТОЛЬКО когда сессия аутентифицирована (анонимно — ноль
//   запросов и состояние `idle`, без ложного 401);
// - хранит честные состояния `idle`/`loading`/`ready`/`error`;
// - при ошибке не подставляет выдуманные пределы/пояс по умолчанию;
// - игнорирует поздний ответ устаревшего запроса (G-4) по счётчику `sequence`;
// - сбрасывается в `idle` при logout/401/смене пользователя, потому что
//   подписан на `session-state`, который сбрасывает `resetPrivateState()`.

import type { components } from '@/api/generated/schema'
import { toTransportError, type WiseWayApiClient } from '@/api/transport'

import {
  getSessionStatus,
  subscribeSessionStatus,
  type SessionStatus,
} from './session-state'

/** Публичный DTO конфигурации из единственного OAS. */
export type AppConfig = components['schemas']['AppConfig']

/** Состояние загрузки app-config. */
export type AppConfigStatus = 'idle' | 'loading' | 'ready' | 'error'

/** Безопасная ошибка загрузки app-config без тел/секретов. */
export interface AppConfigError {
  readonly code: string
  readonly message: string
  readonly requestId: string | null
  readonly operationId: string | null
  readonly retryable: boolean
}

/** Снимок состояния store. */
export interface AppConfigSnapshot {
  readonly status: AppConfigStatus
  readonly config: AppConfig | null
  readonly error: AppConfigError | null
}

/** Контракт store app-config. */
export interface AppConfigStore {
  /** Подписка на изменение снимка (для `useSyncExternalStore`). */
  subscribe: (listener: () => void) => () => void
  /** Текущий неизменяемый снимок. */
  getSnapshot: () => AppConfigSnapshot
  /** Начинает следить за сессией; идемпотентно. */
  start: () => void
  /** Прекращает слежение; идемпотентно. */
  stop: () => void
  /** Явная повторная загрузка (доступна только при активной сессии). */
  reload: () => void
}

const IDLE_SNAPSHOT: AppConfigSnapshot = {
  status: 'idle',
  config: null,
  error: null,
}

/**
 * Создаёт store загрузки app-config поверх переданного API-клиента. Store не
 * выполняет запросов до `start()`; `start()` синхронизируется с текущим
 * состоянием сессии.
 */
export function createAppConfigStore(client: WiseWayApiClient): AppConfigStore {
  const listeners = new Set<() => void>()
  let snapshot: AppConfigSnapshot = IDLE_SNAPSHOT
  let sequence = 0
  let sessionStatus: SessionStatus = 'anonymous'
  let synced = false
  let unsubscribeSession: (() => void) | null = null
  let started = false

  const update = (next: AppConfigSnapshot): void => {
    snapshot = next
    for (const listener of [...listeners]) {
      listener()
    }
  }

  const fetchConfig = async (request: number): Promise<void> => {
    try {
      const result = await client.GET('/app-config')
      if (sequence !== request) {
        return
      }
      if (result.error !== undefined || result.data === undefined) {
        update({
          status: 'error',
          config: null,
          error: toAppConfigError(result),
        })
        return
      }
      update({ status: 'ready', config: result.data, error: null })
    } catch (error) {
      if (sequence !== request) {
        return
      }
      update({ status: 'error', config: null, error: toAppConfigError(error) })
    }
  }

  const load = (): void => {
    sequence += 1
    const request = sequence
    update({ status: 'loading', config: null, error: null })
    void fetchConfig(request)
  }

  const syncSession = (): void => {
    const next = getSessionStatus()
    if (synced && next === sessionStatus) {
      return
    }
    sessionStatus = next
    synced = true
    if (next !== 'authenticated') {
      // Отменяет возможный поздний ответ и очищает конфигурацию предыдущего
      // пользователя.
      sequence += 1
      update(IDLE_SNAPSHOT)
      return
    }
    load()
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
      unsubscribeSession = subscribeSessionStatus(syncSession)
      syncSession()
    },
    stop() {
      if (!started) {
        return
      }
      started = false
      // Следующий `start()` обязан заново свериться с сессией, даже если её
      // состояние не менялось (повторный mount в StrictMode).
      synced = false
      unsubscribeSession?.()
      unsubscribeSession = null
      // Поздний ответ после остановки не должен менять снимок.
      sequence += 1
    },
    reload() {
      if (getSessionStatus() === 'authenticated') {
        load()
      }
    },
  }
}

function toAppConfigError(input: unknown): AppConfigError {
  const error = toTransportError(input)
  return {
    code: error.code,
    message: error.message,
    requestId: error.requestId,
    operationId: error.operationId,
    retryable: error.retryable,
  }
}
