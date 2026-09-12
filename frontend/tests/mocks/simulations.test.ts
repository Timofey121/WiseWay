// LT-07.1b: контрактные mocks симуляции (`createDictionarySimulation`,
// `getSimulation`) без matcher/FS/plan-алгоритма.
//
// Проверки идут через `createApiClient({ mode: 'mock', fetch })` (тот же
// транспорт/CSRF/error-модель, что и real) и через mock-fetch напрямую для
// невалидных запросов, которые типизированный клиент не позволяет собрать.
// Все успешные ответы дополнительно валидируются по схемам OAS.
//
// Revision-модель согласована с `GET /dictionary`: `createDictionarySimulation`
// валидирует `expected_draft_revision` против текущей ревизии `DictionaryStore`
// и фиксирует её в ответе; plan rows/counts/rule_set/base_rule_set остаются
// literal из примеров. `getSimulation` не объявляет 409 и не возвращает его:
// сохранённый результат отдаётся независимо от последующих изменений черновика.

import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext, setCsrfToken } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  createMockFetch,
  MockController,
  type MockFetch,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import { matchMockRoute } from '@/mocks/router'
import type {
  CreateSimulationRequest,
  ErrorResponse,
  LoginRequest,
  ReplaceDictionaryDraftRequest,
  Rule,
  Session,
  Simulation,
} from '@/mocks/types'
import { validateSchema } from '@/mocks/validate'

interface Setup {
  controller: MockController
  mockFetch: MockFetch
  api: WiseWayApiClient
}

function setup(): Setup {
  const controller = new MockController({ sleep: async () => {} })
  const mockFetch = createMockFetch(controller)
  const api = createApiClient({
    mode: 'mock',
    baseUrl: 'http://localhost/api/v1',
    fetch: mockFetch,
  })
  return { controller, mockFetch, api }
}

function request(path: string, init?: RequestInit): Request {
  return new Request(`http://localhost/api/v1${path}`, init)
}

async function readError(response: Response): Promise<ErrorResponse> {
  return (await response.json()) as ErrorResponse
}

async function loginWorkerOne(api: WiseWayApiClient): Promise<Session> {
  const body = getExample<LoginRequest>('auth-login-request-worker-one')
  const result = await api.POST('/auth/login', { body })
  expect(result.response.status).toBe(200)
  if (!result.data) {
    throw new Error('login не вернул Session')
  }
  return result.data
}

/** Логин и установка CSRF-токена в session-context (как реальный UI). */
async function loginWithCsrf(api: WiseWayApiClient): Promise<Session> {
  const session = await loginWorkerOne(api)
  setCsrfToken(session.csrf_token)
  return session
}

function expectSchema(schemaName: string, value: unknown): void {
  expect(validateSchema(schemaName, value).valid, schemaName).toBe(true)
}

const ATLAS = 'company-demo-atlas'
const DICTIONARY = 'dictionary-atlas-general'
/** Ревизия seed-черновика `dictionary-atlas-general` в `DictionaryStore`. */
const SEED_REVISION = 1

function postSimulate(
  api: WiseWayApiClient,
  dictionaryId: string,
  body: CreateSimulationRequest,
) {
  return api.POST('/dictionaries/{dictionary_id}/simulate', {
    params: {
      path: { dictionary_id: dictionaryId },
      header: { 'X-CSRF-Token': 'caller-placeholder' },
    },
    body,
  })
}

function putDraft(
  api: WiseWayApiClient,
  dictionaryId: string,
  body: ReplaceDictionaryDraftRequest,
) {
  return api.PUT('/dictionaries/{dictionary_id}/draft', {
    params: {
      path: { dictionary_id: dictionaryId },
      header: { 'X-CSRF-Token': 'caller-placeholder' },
    },
    body,
  })
}

function getSimulation(
  api: WiseWayApiClient,
  simulationId: string,
  query?: { cursor?: string; limit?: number },
) {
  return api.GET('/simulations/{simulation_id}', {
    params: { path: { simulation_id: simulationId }, query },
  })
}

const SAVE_RULE: Rule = {
  rule_id: 'rule-sim-save-1',
  priority: 10,
  match_field: 'BASENAME',
  mask: '*sim*',
  target: {
    root_id: 'root-demo-atlas',
    relative_directory: 'Archive/Atlas/Orion_2031/Data',
  },
  target_stem: 'Sim',
}

