// Логика выхода из системы (AUTH-03, API §2/§3).
//
// `POST /auth/logout` — неидемпотентная мутация без `Idempotency-Key`, поэтому
// generic retry-политика её никогда не повторяет. При неизвестном исходе
// (сетевой сбой/таймаут/5xx) клиент НЕ считает выход ни успешным, ни
// провалившимся: он перечитывает `GET /session` и различает три состояния:
//
// - `logged_out` — сервер подтвердил завершение (204) или сессия уже
//   недействительна (`401 UNAUTHENTICATED`);
// - `still_authenticated` — `GET /session` вернул активную сессию: выход не
//   состоялся, сессия сохраняется, нужен явный повтор;
// - `unknown` — `GET /session` тоже не дал ответа: успех не заявляется,
//   сессия сохраняется, нужен явный повтор.
//
// Функция не выполняет очистку сама: побочные эффекты завершённой сессии
// применяет вызывающий слой (`auth-lifecycle`).

import {
  toTransportError,
  type TransportError,
  type WiseWayApiClient,
} from '@/api/transport'

import { fetchActiveSession, submitLogout } from './auth-api'

/** Итог попытки выхода. */
export type LogoutResultStatus =
  | 'logged_out'
  | 'still_authenticated'
  | 'unknown'

/** Результат попытки выхода с безопасной причиной для повтора. */
export interface LogoutResult {
  readonly status: LogoutResultStatus
  /** Безопасная ошибка исходного logout-запроса либо `null` при 204. */
  readonly error: TransportError | null
}

/** Подтверждённый `401 UNAUTHENTICATED` (сессия уже недействительна). */
function isUnauthenticated(error: TransportError): boolean {
  return error.status === 401 && error.code === 'UNAUTHENTICATED'
}

/**
 * Пытается завершить сессию и при неизвестном исходе сверяет `GET /session`.
 *
 * `403`/`5xx`/сеть не превращаются в ложный успех: сессия остаётся, а
 * вызывающий слой показывает явный повтор. Автоматического повторного logout
 * нет — только одна попытка плюс одна проверка сессии.
 */
export async function performLogout(
  client: WiseWayApiClient,
): Promise<LogoutResult> {
  try {
    await submitLogout(client)
    return { status: 'logged_out', error: null }
  } catch (error) {
    const logoutError = toTransportError(error)
    if (isUnauthenticated(logoutError)) {
      // Сессия уже недействительна: транспорт очистил её и уведомил
      // подписчиков `onUnauthorized`.
      return { status: 'logged_out', error: logoutError }
    }
    return reconcileLogout(client, logoutError)
  }
}

/**
 * Разрешает неизвестный исход logout через чтение активной сессии.
 *
 * Если сессия активна — выход не состоялся (`still_authenticated`). Если
 * `GET /session` подтвердил `401 UNAUTHENTICATED` — выход состоялся
 * (`logged_out`). Иначе исход остаётся неизвестным (`unknown`), и успех не
 * заявляется.
 */
async function reconcileLogout(
  client: WiseWayApiClient,
  logoutError: TransportError,
): Promise<LogoutResult> {
  try {
    await fetchActiveSession(client)
    return { status: 'still_authenticated', error: logoutError }
  } catch (error) {
    const sessionError = toTransportError(error)
    if (isUnauthenticated(sessionError)) {
      return { status: 'logged_out', error: logoutError }
    }
    return { status: 'unknown', error: logoutError }
  }
}
