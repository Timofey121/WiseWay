// In-memory хранилище публикаций, версий и восстановлений для mock-операций
// dictionary lifecycle (LT-07.1c).
//
// Источник данных — только публичные примеры
// `contracts/examples/dictionaries/*.json` (индексируются по
// `fixtures/synthetic/manifest.json`). Никакого matcher, priority selection,
// RuleSet-вычисления или revision bump здесь нет: store хранит literal
// canned-результаты publish/restore и append'ит уже готовые версии.
//
// Модель состояния согласована с `DictionaryStore` и `SimulationStore`:
//  * версии seed'ятся из `version-atlas-general-v1`,
//    `version-atlas-invoices-v1`, `version-nova-general-v1` и отдаются
//    newest-first; publish append'ит `published_version` из canned-ответа;
//  * `activeRuleSet` компании обновляется literal `rule_set` из canned-ответа
//    publish — RuleSet не пересчитывается;
//  * идемпотентность scoped по actor + dictionary + Idempotency-Key: повтор
//    того же ключа/тела возвращает сохранённый результат, другое тело —
//    `IDEMPOTENCY_KEY_REUSED` (обрабатывает handler);
//  * restore помечает черновик как восстановленный, чтобы последующая ручная
//    правка очистила `based_on_version_id` (API §6).
//
// `reset()` восстанавливает детерминированный seed.

import { fingerprintBody } from '@/api/idempotency'

import { cloneJson, getExample } from '../data'
import type {
  Dictionary,
  DictionaryVersion,
  PageDictionaryVersion,
  PublishedDictionaryResponse,
  RuleSet,
} from '../types'

/** Управляемый сценарий успешной публикации (canned v2/v3). */
export type PublishingScenario = 'v2' | 'v3'

/** Порядок объявленных сценариев публикации. */
export const PUBLISHING_SCENARIOS: readonly PublishingScenario[] = ['v2', 'v3']

/** Id canned-примеров успешной публикации по сценарию. */
const PUBLISH_RESULT_EXAMPLE_IDS: Record<PublishingScenario, string> = {
  v2: 'publish-atlas-general-v2',
  v3: 'publish-atlas-general-v3',
}

/**
 * Canned publish/restore-примеры относятся только к справочнику Atlas general:
 * для остальных справочников publish-результат не объявлен (404), а restore
 * собирается из выбранной версии.
 */
const PUBLISH_RESULT_DICTIONARY = 'dictionary-atlas-general'

/** Id seed-версий каждого справочника в хронологическом порядке. */
const VERSION_SEED_EXAMPLE_IDS: Record<string, readonly string[]> = {
  'dictionary-atlas-general': ['version-atlas-general-v1'],
  'dictionary-atlas-invoices': ['version-atlas-invoices-v1'],
  'dictionary-nova-general': ['version-nova-general-v1'],
}

/** Id canned-результата restore по справочнику. */
const RESTORE_RESULT_EXAMPLE_IDS: Record<string, string> = {
  'dictionary-atlas-general': 'dictionary-atlas-general-restored-v1',
}

/** Сохранённая идемпотентная операция публикации (для replay). */
export interface StoredPublishOperation {
  readonly key: string
  readonly actorId: string
  readonly dictionaryId: string
  readonly bodyFingerprint: string
  readonly response: PublishedDictionaryResponse
}

/** Результат проверки Idempotency-Key в store. */
export type PublishOperationLookup =
  | { readonly kind: 'replay'; readonly response: PublishedDictionaryResponse }
  | { readonly kind: 'reused' }

/** Ключ ячейки операции: actor + dictionary + Idempotency-Key. */
function operationKey(
  actorId: string,
  dictionaryId: string,
  key: string,
): string {
  return `${actorId}\u0000${dictionaryId}\u0000${key}`
}

const GENERATED_CURSOR_PATTERN = /^versions-offset-(\d+)$/

/** Разбирает `limit`; `null` — невалидное значение (вне 1..100). */
export function parseVersionsLimit(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null
  }
  const value = Number.parseInt(raw, 10)
  return value >= 1 && value <= 100 ? value : null
}

/** Параметры страницы `listDictionaryVersions`. */
export interface VersionPageQuery {
  cursor: string | null
  limit: number | null
}

/**
 * Возвращает finite-страницу версий (newest-first). `cursor` — только
 * непрозрачный `versions-offset-<n>`; неизвестный курсор → `null` (handler
 * отдаёт 422). `limit` по умолчанию 100 (контракт), поэтому при малом числе
 * версий первая страница равна literal-примеру с `next_cursor: null`.
 */
export function resolveVersionsPage(
  versions: readonly DictionaryVersion[],
  query: VersionPageQuery,
): PageDictionaryVersion | null {
  let offset = 0
  if (query.cursor !== null) {
    const match = GENERATED_CURSOR_PATTERN.exec(query.cursor)
    if (!match) {
      return null
    }
    offset = Number.parseInt(match[1], 10)
  }
  const pageSize = query.limit ?? 100
  const items = versions.slice(offset, offset + pageSize)
  const nextOffset = offset + pageSize
  const nextCursor =
    nextOffset < versions.length ? `versions-offset-${nextOffset}` : null
  return { items: cloneJson(items), next_cursor: nextCursor }
}

