// Доступное управление выходом из системы (AUTH-03).
//
// Кнопка всегда подписана по-русски и доступна с клавиатуры. Пока запрос
// выполняется, кнопка недоступна и помечена `aria-busy`; при неизвестном
// исходе рядом появляется безопасное русское сообщение, а кнопка меняется на
// «Повторить выход». Успешный выход не перезагружает страницу: auth-гейт
// реактивно показывает экран входа.

import type { WiseWayApiClient } from '@/api/transport'

import { useLogout } from './use-logout'

export interface LogoutControlProps {
  readonly client: WiseWayApiClient
}

export function LogoutControl({ client }: LogoutControlProps) {
  const { status, message, logout } = useLogout(client)
  const isLoggingOut = status === 'logging_out'
  const isRetry = status === 'retry'

  return (
    <div className="logout-control">
      <button
        type="button"
        className="logout-control__button ww-button ww-button--secondary"
        onClick={logout}
        disabled={isLoggingOut}
        aria-busy={isLoggingOut}
      >
        {isLoggingOut ? 'Выход…' : isRetry ? 'Повторить выход' : 'Выйти'}
      </button>
      {message ? (
        <p
          className="logout-control__message ww-alert ww-alert--error"
          role="alert"
        >
          {message}
        </p>
      ) : null}
    </div>
  )
}
