// Общая retry/backoff policy HTTP-транспорта WiseWay.
//
// API §2 «Идемпотентность»/§11 и SEM «Повторы»: автоматический повтор допустим
// только там, где он безопасен. Этот модуль даёт три примитива:
//
// - `shouldRetry`/`computeRetryDelay` — решение о повторе и задержка:
//   `Retry-After` (delta-seconds) имеет приоритет и ограничивается сверху,
//   иначе используется экспоненциальный backoff с ограничением и jitter;
// - `createRetryFetch` — fetch-wrapper, который повторяет ТОТ ЖЕ `Request`
//   (то же тело и тот же `Idempotency-Key`) для разрешённых операций при
//   сетевом сбое/`429`/`503`. После исчерпания попыток исходная ошибка не
//   теряется: сетевой сбой пробрасывается, HTTP-ответ возвращается как есть;
// - `createPollRegistry` — single-flight коалесцинг одинаковых параллельных
//   poll-запросов: пока запрос в полёте, повторный `run` с тем же ключом
//   получает тот же promise и не создаёт второй запрос.
//
// Metadata операции (`operationId`/`method`/`csrf`/`idempotencyKey`) хранится
// в module-level `WeakMap`, которую заполняет транспорт в `onRequest`. Это
// служебное состояние никогда не отправляется на сервер: заголовки не
// добавляются.
//
// Состояние ограничено памятью вкладки: никакого `localStorage`,
// `sessionStorage`, cookie, URL или history state. `clearSession()`/
// `emitUnauthorized()` очищают default poll registry.

import type { OperationMeta } from './generated/operation-meta'
import { toTransportError, type TransportError } from './transport-error'

/** Функция ожидания; инъекция нужна тестам для controlled clocks. */
export type SleepFn = (milliseconds: number) => Promise<void>

/** Функция текущего времени; инъекция нужна тестам для controlled clocks. */
export type NowFn = () => number

/** Ожидание по умолчанию. Тесты всегда подменяют её, не ожидая реально. */
export const defaultSleep: SleepFn = (milliseconds) =>
  new Promise((resolve) => {
    setTimeout(resolve, milliseconds)
  })

/** Часы по умолчанию. */
export const defaultNow: NowFn = () => Date.now()

/**
 * Настройки retry/backoff. Значения в миллисекундах.
 *
 * `maxAttempts` считает и первую попытку: `maxAttempts = 1` означает «без
 * повторов», `maxAttempts = 3` — до двух повторов.
 */
export interface RetryConfig {
  /** Общее число попыток, включая первую (>= 1). */
  maxAttempts: number
  /** Базовая задержка экспоненциального backoff. */
  baseDelayMs: number
  /** Верхняя граница любой задержки, включая `Retry-After`. */
  maxDelayMs: number
  /** Добавлять ли случайный jitter к экспоненциальной задержке. */
  jitter: boolean
}

/** Консервативные значения по умолчанию: 3 попытки, 0.5→8 с, jitter. */
export const defaultRetryConfig: RetryConfig = {
  maxAttempts: 3,
  baseDelayMs: 500,
  maxDelayMs: 8000,
  jitter: true,
}

/**
 * Metadata операции для retry-решения: generated `OperationMeta` плюс
 * HTTP-метод. Метод нужен, чтобы отличать безопасные чтения (`GET`) от
 * читающих POST, не опираясь только на `csrf`.
 */
export interface RetryOperationMeta extends OperationMeta {
  /** HTTP-метод в верхнем регистре. */
  method: string
}

/** Информация о выполненном повторе (для логирования/наблюдаемости). */
export interface RetryAttemptInfo {
  /** Номер предстоящей попытки: `2` для первого повтора. */
  attempt: number
  /** Задержка перед повтором в миллисекундах. */
  delayMs: number
  /** Безопасная ошибка, из-за которой выполняется повтор. */
  error: TransportError
  /** Время решения по инъецированным часам `now`. */
  at: number
}

