// Русский экран входа WiseWay (AUTH-01…05, FE §4 «Вход»).
//
// Форма отправляет ровно `{login, password}` на `POST /auth/login` через общий
// транспорт и различает три исхода:
// - 200 `Session` — серверная сессия фиксируется вызывающей стороной
//   (`onAuthenticated`), пароль немедленно удаляется из поля и нигде не хранится;
// - 401 `LOGIN_FAILED` — одно общее русское сообщение формы, которое не
//   указывает, какое именно поле неверно; введённый логин сохраняется;
// - сетевой сбой/5xx/иная ошибка — безопасное сообщение о недоступности и
//   явное действие «Повторить»; это не «неверный пароль».
//
// Клиентская валидация не даёт отправить пустую форму: кнопка входа недоступна
// с явной русской причиной, пока логин и пароль не заполнены. Пароль хранится
// только в DOM-поле (`useRef`), а не в React-состоянии, и очищается сразу после
// успешного входа. Саморегистрация и сброс пароля отсутствуют.

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from 'react'

import { toTransportError, type WiseWayApiClient } from '@/api/transport'

import { submitLogin, type Session } from './auth-api'

export interface LoginScreenProps {
  readonly client: WiseWayApiClient
  /** Вызывается с серверным `Session` после успешного входа. */
  readonly onAuthenticated: (session: Session) => void
}

type LoginStatus = 'idle' | 'submitting' | 'login_failed' | 'unavailable'

export function LoginScreen({ client, onAuthenticated }: LoginScreenProps) {
  const loginInputId = useId()
  const passwordInputId = useId()
  const reasonId = useId()

  const [login, setLogin] = useState('')
  const [hasPassword, setHasPassword] = useState(false)
  const [status, setStatus] = useState<LoginStatus>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const passwordRef = useRef<HTMLInputElement>(null)
  const alertRef = useRef<HTMLDivElement>(null)

  const isSubmitting = status === 'submitting'
  const hasLogin = login.trim().length > 0
  const canSubmit = hasLogin && hasPassword && !isSubmitting

  const disabledReason = !hasLogin
    ? hasPassword
      ? 'Введите логин, чтобы войти.'
      : 'Введите логин и пароль, чтобы войти.'
    : !hasPassword
      ? 'Введите пароль, чтобы войти.'
      : null

  const performLogin = useCallback(async (): Promise<void> => {
    const password = passwordRef.current?.value ?? ''
    const loginValue = login.trim()
    if (loginValue.length === 0 || password.length === 0) {
      return
    }

    setStatus('submitting')
    setErrorMessage(null)

    try {
      const session = await submitLogin(client, {
        login: loginValue,
        password,
      })
      // Пароль больше не нужен: удаляем его из поля до показа оболочки.
      if (passwordRef.current) {
        passwordRef.current.value = ''
      }
      setHasPassword(false)
      onAuthenticated(session)
    } catch (error) {
      const transportError = toTransportError(error)
      if (
        transportError.status === 401 &&
        transportError.code === 'LOGIN_FAILED'
      ) {
        // Общая ошибка формы: не раскрываем, какое поле неверно, и не трогаем
        // состояние сессии (это не `UNAUTHENTICATED`).
        setStatus('login_failed')
        return
      }
      // Сеть/5xx/иная ошибка: не выдаём её за неверные credentials.
      setStatus('unavailable')
      setErrorMessage(transportError.message)
    }
  }, [client, login, onAuthenticated])

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    if (!canSubmit) {
      return
    }
    void performLogin()
  }

  // Фокусируем сообщение об ошибке для клавиатуры и скринридера (NFR-01).
  useEffect(() => {
    if (status === 'login_failed' || status === 'unavailable') {
      alertRef.current?.focus()
    }
  }, [status])

  return (
    <main className="login-screen">
      <form
        className="login-form ww-card"
        onSubmit={handleSubmit}
        aria-labelledby={`${loginInputId}-title`}
        noValidate
      >
        <h1 id={`${loginInputId}-title`} className="login-form__title">
          Вход в WiseWay
        </h1>
        <p className="login-form__intro">Введите логин и пароль.</p>

        <div className="login-form__field">
          <label className="login-form__label ww-label" htmlFor={loginInputId}>
            Логин
          </label>
          <input
            id={loginInputId}
            className="login-form__input ww-input"
            name="login"
            type="text"
            autoComplete="username"
            placeholder="Введите логин"
            value={login}
            onChange={(event) => {
              setLogin(event.target.value)
              if (status === 'login_failed' || status === 'unavailable') {
                setStatus('idle')
                setErrorMessage(null)
              }
            }}
            disabled={isSubmitting}
            required
          />
        </div>

        <div className="login-form__field">
          <label className="login-form__label ww-label" htmlFor={passwordInputId}>
            Пароль
          </label>
          <input
            id={passwordInputId}
            className="login-form__input ww-input"
            name="password"
            type="password"
            autoComplete="current-password"
            placeholder="Введите пароль"
            ref={passwordRef}
            onChange={(event) => {
              setHasPassword(event.target.value.length > 0)
              if (status === 'login_failed' || status === 'unavailable') {
                setStatus('idle')
                setErrorMessage(null)
              }
            }}
            disabled={isSubmitting}
            required
          />
        </div>

        <button
          type="submit"
          className="login-form__submit ww-button ww-button--primary"
          disabled={!canSubmit}
          aria-describedby={disabledReason ? reasonId : undefined}
        >
          {isSubmitting ? 'Выполняется вход…' : 'Войти'}
        </button>

        {disabledReason ? (
          <p id={reasonId} className="login-form__reason">
            {disabledReason}
          </p>
        ) : null}

        {status === 'login_failed' ? (
          <div
            className="login-form__error ww-alert ww-alert--error"
            role="alert"
            tabIndex={-1}
            ref={alertRef}
          >
            <p className="login-form__error-message ww-alert__message">
              Неверный логин или пароль.
            </p>
          </div>
        ) : null}

        {status === 'unavailable' ? (
          <div
            className="login-form__error ww-alert ww-alert--error"
            role="alert"
            tabIndex={-1}
            ref={alertRef}
          >
            <p className="login-form__error-message ww-alert__message">
              {errorMessage ??
                'Не удалось связаться с сервером. Повторите попытку позже.'}
            </p>
            <button
              type="button"
              className="login-form__retry ww-button ww-button--secondary"
              onClick={() => {
                void performLogin()
              }}
            >
              Повторить
            </button>
          </div>
        ) : null}
      </form>
    </main>
  )
}
