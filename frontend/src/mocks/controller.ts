// Управление сценариями mock-сервера WiseWay.
//
// Контроллер хранит только воспроизводимое состояние сценария: активную
// mock-сессию, управляемую задержку ответа, профиль app-config (N=100/N=10),
// пустые состояния roots/companies и freshness-профиль поиска
// (CURRENT/UPDATING/STALE). Дополнительно (LT-06.2b) контроллер управляет
// отдельными scope поиска — `search` (таблица) и `facet` (выпадающий список
// уровня): базовой задержкой scope, очередью per-send задержек для
// детерминированного порядка ответов и объявленной ошибкой операции.
// Контроллер также управляет canned-сценариями и TTL-временем сортировки:
// queue/selection (LT-07.2a) и preview (LT-07.2b, `setPreviewScenario`/
// `setPreviewNow`). Никаких
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
import {
  isBatchErrorDeclaredForOperation,
  type MockBatchErrorCode,
  type MockBatchOperation,
} from './sorting/batch-errors'
import {
  BatchStore,
  type BatchPhase,
  type BatchScenario,
} from './sorting/batch'
import {
  isPreviewErrorCode,
  isSortingErrorDeclaredForOperation,
  type CreateSortingPreviewErrorCode,
  type CreateSortingSelectionErrorCode,
  type GetSortingPreviewErrorCode,
  type MockPreviewErrorCode,
  type MockPreviewOperation,
  type MockSortingErrorCode,
  type MockSortingOperation,
  type QuerySortingQueueErrorCode,
} from './sorting/errors'
import type { PreviewScenario } from './sorting/preview'
import { PreviewStore } from './sorting/preview'
import type { QueueScenario } from './sorting/queue'
import { SelectionStore } from './sorting/selection'
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

/**
 * Gate создания партии, воспроизводимый управляемо (LT-07.2c): изменённый
 * источник DIRECT, устаревший preview PREVIEWED и превышение предела партии.
 */
export type BatchGate =
  | 'SELECTION_CHANGED'
  | 'STALE_PREVIEW'
  | 'BATCH_LIMIT_EXCEEDED'

/** Любая операция, для которой контроллер умеет управлять ошибкой. */
type MockOperation =
  | MockSearchOperation
  | MockDictionaryOperation
  | MockSimulationOperation
  | MockPublishingOperation
  | MockSortingOperation
  | MockBatchOperation

/** Возвращает `true` для операции поиска (иначе — targets/dictionaries). */
function isSearchOperation(
  operation: MockOperation,
): operation is MockSearchOperation {
  return operation === 'searchFiles' || operation === 'getSearchFacet'
}

/** Возвращает `true` для операции симуляции. */
function isSimulationOperation(
  operation: MockOperation,
): operation is MockSimulationOperation {
  return (
    operation === 'createDictionarySimulation' ||
    operation === 'getSimulation'
  )
}

/** Возвращает `true` для операции публикации/версий/восстановления. */
function isPublishingOperation(
  operation: MockOperation,
): operation is MockPublishingOperation {
  return (
    operation === 'publishDictionary' ||
    operation === 'listDictionaryVersions' ||
    operation === 'getDictionaryVersion' ||
    operation === 'restoreDictionaryDraft'
  )
}

/** Возвращает `true` для операции очереди/выбора/preview (LT-07.2a/07.2b). */
function isSortingOperation(
  operation: MockOperation,
): operation is MockSortingOperation {
  return (
    operation === 'querySortingQueue' ||
    operation === 'createSortingSelection' ||
    operation === 'createSortingPreview' ||
    operation === 'getSortingPreview'
  )
}