function draftBody(expectedDraftRevision: number): ReplaceDictionaryDraftRequest {
  return {
    expected_draft_revision: expectedDraftRevision,
    name: 'Общие правила Atlas',
    description: 'Синтетические общие правила Atlas.',
    rules: [SAVE_RULE],
  }
}

/** Literal пример с ревизией, зафиксированной create-операцией. */
function expectedCreated(exampleId: string, revision: number): Simulation {
  return { ...getExample<Simulation>(exampleId), draft_revision: revision }
}

beforeEach(() => {
  resetSessionContext()
})

describe('mock-fetch: маршрутизация симуляции', () => {
  it('регистрирует 2 операции и извлекает path-параметры', () => {
    expect(
      matchMockRoute('POST', '/dictionaries/dictionary-atlas-general/simulate'),
    ).toBeDefined()
    expect(
      matchMockRoute('GET', '/simulations/simulation-atlas-general-v2-full'),
    ).toBeDefined()
    expect(
      matchMockRoute('POST', '/dictionaries/dictionary-atlas-general/simulate')
        ?.params,
    ).toEqual({ dictionary_id: 'dictionary-atlas-general' })
    expect(
      matchMockRoute('GET', '/simulations/simulation-atlas-general-v2-full')
        ?.params,
    ).toEqual({ simulation_id: 'simulation-atlas-general-v2-full' })
  })

  it('успешные ответы несут X-Request-ID, Cache-Control и mock-маркер', async () => {
    const { api } = setup()
    await loginWithCsrf(api)
    const result = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(result.response.status).toBe(201)
    expect(result.response.headers.get('Cache-Control')).toBe('no-store')
    expect(result.response.headers.get('X-Request-ID')).toMatch(
      /^request-mock-\d+$/,
    )
  })
})

describe('mock simulations: create success (literal canned)', () => {
  const cases: Array<{
    scenario: Parameters<MockController['setSimulationScenario']>[0]
    exampleId: string
  }> = [
    { scenario: 'full', exampleId: 'simulation-atlas-full-page1' },
    { scenario: 'empty', exampleId: 'simulation-atlas-empty' },
    { scenario: 'conflict', exampleId: 'simulation-atlas-conflict' },
    { scenario: 'same-target', exampleId: 'simulation-atlas-same-target' },
    { scenario: 'no-scenario', exampleId: 'simulation-atlas-v3-restored' },
  ]

  for (const { scenario, exampleId } of cases) {
    it(`${scenario}: 201 literal ${exampleId} с ревизией черновика и schema-valid`, async () => {
      const { api, controller } = setup()
      await loginWithCsrf(api)
      controller.setSimulationScenario(scenario)

      const result = await postSimulate(api, DICTIONARY, {
        expected_draft_revision: SEED_REVISION,
      })

      expect(result.response.status).toBe(201)
      // literal plan content, draft_revision — производная состояния.
      expect(result.data).toEqual(expectedCreated(exampleId, SEED_REVISION))
      expect(result.data?.draft_revision).toBe(SEED_REVISION)
      expectSchema('Simulation', result.data)
    })
  }

  it('empty несёт warning EMPTY_READY_SET и zero counts', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setSimulationScenario('empty')

    const result = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(result.response.status).toBe(201)
    expect(result.data?.warnings).toEqual(['EMPTY_READY_SET'])
    expect(result.data?.total).toBe(0)
    expect(result.data?.rows).toEqual([])
    expect(result.data?.counts).toEqual({
      will_move: 0,
      will_manual_review: 0,
      requires_decision: 0,
      not_ready: 0,
      rule_conflicts: 0,
      no_scenario: 0,
    })
  })
})

