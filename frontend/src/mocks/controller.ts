// Управление сценариями mock-сервера WiseWay.
//
// Контроллер хранит только воспроизводимое состояние сценария: активную
// mock-сессию, управляемую задержку ответа, профиль app-config (N=100/N=10),
// пустые состояния roots/companies и freshness-профиль поиска
// (CURRENT/UPDATING/STALE). Дополнительно (LT-06.2b) контроллер управляет
// отдельными scope поиска — `search` (таблица) и `facet` (выпадающий список
// уровня): базовой задержкой scope, очередью per-send задержек для
// детерминированного порядка ответов и объявленной ошибкой операции. Никаких
// реальных учётных данных, файлов или сетевых подключений здесь нет: mock не
// является защищённым auth backend.
//
// Задержка инъектируется через `sleep`, поэтому тесты проверяют её без реальных
// ожиданий (controlled clock / fake sleep).

import type { SearchFreshness, Session } from './types'
import type { SearchErrorCode } from './search/errors'
import type { MockDictionaryErrorCode } from './dictionaries/errors'
import type {
  CreateDictionarySimulationErrorCode,
  GetSimulationErrorCode,
  MockSimulationErrorCode,
} from './simulations/errors'
import type {
  GetDictionaryVersionErrorCode,
  ListDictionaryVersionsErrorCode,
  MockPublishingErrorCode,
  PublishDictionaryErrorCode,
  RestoreDictionaryDraftErrorCode,
} from './publishing/errors'
import { DictionaryStore } from './dictionaries/store'
import { SimulationStore, type SimulationScenario } from './simulations/store'
import {
  PublishingStore,
  type PublishingScenario,
} from './publishing/store'

export type ConfigProfile = 'n100' | 'n10'

/** Профиль freshness, выбираемый для `/search` из golden-эталона. */
export type SearchFreshnessProfile = SearchFreshness['status']

/**
 * Независимый request scope поиска (LT-06.2b): `search` — основная таблица
 * (`searchFiles`), `facet` — отдельный выпадающий список уровня
 * (`getSearchFacet`). У каждого scope собственная задержка и очередь per-send
 * задержек, поэтому поздний ответ одного не влияет на другой.
 */
export type MockSearchScope = 'search' | 'facet'

/** Операции поиска, для которых включается управляемая ошибка. */
export type MockSearchOperation = 'searchFiles' | 'getSearchFacet'

/**
 * Операции targets/dictionaries, для которых включается управляемая ошибка
 * (LT-07.1a).
 */
export type MockDictionaryOperation =
  | 'listTargetDirectories'
  | 'resolveTargetDirectory'
  | 'listDictionaries'
  | 'createDictionary'
  | 'getDictionary'
  | 'replaceDictionaryDraft'

/**
 * Операции симуляции, для которых включается управляемая ошибка (LT-07.1b).
 */
export type MockSimulationOperation =
  | 'createDictionarySimulation'
  | 'getSimulation'

/**
 * Операции публикации/версий/восстановления, для которых включается управляемая
 * ошибка (LT-07.1c).
 */
export type MockPublishingOperation =
  | 'publishDictionary'
  | 'listDictionaryVersions'
  | 'getDictionaryVersion'
  | 'restoreDictionaryDraft'

/** Возвращает `true` для операции поиска (иначе — targets/dictionaries). */
function isSearchOperation(
  operation:
    | MockSearchOperation
    | MockDictionaryOperation
    | MockSimulationOperation
    | MockPublishingOperation,
): operation is MockSearchOperation {
  return operation === 'searchFiles' || operation === 'getSearchFacet'
}

/** Возвращает `true` для операции симуляции. */
function isSimulationOperation(
  operation:
    | MockSearchOperation
    | MockDictionaryOperation
    | MockSimulationOperation
    | MockPublishingOperation,
): operation is MockSimulationOperation {
  return (
    operation === 'createDictionarySimulation' ||
    operation === 'getSimulation'
  )
}

/** Возвращает `true` для операции публикации/версий/восстановления. */
function isPublishingOperation(
  operation:
    | MockSearchOperation
    | MockDictionaryOperation
    | MockSimulationOperation
    | MockPublishingOperation,
): operation is MockPublishingOperation {
  return (
    operation === 'publishDictionary' ||
    operation === 'listDictionaryVersions' ||
    operation === 'getDictionaryVersion' ||
    operation === 'restoreDictionaryDraft'
  )
}