/** In-memory store публикаций/версий/восстановлений с seed и `reset()`. */
export class PublishingStore {
  private readonly versionsByDictionary = new Map<string, DictionaryVersion[]>()
  private readonly publishResults = new Map<
    PublishingScenario,
    PublishedDictionaryResponse
  >()
  private readonly restoreResults = new Map<string, Dictionary>()
  private readonly activeRuleSets = new Map<string, RuleSet>()
  private readonly restoredDrafts = new Map<string, string>()
  private readonly operations = new Map<string, StoredPublishOperation>()

  constructor() {
    this.reset()
  }

  /** Восстанавливает базовое состояние из публичных примеров контракта. */
  reset(): void {
    this.versionsByDictionary.clear()
    this.publishResults.clear()
    this.restoreResults.clear()
    this.activeRuleSets.clear()
    this.restoredDrafts.clear()
    this.operations.clear()

    for (const [dictionaryId, ids] of Object.entries(VERSION_SEED_EXAMPLE_IDS)) {
      this.versionsByDictionary.set(
        dictionaryId,
        ids.map((id) => getExample<DictionaryVersion>(id)),
      )
    }
    for (const scenario of PUBLISHING_SCENARIOS) {
      this.publishResults.set(
        scenario,
        getExample<PublishedDictionaryResponse>(
          PUBLISH_RESULT_EXAMPLE_IDS[scenario],
        ),
      )
    }
    for (const [dictionaryId, id] of Object.entries(RESTORE_RESULT_EXAMPLE_IDS)) {
      this.restoreResults.set(dictionaryId, getExample<Dictionary>(id))
    }
  }

  /** История справочника newest-first (копии, не ссылки на store). */
  listVersions(dictionaryId: string): DictionaryVersion[] {
    const versions = this.versionsByDictionary.get(dictionaryId) ?? []
    return [...versions].reverse().map((version) => cloneJson(version))
  }

  /** Версия справочника по id или `undefined` (копия). */
  getVersion(
    dictionaryId: string,
    versionId: string,
  ): DictionaryVersion | undefined {
    const versions = this.versionsByDictionary.get(dictionaryId) ?? []
    const found = versions.find((version) => version.version_id === versionId)
    return found ? cloneJson(found) : undefined
  }

  /**
   * Добавляет опубликованную версию в конец истории (без дублей). Версия уже
   * готова в canned-ответе; store не пересчитывает `version_number`.
   */
  appendVersion(version: DictionaryVersion): void {
    const versions = this.versionsByDictionary.get(version.dictionary_id) ?? []
    if (versions.some((item) => item.version_id === version.version_id)) {
      return
    }
    versions.push(cloneJson(version))
    this.versionsByDictionary.set(version.dictionary_id, versions)
  }

  /**
   * Canned-результат успешной публикации для справочника/сценария или
   * `undefined`, если для этого справочника результат не объявлен.
   */
  getPublishResult(
    dictionaryId: string,
    scenario: PublishingScenario,
  ): PublishedDictionaryResponse | undefined {
    if (dictionaryId !== PUBLISH_RESULT_DICTIONARY) {
      return undefined
    }
    const result = this.publishResults.get(scenario)
    return result ? cloneJson(result) : undefined
  }

  /** Canned-результат restore для справочника или `undefined`. */
  getRestoreResult(dictionaryId: string): Dictionary | undefined {
    const result = this.restoreResults.get(dictionaryId)
    return result ? cloneJson(result) : undefined
  }

  /** Literal RuleSet активных версий компании после publish. */
  setActiveRuleSet(ruleSet: RuleSet): void {
    this.activeRuleSets.set(ruleSet.company_id, cloneJson(ruleSet))
  }

  /** Текущий literal RuleSet компании или `undefined`. */
  getActiveRuleSet(companyId: string): RuleSet | undefined {
    const ruleSet = this.activeRuleSets.get(companyId)
    return ruleSet ? cloneJson(ruleSet) : undefined
  }

  /** Помечает черновик восстановленным из версии (provenance restore). */
  markRestoredDraft(dictionaryId: string, versionId: string): void {
    this.restoredDrafts.set(dictionaryId, versionId)
  }

  /** Восстановлен ли текущий черновик (ручная правка очищает provenance). */
  isRestoredDraft(dictionaryId: string): boolean {
    return this.restoredDrafts.has(dictionaryId)
  }

  /** Снимает пометку restore (после ручной правки черновика). */
  clearRestoredDraft(dictionaryId: string): void {
    this.restoredDrafts.delete(dictionaryId)
  }

  /**
   * Ищет сохранённую операцию publish по actor/dictionary/ключу: `replay` при
   * совпадении отпечатка тела, `reused` при другом теле, `undefined` если
   * ключ не принимался.
   */
  resolveOperation(
    actorId: string,
    dictionaryId: string,
    key: string,
    body: unknown,
  ): PublishOperationLookup | undefined {
    const record = this.operations.get(operationKey(actorId, dictionaryId, key))
    if (!record) {
      return undefined
    }
    if (record.bodyFingerprint === fingerprintBody(body)) {
      return { kind: 'replay', response: cloneJson(record.response) }
    }
    return { kind: 'reused' }
  }

  /** Сохраняет принятую операцию publish для идемпотентного повтора. */
  recordOperation(
    actorId: string,
    dictionaryId: string,
    key: string,
    body: unknown,
    response: PublishedDictionaryResponse,
  ): void {
    this.operations.set(operationKey(actorId, dictionaryId, key), {
      key,
      actorId,
      dictionaryId,
      bodyFingerprint: fingerprintBody(body),
      response: cloneJson(response),
    })
  }
}