describe('mock simulations: counts и full RuleSet references', () => {
  const scenarioExamples: Array<{
    scenario: string
    exampleId: string
    ruleConflicts: number
    noScenario: number
  }> = [
    {
      scenario: 'full',
      exampleId: 'simulation-atlas-full-page1',
      ruleConflicts: 0,
      noScenario: 1,
    },
    {
      scenario: 'empty',
      exampleId: 'simulation-atlas-empty',
      ruleConflicts: 0,
      noScenario: 0,
    },
    {
      scenario: 'conflict',
      exampleId: 'simulation-atlas-conflict',
      ruleConflicts: 1,
      noScenario: 0,
    },
    {
      scenario: 'same-target',
      exampleId: 'simulation-atlas-same-target',
      ruleConflicts: 0,
      noScenario: 0,
    },
    {
      scenario: 'no-scenario',
      exampleId: 'simulation-atlas-v3-restored',
      ruleConflicts: 0,
      noScenario: 3,
    },
  ]

  it('total = первые четыре counts; rule_conflicts/no_scenario — отдельные причины', () => {
    for (const { scenario, exampleId, ruleConflicts, noScenario } of scenarioExamples) {
      const simulation = getExample<Simulation>(exampleId)
      const { counts } = simulation
      expect(
        counts.will_move +
          counts.will_manual_review +
          counts.requires_decision +
          counts.not_ready,
        scenario,
      ).toBe(simulation.total)
      // Дополнительные причины не прибавляются к total, но имеют точное значение.
      expect(counts.rule_conflicts, scenario).toBe(ruleConflicts)
      expect(counts.no_scenario, scenario).toBe(noScenario)
    }
  })

  it('base_rule_set полный, references входят в него, version_id=null только для тестируемого черновика', () => {
    for (const { scenario, exampleId } of scenarioExamples) {
      const simulation = getExample<Simulation>(exampleId)
      const members = new Set(
        simulation.base_rule_set.members.map(
          (member) => `${member.dictionary_id}:${member.version_id}`,
        ),
      )
      expect(simulation.base_rule_set.company_id, scenario).toBe(ATLAS)
      expect(simulation.base_rule_set.members.length, scenario).toBeGreaterThan(
        0,
      )
      for (const row of simulation.rows) {
        const references = [...row.matched_rules]
        if (row.selected_rule) {
          references.push(row.selected_rule)
        }
        for (const reference of references) {
          if (reference.version_id === null) {
            // version_id=null только для тестируемого черновика.
            expect(reference.dictionary_id, scenario).toBe(
              simulation.dictionary_id,
            )
          } else {
            expect(
              members.has(
                `${reference.dictionary_id}:${reference.version_id}`,
              ),
              `${scenario}: ${reference.dictionary_id}/${reference.version_id}`,
            ).toBe(true)
          }
        }
      }
    }
  })

  it('ready_snapshot_id задан и различает независимые сценарии', () => {
    const snapshots = new Map<string, string>()
    for (const { scenario, exampleId } of scenarioExamples) {
      const simulation = getExample<Simulation>(exampleId)
      expect(simulation.ready_snapshot_id.length, scenario).toBeGreaterThan(0)
      snapshots.set(scenario, simulation.ready_snapshot_id)
    }
    // full и no-scenario (restored) используют тот же READY-набор, как в примерах.
    expect(snapshots.get('empty')).not.toBe(snapshots.get('full'))
    expect(snapshots.get('conflict')).not.toBe(snapshots.get('full'))
    expect(snapshots.get('same-target')).not.toBe(snapshots.get('full'))
  })
})

describe('mock simulations: согласованная revision-семантика', () => {
  it('seed rev R → create R → 201 R; stale R-1 → 409; после PUT rev R+1 → create R+1', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setSimulationScenario('full')

    const created = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(created.response.status).toBe(201)
    expect(created.data?.draft_revision).toBe(SEED_REVISION)
    expect(created.data).toEqual(
      expectedCreated('simulation-atlas-full-page1', SEED_REVISION),
    )

    const stale = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION - 1,
    })
    expect(stale.response.status).toBe(409)
    expect(stale.error?.error.code).toBe('DRAFT_VERSION_CONFLICT')
    expectSchema('ErrorResponse', stale.error)

    const saved = await putDraft(api, DICTIONARY, draftBody(SEED_REVISION))
    expect(saved.response.status).toBe(200)
    expect(saved.data?.draft.draft_revision).toBe(SEED_REVISION + 1)

    const createdNext = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION + 1,
    })
    expect(createdNext.response.status).toBe(201)
    expect(createdNext.data?.draft_revision).toBe(SEED_REVISION + 1)
    expect(createdNext.data).toEqual(
      expectedCreated('simulation-atlas-full-page1', SEED_REVISION + 1),
    )
  })

  it('GET /dictionary и create используют одну текущую ревизию', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const dictionary = await api.GET('/dictionaries/{dictionary_id}', {
      params: { path: { dictionary_id: DICTIONARY } },
    })
    const currentRevision = dictionary.data?.draft.draft_revision
    expect(currentRevision).toBe(SEED_REVISION)

    const created = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: currentRevision ?? -1,
    })
    expect(created.response.status).toBe(201)
    expect(created.data?.draft_revision).toBe(currentRevision)
  })
})

