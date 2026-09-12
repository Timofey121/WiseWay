// Контекст app-config и хук доступа к нему.
//
// Контекст и хук вынесены из файла провайдера, чтобы Fast Refresh видел файл
// провайдера как «только компонент» (react-refresh/only-export-components).

import { createContext, useContext } from 'react'

import type {
  AppConfig,
  AppConfigError,
  AppConfigStatus,
} from './app-config-store'

/** Значение контекста app-config, доступное потомкам. */
export interface AppConfigContextValue {
  readonly status: AppConfigStatus
  readonly config: AppConfig | null
  readonly error: AppConfigError | null
  /** Явная повторная загрузка; при анонимной сессии ничего не делает. */
  readonly reload: () => void
}

export const AppConfigContext = createContext<AppConfigContextValue | null>(null)

/**
 * Доступ к состоянию и данным app-config. Должен вызываться внутри
 * `AppConfigProvider`.
 */
export function useAppConfig(): AppConfigContextValue {
  const value = useContext(AppConfigContext)
  if (!value) {
    throw new Error('useAppConfig должен вызываться внутри AppConfigProvider.')
  }
  return value
}
