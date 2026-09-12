// React-хук выхода из системы с явным повтором при неизвестном исходе.
//
// Хук хранит только состояние текущей попытки (`idle`/`logging_out`/`retry`) и
// безопасное русское сообщение. Успешный выход применяет
// `endAuthenticatedSession()`; при `still_authenticated`/`unknown` сессия
// сохраняется и показывается явная кнопка повтора. Хук не персистит ничего и не
// выполняет иных запросов, кроме `POST /auth/logout` и сверки `GET /session`.

import { useCallback, useRef, useState } from 'react'

import type { WiseWayApiClient } from '@/api/transport'

import { endAuthenticatedSession } from './auth-lifecycle'
import { performLogout } from './logout'

/** Состояние управления выходом. */
export type LogoutStatus = 'idle' | 'logging_out' | 'retry'

/** Значение хука выхода. */
export interface UseLogoutResult {
  readonly status: LogoutStatus
  /** Безопасное русское сообщение при необходимости повтора. */
  readonly message: string | null
  /** Запускает попытку выхода; повторный вызов во время запроса игнорируется. */
  readonly logout: () => void
}

const STILL_AUTHENTICATED_MESSAGE =
  'Выйти не удалось: сессия всё ещё активна. Повторите выход.'
const UNKNOWN_MESSAGE =
  'Не удалось подтвердить выход из системы. Повторите попытку.'

/** Управляет попыткой выхода для переданного API-клиента. */
export function useLogout(client: WiseWayApiClient): UseLogoutResult {
  const [status, setStatus] = useState<LogoutStatus>('idle')
  const [message, setMessage] = useState<string | null>(null)
  const inFlight = useRef(false)

  const logout = useCallback((): void => {
    if (inFlight.current) {
      return
    }
    inFlight.current = true
    setStatus('logging_out')
    setMessage(null)

    void (async () => {
      try {
        const result = await performLogout(client)
        if (result.status === 'logged_out') {
          // Успех/подтверждённое истечение: очищаем сессию и приватное
          // состояние. Гейт реактивно показывает экран входа без перезагрузки.
          endAuthenticatedSession()
          return
        }
        // Успех НЕ заявляется: сессия сохранена, нужен явный повтор.
        setStatus('retry')
        setMessage(
          result.status === 'still_authenticated'
            ? STILL_AUTHENTICATED_MESSAGE
            : UNKNOWN_MESSAGE,
        )
      } finally {
        inFlight.current = false
      }
    })()
  }, [client])

  return { status, message, logout }
}
