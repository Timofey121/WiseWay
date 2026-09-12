// Минимальный in-memory контейнер присутствия сессии приложения.
//
// Контейнер отвечает ровно на один вопрос: есть ли активная сессия, чтобы
// app-config и последующие приватные данные запрашивались только после входа.
// Он намеренно НЕ хранит токены и учётные данные: CSRF-токен живёт отдельно в
// `@/api/session-context`, а серверную cookie обслуживает браузер. Контейнер
// также ничего не персистит (URL, history state, localStorage, sessionStorage,
// cookie) и не выполняет сетевых запросов.
//
// Драйвером контейнера будет LT-09.1 (login/session/logout): после успешного
// входа он вызовет `markAuthenticated()`, а logout/401/смена пользователя —
// `markAnonymous()`/`resetPrivateState()`. Здесь реализован только контейнер и
// его регистрация в общем реестре сброса LT-08.1.

import { registerPrivateStateReset } from './private-state-registry'

/** Наличие активной сессии: аноним или аутентифицирован. */
export type SessionStatus = 'anonymous' | 'authenticated'

let sessionStatus: SessionStatus = 'anonymous'

const listeners = new Set<() => void>()

/** Текущее состояние присутствия сессии. По умолчанию — `anonymous`. */
export function getSessionStatus(): SessionStatus {
  return sessionStatus
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

/** Помечает сессию как аутентифицированную (вызывается после входа). */
export function markAuthenticated(): void {
  setSessionStatus('authenticated')
}

/** Помечает сессию как анонимную (вызывается при logout/истечении). */
export function markAnonymous(): void {
  setSessionStatus('anonymous')
}

/** Безусловно возвращает контейнер в исходное `anonymous`. Нужен тестам. */
export function resetSessionState(): void {
  setSessionStatus('anonymous')
}

function setSessionStatus(next: SessionStatus): void {
  if (next === sessionStatus) {
    return
  }
  sessionStatus = next
  for (const listener of [...listeners]) {
    listener()
  }
}

// Регистрация в общем реестре LT-08.1: logout/401/смена пользователя вызывают
// `resetPrivateState()`, который обязан вернуть контейнер в `anonymous`.
registerPrivateStateReset(resetSessionState)
