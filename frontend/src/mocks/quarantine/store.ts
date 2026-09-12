// In-memory store карантина/возврата для mock-операций
// `listQuarantineItems`/`returnQuarantineItem` (LT-07.3a).
//
// Источник данных — только публичные примеры
// `contracts/examples/quarantine/*.json` (индексируются по
// `fixtures/synthetic/manifest.json`). Store не выполняет возврат, recovery,
// matcher, перемещение файлов и не ведёт журнал: он хранит literal canned-записи
// и воспроизводит объявленные состояния/конфликты.
//
// `QuarantineItem` — серверная запись карантина. `can_return` — флаг
// стабильности возврата из OAS, не право/роль: `false` сопровождается
// зарегистрированным `recovery_operation_id`. `reset()` восстанавливает
// детерминированный seed (подтверждённая техническая запись, revision=1).
//
// Идемпотентность scoped по `user_id` + ключу (API §2): повтор того же
// ключа/тела возвращает прежний исход (успех или зарегистрированный recovery),
// другое тело с тем же ключом — конфликт; тот же ключ у другого пользователя —
// отдельный scope. Ключ проверяется до staleness/state-проверок.

import { cloneJson, getExample } from '../data'
import type {
  QuarantineItem,
  QuarantinePage,
  QuarantineReturnRequest,
  QuarantineReturnResponse,
} from '../types'

/** Канонический id подтверждённой записи карантина (LT-03.5a). */
export const QUARANTINE_ID = 'quarantine-atlas-batch-tech-quarantine'

/** Компания подтверждённой записи карантина. */
export const QUARANTINE_COMPANY_ID = 'company-demo-atlas'

/** Зарегистрированная операция неоднозначного возврата (LT-03.5a). */
export const QUARANTINE_RECOVERY_OPERATION_ID =
  'return-atlas-batch-tech-quarantine-recovery'

/** Управляемое состояние записи карантина. */
export type QuarantineScenario = 'technical' | 'ambiguous' | 'returned'

/** Порядок объявленных состояний карантина. */
export const QUARANTINE_SCENARIOS: readonly QuarantineScenario[] = [
  'technical',
  'ambiguous',
  'returned',
]

/** Разбирает `limit`; `null` — невалидное значение (вне 1..100). */
export function parseQuarantineLimit(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null
  }
  const value = Number.parseInt(raw, 10)
  return value >= 1 && value <= 100 ? value : null
}

/** Параметры страницы `listQuarantineItems`. */
export interface QuarantinePageQuery {
  readonly cursor: string | null
  readonly limit: number | null
}

const OFFSET_CURSOR_PATTERN = /^quarantine-offset-(\d+)$/

/**
 * Строит страницу `QuarantinePage` из literal-записей по непрозрачному
 * курсору `quarantine-offset-<n>` и finite `limit` (1..100). Неизвестный
 * формат курсора → `null` (handler отдаёт 422). Cursor по умолчанию (`null`) —
 * начало; `next_cursor` равен `null`, когда записи исчерпаны.
 */
export function resolveQuarantinePage(
  items: readonly QuarantineItem[],
  query: QuarantinePageQuery,
): QuarantinePage | null {
  let offset = 0
  if (query.cursor !== null) {
    const match = OFFSET_CURSOR_PATTERN.exec(query.cursor)
    if (!match) {
      return null
    }
    offset = Number.parseInt(match[1], 10)
  }
  const pageSize = query.limit ?? 100
  const pageItems = items.slice(offset, offset + pageSize)
  const nextOffset = offset + pageSize
  const nextCursor =
    nextOffset < items.length ? `quarantine-offset-${nextOffset}` : null
  return { items: cloneJson(pageItems), next_cursor: nextCursor }
}

/** Исход зарегистрированной операции возврата. */
export type QuarantineOperationOutcome =
  | { readonly kind: 'returned'; readonly response: QuarantineReturnResponse }
  | { readonly kind: 'recovery'; readonly operationId: string }

/** Результат проверки идемпотентного ключа. */
export type QuarantineOperationLookup =
  | { readonly kind: 'replay'; readonly outcome: QuarantineOperationOutcome }
  | { readonly kind: 'reused' }

interface StoredOperation {
  readonly body: QuarantineReturnRequest
  readonly outcome: QuarantineOperationOutcome
}

