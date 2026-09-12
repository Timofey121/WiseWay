// Canned-состояние журнала аудита для mock-операций `queryAuditEvents`,
// `getAuditUpdates` и `listAuditActors` (LT-07.3b).
//
// Источник данных — публичные примеры `contracts/examples/audit/*.json`
// (индексируются по `fixtures/synthetic/manifest.json`):
// `audit-query-day-atlas`, `audit-query-batch-accepted`, `audit-query-issue`,
// `audit-query-cursor-page2`, `audit-query-empty-window`,
// `audit-actors-atlas`, `audit-updates-after-known`.
//
// События категории SYSTEM (включая единственный допустимый `actor=null` для
// неинициированного `LOGIN_FAILED`) взяты literal из канонического
// синтетического эталона `fixtures/synthetic/audit_expectations.json`
// (`explicit_events`) и приведены к полному `AuditEvent`; снимок автора — из
// публичного `audit-actors-atlas`. Mock НЕ ведёт журнал, не реализует запись,
// immutability, серверный фильтр-алгоритм, cursor-store или actor-directory:
// он делает lookup заранее заданной canned-страницы по фильтрам/сценарию и
// простой отбор literal-элементов по `actor_id`/`query_text`.
//
// Роль видимости: WORKER видит только BUSINESS, ADMIN — BUSINESS+SYSTEM
// (canned-переключение). `actor=null` не выдумывается: он остаётся только у
// SYSTEM-события `LOGIN_FAILED` без установленного инициатора.
//
// `reset()` восстанавливает сценарий по умолчанию (`day`, роль берётся из
// сессии) и снимает флаг пустого журнала.

import { cloneJson, getExample } from '../data'
import type {
  Actor,
  ActorPage,
  AuditEvent,
  AuditQueryRequest,
  AuditQueryResponse,
  AuditUpdatesResponse,
} from '../types'

/** Компания, для которой объявлена canned-страница журнала. */
export const AUDIT_ATLAS_COMPANY_ID = 'company-demo-atlas'

/** Новейшее доступное ADMIN-событие канонического дня. */
export const AUDIT_NEWEST_EVENT_ID = 'AUD-LOGIN-SUCCESS-WORKER2-LATE'

/**
 * Новейшее доступное WORKER-событие: SYSTEM-события рабочей роли не видны,
 * поэтому индикатор новизны для WORKER привязан к новейшему BUSINESS-событию.
 */
export const AUDIT_WORKER_NEWEST_EVENT_ID = 'AUD-QR-RETURN-RECOVERY'

/** Объявленный id публичного примера страницы авторов. */
export const AUDIT_ACTORS_PAGE_ID = 'audit-actors-atlas'

/** Известные курсоры второй страницы журнала (canned page2). */
export const AUDIT_QUERY_PAGE2_CURSORS: readonly string[] = [
  'cursor-audit-atlas-page2',
  'cursor-audit-primary-page2',
]

/**
 * Граница canned-дня: окно, начинающееся в 10:00 UTC, уже не содержит
 * ни одного canned-события (новейшее — 09:58 UTC) и даёт пустую страницу.
 */
const AUDIT_EMPTY_WINDOW_FROM = '2031-05-10T10:00:00Z'

/** Управляемый canned-сценарий страницы журнала. */
export type AuditScenario =
  | 'day'
  | 'issue'
  | 'batch-accepted'
  | 'cursor-page2'
  | 'empty'

/** Порядок объявленных сценариев. */
export const AUDIT_SCENARIOS: readonly AuditScenario[] = [
  'day',
  'issue',
  'batch-accepted',
  'cursor-page2',
  'empty',
]

/** Роль читателя журнала из сессии. */
export type AuditRole = 'WORKER' | 'ADMIN'

const QUERY_EXAMPLE_BY_SCENARIO: Readonly<Record<AuditScenario, string>> = {
  day: 'audit-query-day-atlas',
  issue: 'audit-query-issue',
  'batch-accepted': 'audit-query-batch-accepted',
  'cursor-page2': 'audit-query-cursor-page2',
  empty: 'audit-query-empty-window',
}

