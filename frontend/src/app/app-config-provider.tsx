// React-провайдер загрузки `AppConfig`.
//
// Провайдер монтируется в реальной композиции приложения (`App.tsx`) и
// гейтируется состоянием сессии (`session-state`): пока пользователь анонимен,
// запрос `GET /app-config` не выполняется. Значения конфигурации не
// дублируются и не подставляются по умолчанию — они берутся из ответа сервера.
//
// При ошибке показывается безопасное русское сообщение и явная кнопка
// «Повторить»; выдуманные пределы/пояс при этом не используются. Пока идёт
// загрузка, показывается статус «Загрузка настроек приложения…».
//
// Хук `useAppConfig` и контекст живут в `app-config-context.ts`.

import { useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react'

import type { WiseWayApiClient } from '@/api/transport'

import { AppConfigContext, type AppConfigContextValue } from './app-config-context'
import { createAppConfigStore } from './app-config-store'

export interface AppConfigProviderProps {
  readonly children: ReactNode
  /**
   * API-клиент приложения. Создаётся в композиционном корне (`App.tsx`) единой
   * фабрикой `createAppApiClient()`; UI-компоненты транспорт не конструируют.
   * Тесты передают mock-клиент.
   */
  readonly client: WiseWayApiClient
}

/**
 * Провайдер конфигурации приложения. Загружает `GET /app-config` только при
 * аутентифицированной сессии и отдаёт потомкам честное состояние и данные.
 */
export function AppConfigProvider({ children, client }: AppConfigProviderProps) {
  const store = useMemo(() => createAppConfigStore(client), [client])

  useEffect(() => {
    store.start()
    return () => {
      store.stop()
    }
  }, [store])

  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot,
  )

  const value = useMemo<AppConfigContextValue>(
    () => ({
      status: snapshot.status,
      config: snapshot.config,
      error: snapshot.error,
      reload: store.reload,
    }),
    [snapshot, store],
  )

  return (
    <AppConfigContext.Provider value={value}>
      {snapshot.status === 'loading' ? (
        <p className="app-config-status" role="status">
          Загрузка настроек приложения…
        </p>
      ) : null}
      {snapshot.status === 'error' && snapshot.error ? (
        <div className="app-config-error" role="alert">
          <p className="app-config-error__title">
            Не удалось загрузить настройки приложения
          </p>
          <p className="app-config-error__message">{snapshot.error.message}</p>
          {snapshot.error.requestId ? (
            <p className="app-config-error__request">
              Идентификатор запроса: {snapshot.error.requestId}
            </p>
          ) : null}
          <button
            type="button"
            className="app-config-error__retry"
            onClick={store.reload}
          >
            Повторить
          </button>
        </div>
      ) : null}
      {children}
    </AppConfigContext.Provider>
  )
}