/** Опции `createRetryFetch`. */
export interface CreateRetryFetchOptions {
  /** Частичное переопределение `defaultRetryConfig`. */
  config?: Partial<RetryConfig>
  /** Инъекция ожидания; по умолчанию `defaultSleep`. */
  sleep?: SleepFn
  /** Инъекция часов; по умолчанию `defaultNow`. */
  now?: NowFn
  /** Необязательный наблюдатель повторов. */
  onRetry?: (info: RetryAttemptInfo) => void
}

/**
 * Регистрирует metadata операции для конкретного `Request`. Транспорт вызывает
 * это в `onRequest` для того самого объекта `Request`, который затем получает
 * retry-fetch. Заголовки не затрагиваются.
 */
const requestOperationMeta = new WeakMap<Request, RetryOperationMeta>()

export function setRequestOperationMeta(
  request: Request,
  meta: RetryOperationMeta,
): void {
  requestOperationMeta.set(request, meta)
}

/** Возвращает metadata операции для `Request` либо `undefined`. */
export function getRequestOperationMeta(
  request: Request,
): RetryOperationMeta | undefined {
  return requestOperationMeta.get(request)
}

/**
 * Разрешает ли политика автоматический повтор для операции.
 *
 * Повтор допустим только для безопасных чтений (`GET` и читающие POST без
 * CSRF) и для трёх идемпотентных операций (`Idempotency-Key`). Все прочие
 * мутации (`logout`, `createDictionary`, `replaceDictionaryDraft`,
 * `restoreDictionaryDraft`, `createDictionarySimulation`,
 * `createSortingSelection`, `createSortingPreview`) не повторяются никогда:
 * повтор такой операции — новое явное действие пользователя. `login` тоже не
 * повторяется автоматически (API §2: «Повторный login — явная отправка формы»).
 *
 * Дополнительно требуется `error.retryable`: окончательные ошибки условий
 * (409/422/… ) не повторяются.
 */
export function shouldRetry(
  error: TransportError,
  operationMeta: RetryOperationMeta | undefined,
): boolean {
  if (!error.retryable || !operationMeta) {
    return false
  }
  if (operationMeta.idempotencyKey) {
    return true
  }
  if (operationMeta.csrf) {
    // CSRF-мутации не идемпотентны; исключений нет.
    return false
  }
  if (operationMeta.method === 'GET') {
    return true
  }
  // POST без CSRF — читающая операция (search/facet/queue/audit/resolver).
  // Единственная csrf=false мутация — login; её повтор только явный.
  return operationMeta.operationId !== 'login'
}

/**
 * Вычисляет задержку перед повтором в миллисекундах.
 *
 * Приоритет у `Retry-After` (delta-seconds), значение ограничивается сверху
 * `maxDelayMs`. Иначе — экспоненциальный backoff `baseDelayMs * 2^attempt` с
 * тем же ограничением; при `jitter: true` задержка случайно уменьшается
 * (full jitter), чтобы избежать синхронных повторов.
 */
export function computeRetryDelay(
  error: TransportError,
  attempt: number,
  config: RetryConfig,
): number {
  const safeAttempt = Number.isFinite(attempt) && attempt > 0 ? attempt : 0
  if (error.retryAfterSeconds !== null) {
    return Math.min(error.retryAfterSeconds * 1000, config.maxDelayMs)
  }
  const exponential = config.baseDelayMs * 2 ** safeAttempt
  const capped = Math.min(exponential, config.maxDelayMs)
  if (!config.jitter) {
    return capped
  }
  return Math.floor(Math.random() * capped)
}

/** Читает тело ответа через `Response.clone()`, не расходуя оригинал. */
async function readErrorBody(response: Response): Promise<unknown> {
  try {
    return await response.clone().json()
  } catch {
    return undefined
  }
}

/**
 * Строит безопасную ошибку из не-`ok` ответа. Тело читается из клона, поэтому
 * оригинальный ответ остаётся пригодным для `openapi-fetch`.
 */
async function toResponseError(response: Response): Promise<TransportError> {
  return toTransportError({ response, error: await readErrorBody(response) })
}