/** Разбирает `limit`; `null` — невалидное значение (вне 1..100). */
export function parseAuditLimit(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null
  }
  const value = Number.parseInt(raw, 10)
  return value >= 1 && value <= 100 ? value : null
}

/** Проверяет объявленный порядок интервала `[from,to)`: `from < to`. */
export function isValidAuditInterval(from: string, to: string): boolean {
  const fromMs = Date.parse(from)
  const toMs = Date.parse(to)
  return (
    Number.isFinite(fromMs) && Number.isFinite(toMs) && fromMs < toMs
  )
}

function isAfterCannedDay(from: string): boolean {
  const fromMs = Date.parse(from)
  const boundaryMs = Date.parse(AUDIT_EMPTY_WINDOW_FROM)
  return Number.isFinite(fromMs) && fromMs >= boundaryMs
}

/**
 * Определяет canned-сценарий по фильтрам запроса (lookup, не серверный
 * фильтр-алгоритм): action/result/курсор/окно/компания выбирают объявленную
 * страницу. Неизвестный непустой курсор и окно после canned-дня дают
 * безопасную пустую страницу, а не выдуманный успех.
 */
export function deriveAuditScenario(
  request: AuditQueryRequest,
): AuditScenario {
  if (request.action === 'BATCH_ACCEPTED') {
    return 'batch-accepted'
  }
  if (request.result === 'ISSUE') {
    return 'issue'
  }
  if (request.cursor !== null) {
    return AUDIT_QUERY_PAGE2_CURSORS.includes(request.cursor)
      ? 'cursor-page2'
      : 'empty'
  }
  if (isAfterCannedDay(request.from)) {
    return 'empty'
  }
  if (
    request.company_id !== null &&
    request.company_id !== AUDIT_ATLAS_COMPANY_ID
  ) {
    return 'empty'
  }
  return 'day'
}

/** Литеральное описание SYSTEM-события канонического эталона (LT-03.5b). */
interface SystemEventSpec {
  readonly event_id: string
  readonly action: AuditEvent['action']
  readonly result: AuditEvent['result']
  readonly actor_user_id: string | null
  readonly occurred_at: string
  readonly request_id: string
}

const SYSTEM_EVENT_SPECS: readonly SystemEventSpec[] = [
  {
    event_id: 'AUD-LOGIN-SUCCESS-WORKER1',
    action: 'LOGIN_SUCCEEDED',
    result: 'SUCCESS',
    actor_user_id: 'user-demo-worker-1',
    occurred_at: '2031-05-10T08:30:00Z',
    request_id: 'request-login-01',
  },
  {
    event_id: 'AUD-LOGIN-SUCCESS-ADMIN',
    action: 'LOGIN_SUCCEEDED',
    result: 'SUCCESS',
    actor_user_id: 'user-demo-admin-1',
    occurred_at: '2031-05-10T08:31:00Z',
    request_id: 'request-login-02',
  },
  {
    event_id: 'AUD-LOGIN-FAILED-ANONYMOUS',
    action: 'LOGIN_FAILED',
    result: 'FAILED',
    actor_user_id: null,
    occurred_at: '2031-05-10T08:32:00Z',
    request_id: 'request-login-03',
  },
  {
    event_id: 'AUD-LOGIN-FAILED-KNOWN',
    action: 'LOGIN_FAILED',
    result: 'FAILED',
    actor_user_id: 'user-demo-worker-2',
    occurred_at: '2031-05-10T08:33:00Z',
    request_id: 'request-login-04',
  },
  {
    event_id: 'AUD-ACCOUNT-BLOCKED',
    action: 'ACCOUNT_BLOCKED',
    result: 'SUCCESS',
    actor_user_id: 'user-demo-admin-1',
    occurred_at: '2031-05-10T08:34:00Z',
    request_id: 'request-account-block-01',
  },
  {
    event_id: 'AUD-LOGOUT-SYSTEM',
    action: 'LOGOUT',
    result: 'SUCCESS',
    actor_user_id: 'user-demo-worker-1',
    occurred_at: '2031-05-10T09:36:00Z',
    request_id: 'request-demo-batch-14',
  },
  {
    event_id: AUDIT_NEWEST_EVENT_ID,
    action: 'LOGIN_SUCCEEDED',
    result: 'SUCCESS',
    actor_user_id: 'user-demo-worker-2',
    occurred_at: '2031-05-10T09:58:00Z',
    request_id: 'request-login-05',
  },
]