export interface MockControllerOptions {
  /** Инъекция ожидания; по умолчанию реальный `setTimeout`. */
  sleep?: (ms: number) => Promise<void>
}

const defaultSleep = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms)
  })

/** Состояние сценариев mock-сервера bootstrap/session/config. */
export class MockController {
  private session: Session | null = null
  private delayMs = 0
  private configProfile: ConfigProfile = 'n100'
  private searchFreshnessProfile: SearchFreshnessProfile = 'CURRENT'
  private rootsEmpty = false
  private companiesEmpty = false
  private requestSequence = 0
  private readonly scopeDelays: Record<MockSearchScope, number> = {
    search: 0,
    facet: 0,
  }
  private readonly sendDelayQueues: Record<MockSearchScope, number[]> = {
    search: [],
    facet: [],
  }
  private readonly persistentErrors = new Map<MockSearchOperation, SearchErrorCode>()
  private readonly nextErrors = new Map<MockSearchOperation, SearchErrorCode[]>()
  private readonly dictionaryStore = new DictionaryStore()
  private readonly persistentDictionaryErrors = new Map<
    MockDictionaryOperation,
    MockDictionaryErrorCode
  >()
  private readonly nextDictionaryErrors = new Map<
    MockDictionaryOperation,
    MockDictionaryErrorCode[]
  >()
  private simulationScenario: SimulationScenario = 'full'
  private readonly simulationStore = new SimulationStore()
  private readonly persistentSimulationErrors = new Map<
    MockSimulationOperation,
    MockSimulationErrorCode
  >()
  private readonly nextSimulationErrors = new Map<
    MockSimulationOperation,
    MockSimulationErrorCode[]
  >()
  private publishingScenario: PublishingScenario = 'v2'
  private publishingNow: string | null = null
  private readonly publishingStore = new PublishingStore()
  private readonly persistentPublishingErrors = new Map<
    MockPublishingOperation,
    MockPublishingErrorCode
  >()
  private readonly nextPublishingErrors = new Map<
    MockPublishingOperation,
    MockPublishingErrorCode[]
  >()
  private readonly sleep: (ms: number) => Promise<void>

  constructor(options: MockControllerOptions = {}) {
    this.sleep = options.sleep ?? defaultSleep
  }

  /** Активная mock-сессия или null. */
  getSession(): Session | null {
    return this.session
  }

  /** Устанавливает активную mock-сессию (без реальной проверки credentials). */
  setSession(session: Session): void {
    this.session = session
  }

  /** Очищает mock-сессию (logout/сброс). */
  clearSession(): void {
    this.session = null
  }

  /** Есть ли активная mock-сессия. */
  isAuthenticated(): boolean {
    return this.session !== null
  }

  /** Текущая управляемая задержка ответа в миллисекундах. */
  getDelayMs(): number {
    return this.delayMs
  }

  /** Задаёт задержку ответа; отрицательные значения приводятся к 0. */
  setDelayMs(ms: number): void {
    this.delayMs = Number.isFinite(ms) ? Math.max(0, Math.floor(ms)) : 0
  }

  /** Ждёт управляемую задержку через инъектированный `sleep`. */
  async wait(): Promise<void> {
    if (this.delayMs > 0) {
      await this.sleep(this.delayMs)
    }
  }

  /** Текущая задержка отдельного scope поиска. */
  getScopeDelay(scope: MockSearchScope): number {
    return this.scopeDelays[scope]
  }

  /**
   * Задаёт базовую задержку отдельного scope поиска; отрицательные значения
   * приводятся к 0. `search` (таблица) и `facet` (список уровня) независимы.
   */
  setScopeDelay(scope: MockSearchScope, ms: number): void {
    this.scopeDelays[scope] = Number.isFinite(ms) ? Math.max(0, Math.floor(ms)) : 0
  }

  /**
   * Очередь per-send задержек scope: следующая отправка возьмёт первое
   * значение, следующая — второе и так далее. Позволяет детерминированно
   * воспроизвести порядок ответов (race), не ожидая реально. Очередь заменяет
   * предыдущую; исчерпание возвращает базовую задержку `setScopeDelay`.
   */
  setSendDelays(scope: MockSearchScope, delays: readonly number[]): void {
    this.sendDelayQueues[scope] = delays.map((ms) =>
      Number.isFinite(ms) ? Math.max(0, Math.floor(ms)) : 0,
    )
  }