/**
 * Оборачивает `baseFetch` политикой повторов.
 *
 * Повторяется ровно тот же `Request` (то же тело, заголовки и
 * `Idempotency-Key`): каждый попытка получает `request.clone()`, оригинал не
 * расходуется. Повторяются только сетевые сбои и ответы `429`/`503` для
 * операций, разрешённых `shouldRetry`. После исчерпания `maxAttempts`:
 *
 * - сетевой сбой пробрасывается как исходная ошибка;
 * - HTTP-ответ возвращается без изменений (openapi-fetch сам построит ошибку).
 */
export function createRetryFetch(
  baseFetch: (input: Request, init?: RequestInit) => Promise<Response>,
  options: CreateRetryFetchOptions = {},
): (input: Request, init?: RequestInit) => Promise<Response> {
  const config: RetryConfig = { ...defaultRetryConfig, ...options.config }
  const sleep = options.sleep ?? defaultSleep
  const now = options.now ?? defaultNow
  // Некорректный `maxAttempts` не должен превращаться в бесконечный цикл.
  const maxAttempts = Number.isFinite(config.maxAttempts)
    ? Math.max(1, Math.floor(config.maxAttempts))
    : defaultRetryConfig.maxAttempts

  return async function retryFetch(request, init) {
    const meta = getRequestOperationMeta(request)
    let attempt = 0

    for (;;) {
      let response: Response
      try {
        response = await baseFetch(request.clone(), init)
      } catch (rawError) {
        const error = toTransportError(rawError)
        if (attempt >= maxAttempts - 1 || !shouldRetry(error, meta)) {
          throw rawError
        }
        const delayMs = computeRetryDelay(error, attempt, config)
        options.onRetry?.({ attempt: attempt + 1, delayMs, error, at: now() })
        await sleep(delayMs)
        attempt += 1
        continue
      }

      const retryableResponse =
        !response.ok && (response.status === 429 || response.status === 503)
      if (!retryableResponse || attempt >= maxAttempts - 1) {
        return response
      }

      const error = await toResponseError(response)
      if (!shouldRetry(error, meta)) {
        return response
      }
      const delayMs = computeRetryDelay(error, attempt, config)
      options.onRetry?.({ attempt: attempt + 1, delayMs, error, at: now() })
      await sleep(delayMs)
      attempt += 1
    }
  }
}

/** Реестр single-flight poll-запросов, ограниченный памятью вкладки. */
export interface PollRegistry {
  /**
   * Запускает `fn` для ключа. Пока запрос по ключу в полёте, повторный вызов
   * возвращает тот же promise и не создаёт второй запрос. После завершения
   * (успех или ошибка) следующий вызов запускает новый запрос.
   */
  run<T>(key: string, fn: () => Promise<T>): Promise<T>
  /** Есть ли сейчас in-flight запрос по ключу. */
  has(key: string): boolean
  /** Очищает состояние (logout/401/смена пользователя). */
  clear(): void
}

/**
 * Создаёт изолированный single-flight реестр. Фабрика нужна тестам и изоляции:
 * каждый экземпляр имеет собственное состояние.
 */
export function createPollRegistry(): PollRegistry {
  const inFlight = new Map<string, Promise<unknown>>()

  return {
    run<T>(key: string, fn: () => Promise<T>): Promise<T> {
      const existing = inFlight.get(key)
      if (existing) {
        return existing as Promise<T>
      }
      const promise = (async () => fn())()
      inFlight.set(key, promise)
      const settle = () => {
        if (inFlight.get(key) === promise) {
          inFlight.delete(key)
        }
      }
      // `then` с двумя обработчиками не создаёт необработанный rejection.
      promise.then(settle, settle)
      return promise
    },
    has(key) {
      return inFlight.has(key)
    },
    clear() {
      inFlight.clear()
    },
  }
}

/**
 * Session-scoped реестр по умолчанию. Feature-уровень использует его для
 * коалесцинга poll-запросов; `clearSession()`/`emitUnauthorized()`
 * (`session-context`) очищают его вместе с остальным клиентским состоянием.
 */
export const defaultPollRegistry: PollRegistry = createPollRegistry()