function requireActor(actors: Map<string, Actor>, userId: string): Actor {
  const actor = actors.get(userId)
  if (!actor) {
    throw new Error(
      `Автор "${userId}" отсутствует в публичном примере ${AUDIT_ACTORS_PAGE_ID}`,
    )
  }
  return actor
}

/** Собирает literal SYSTEM-события со снимком автора из публичного примера. */
function getSystemEvents(): AuditEvent[] {
  const actors = new Map(
    getExample<ActorPage>(AUDIT_ACTORS_PAGE_ID).items.map((actor) => [
      actor.user_id,
      actor,
    ]),
  )
  return SYSTEM_EVENT_SPECS.map((spec) => ({
    event_id: spec.event_id,
    occurred_at: spec.occurred_at,
    actor:
      spec.actor_user_id === null
        ? null
        : cloneJson(requireActor(actors, spec.actor_user_id)),
    category: 'SYSTEM',
    action: spec.action,
    result: spec.result,
    request_id: spec.request_id,
    operation_id: null,
    source_attempt_id: null,
    company_id: null,
    dictionary_id: null,
    version_id: null,
    rule_set_id: null,
    batch_id: null,
    attempt_id: null,
    item_id: null,
    source: null,
    target: null,
    reason_code: null,
    comment: null,
  }))
}

/** Порядок ленты: `occurred_at` DESC, затем `event_id` DESC. */
function byOccurredAtDesc(left: AuditEvent, right: AuditEvent): number {
  if (left.occurred_at !== right.occurred_at) {
    return left.occurred_at < right.occurred_at ? 1 : -1
  }
  if (left.event_id === right.event_id) {
    return 0
  }
  return left.event_id < right.event_id ? 1 : -1
}

function searchableText(item: AuditEvent): string {
  return [
    item.item_id,
    item.source?.relative_path,
    item.source?.display_path,
    item.target?.relative_path,
    item.target?.display_path,
  ]
    .filter((value): value is string => typeof value === 'string')
    .join(' ')
    .toLowerCase()
}

/** Параметры страницы авторов. */
export interface AuditActorsQuery {
  readonly prefix: string
  readonly cursor: string | null
  readonly limit: number | null
}

const ACTORS_CURSOR_PATTERN = /^audit-actors-offset-(\d+)$/

/** In-memory canned-состояние журнала аудита и его lookup-резолверы. */
export class AuditStore {
  private scenario: AuditScenario | null = null
  private emptyJournal = false

  /** Восстанавливает сценарий по умолчанию и непустой журнал. */
  reset(): void {
    this.scenario = null
    this.emptyJournal = false
  }

  /** Явно выбранный сценарий или `null` (выводится из фильтров). */
  getScenario(): AuditScenario | null {
    return this.scenario
  }

  /** Выбирает canned-сценарий или снимает override (`null`). */
  setScenario(scenario: AuditScenario | null): void {
    this.scenario = scenario
  }

  /** Флаг «журнал пуст» (первичный пустой журнал обновлений). */
  isEmptyJournal(): boolean {
    return this.emptyJournal
  }

  /** Управляет флагом пустого журнала. */
  setEmptyJournal(empty: boolean): void {
    this.emptyJournal = empty
  }