  /** Добавляет одно per-send значение в конец очереди scope. */
  enqueueSendDelay(scope: MockSearchScope, ms: number): void {
    const value = Number.isFinite(ms) ? Math.max(0, Math.floor(ms)) : 0
    this.sendDelayQueues[scope].push(value)
  }

  /** Текущая очередь per-send задержек scope (копия, только чтение). */
  getPendingSendDelays(scope: MockSearchScope): number[] {
    return [...this.sendDelayQueues[scope]]
  }

  /** Извлекает задержку следующей отправки scope (очередь → базовая). */
  private consumeSendDelay(scope: MockSearchScope): number {
    const queue = this.sendDelayQueues[scope]
    if (queue.length > 0) {
      return queue.shift() ?? this.scopeDelays[scope]
    }
    return this.scopeDelays[scope]
  }

  /**
   * Ждёт задержку конкретной отправки scope. Сначала расходуется per-send
   * очередь, затем базовая задержка scope. Задержка применяется до нормального
   * lookup handler-а.
   */
  async waitForScope(scope: MockSearchScope): Promise<void> {
    const delay = this.consumeSendDelay(scope)
    if (delay > 0) {
      await this.sleep(delay)
    }
  }

  /**
   * Включает объявленную ошибку для операции до её снятия. Значение — код из
   * публичного `ErrorCode`; тело/статус берутся из контрактного примера.
   */
  setError(operation: MockSearchOperation, code: SearchErrorCode): void
  setError(operation: MockDictionaryOperation, code: MockDictionaryErrorCode): void
  setError(
    operation: 'createDictionarySimulation',
    code: CreateDictionarySimulationErrorCode,
  ): void
  setError(operation: 'getSimulation', code: GetSimulationErrorCode): void
  setError(
    operation: 'publishDictionary',
    code: PublishDictionaryErrorCode,
  ): void
  setError(
    operation: 'listDictionaryVersions',
    code: ListDictionaryVersionsErrorCode,
  ): void
  setError(
    operation: 'getDictionaryVersion',
    code: GetDictionaryVersionErrorCode,
  ): void
  setError(
    operation: 'restoreDictionaryDraft',
    code: RestoreDictionaryDraftErrorCode,
  ): void
  setError(
    operation:
      | MockSearchOperation
      | MockDictionaryOperation
      | MockSimulationOperation
      | MockPublishingOperation,
    code:
      | SearchErrorCode
      | MockDictionaryErrorCode
      | MockSimulationErrorCode
      | MockPublishingErrorCode,
  ): void {
    if (isSearchOperation(operation)) {
      this.persistentErrors.set(operation, code as SearchErrorCode)
    } else if (isSimulationOperation(operation)) {
      this.persistentSimulationErrors.set(
        operation,
        code as MockSimulationErrorCode,
      )
    } else if (isPublishingOperation(operation)) {
      this.persistentPublishingErrors.set(
        operation,
        code as MockPublishingErrorCode,
      )
    } else {
      this.persistentDictionaryErrors.set(
        operation,
        code as MockDictionaryErrorCode,
      )
    }
  }