/** Возвращает `true` для операции партий (LT-07.2c). */
function isBatchOperation(
  operation: MockOperation,
): operation is MockBatchOperation {
  return (
    operation === 'createSortingBatch' ||
    operation === 'getSortingBatch' ||
    operation === 'listSortingBatches'
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
  private queueScenario: QueueScenario = 'ready-120'
  private eligibleCountOverride: number | null = null
  private selectionNow: string | null = null
  private readonly selectionStore = new SelectionStore()
  private previewScenario: PreviewScenario | null = null
  private previewNow: string | null = null
  private readonly previewStore = new PreviewStore()
  private readonly persistentSortingErrors = new Map<
    MockSortingOperation,
    MockSortingErrorCode
  >()
  private readonly nextSortingErrors = new Map<
    MockSortingOperation,
    MockSortingErrorCode[]
  >()
  private batchScenario: BatchScenario | null = null
  private batchPhase: BatchPhase | null = null
  private batchGate: BatchGate | null = null
  private readonly batchStore = new BatchStore()
  private readonly persistentBatchErrors = new Map<
    MockBatchOperation,
    MockBatchErrorCode
  >()
  private readonly nextBatchErrors = new Map<
    MockBatchOperation,
    MockBatchErrorCode[]
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
    operation: 'querySortingQueue',
    code: QuerySortingQueueErrorCode,
  ): void
  setError(
    operation: 'createSortingSelection',
    code: CreateSortingSelectionErrorCode,
  ): void
  setError(
    operation: 'createSortingPreview',
    code: CreateSortingPreviewErrorCode,
  ): void
  setError(
    operation: 'getSortingPreview',
    code: GetSortingPreviewErrorCode,
  ): void
  setError(operation: MockBatchOperation, code: MockBatchErrorCode): void
  setError(
    operation: MockOperation,
    code:
      | SearchErrorCode
      | MockDictionaryErrorCode
      | MockSimulationErrorCode
      | MockPublishingErrorCode
      | MockSortingErrorCode
      | MockBatchErrorCode,
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
    } else if (isBatchOperation(operation)) {
      const batchCode = code as MockBatchErrorCode
      // Runtime-guard: код, не объявленный для операции, игнорируется, чтобы
      // mock не мог отдать undeclared HTTP-статус.
      if (!isBatchErrorDeclaredForOperation(operation, batchCode)) {
        return
      }
      this.persistentBatchErrors.set(operation, batchCode)
    } else if (isSortingOperation(operation)) {
      const sortingCode = code as MockSortingErrorCode
      // Runtime-guard: код, не объявленный для операции, игнорируется, чтобы
      // mock не мог отдать undeclared HTTP-статус.
      if (!isSortingErrorDeclaredForOperation(operation, sortingCode)) {
        return
      }
      this.persistentSortingErrors.set(operation, sortingCode)
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
    operation: 'querySortingQueue',
    code: QuerySortingQueueErrorCode,
  ): void
  failNext(
    operation: 'createSortingSelection',
    code: CreateSortingSelectionErrorCode,
  ): void
  failNext(
    operation: 'createSortingPreview',
    code: CreateSortingPreviewErrorCode,
  ): void
  failNext(
    operation: 'getSortingPreview',
    code: GetSortingPreviewErrorCode,
  ): void
  failNext(operation: MockBatchOperation, code: MockBatchErrorCode): void
  failNext(
    operation: MockOperation,
    code:
      | SearchErrorCode
      | MockDictionaryErrorCode
      | MockSimulationErrorCode
      | MockPublishingErrorCode
      | MockSortingErrorCode
      | MockBatchErrorCode,
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
    if (isBatchOperation(operation)) {
      const batchCode = code as MockBatchErrorCode
      // Runtime-guard: необъявленный для операции код не ставится в очередь.
      if (!isBatchErrorDeclaredForOperation(operation, batchCode)) {
        return
      }
      const queue = this.nextBatchErrors.get(operation)
      if (queue) {
        queue.push(batchCode)
      } else {
        this.nextBatchErrors.set(operation, [batchCode])
      }
      return
    }
    if (isSortingOperation(operation)) {
      const sortingCode = code as MockSortingErrorCode
      // Runtime-guard: необъявленный для операции код не ставится в очередь.
      if (!isSortingErrorDeclaredForOperation(operation, sortingCode)) {
        return
      }
      const queue = this.nextSortingErrors.get(operation)
      if (queue) {
        queue.push(sortingCode)
      } else {
        this.nextSortingErrors.set(operation, [sortingCode])
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
  clearError(operation: MockSortingOperation): void
  clearError(operation: MockBatchOperation): void
  clearError(operation: MockOperation): void {
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
    if (isBatchOperation(operation)) {
      this.persistentBatchErrors.delete(operation)
      this.nextBatchErrors.delete(operation)
      return
    }
    if (isSortingOperation(operation)) {
      this.persistentSortingErrors.delete(operation)
      this.nextSortingErrors.delete(operation)
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

  /**
   * Возвращает объявленную ошибку очереди/выбора для текущей отправки и
   * расходует одноразовую (LT-07.2a). Код, не объявленный для операции,
   * никогда не возвращается (защита от undeclared статуса).
   */
  consumeSortingError(
    operation: MockSortingOperation,
  ): MockSortingErrorCode | undefined {
    const queue = this.nextSortingErrors.get(operation)
    if (queue && queue.length > 0) {
      const code = queue.shift()
      if (
        code !== undefined &&
        isSortingErrorDeclaredForOperation(operation, code)
      ) {
        return code
      }
    }
    const persistent = this.persistentSortingErrors.get(operation)
    if (
      persistent !== undefined &&
      isSortingErrorDeclaredForOperation(operation, persistent)
    ) {
      return persistent
    }
    return undefined
  }

  /**
   * Возвращает объявленную ошибку preview для текущей отправки (LT-07.2b).
   * Набор кода ограничен per-operation списком preview-операции, поэтому
   * undeclared код (например `STALE_PREVIEW`) не возвращается.
   */
  consumePreviewError(
    operation: MockPreviewOperation,
  ): MockPreviewErrorCode | undefined {
    const code = this.consumeSortingError(operation)
    return code !== undefined && isPreviewErrorCode(code) ? code : undefined
  }

  /**
   * Возвращает объявленную ошибку партии для текущей отправки и расходует
   * одноразовую (LT-07.2c). Код, не объявленный для операции, никогда не
   * возвращается (защита от undeclared статуса).
   */
  consumeBatchError(
    operation: MockBatchOperation,
  ): MockBatchErrorCode | undefined {
    const queue = this.nextBatchErrors.get(operation)
    if (queue && queue.length > 0) {
      const code = queue.shift()
      if (
        code !== undefined &&
        isBatchErrorDeclaredForOperation(operation, code)
      ) {
        return code
      }
    }
    const persistent = this.persistentBatchErrors.get(operation)
    if (
      persistent !== undefined &&
      isBatchErrorDeclaredForOperation(operation, persistent)
    ) {
      return persistent
    }
    return undefined
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

  /** Текущий выбранный queue-сценарий (по умолчанию `ready-120`). */
  getQueueScenario(): QueueScenario {
    return this.queueScenario
  }

  /** Выбирает canned-сценарий `querySortingQueue`. */
  setQueueScenario(scenario: QueueScenario): void {
    this.queueScenario = scenario
  }

  /**
   * Переопределение текущего eligible_count для ALL_MATCHING-выбора; `null`
   * (по умолчанию) — использовать canned значение queue-сценария. Позволяет
   * воспроизвести `expected_eligible_count` mismatch.
   */
  getEligibleCountOverride(): number | null {
    return this.eligibleCountOverride
  }

  /** Задаёт переопределение eligible_count или `null` (без переопределения). */
  setEligibleCountOverride(count: number | null): void {
    this.eligibleCountOverride =
      count === null || !Number.isFinite(count) ? null : Math.max(0, Math.floor(count))
  }

  /**
   * Инъектированное «текущее время» (Instant) для проверки TTL снимка выбора;
   * `null` (по умолчанию) отключает TTL-проверку. Сама create-операция TTL не
   * проверяет: время использует резолвер снимка для preview/batch.
   */
  getSelectionNow(): string | null {
    return this.selectionNow
  }

  /** Задаёт «текущее время» (Instant) для TTL-проверки снимка или `null`. */
  setSelectionNow(instant: string | null): void {
    this.selectionNow = instant
  }

  /** In-memory store созданных снимков выбора (LT-07.2a). */
  getSelectionStore(): SelectionStore {
    return this.selectionStore
  }

  /**
   * Явно выбранный preview-сценарий или `null` (по умолчанию). `null` означает,
   * что `createSortingPreview` выводит сценарий из разрешённого снимка:
   * EXPLICIT one/multiple, ALL_MATCHING 120. `hetero`/`conflict` выбираются
   * явно.
   */
  getPreviewScenario(): PreviewScenario | null {
    return this.previewScenario
  }

  /** Выбирает canned preview-сценарий или снимает override (`null`). */
  setPreviewScenario(scenario: PreviewScenario | null): void {
    this.previewScenario = scenario
  }

  /**
   * Инъектированное «текущее время» (Instant) для проверки TTL preview.
   * `null` (по умолчанию) отключает TTL-проверку. Preview create/get его не
   * применяют: `create` проверяет срок снимка (`setSelectionNow`), `get` 409 не
   * объявляет и срок не продлевает.
   */
  getPreviewNow(): string | null {
    return this.previewNow
  }

  /** Задаёт «текущее время» (Instant) для TTL preview или `null`. */
  setPreviewNow(instant: string | null): void {
    this.previewNow = instant
  }

  /** In-memory store созданных preview (LT-07.2b). */
  getPreviewStore(): PreviewStore {
    return this.previewStore
  }

  /**
   * Явно выбранный batch-сценарий или `null` (по умолчанию). `null` означает,
   * что `createSortingBatch` выводит сценарий из `execution_mode`
   * (DIRECT/PREVIEWED), а `getSortingBatch` — из фазы прогресса или
   * канонического сценария сохранённой партии.
   */
  getBatchScenario(): BatchScenario | null {
    return this.batchScenario
  }

  /** Выбирает canned batch-сценарий или снимает override (`null`). */
  setBatchScenario(scenario: BatchScenario | null): void {
    this.batchScenario = scenario
  }

  /**
   * Фаза прогресса партии для `getSortingBatch` или `null` (по умолчанию).
   * Позволяет переключать `ACCEPTED`→`RUNNING`→`COMPLETED`/… и отдавать
   * прогрессирующие canned-страницы без реальных таймеров.
   */
  getBatchPhase(): BatchPhase | null {
    return this.batchPhase
  }

  /** Задаёт фазу прогресса или снимает override (`null`). */
  setBatchPhase(phase: BatchPhase | null): void {
    this.batchPhase = phase
  }

  /**
   * Управляемый gate создания партии или `null` (по умолчанию): изменённый
   * источник DIRECT (`SELECTION_CHANGED`), устаревший preview PREVIEWED
   * (`STALE_PREVIEW`) или превышение предела партии (`BATCH_LIMIT_EXCEEDED`).
   */
  getBatchGate(): BatchGate | null {
    return this.batchGate
  }

  /** Задаёт управляемый gate создания партии или снимает его (`null`). */
  setBatchGate(gate: BatchGate | null): void {
    this.batchGate = gate
  }

  /** In-memory store принятых партий и идемпотентных операций (LT-07.2c). */
  getBatchStore(): BatchStore {
    return this.batchStore
  }

  /**
   * Заполняет store literal-историей `batch-history-atlas-page1` для
   * `listSortingBatches`/`getSortingBatch` без предварительного создания.
   */
  seedBatchHistory(): void {
    this.batchStore.seedHistory()
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
   * targets/dictionaries, симуляции, публикации, очереди/выбора, preview и
   * партий, а также восстанавливает seed справочников/симуляций/публикаций,
   * сценарии `full`/`v2`/`ready-120`, снимает TTL-время publish/selection/
   * preview, batch-сценарий/фазу/gate и очищает созданные снимки выбора,
   * preview и партии.
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
    this.persistentSortingErrors.clear()
    this.nextSortingErrors.clear()
    this.persistentBatchErrors.clear()
    this.nextBatchErrors.clear()
    this.simulationScenario = 'full'
    this.publishingScenario = 'v2'
    this.publishingNow = null
    this.queueScenario = 'ready-120'
    this.eligibleCountOverride = null
    this.selectionNow = null
    this.previewScenario = null
    this.previewNow = null
    this.batchScenario = null
    this.batchPhase = null
    this.batchGate = null
    this.dictionaryStore.reset()
    this.simulationStore.reset()
    this.publishingStore.reset()
    this.selectionStore.reset()
    this.previewStore.reset()
    this.batchStore.reset()
  }
}