  /**
   * Lookup canned-страницы `queryAuditEvents` по фильтрам/сценарию и роли.
   * ADMIN получает BUSINESS+SYSTEM для полного журнала (company_id=null),
   * WORKER — только BUSINESS. Дополнительные фильтры (`action`/`result` вне
   * уже выбранного canned-сценария, `actor_id`, `query_text`) отбирают
   * literal-элементы уже выбранной страницы (без серверного matcher/ranking).
   */
  resolveQuery(
    request: AuditQueryRequest,
    role: AuditRole,
  ): AuditQueryResponse {
    const scenario = this.scenario ?? deriveAuditScenario(request)
    const example = getExample<AuditQueryResponse>(
      QUERY_EXAMPLE_BY_SCENARIO[scenario],
    )
    let items = cloneJson(example.items)
    let nextCursor = example.next_cursor
    let newestEventId = example.newest_event_id

    if (scenario === 'day' && role === 'ADMIN' && request.company_id === null) {
      items = [...getSystemEvents(), ...items].sort(byOccurredAtDesc)
      newestEventId = items[0]?.event_id ?? null
    }

    const actionFiltered =
      request.action !== null && scenario !== 'batch-accepted'
    const resultFiltered = request.result !== null && scenario !== 'issue'
    const actorId = request.actor_id
    const queryText = request.query_text.trim().toLowerCase()
    const postFiltered =
      actionFiltered ||
      resultFiltered ||
      actorId !== null ||
      queryText.length > 0

    if (postFiltered) {
      items = items.filter((item) => {
        if (actionFiltered && item.action !== request.action) {
          return false
        }
        if (resultFiltered && item.result !== request.result) {
          return false
        }
        if (actorId !== null && item.actor?.user_id !== actorId) {
          return false
        }
        if (queryText.length > 0 && !searchableText(item).includes(queryText)) {
          return false
        }
        return true
      })
      nextCursor = null
      newestEventId = items[0]?.event_id ?? null
    }

    return {
      items,
      next_cursor: nextCursor,
      newest_event_id: newestEventId,
    }
  }

  /**
   * Индикатор новых событий. Без `after_event_id` нижней границы нет: непустой
   * журнал сообщает `true`, пустой — `false`. Иначе сравнивается с новейшим
   * доступным событием роли.
   */
  resolveUpdates(
    afterEventId: string | null,
    role: AuditRole,
  ): AuditUpdatesResponse {
    if (this.emptyJournal) {
      return { has_new_events: false }
    }
    if (afterEventId === null) {
      return { has_new_events: true }
    }
    const newest =
      role === 'ADMIN'
        ? AUDIT_NEWEST_EVENT_ID
        : AUDIT_WORKER_NEWEST_EVENT_ID
    return { has_new_events: afterEventId !== newest }
  }

  /**
   * Canned-страница авторов: literal `audit-actors-atlas`, регистронезависимый
   * prefix по login/display_name, заблокированный автор с событиями остаётся.
   * Неизвестный формат курсора → `null` (handler отдаёт 422).
   */
  resolveActors(query: AuditActorsQuery): ActorPage | null {
    const page = getExample<ActorPage>(AUDIT_ACTORS_PAGE_ID)
    const prefix = query.prefix.trim().toLowerCase()
    const filtered = page.items.filter(
      (actor) =>
        prefix.length === 0 ||
        actor.login.toLowerCase().startsWith(prefix) ||
        actor.display_name.toLowerCase().startsWith(prefix),
    )

    let offset = 0
    if (query.cursor !== null) {
      const match = ACTORS_CURSOR_PATTERN.exec(query.cursor)
      if (!match) {
        return null
      }
      offset = Number.parseInt(match[1], 10)
    }
    const pageSize = query.limit ?? 100
    const items = filtered.slice(offset, offset + pageSize)
    const nextOffset = offset + pageSize
    const nextCursor =
      nextOffset < filtered.length
        ? `audit-actors-offset-${nextOffset}`
        : null
    return { items: cloneJson(items), next_cursor: nextCursor }
  }
}
