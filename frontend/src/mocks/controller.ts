// Управление сценариями mock-сервера WiseWay.
//
// Контроллер хранит только воспроизводимое состояние сценария: активную
// mock-сессию, управляемую задержку ответа, профиль app-config (N=100/N=10),
// пустые состояния roots/companies и freshness-профиль поиска
// (CURRENT/UPDATING/STALE). Никаких реальных учётных данных, файлов или
// сетевых подключений здесь нет: mock не является защищённым auth backend.
//
// Задержка инъектируется через `sleep`, поэтому тесты проверяют её без реальных
// ожиданий (controlled clock / fake sleep).

import type { SearchFreshness, Session } from './types'

export type ConfigProfile = 'n100' | 'n10'

/** Профиль freshness, выбираемый для `/search` из golden-эталона. */
export type SearchFreshnessProfile = SearchFreshness['status']

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

  /** Сбрасывает сессию, задержку, профиль, freshness и empty-переопределения. */
  reset(): void {
    this.session = null
    this.delayMs = 0
    this.configProfile = 'n100'
    this.searchFreshnessProfile = 'CURRENT'
    this.rootsEmpty = false
    this.companiesEmpty = false
    this.requestSequence = 0
  }
}