  /**
   * Включает объявленную ошибку ровно для следующей отправки операции
   * (one-shot). Значения расходуются по порядку; после них действует
   * `setError`.
   */
  failNext(operation: MockSearchOperation, code: SearchErrorCode): void
  failNext(operation: MockDictionaryOperation, code: MockDictionaryErrorCode): void
  failNext(
    operation: 'createDictionarySimulation',
    code: CreateDictionarySimulationErrorCode,
  ): void
  failNext(operation: 'getSimulation', code: GetSimulationErrorCode): void
  failNext(
    operation: 'publishDictionary',
    code: PublishDictionaryErrorCode,
  ): void
  failNext(
    operation: 'listDictionaryVersions',
    code: ListDictionaryVersionsErrorCode,
  ): void
  failNext(
    operation: 'getDictionaryVersion',
    code: GetDictionaryVersionErrorCode,
  ): void
  failNext(
    operation: 'restoreDictionaryDraft',
    code: RestoreDictionaryDraftErrorCode,
  ): void
  failNext(
    operation:
      | MockSearchOperation
      | MockDictionaryOperation
      | MockSimulationOperation
      | MockPublishingOperation,
    code:
      | SearchErrorCode
      | MockDictionaryErrorCode
      | MockSimulationErrorCode
      | MockPublishingErrorCode,
  ): void {
    if (isSearchOperation(operation)) {
      const queue = this.nextErrors.get(operation)
      if (queue) {
        queue.push(code as SearchErrorCode)
      } else {
        this.nextErrors.set(operation, [code as SearchErrorCode])
      }
      return
    }
    if (isSimulationOperation(operation)) {
      const queue = this.nextSimulationErrors.get(operation)
      if (queue) {
        queue.push(code as MockSimulationErrorCode)
      } else {
        this.nextSimulationErrors.set(operation, [
          code as MockSimulationErrorCode,
        ])
      }
      return
    }
    if (isPublishingOperation(operation)) {
      const queue = this.nextPublishingErrors.get(operation)
      if (queue) {
        queue.push(code as MockPublishingErrorCode)
      } else {
        this.nextPublishingErrors.set(operation, [
          code as MockPublishingErrorCode,
        ])
      }
      return
    }
    const queue = this.nextDictionaryErrors.get(operation)
    if (queue) {
      queue.push(code as MockDictionaryErrorCode)
    } else {
      this.nextDictionaryErrors.set(operation, [code as MockDictionaryErrorCode])
    }
  }

  /** Снимает и постоянную, и одноразовые ошибки операции. */
  clearError(operation: MockSearchOperation): void
  clearError(operation: MockDictionaryOperation): void
  clearError(operation: MockSimulationOperation): void
  clearError(operation: MockPublishingOperation): void
  clearError(
    operation:
      | MockSearchOperation
      | MockDictionaryOperation
      | MockSimulationOperation
      | MockPublishingOperation,
  ): void {
    if (isSearchOperation(operation)) {
      this.persistentErrors.delete(operation)
      this.nextErrors.delete(operation)
      return
    }
    if (isSimulationOperation(operation)) {
      this.persistentSimulationErrors.delete(operation)
      this.nextSimulationErrors.delete(operation)
      return
    }
    if (isPublishingOperation(operation)) {
      this.persistentPublishingErrors.delete(operation)
      this.nextPublishingErrors.delete(operation)
      return
    }
    this.persistentDictionaryErrors.delete(operation)
    this.nextDictionaryErrors.delete(operation)
  }

  /**
   * Возвращает ошибку для текущей отправки операции и расходует одноразовую:
   * сначала очередь `failNext`, затем постоянный `setError`.
   */
  consumeError(operation: MockSearchOperation): SearchErrorCode | undefined {
    const queue = this.nextErrors.get(operation)
    if (queue && queue.length > 0) {
      return queue.shift()
    }
    return this.persistentErrors.get(operation)
  }

  /**
   * Возвращает объявленную ошибку targets/dictionaries для текущей отправки и
   * расходует одноразовую (LT-07.1a).
   */
  consumeDictionaryError(
    operation: MockDictionaryOperation,
  ): MockDictionaryErrorCode | undefined {
    const queue = this.nextDictionaryErrors.get(operation)
    if (queue && queue.length > 0) {
      return queue.shift()
    }
    return this.persistentDictionaryErrors.get(operation)
  }

  /**
   * Возвращает объявленную ошибку симуляции для текущей отправки и расходует
   * одноразовую (LT-07.1b).
   */
  consumeSimulationError(
    operation: MockSimulationOperation,
  ): MockSimulationErrorCode | undefined {
    const queue = this.nextSimulationErrors.get(operation)
    if (queue && queue.length > 0) {
      return queue.shift()
    }
    return this.persistentSimulationErrors.get(operation)
  }

  /**
   * Возвращает объявленную ошибку публикации/версий/восстановления для текущей
   * отправки и расходует одноразовую (LT-07.1c).
   */
  consumePublishingError(
    operation: MockPublishingOperation,
  ): MockPublishingErrorCode | undefined {
    const queue = this.nextPublishingErrors.get(operation)
    if (queue && queue.length > 0) {
      return queue.shift()
    }
    return this.persistentPublishingErrors.get(operation)
  }

