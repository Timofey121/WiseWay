// Операции входа и чтения активной сессии поверх публичного API-клиента.
//
// Модуль не хранит состояние и не занимается UI: он только вызывает
// `GET /session` и `POST /auth/login` через общий транспорт и возвращает
// серверный `Session` либо бросает безопасную `TransportError`. Пароль
// передаётся ровно в теле login-запроса и нигде не сохраняется.
//
// Семантика ошибок (`02_API_CONTRACT.md` §3/§11):
// - `GET /session` → 401 `UNAUTHENTICATED` означает отсутствие/истечение сессии;
// - `POST /auth/login` → 401 `LOGIN_FAILED` означает неверный логин/пароль;
// - сетевой сбой/5xx не является ни тем, ни другим и не превращается в успех.

import type { components } from '@/api/generated/schema'
import { getCsrfToken } from '@/api/session-context'
import { throwIfError, type WiseWayApiClient } from '@/api/transport'

/** Серверная сессия из публичного контракта. */
export type Session = components['schemas']['Session']

/** Учётные данные формы входа; пароль не выходит за пределы запроса. */
export interface LoginCredentials {
  readonly login: string
  readonly password: string
}

/**
 * Читает активную сессию (`GET /session`). Успех — серверный `Session`; при
 * отсутствии/истечении сессии бросает `TransportError` с кодом
 * `UNAUTHENTICATED`.
 */
export async function fetchActiveSession(
  client: WiseWayApiClient,
): Promise<Session> {
  return throwIfError(await client.GET('/session'))
}

/**
 * Отправляет ровно `{login, password}` на `POST /auth/login` (без `actor_id` и
 * лишних полей) и возвращает серверный `Session`. Неверные учётные данные
 * бросают `TransportError` с кодом `LOGIN_FAILED`.
 */
export async function submitLogin(
  client: WiseWayApiClient,
  credentials: LoginCredentials,
): Promise<Session> {
  return throwIfError(
    await client.POST('/auth/login', {
      body: {
        login: credentials.login,
        password: credentials.password,
      },
    }),
  )
}

/**
 * Завершает серверную сессию: `POST /auth/logout` с ПУСТЫМ телом и без
 * `Idempotency-Key` (операция его не объявляет). Успех — `204`, и `undefined`
 * не превращается в ошибку.
 *
 * Заголовок `X-CSRF-Token` в `params.header` нужен только для типа
 * generated-клиента: фактическое значение подставляет общий транспорт из
 * in-memory `@/api/session-context` (тот же путь, что и для остальных
 * CSRF-мутаций). Отдельный токен здесь не выдумывается и не персистится.
 */
export async function submitLogout(client: WiseWayApiClient): Promise<void> {
  throwIfError(
    await client.POST('/auth/logout', {
      params: { header: { 'X-CSRF-Token': getCsrfToken() ?? '' } },
    }),
  )
}
