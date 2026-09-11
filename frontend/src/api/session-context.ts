// In-memory держатель состояния сессии на клиенте.
//
// CSRF-токен WiseWay живёт только в памяти вкладки: он не пишется в
// `localStorage`, `sessionStorage`, cookie, URL или history state. Cookie
// `wiseway_session` устанавливает и обслуживает сам браузер (HttpOnly), поэтому
// frontend её не читает и не хранит.
//
// Модуль намеренно не персистит токен: перезагрузка вкладки или новый вход
// начинают с чистого состояния, а `emitUnauthorized()` сигнализирует слоям
// приложения об очистке приватного состояния.
//
// Единая session-scope очистка включает и in-memory состояние идемпотентности:
// `clearSession()` освобождает ожидающие `Idempotency-Key` (publish/batch/
// return), чтобы logout/401/смена пользователя не оставляли чужой контекст.

import { defaultIdempotencyStore } from './idempotency'

let csrfToken: string | null = null

const unauthorizedListeners = new Set<() => void>()

/** Возвращает текущий CSRF-токен или null, если сессия не активна. */
export function getCsrfToken(): string | null {
  return csrfToken
}

/** Устанавливает CSRF-токен, полученный из login/session. */
export function setCsrfToken(token: string): void {
  csrfToken = token
}

/**
 * Очищает клиентское состояние сессии (CSRF-токен и ожидающие
 * `Idempotency-Key`). Используется при logout, истечении сессии и смене
 * пользователя.
 */
export function clearSession(): void {
  csrfToken = null
  defaultIdempotencyStore.clear()
}

/**
 * Подписывает слушателя на сигнал `401/UNAUTHENTICATED`.
 *
 * @returns функция отписки.
 */
export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

/**
 * Сообщает приложению, что сессия недействительна: очищает токен и уведомляет
 * подписчиков. Транспорт вызывает это только для `401` с кодом
 * `UNAUTHENTICATED`; `LOGIN_FAILED` не очищает сессию.
 */
export function emitUnauthorized(): void {
  clearSession()
  for (const listener of [...unauthorizedListeners]) {
    listener()
  }
}

/** Сбрасывает и токен, и подписки. Нужен тестам для изоляции состояния. */
export function resetSessionContext(): void {
  clearSession()
  unauthorizedListeners.clear()
}
