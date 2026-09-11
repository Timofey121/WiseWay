// In-memory хранилище справочников для mock-операций dictionary lifecycle
// (LT-07.1a).
//
// Состояние живёт только в рамках mock-сессии: `reset()` восстанавливает
// детерминированный seed из публичных примеров
// `contracts/examples/dictionaries/*`. Никакого backend, filesystem или
// matcher-алгоритма здесь нет: `replaceDraft` просто сохраняет переданный
// черновик и увеличивает `draft_revision`.
//
// Уникальность имени — синтетическая in-memory проверка внутри компании после
// `trim` + casefold (приближение `String.prototype.toLowerCase`), а не
// домен-сервер.

import { cloneJson, getExample } from '../data'
import type { Actor, Dictionary, Rule } from '../types'

/** Детерминированная метка времени mock-мутаций (без реальных часов). */
export const MOCK_DICTIONARY_UPDATED_AT = '2031-05-10T10:00:00Z'

/** Id seed-примеров в стабильном порядке базового состояния. */
const SEED_DICTIONARY_IDS = [
  'dictionary-atlas-general',
  'dictionary-atlas-invoices',
  'dictionary-nova-general',
] as const

/** Нормализация имени для проверки уникальности: trim + casefold. */
export function normalizeDictionaryName(name: string): string {
  return name.trim().toLowerCase()
}

export interface ReplaceDraftInput {
  name: string
  description: string
  rules: Rule[]
}

/** In-memory store `dictionary_id → Dictionary` с seed и `reset()`. */
export class DictionaryStore {
  private readonly byId = new Map<string, Dictionary>()
  private createdSequence = 0

  constructor() {
    this.reset()
  }

  /** Восстанавливает базовое состояние из публичных примеров контракта. */
  reset(): void {
    this.byId.clear()
    this.createdSequence = 0
    for (const id of SEED_DICTIONARY_IDS) {
      const dictionary = getExample<Dictionary>(id)
      this.byId.set(dictionary.dictionary_id, cloneJson(dictionary))
    }
  }

  /** Справочник по id или `undefined` (копия, не ссылка на store). */
  get(dictionaryId: string): Dictionary | undefined {
    const found = this.byId.get(dictionaryId)
    return found ? cloneJson(found) : undefined
  }

  /** Справочники компании в стабильном порядке `dictionary_id`. */
  list(companyId: string): Dictionary[] {
    return [...this.byId.values()]
      .filter((dictionary) => dictionary.company_id === companyId)
      .sort((a, b) => a.dictionary_id.localeCompare(b.dictionary_id))
      .map((dictionary) => cloneJson(dictionary))
  }

  /**
   * Есть ли в компании справочник с таким же именем после trim+casefold.
   * `exceptDictionaryId` исключает сам справочник при сохранении черновика.
   */
  hasNameConflict(
    companyId: string,
    name: string,
    exceptDictionaryId?: string,
  ): boolean {
    const normalized = normalizeDictionaryName(name)
    for (const dictionary of this.byId.values()) {
      if (dictionary.company_id !== companyId) {
        continue
      }
      if (
        exceptDictionaryId !== undefined &&
        dictionary.dictionary_id === exceptDictionaryId
      ) {
        continue
      }
      if (normalizeDictionaryName(dictionary.name) === normalized) {
        return true
      }
    }
    return false
  }

  /**
   * Создаёт справочник с пустым черновиком `draft_revision = 0`. Вызывающая
   * сторона уже проверила уникальность имени и валидность тела.
   */
  create(
    companyId: string,
    name: string,
    description: string,
    actor: Actor,
  ): Dictionary {
    this.createdSequence += 1
    const dictionary: Dictionary = {
      dictionary_id: `dictionary-created-${this.createdSequence}`,
      company_id: companyId,
      name,
      description,
      draft: { draft_revision: 0, rules: [], based_on_version_id: null },
      active_version_id: null,
      versions_count: 0,
      updated_at: MOCK_DICTIONARY_UPDATED_AT,
      updated_by: cloneJson(actor),
    }
    this.byId.set(dictionary.dictionary_id, dictionary)
    return cloneJson(dictionary)
  }

  /**
   * Атомарно заменяет имя/описание/правила черновика и увеличивает
   * `draft_revision` на 1. `based_on_version_id`, `active_version_id` и
   * `versions_count` не пересчитываются: mock не выполняет publish/restore.
   */
  replaceDraft(
    dictionaryId: string,
    input: ReplaceDraftInput,
    actor: Actor,
  ): Dictionary {
    const current = this.byId.get(dictionaryId)
    if (!current) {
      throw new Error(`Справочник "${dictionaryId}" отсутствует в mock-store`)
    }
    const next: Dictionary = {
      ...cloneJson(current),
      name: input.name,
      description: input.description,
      draft: {
        draft_revision: current.draft.draft_revision + 1,
        rules: cloneJson(input.rules),
        based_on_version_id: current.draft.based_on_version_id,
      },
      updated_at: MOCK_DICTIONARY_UPDATED_AT,
      updated_by: cloneJson(actor),
    }
    this.byId.set(dictionaryId, next)
    return cloneJson(next)
  }
}