/** Запись карантина: literal item плюс признак уже выполненного возврата. */
export interface QuarantineRecord {
  readonly item: QuarantineItem
  readonly returned: boolean
}

/** Сравнивает тело запроса возврата по значимым полям (без учёта порядка). */
function sameBody(
  left: QuarantineReturnRequest,
  right: QuarantineReturnRequest,
): boolean {
  return (
    left.expected_revision === right.expected_revision &&
    left.comment === right.comment
  )
}

/** In-memory store literal-записей карантина и идемпотентных операций. */
export class QuarantineStore {
  private scenario: QuarantineScenario = 'technical'
  private returned = false
  private returnCount = 0
  private readonly operations = new Map<string, StoredOperation>()

  /** Восстанавливает seed: техническая запись, нет возвратов и операций. */
  reset(): void {
    this.scenario = 'technical'
    this.returned = false
    this.returnCount = 0
    this.operations.clear()
  }

  /** Текущее управляемое состояние записи. */
  getScenario(): QuarantineScenario {
    return this.scenario
  }

  /**
   * Выбирает состояние записи: `technical` — возвратимая (can_return=true),
   * `ambiguous` — can_return=false с зарегистрированной recovery-операцией,
   * `returned` — уже возвращённая (повтор с новым ключом → 409 INVALID_STATE).
   */
  setScenario(scenario: QuarantineScenario): void {
    this.scenario = scenario
    this.returned = scenario === 'returned'
  }

  /** Флаг стабильности возврата текущей записи (OAS `can_return`). */
  canReturn(): boolean {
    return this.scenario === 'technical' && !this.returned
  }

  /** Выполнен ли возврат записи (в т.ч. через сценарий `returned`). */
  isReturned(): boolean {
    return this.returned
  }

  /** Число фактически выполненных возвратов (для проверки replay). */
  getReturnCount(): number {
    return this.returnCount
  }

  private baseItem(): QuarantineItem {
    return this.scenario === 'ambiguous'
      ? getExample<QuarantineItem>('quarantine-item-atlas-ambiguous')
      : getExample<QuarantineItem>('quarantine-item-atlas-technical')
  }

  /** Активная literal-запись по id или `undefined`, если id неизвестен. */
  getRecord(quarantineId: string): QuarantineRecord | undefined {
    if (quarantineId !== QUARANTINE_ID) {
      return undefined
    }
    return { item: cloneJson(this.baseItem()), returned: this.returned }
  }

  /**
   * Company-scoped literal-список записей карантина. Возвращаются только
   * подтверждённые записи; RECOVERY_REQUIRED-исходы партии сюда не входят.
   * Неизвестная компания и уже возвращённая запись дают пустой список.
   */
  listByCompany(companyId: string): QuarantineItem[] {
    if (companyId !== QUARANTINE_COMPANY_ID || this.returned) {
      return []
    }
    return [cloneJson(this.baseItem())]
  }

  /**
   * Выполняет успешный возврат: помечает запись возвращённой и отдаёт literal
   * `QuarantineReturnResponse` (item.status=WAITING_READY, selectable=false, без
   * active attempt). Файловых операций и автосортировки нет.
   */
  returnItem(): QuarantineReturnResponse {
    this.returned = true
    this.returnCount += 1
    return getExample<QuarantineReturnResponse>('quarantine-return-response')
  }

  private operationKey(actorUserId: string, key: string): string {
    return `${actorUserId}\n${key}`
  }

  /**
   * Проверяет ключ идемпотентности для актора: `undefined` — ключа нет;
   * `replay` — тот же ключ и тело (прежний исход); `reused` — тот же ключ с
   * другим телом.
   */
  resolveOperation(
    actorUserId: string,
    key: string,
    body: QuarantineReturnRequest,
  ): QuarantineOperationLookup | undefined {
    const stored = this.operations.get(this.operationKey(actorUserId, key))
    if (!stored) {
      return undefined
    }
    if (sameBody(stored.body, body)) {
      return { kind: 'replay', outcome: stored.outcome }
    }
    return { kind: 'reused' }
  }

  /** Регистрирует исход операции для ключа (успех или recovery). */
  recordOperation(
    actorUserId: string,
    key: string,
    body: QuarantineReturnRequest,
    outcome: QuarantineOperationOutcome,
  ): void {
    this.operations.set(this.operationKey(actorUserId, key), {
      body: cloneJson(body),
      outcome,
    })
  }
}
