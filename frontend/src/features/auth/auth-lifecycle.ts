// Завершение клиентского контекста сессии (AUTH-03, API §2/§11, FE §4).
//
// Модуль сводит в одну точку две операции, которые обязаны происходить вместе
// при logout, истечении сессии, блокировке пользователя и смене пользователя:
//
// 1. `clearSession()` (`@/api/session-context`) освобождает CSRF-токен,
//    ожидающие `Idempotency-Key` и single-flight poll-реестр;
// 2. `resetPrivateState()` (`@/app/private-state-registry`) возвращает в
//    исходное состояние все зарегистрированные приватные состояния, включая
//    `session-state` (actor/`expires_at` → anonymous).
//
// Здесь нет повторной реализации очистки CSRF/idempotency/polls: это ровно
// существующий `clearSession()`. Никаких сетевых запросов, cookie, storage,
// URL или history state модуль не трогает.
//
// `onUnauthorized` вызывается транспортом только для `401 UNAUTHENTICATED`;
// `emitUnauthorized()` уже выполнил `clearSession()`, поэтому слушатель
// добавляет только сброс приватного состояния и не дублирует очистку сессии.

import { clearSession, onUnauthorized } from '@/api/session-context'
import { resetPrivateState } from '@/app/private-state-registry'
import { markAnonymous } from '@/app/session-state'

/**
 * Завершает клиентскую сессию: очищает CSRF/idempotency/polls, помечает сессию
 * анонимной и сбрасывает всё зарегистрированное приватное состояние. Вызывается
 * после подтверждённого logout (204) или `401 UNAUTHENTICATED`.
 */
export function endAuthenticatedSession(): void {
  clearSession()
  markAnonymous()
  resetPrivateState()
}

/**
 * Подписывает сброс приватного состояния на сигнал `401 UNAUTHENTICATED`.
 *
 * `emitUnauthorized()` уже очистил CSRF/idempotency/polls через
 * `clearSession()`, поэтому здесь повторно вызывается только
 * `resetPrivateState()`.
 *
 * @returns функция отписки.
 */
export function installUnauthorizedReset(): () => void {
  return onUnauthorized(() => {
    resetPrivateState()
  })
}
