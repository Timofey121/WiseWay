// Единая безопасная модель ошибок HTTP-транспорта WiseWay.
//
// `openapi-fetch` возвращает `{ data, error, response }` для HTTP-ответов и
// бросает исключение при сетевом сбое (нет `response`). Этот модуль приводит
// оба случая к одному безопасному типу `TransportError`, из которого UI берёт
// ровно объявленные публичным OAS поля:
//
// - `code` (`#/components/schemas/ErrorCode`);
// - `message` — безопасное русское пользовательское сообщение;
// - `request_id`/`operation_id` — технические идентификаторы (не переводятся);
// - `field_errors` (`#/components/schemas/FieldError`);
// - `retryable`;
// - `Retry-After` (delta-seconds, `#/components/headers/RetryAfter`).
//
// Безопасность: модель никогда не включает сырое тело ответа, пароль,
// поисковый текст, физические пути, стек или текст исключения. Если тело
// отсутствует/битое, `code` синтезируется по HTTP-статусу, а сообщение берётся
// из безопасного справочника. Сетевой сбой не превращается в success.

import type { components } from './generated/schema'

/** Безопасная ошибка поля из контракта (`#/components/schemas/FieldError`). */
export type FieldError = components['schemas']['FieldError']

/** Код ошибки из контракта (`#/components/schemas/ErrorCode`). */
export type ErrorCode = components['schemas']['ErrorCode']

/** Источник ошибки: HTTP-ответ или сетевой сбой/таймаут. */
export type TransportErrorKind = 'http' | 'network'

/** Безопасные metadata ошибки транспорта. */
export interface TransportErrorOptions {
  kind: TransportErrorKind
  /** HTTP-статус; `null` для сетевого сбоя. */
  status: number | null
  /** Код из контракта или синтезированный безопасный код. */
  code: string
  /** Безопасное русское пользовательское сообщение. */
  message: string
  /** `error.request_id` либо `X-Request-ID`; `null`, если недоступен. */
  requestId: string | null
  /** `error.operation_id`; `null`, если операция не создавалась. */
  operationId: string | null
  /** Техническая возможность безопасного повтора без изменения условий. */
  retryable: boolean
  /** Безопасные ошибки полей из контракта; пустой массив, если их нет. */
  fieldErrors: FieldError[]
  /** `Retry-After` в секундах; `null`, если заголовок отсутствует. */
  retryAfterSeconds: number | null
}

/** Единая безопасная ошибка транспорта WiseWay. */
export class TransportError extends Error {
  readonly kind: TransportErrorKind
  readonly status: number | null
  readonly code: string
  readonly requestId: string | null
  readonly operationId: string | null
  readonly retryable: boolean
  readonly fieldErrors: FieldError[]
  readonly retryAfterSeconds: number | null

  constructor(options: TransportErrorOptions) {
    super(options.message)
    this.name = 'TransportError'
    this.kind = options.kind
    this.status = options.status
    this.code = options.code
    this.requestId = options.requestId
    this.operationId = options.operationId
    this.retryable = options.retryable
    this.fieldErrors = options.fieldErrors
    this.retryAfterSeconds = options.retryAfterSeconds
  }
}

/**
 * Минимальная форма результата `openapi-fetch`, достаточная для разбора
 * ошибки. Результат успеха сюда не передаётся (см. `throwIfError`).
 */
export interface ApiResultLike<T = unknown> {
  data?: T
  error?: unknown
  response?: Response
}

/** Безопасный код по HTTP-статусу, если тело отсутствует/битое. */
const FALLBACK_CODE_BY_STATUS: Readonly<Record<number, string>> = {
  400: 'INVALID_QUERY',
  401: 'UNAUTHENTICATED',
  403: 'FORBIDDEN',
  404: 'NOT_FOUND',
  409: 'INVALID_STATE',
  422: 'VALIDATION_ERROR',
  429: 'RATE_LIMITED',
  500: 'INTERNAL_ERROR',
  503: 'SERVICE_UNAVAILABLE',
}

/** Код, если статус не объявлен в контракте. */
const DEFAULT_ERROR_CODE = 'INTERNAL_ERROR'

/**
 * Сообщение по умолчанию для статуса/кода, отсутствующего в справочнике.
 * Намеренно общее и без технических подробностей.
 */
