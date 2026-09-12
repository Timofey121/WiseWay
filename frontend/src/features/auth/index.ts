// Публичная точка входа auth-фичи WiseWay (LT-09.1).
//
// Экран входа, bootstrap-проверка сессии и auth-гейт. Компоненты не хранят
// пароль и не персистят приватное состояние.

export { AuthGate, type AuthGateProps } from './auth-gate'
export { LoginScreen, type LoginScreenProps } from './login-screen'
export {
  SessionCheckingScreen,
  SessionUnavailableScreen,
  type SessionUnavailableScreenProps,
} from './session-states'
export {
  createSessionBootstrapStore,
  type SessionBootstrapError,
  type SessionBootstrapSnapshot,
  type SessionBootstrapStatus,
  type SessionBootstrapStore,
} from './session-bootstrap-store'
export {
  useSessionBootstrap,
  type UseSessionBootstrapResult,
} from './use-session-bootstrap'
export {
  fetchActiveSession,
  submitLogin,
  type LoginCredentials,
  type Session,
} from './auth-api'