describe('mock simulations: getSimulation paging без 409', () => {
  it('page1 → page2 по объявленному курсору, limit finite', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const first = await getSimulation(
      api,
      'simulation-atlas-general-v2-full',
      { limit: 3 },
    )
    expect(first.response.status).toBe(200)
    expect(first.data).toEqual(
      getExample<Simulation>('simulation-atlas-full-page1'),
    )
    expectSchema('Simulation', first.data)

    const second = await getSimulation(
      api,
      'simulation-atlas-general-v2-full',
      { limit: 3, cursor: first.data?.next_cursor ?? '' },
    )
    expect(second.response.status).toBe(200)
    expect(second.data).toEqual(
      getExample<Simulation>('simulation-atlas-full-page2'),
    )
    expect(second.data?.next_cursor).toBeNull()

    const ids = [
      ...(first.data?.rows ?? []),
      ...(second.data?.rows ?? []),
    ].map((row) => row.item_id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toHaveLength(first.data?.total ?? 0)
  })

  it('single-page сценарии: одна страница, next_cursor=null, counts не меняются', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const result = await getSimulation(api, 'simulation-atlas-general-conflict')
    expect(result.response.status).toBe(200)
    expect(result.data).toEqual(
      getExample<Simulation>('simulation-atlas-conflict'),
    )
    expect(result.data?.next_cursor).toBeNull()
    expect(result.data?.counts.rule_conflicts).toBe(1)
  })

  it('изменение черновика после create не даёт 409: сохранённая страница и фиксированная ревизия', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setSimulationScenario('full')

    const created = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(created.response.status).toBe(201)

    const saved = await putDraft(api, DICTIONARY, draftBody(SEED_REVISION))
    expect(saved.response.status).toBe(200)
    expect(saved.data?.draft.draft_revision).toBe(SEED_REVISION + 1)

    const first = await getSimulation(
      api,
      'simulation-atlas-general-v2-full',
      { limit: 3 },
    )
    expect(first.response.status).toBe(200)
    expect(first.data?.draft_revision).toBe(SEED_REVISION)

    const second = await getSimulation(
      api,
      'simulation-atlas-general-v2-full',
      { limit: 3, cursor: first.data?.next_cursor ?? '' },
    )
    expect(second.response.status).toBe(200)
    expect(second.data?.next_cursor).toBeNull()
  })

  it('невалидный limit/cursor → 422 без правдоподобного успеха', async () => {
    const { api, mockFetch } = setup()
    await loginWorkerOne(api)

    const badLimit = await mockFetch(
      request('/simulations/simulation-atlas-general-v2-full?limit=0'),
    )
    expect(badLimit.status).toBe(422)
    expect((await readError(badLimit)).error.code).toBe('VALIDATION_ERROR')

    const tooBig = await mockFetch(
      request('/simulations/simulation-atlas-general-v2-full?limit=101'),
    )
    expect(tooBig.status).toBe(422)

    const badCursor = await mockFetch(
      request('/simulations/simulation-atlas-general-v2-full?cursor=nope'),
    )
    expect(badCursor.status).toBe(422)
  })

  it('getSimulation не возвращает 409 и без сессии даёт 401', async () => {
    const { api } = setup()
    const unauth = await getSimulation(api, 'simulation-atlas-general-v2-full')
    expect(unauth.response.status).toBe(401)
    expect(unauth.response.status).not.toBe(409)

    await loginWorkerOne(api)
    const known = await getSimulation(api, 'simulation-atlas-general-empty')
    expect(known.response.status).toBe(200)
  })
})

