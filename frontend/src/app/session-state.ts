// Минимальный in-memory контейнер присутствия сессии приложения.
//
// Контейнер отвечает на два вопроса: есть ли активная сессия (чтобы app-config
// и последующие приватные данные запрашивались только после входа) и какой
// аутентифицированный actor/`expires_at` вернул сервер. Он намеренно НЕ хранит
// токены и учётные данные: CSRF-токен живёт отдельно в `@/api/session-context`
// (`setCsrfToken`), а серверную cookie обслуживает браузер. Пароль сюда не
// попадает вообще. Контейнер также ничего не персистит (URL, history state,
// localStorage, sessionStorage, cookie) и не выполняет сетевых запросов.
//
// Источник actor — только серверный ответ `Session`: login/session bootstrap
// вызывают `markAuthenticated({ actor, expires_at })`. Клиент никогда не
// подставляет actor_id в запросы.
//
// Драйвер контейнера — LT-09.1 (login/session bootstrap): после успешного входа
// он вызывает `markAuthenticated(session)`, а logout/401/смена пользователя —
// `markAnonymous()`/`resetPrivateState()`. Общий реестр сброса LT-08.1
// зарегистрирован ниже.

import type { components } from '@/api/generated/schema'

import { registerPrivateStateReset } from './private-state-registry'

/** Наличие активной сессии: аноним или аутентифицирован. */
export type SessionStatus = 'anonymous' | 'authenticated'

/** Серверный actor из `Session.actor` (неизменяемый ID, логин, имя, роль). */
export type SessionActor = components['schemas']['Actor']

/** Роль пользователя из публичного контракта: `WORKER`/`ADMIN`. */
export type SessionRole = SessionActor['role']

/**
 * Серверная сессия в памяти приложения БЕЗ CSRF-токена: токен хранится ровно в
 * одном месте — `@/api/session-context`. `expires_at` хранится как пришёл от
 * сервера и не продлевается клиентом.
 */
export type AuthenticatedSession = Omit<
  components['schemas']['Session'],
  'csrf_token'
>

let sessionStatus: SessionStatus = 'anonymous'
let authenticatedSession: AuthenticatedSession | null = null

const listeners = new Set<() => void>()

/** Текущее состояние присутствия сессии. По умолчанию — `anonymous`. */
export function getSessionStatus(): SessionStatus {
  return sessionStatus
}

/**
 * Аутентифицированная сессия (actor/`expires_at`) или `null`. Ссылка стабильна
 * до следующего изменения, поэтому её можно читать через `useSyncExternalStore`.
 */
export function getAuthenticatedSession(): AuthenticatedSession | null {
  return authenticatedSession
}

/** Серверный actor активной сессии или `null`. */
export function getAuthenticatedActor(): SessionActor | null {
  return authenticatedSession?.actor ?? null
}

/**
 * Подписывает слушателя на изменение состояния.
 *
 * @returns функция отписки.
 */
export function subscribeSessionStatus(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/**
 * Помечает сессию как аутентифицированную.
 *
 * @param session серверная сессия из login/`GET /session`. Если не передана,
 *   статус меняется без изменения сохранённого actor (нужно тестам app-config).
 */
export function markAuthenticated(session?: AuthenticatedSession): void {
  commit('authenticated', session ?? authenticatedSession)
}

/** Помечает сессию как анонимную и очищает сохранённого actor. */
export function markAnonymous(): void {
  commit('anonymous', null)
}

/** Безусловно возвращает контейнер в исходное `anonymous`. Нужен тестам. */
export function resetSessionState(): void {
  commit('anonymous', null)
}

function commit(
  nextStatus: SessionStatus,
  nextSession: AuthenticatedSession | null,
): void {
  if (nextStatus === sessionStatus && nextSession === authenticatedSession) {
    return
  }
  sessionStatus = nextStatus
  authenticatedSession = nextSession
  for (const listener of [...listeners]) {
    listener()
  }
}

// Регистрация в общем реестре LT-08.1: logout/401/смена пользователя вызывают
// `resetPrivateState()`, который обязан вернуть контейнер в `anonymous`.
registerPrivateStateReset(resetSessionState)