  /** In-memory store справочников (seed, reset и мутации). */
  getDictionaryStore(): DictionaryStore {
    return this.dictionaryStore
  }

  /** In-memory store симуляций (seed, reset и созданные результаты). */
  getSimulationStore(): SimulationStore {
    return this.simulationStore
  }

  /** In-memory store публикаций/версий/восстановлений (LT-07.1c). */
  getPublishingStore(): PublishingStore {
    return this.publishingStore
  }

  /** Текущий выбранный сценарий успешной публикации (по умолчанию `v2`). */
  getPublishingScenario(): PublishingScenario {
    return this.publishingScenario
  }

  /** Выбирает canned-сценарий успешной публикации (`v2`/`v3`). */
  setPublishingScenario(scenario: PublishingScenario): void {
    this.publishingScenario = scenario
  }

  /**
   * Инъектированное «текущее время» для проверки TTL simulation при publish.
   * `null` (по умолчанию) отключает TTL-проверку: mock не привязан к реальным
   * часам.
   */
  getPublishingNow(): string | null {
    return this.publishingNow
  }

  /** Задаёт «текущее время» (Instant) для TTL-проверки или `null`. */
  setPublishingNow(instant: string | null): void {
    this.publishingNow = instant
  }

  /** Текущий выбранный сценарий симуляции (по умолчанию `full`). */
  getSimulationScenario(): SimulationScenario {
    return this.simulationScenario
  }

  /** Выбирает canned-сценарий `createDictionarySimulation`. */
  setSimulationScenario(scenario: SimulationScenario): void {
    this.simulationScenario = scenario
  }

  /** Текущий профиль app-config. */
  getConfigProfile(): ConfigProfile {
    return this.configProfile
  }

  /** Переключает профиль app-config (N=100 / N=10). */
  setConfigProfile(profile: ConfigProfile): void {
    this.configProfile = profile
  }

  /** Текущий freshness-профиль поиска (CURRENT по умолчанию). */
  getSearchFreshnessProfile(): SearchFreshnessProfile {
    return this.searchFreshnessProfile
  }

  /** Задаёт freshness-профиль, отражаемый в ответах `/search`. */
  setSearchFreshnessProfile(profile: SearchFreshnessProfile): void {
    this.searchFreshnessProfile = profile
  }

  /** Пустое состояние roots. */
  isRootsEmpty(): boolean {
    return this.rootsEmpty
  }

  setRootsEmpty(empty: boolean): void {
    this.rootsEmpty = empty
  }

  /** Пустое состояние companies. */
  isCompaniesEmpty(): boolean {
    return this.companiesEmpty
  }

  setCompaniesEmpty(empty: boolean): void {
    this.companiesEmpty = empty
  }

  /** Выдаёт следующий детерминированный безопасный `X-Request-ID`. */
  nextRequestId(): string {
    this.requestSequence += 1
    return `request-mock-${this.requestSequence}`
  }

  /**
   * Сбрасывает сессию, задержку, профиль, freshness, empty-переопределения,
   * scope-задержки, per-send очереди, управляемые ошибки поиска,
   * targets/dictionaries, симуляции и публикации, а также восстанавливает seed
   * справочников/симуляций/публикаций, сценарии `full`/`v2` и снимает
   * TTL-время publish.
   */
  reset(): void {
    this.session = null
    this.delayMs = 0
    this.configProfile = 'n100'
    this.searchFreshnessProfile = 'CURRENT'
    this.rootsEmpty = false
    this.companiesEmpty = false
    this.requestSequence = 0
    this.scopeDelays.search = 0
    this.scopeDelays.facet = 0
    this.sendDelayQueues.search = []
    this.sendDelayQueues.facet = []
    this.persistentErrors.clear()
    this.nextErrors.clear()
    this.persistentDictionaryErrors.clear()
    this.nextDictionaryErrors.clear()
    this.persistentSimulationErrors.clear()
    this.nextSimulationErrors.clear()
    this.persistentPublishingErrors.clear()
    this.nextPublishingErrors.clear()
    this.simulationScenario = 'full'
    this.publishingScenario = 'v2'
    this.publishingNow = null
    this.dictionaryStore.reset()
    this.simulationStore.reset()
    this.publishingStore.reset()
  }
}
