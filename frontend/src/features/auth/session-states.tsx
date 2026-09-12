// Экраны состояний bootstrap-проверки сессии: загрузка и недоступность.
//
// Оба состояния не показывают вход и не изображают успешную сессию. Экран
// недоступности сохраняет безопасное русское сообщение и явное действие
// «Повторить»; технический `request_id` (если есть) показывается как есть для
// разбора, без тел и секретов.

import type { SessionBootstrapError } from './session-bootstrap-store'

/** Русское состояние «проверяем сессию» до ответа сервера. */
export function SessionCheckingScreen() {
  return (
    <main className="session-screen" aria-busy="true">
      <p className="session-screen__status" role="status">
        Проверка сессии…
      </p>
    </main>
  )
}

export interface SessionUnavailableScreenProps {
  readonly error: SessionBootstrapError | null
  readonly onRetry: () => void
}

/**
 * Экран недоступности сервиса: сетевой сбой/5xx не превращается в анонимное
 * состояние и не показывает форму входа.
 */
export function SessionUnavailableScreen({
  error,
  onRetry,
}: SessionUnavailableScreenProps) {
  return (
    <main className="session-screen">
      <div className="session-unavailable" role="alert">
        <h1 className="session-unavailable__title">
          Не удалось проверить сессию
        </h1>
        <p className="session-unavailable__message">
          {error?.message ??
            'Сервис временно недоступен. Повторите попытку позже.'}
        </p>
        {error?.requestId ? (
          <p className="session-unavailable__request">
            Идентификатор запроса: {error.requestId}
          </p>
        ) : null}
        <button
          type="button"
          className="session-unavailable__retry"
          onClick={onRetry}
        >
          Повторить
        </button>
      </div>
    </main>
  )
}
