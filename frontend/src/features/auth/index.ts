// Публичная точка входа auth-фичи WiseWay (LT-09.1/LT-09.2).
//
// Экран входа, bootstrap-проверка сессии, auth-гейт и выход из системы.
// Компоненты не хранят пароль и не персистят приватное состояние.

export { AuthGate, type AuthGateProps } from './auth-gate'
export { LoginScreen, type LoginScreenProps } from './login-screen'
export { LogoutControl, type LogoutControlProps } from './logout-control'
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
  endAuthenticatedSession,
  installUnauthorizedReset,
} from './auth-lifecycle'
export {
  performLogout,
  type LogoutResult,
  type LogoutResultStatus,
} from './logout'
export { useLogout, type LogoutStatus, type UseLogoutResult } from './use-logout'
export {
  fetchActiveSession,
  submitLogin,
  submitLogout,
  type LoginCredentials,
  type Session,
} from './auth-api'