describe('mock simulations: 401/403/404/422', () => {
  it('без сессии → 401 (create и get)', async () => {
    const { api } = setup()
    const create = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(create.response.status).toBe(401)
    expect(create.error?.error.code).toBe('UNAUTHENTICATED')

    const get = await getSimulation(api, 'simulation-atlas-general-v2-full')
    expect(get.response.status).toBe(401)
  })

  it('create без/с неверным CSRF → 403, store не меняется', async () => {
    const { api, controller } = setup()
    const session = await loginWorkerOne(api)

    const noToken = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(noToken.response.status).toBe(403)
    expect(noToken.error?.error.code).toBe('CSRF_FAILED')

    setCsrfToken(`${session.csrf_token}-wrong`)
    const wrong = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(wrong.response.status).toBe(403)
    expect(
      controller
        .getSimulationStore()
        .getCreatedRevision('simulation-atlas-general-v2-full'),
    ).toBeUndefined()
  })

  it('неизвестный dictionary на create → 404; неизвестная simulation → 404', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const missingDictionary = await postSimulate(api, 'dictionary-nope', {
      expected_draft_revision: SEED_REVISION,
    })
    expect(missingDictionary.response.status).toBe(404)
    expect(missingDictionary.error?.error.code).toBe('NOT_FOUND')

    const missingSimulation = await getSimulation(
      api,
      'simulation-does-not-exist',
    )
    expect(missingSimulation.response.status).toBe(404)
    expect(missingSimulation.error?.error.code).toBe('NOT_FOUND')
  })

  it('invalid body (лишнее поле/битый JSON/пустое) → 422 без успеха', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const extra = await mockFetch(
      request('/dictionaries/dictionary-atlas-general/simulate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: JSON.stringify({
          expected_draft_revision: SEED_REVISION,
          extra: true,
        }),
      }),
    )
    expect(extra.status).toBe(422)
    expect((await readError(extra)).error.code).toBe('VALIDATION_ERROR')

    const broken = await mockFetch(
      request('/dictionaries/dictionary-atlas-general/simulate', {
        method: 'POST',
        headers: { 'X-CSRF-Token': session.csrf_token },
        body: '{not-json',
      }),
    )
    expect(broken.status).toBe(422)

    const missing = await mockFetch(
      request('/dictionaries/dictionary-atlas-general/simulate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: JSON.stringify({}),
      }),
    )
    expect(missing.status).toBe(422)
  })
})

describe('mock simulations: управляемые ошибки и reset', () => {
  it('failNext для create расходуется один раз (объявленный код)', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setSimulationScenario('full')
    controller.failNext('createDictionarySimulation', 'DRAFT_VERSION_CONFLICT')

    const first = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(first.response.status).toBe(409)
    expect(first.error?.error.code).toBe('DRAFT_VERSION_CONFLICT')

    const second = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(second.response.status).toBe(201)
  })

  it('setError для getSimulation использует только объявленный VALIDATION_ERROR', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setError('getSimulation', 'VALIDATION_ERROR')

    const forced = await getSimulation(api, 'simulation-atlas-general-v2-full')
    expect(forced.response.status).toBe(422)
    expect(forced.error?.error.code).toBe('VALIDATION_ERROR')

    controller.clearError('getSimulation')
    const normal = await getSimulation(api, 'simulation-atlas-general-v2-full')
    expect(normal.response.status).toBe(200)
  })

  it('reset восстанавливает seed, сценарий и очищает управляемые ошибки', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setSimulationScenario('conflict')
    controller.failNext('createDictionarySimulation', 'DRAFT_VERSION_CONFLICT')
    controller
      .getSimulationStore()
      .markCreated('simulation-atlas-general-v2-full', 99)

    controller.reset()

    expect(controller.getSimulationScenario()).toBe('full')
    expect(
      controller
        .getSimulationStore()
        .getCreatedRevision('simulation-atlas-general-v2-full'),
    ).toBeUndefined()
    expect(
      controller
        .getSimulationStore()
        .get('simulation-atlas-general-v2-full')?.base.draft_revision,
    ).toBe(2)

    resetSessionContext()
    await loginWithCsrf(api)
    const result = await postSimulate(api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION,
    })
    expect(result.response.status).toBe(201)
    expect(result.data).toEqual(
      expectedCreated('simulation-atlas-full-page1', SEED_REVISION),
    )
  })
})
