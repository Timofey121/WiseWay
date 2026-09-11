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
  setError(operation: MockSearchOperation, code: SearchErrorCode): void {
    this.persistentErrors.set(operation, code)
  }

  /**
   * Включает объявленную ошибку ровно для следующей отправки операции
   * (one-shot). Значения расходуются по порядку; после них действует
   * `setError`.
   */
  failNext(operation: MockSearchOperation, code: SearchErrorCode): void {
    const queue = this.nextErrors.get(operation)
    if (queue) {
      queue.push(code)
    } else {
      this.nextErrors.set(operation, [code])
    }
  }

  /** Снимает и постоянную, и одноразовые ошибки операции. */
  clearError(operation: MockSearchOperation): void {
    this.persistentErrors.delete(operation)
    this.nextErrors.delete(operation)
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
   * scope-задержки, per-send очереди и управляемые ошибки поиска.
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
  }
}
