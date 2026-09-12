// App-level каркас WiseWay: русская оболочка с навигацией по разделам, единая
// фабрика API-клиента с переключателем real/mock, контейнер присутствия сессии
// и провайдер загрузки `AppConfig`. Приватное состояние живёт только в памяти
// вкладки.

export { AppShell } from './AppShell'
export {
  appSections,
  defaultSectionId,
  notImplementedStatus,
  type AppSection,
  type AppSectionId,
} from './sections'
export {
  registerPrivateStateReset,
  resetPrivateState,
  type PrivateStateReset,
} from './private-state-registry'
export {
  createAppApiClient,
  readTestFetchOverride,
  resolveAppApiMode,
  TEST_FETCH_GLOBAL,
  type AppApiFetch,
  type AppApiMode,
} from './app-api'
export { roleLabel, type UserRole } from './roles'
export { useAuthenticatedSession } from './use-session'
export {
  AppConfigProvider,
  type AppConfigProviderProps,
} from './app-config-provider'
export {
  useAppConfig,
  type AppConfigContextValue,
} from './app-config-context'
export type {
  AppConfig,
  AppConfigError,
  AppConfigStatus,
} from './app-config-store'
export {
  getAuthenticatedActor,
  getAuthenticatedSession,
  getSessionStatus,
  markAnonymous,
  markAuthenticated,
  resetSessionState,
  subscribeSessionStatus,
  type AuthenticatedSession,
  type SessionActor,
  type SessionRole,
  type SessionStatus,
} from './session-state'
