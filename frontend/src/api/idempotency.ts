// In-memory состояние идемпотентности WiseWay.
//
// API §2 «Идемпотентность»: публикация справочника, создание партии и возврат
// из карантина требуют `Idempotency-Key` (UUID). Сервер связывает ключ с
// user_id, операцией и хешем тела: повтор того же ключа/тела возвращает прежний
// результат, другое тело с тем же ключом — 409 `IDEMPOTENCY_KEY_REUSED`.
//
// Клиент обязан:
//
// - при потере ответа/сетевой неопределённости повторить исходный ключ и тело,
//   а не создавать новую операцию;
// - при новом явном действии (изменённом теле) взять новый ключ;
// - не добавлять фиктивный `Idempotency-Key` операциям, которые его не
//   объявляют (набор задаёт generated `operation-meta`).
//
// Состояние живёт только в памяти вкладки: никакого `localStorage`,
// `sessionStorage`, cookie, URL или history state. Перезагрузка, logout и
// `401 UNAUTHENTICATED` начинают с чистого состояния. Хранилище сохраняет лишь
// UUID и детерминированный отпечаток тела; сами тела и секреты не сохраняются и
// не логируются.

/** Одна ожидающая запись: UUID и отпечаток связанного с ним тела. */
export interface IdempotencyRecord {
  /** UUID, отправляемый в заголовке `Idempotency-Key`. */
  readonly key: string
  /** Детерминированный отпечаток тела, с которым связан ключ. */
  readonly bodyFingerprint: string
}

/**
 * In-memory хранилище идемпотентности, ограниченное сессией вкладки.
 *
 * Пара `operationId` + необязательный стабильный `scope` (например id ресурса)
 * задаёт независимую ячейку действия. Пока по ячейке есть ожидающая запись:
 *
 * - повтор с тем же телом получает прежний ключ (retry/lost response/double
 *   submit);
 * - изменённое тело заменяет запись новым ключом — старый ключ с новым телом
 *   не отправляется никогда;
 * - отсутствие записи даёт новый ключ.
 *
 * `complete` освобождает ячейку при успехе или окончательном не-retryable
 * отказе; `retain` сохраняет её при сетевой неопределённости/retryable исходе;
 * `clear` очищает всё состояние сессии.
 */
export interface IdempotencyStore {
  /**
   * Возвращает ключ для операции и тела: прежний при том же теле, новый при
   * изменённом теле или отсутствии ожидающей записи. Возвращённый ключ всегда
   * связан ровно с переданным телом.
   */
  begin(operationId: string, body: unknown, scope?: string): string
  /** Успешное/окончательное завершение: ячейка действия освобождается. */
  complete(operationId: string, scope?: string): void
  /**
   * Сетевой/retryable исход: ожидающая запись сохраняется для повтора с тем же
   * ключом. Возвращает сохранённую запись либо `undefined`, если сохранять
   * нечего (фиктивная запись не создаётся).
   */
  retain(operationId: string, scope?: string): IdempotencyRecord | undefined
  /** Очищает всё состояние (logout/401/смена пользователя). */
  clear(): void
}

const FNV_OFFSET_BASIS_64 = 0xcbf29ce484222325n
const FNV_PRIME_64 = 0x100000001b3n
const UINT64_MASK = 0xffffffffffffffffn

/** Стабильная сериализация значения: ключи объектов сортируются. */
function stableSerialize(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value) ?? 'undefined'
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(',')}]`
  }
  const record = value as Record<string, unknown>
  const entries = Object.keys(record)
    .sort()
    .map((name) => `${JSON.stringify(name)}:${stableSerialize(record[name])}`)
  return `{${entries.join(',')}}`
}

/**
 * Детерминированный отпечаток тела (FNV-1a 64). Необратимо преобразует
 * сериализованное тело, поэтому сами тела и секреты не сохраняются.
 */
export function fingerprintBody(body: unknown): string {
  const serialized = stableSerialize(body)
  let hash = FNV_OFFSET_BASIS_64
  for (let index = 0; index < serialized.length; index += 1) {
    hash ^= BigInt(serialized.charCodeAt(index))
    hash = (hash * FNV_PRIME_64) & UINT64_MASK
  }
  return hash.toString(16).padStart(16, '0')
}

/** UUID v4-подобный fallback, если `crypto.randomUUID` недоступен. */
function fallbackUuid(cryptoObject: Crypto | undefined): string {
  const bytes = new Uint8Array(16)
  if (cryptoObject && typeof cryptoObject.getRandomValues === 'function') {
    cryptoObject.getRandomValues(bytes)
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256)
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0'))
  return [
    hex.slice(0, 4).join(''),
    hex.slice(4, 6).join(''),
    hex.slice(6, 8).join(''),
    hex.slice(8, 10).join(''),
    hex.slice(10, 16).join(''),
  ].join('-')
}

/** Возвращает UUID для `Idempotency-Key` с безопасным fallback. */
function generateUuid(): string {
  const cryptoObject = globalThis.crypto
  if (cryptoObject && typeof cryptoObject.randomUUID === 'function') {
    return cryptoObject.randomUUID()
  }
  return fallbackUuid(cryptoObject)
}

/** Ключ ячейки: операция плюс необязательный стабильный action-scope. */
function scopedKey(operationId: string, scope: string | undefined): string {
  return scope ? `${operationId}\u0000${scope}` : operationId
}

/**
 * Создаёт изолированное in-memory хранилище идемпотентности.
 *
 * Фабрика нужна тестам и изоляции: каждый экземпляр имеет собственное
 * состояние и не делит его с module-level `defaultIdempotencyStore`.
 */
export function createIdempotencyStore(): IdempotencyStore {
  const records = new Map<string, IdempotencyRecord>()

  return {
    begin(operationId, body, scope) {
      const mapKey = scopedKey(operationId, scope)
      const bodyFingerprint = fingerprintBody(body)
      const existing = records.get(mapKey)
      if (existing && existing.bodyFingerprint === bodyFingerprint) {
        return existing.key
      }
      const key = generateUuid()
      records.set(mapKey, { key, bodyFingerprint })
      return key
    },
    complete(operationId, scope) {
      records.delete(scopedKey(operationId, scope))
    },
    retain(operationId, scope) {
      // `begin` уже сохраняет ожидающую запись; `retain` подтверждает, что при
      // сетевой неопределённости её нельзя освобождать. Новую запись/ключ здесь
      // не создаём: фиктивная идемпотентность недопустима.
      return records.get(scopedKey(operationId, scope))
    },
    clear() {
      records.clear()
    },
  }
}

/**
 * Session-scoped хранилище по умолчанию: транспорт использует его, когда не
 * передан собственный `idempotencyStore`. `clearSession()`/`emitUnauthorized()`
 * очищают его вместе с остальным клиентским состоянием сессии.
 */
export const defaultIdempotencyStore: IdempotencyStore = createIdempotencyStore()