const DEFAULT_ERROR_MESSAGE = 'Не удалось выполнить запрос. Повторите попытку позже.'

/** Безопасное сообщение сетевого сбоя (нет ответа сервера). */
const NETWORK_ERROR_MESSAGE =
  'Не удалось связаться с сервером. Проверьте соединение и повторите попытку.'

/**
 * Безопасные русские сообщения по коду контракта. Используются только когда
 * сервер не прислал `error.message`; значения не эхо-тело запроса.
 */
const SAFE_MESSAGE_BY_CODE: Readonly<Record<string, string>> = {
  INVALID_QUERY: 'Неверный синтаксис поискового запроса.',
  LOGIN_FAILED: 'Неверный логин или пароль.',
  UNAUTHENTICATED: 'Сессия отсутствует или истекла. Войдите снова.',
  FORBIDDEN: 'Действие недоступно.',
  CSRF_FAILED: 'Не удалось подтвердить запрос текущей сессии.',
  NOT_FOUND: 'Объект не найден.',
  DRAFT_VERSION_CONFLICT: 'Черновик изменён другим пользователем. Перечитайте его.',
  DICTIONARY_NAME_CONFLICT: 'Название справочника уже используется в компании.',
  QUARANTINE_VERSION_CONFLICT: 'Состояние карантинного файла изменилось.',
  STALE_SIMULATION: 'Результат теста устарел. Выполните тест повторно.',
  STALE_PREVIEW: 'Данные изменились. Выполните проверку повторно.',
  SELECTION_EXPIRED: 'Срок действия выбора истёк. Выберите файлы повторно.',
  SELECTION_CHANGED: 'Выбранные файлы изменились. Обновите выбор.',
  SCHEMA_VERSION_CHANGED:
    'Схема уровней изменилась. Обновите корни и выбранные уровни.',
  ROOT_NOT_READY: 'Выбранный корень сейчас не опубликован для поиска.',
  RULE_CONFLICT: 'Обнаружен конфликт правил. Исправьте его перед публикацией.',
  NO_SCENARIO_ACK_REQUIRED:
    'Подтвердите отсутствие сценария для указанного результата теста.',
  ORIGINAL_PATH_OCCUPIED: 'Исходный входящий путь занят. Возврат не выполнен.',
  RECOVERY_REQUIRED:
    'Результат операции требует ручной проверки. Не повторяйте перемещение.',
  IDEMPOTENCY_KEY_REUSED:
    'Ключ идемпотентности уже использован с другим телом запроса.',
  INVALID_STATE: 'Операция недопустима для текущего состояния объекта.',
  VALIDATION_ERROR: 'Проверьте значения полей запроса.',
  INVALID_MARKER_SELECTION:
    'Выбранная цепочка уровней недопустима. Обновите выбор.',
  INVALID_TARGET: 'Целевой каталог отсутствует или недопустим.',
  PATH_OUTSIDE_ROOT: 'Путь находится вне разрешённого корня.',
  EMPTY_SELECTION: 'Нет доступных файлов для запуска.',
  BATCH_LIMIT_EXCEEDED: 'Количество файлов превышает предел одной партии.',
  RATE_LIMITED: 'Слишком много запросов. Повторите позже.',
  SEARCH_UNAVAILABLE: 'Поиск временно недоступен.',
  SERVICE_UNAVAILABLE: 'Сервис временно недоступен.',
  INTERNAL_ERROR:
    'Не удалось выполнить запрос. Сохраните идентификатор запроса для разбора.',
}

/**
 * Коды, которые API §11 помечает `retryable: true`: технический повтор без
 * изменения условий. Остальные коды по умолчанию не повторяемы.
 */
const RETRYABLE_CODES: ReadonlySet<string> = new Set([
  'RATE_LIMITED',
  'SEARCH_UNAVAILABLE',
  'SERVICE_UNAVAILABLE',
])

interface ErrorDetailsLike {
  code?: unknown
  message?: unknown
  request_id?: unknown
  operation_id?: unknown
  retryable?: unknown
  field_errors?: unknown
}

/** Возвращает непустую строку либо `null`. */
function asNonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

/** Извлекает `error` из тела `ErrorResponse`, не доверяя лишним полям. */
function extractErrorDetails(raw: unknown): ErrorDetailsLike | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  const error = (raw as { error?: unknown }).error
  if (!error || typeof error !== 'object') {
    return null
  }
  return error as ErrorDetailsLike
}

/** Оставляет только объявленные поля `FieldError`, отбрасывая мусор. */
function extractFieldErrors(value: unknown): FieldError[] {
  if (!Array.isArray(value)) {
    return []
  }
  const fieldErrors: FieldError[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') {
      continue
    }
    const candidate = item as Record<string, unknown>
    const field = asNonEmptyString(candidate.field)
    const code = asNonEmptyString(candidate.code)
    const message = asNonEmptyString(candidate.message)
    if (field && code && message) {
      fieldErrors.push({ field, code, message })
    }
  }
  return fieldErrors
}

/**
 * Разбирает `Retry-After` в секундах. По OAS первая версия использует только
 * delta-seconds; HTTP-дата не принимается и не превращается в число.
 */
function parseRetryAfter(header: string | null): number | null {
  if (!header) {
    return null
  }
  const trimmed = header.trim()
  if (!/^[0-9]+$/.test(trimmed)) {
    return null
  }
  const seconds = Number(trimmed)
  return Number.isFinite(seconds) ? seconds : null
}

/** Строит безопасную ошибку из HTTP-ответа и его разобранного тела. */
function fromHttpResponse(response: Response, rawError: unknown): TransportError {
  const details = extractErrorDetails(rawError)
  const code =
    asNonEmptyString(details?.code) ??
    FALLBACK_CODE_BY_STATUS[response.status] ??
    DEFAULT_ERROR_CODE
  const message =
    asNonEmptyString(details?.message) ??
    SAFE_MESSAGE_BY_CODE[code] ??
    DEFAULT_ERROR_MESSAGE
  const requestId =
    asNonEmptyString(details?.request_id) ??
    response.headers.get('X-Request-ID')
  const operationId = asNonEmptyString(details?.operation_id)
  const retryable =
    typeof details?.retryable === 'boolean'
      ? details.retryable
      : RETRYABLE_CODES.has(code)

  return new TransportError({
    kind: 'http',
    status: response.status,
    code,
    message,
    requestId,
    operationId,
    retryable,
    fieldErrors: extractFieldErrors(details?.field_errors),
    retryAfterSeconds: parseRetryAfter(response.headers.get('Retry-After')),
  })
}

/** Строит безопасную ошибку сетевого сбоя/таймаута без текста исключения. */
function fromNetworkError(): TransportError {
  return new TransportError({
    kind: 'network',
    status: null,
    code: 'NETWORK_ERROR',
    message: NETWORK_ERROR_MESSAGE,
    requestId: null,
    operationId: null,
    retryable: true,
    fieldErrors: [],
    retryAfterSeconds: null,
  })
}

/**
 * Приводит результат `openapi-fetch` или брошенное исключение к
 * `TransportError`. Уже готовая `TransportError` возвращается без изменений.
 *
 * Результат успеха сюда передавать не нужно: для него используйте
 * `throwIfError`, который вернёт `data`.
 */
export function toTransportError(input: unknown): TransportError {
  if (input instanceof TransportError) {
    return input
  }
  if (input instanceof Response) {
    return fromHttpResponse(input, undefined)
  }
  if (
    input &&
    typeof input === 'object' &&
    (input as ApiResultLike).response instanceof Response
  ) {
    const result = input as ApiResultLike
    return fromHttpResponse(result.response as Response, result.error)
  }
  return fromNetworkError()
}

/** Проверяет, что значение — `TransportError` из этого модуля. */
export function isTransportError(value: unknown): value is TransportError {
  return value instanceof TransportError
}

/**
 * Возвращает `data` успешного результата `openapi-fetch`, иначе бросает
 * `TransportError`. Успех определяется по `response.ok`, поэтому пустой
 * успешный ответ (200/204) не превращается в ошибку, а ошибочный ответ без
 * тела — в ложный успех.
 */
export function throwIfError<T>(result: ApiResultLike<T>): T {
  if (result && result.response instanceof Response && result.response.ok) {
    return result.data as T
  }
  throw toTransportError(result)
}
