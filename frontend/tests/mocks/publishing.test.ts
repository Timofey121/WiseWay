// LT-07.1c: контрактные mocks публикации/версий/восстановления
// (`publishDictionary`, `listDictionaryVersions`, `getDictionaryVersion`,
// `restoreDictionaryDraft`) без matcher/RuleSet-вычисления/FS-действий.
//
// Проверки идут через `createApiClient({ mode: 'mock', fetch })` (тот же
// транспорт/CSRF/error-модель, что и real) и через mock-fetch напрямую для
// явного `Idempotency-Key` и невалидных запросов, которые типизированный клиент
// не позволяет собрать. Все успешные ответы дополнительно валидируются по
// схемам OAS.
//
// Модель состояния согласована: publish валидирует `expected_draft_revision`
// против текущей ревизии `DictionaryStore`, staleness simulation — против
// ревизии, зафиксированной create-операцией; успех append'ит literal
// `published_version` и literal `rule_set` из canned-примера. Идемпотентность
// scoped по actor+dictionary+ключу и проверяется до staleness-гейтов.

import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext, setCsrfToken } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  createMockFetch,
  MOCK_MARKER_HEADER,
  MOCK_MODE,
  MockController,
  type MockFetch,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import { matchMockRoute } from '@/mocks/router'
import type {
  CreateSimulationRequest,
  Dictionary,
  DictionaryVersion,
  ErrorResponse,
  LoginRequest,
  PageDictionaryVersion,
  PublishDictionaryRequest,
  PublishedDictionaryResponse,
  ReplaceDictionaryDraftRequest,
  Rule,
  RuleSet,
  Session,
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

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T
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

/** Логин другого актора: идемпотентность scoped по user_id. */
async function loginWorkerTwo(api: WiseWayApiClient): Promise<Session> {
  const body = getExample<LoginRequest>('auth-login-request-worker-two')
  const result = await api.POST('/auth/login', { body })
  expect(result.response.status).toBe(200)
  if (!result.data) {
    throw new Error('login не вернул Session')
  }
  setCsrfToken(result.data.csrf_token)
  return result.data
}

function expectSchema(schemaName: string, value: unknown): void {
  expect(validateSchema(schemaName, value).valid, schemaName).toBe(true)
}

const ATLAS = 'company-demo-atlas'
const DICTIONARY = 'dictionary-atlas-general'
/** Ревизия seed-черновика `dictionary-atlas-general` в `DictionaryStore`. */
const SEED_REVISION = 1
const FULL_SIM = 'simulation-atlas-general-v2-full'
const V3_SIM = 'simulation-atlas-general-v3-restored'
const VERSION_V1 = 'version-atlas-general-v1'
const VERSION_V2 = 'version-atlas-general-v2'
const KEY_V2 = '11111111-1111-4111-8111-111111111111'
const KEY_V3 = '22222222-2222-4222-8222-222222222222'

const SAVE_RULE: Rule = {
  rule_id: 'rule-publish-save-1',
  priority: 10,
  match_field: 'BASENAME',
  mask: '*publish*',
  target: {
    root_id: 'root-demo-atlas',
    relative_directory: 'Archive/Atlas/Orion_2031/Data',
  },
  target_stem: 'Publish',
}

function draftBody(expectedDraftRevision: number): ReplaceDictionaryDraftRequest {
  return {
    expected_draft_revision: expectedDraftRevision,
    name: 'Общие правила Atlas',
    description: 'Синтетические общие правила Atlas.',
    rules: [SAVE_RULE],
  }
}

function publishBody(
  expectedRevision: number,
  overrides: Partial<PublishDictionaryRequest> = {},
): PublishDictionaryRequest {
  return {
    expected_draft_revision: expectedRevision,
    simulation_id: FULL_SIM,
    acknowledge_no_scenario: true,
    comment: 'Публикация проверенного черновика Atlas.',
    ...overrides,
  }
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

interface RawRequestOptions {
  csrfToken?: string | null
  idempotencyKey?: string
  body?: unknown
}

function publishRequest(
  dictionaryId: string,
  body: unknown,
  options: RawRequestOptions = {},
): Request {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (options.csrfToken !== null) {
    headers['X-CSRF-Token'] = options.csrfToken ?? 'caller-placeholder'
  }
  if (options.idempotencyKey !== undefined) {
    headers['Idempotency-Key'] = options.idempotencyKey
  }
  return request(`/dictionaries/${dictionaryId}/publish`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
}

function restoreRequest(
  dictionaryId: string,
  body: unknown,
  options: RawRequestOptions = {},
): Request {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (options.csrfToken !== null) {
    headers['X-CSRF-Token'] = options.csrfToken ?? 'caller-placeholder'
  }
  return request(`/dictionaries/${dictionaryId}/restore-draft`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
}

/**
 * Доводит справочник до публикуемого состояния v2: PUT draft (revision 2) →
 * simulate full (revision 2) → publish v2 с явным ключом. Возвращает Response.
 */
async function drivePublishedV2(
  setup: Setup,
  session: Session,
  key = KEY_V2,
): Promise<Response> {
  const saved = await putDraft(setup.api, DICTIONARY, draftBody(SEED_REVISION))
  expect(saved.response.status).toBe(200)
  setup.controller.setSimulationScenario('full')
  const simulated = await postSimulate(setup.api, DICTIONARY, {
    expected_draft_revision: SEED_REVISION + 1,
  })
  expect(simulated.response.status).toBe(201)
  return setup.mockFetch(
    publishRequest(
      DICTIONARY,
      publishBody(SEED_REVISION + 1),
      { csrfToken: session.csrf_token, idempotencyKey: key },
    ),
  )
}

/**
 * Продолжает жизненный цикл до публикации v3: restore v1 (revision 3) →
 * simulate no-scenario (revision 3) → publish v3 с явным ключом.
 */
async function drivePublishedV3(
  setup: Setup,
  session: Session,
): Promise<Response> {
  const publishedV2 = await drivePublishedV2(setup, session)
  expect(publishedV2.status).toBe(201)

  const restored = await setup.mockFetch(
    restoreRequest(
      DICTIONARY,
      { version_id: VERSION_V1, expected_draft_revision: SEED_REVISION + 1 },
      { csrfToken: session.csrf_token },
    ),
  )
  expect(restored.status).toBe(200)

  setup.controller.setSimulationScenario('no-scenario')
  const simulated = await postSimulate(setup.api, DICTIONARY, {
    expected_draft_revision: SEED_REVISION + 2,
  })
  expect(simulated.response.status).toBe(201)

  setup.controller.setPublishingScenario('v3')
  return setup.mockFetch(
    publishRequest(
      DICTIONARY,
      publishBody(SEED_REVISION + 2, {
        simulation_id: V3_SIM,
        comment: 'Публикация восстановленной версии 1.',
      }),
      { csrfToken: session.csrf_token, idempotencyKey: KEY_V3 },
    ),
  )
}

beforeEach(() => {
  resetSessionContext()
})

describe('mock-fetch: маршрутизация публикации/версий', () => {
  it('регистрирует 4 операции и извлекает path-параметры', () => {
    const routes = [
      ['GET', `/dictionaries/${DICTIONARY}/versions`],
      ['GET', `/dictionaries/${DICTIONARY}/versions/${VERSION_V1}`],
      ['POST', `/dictionaries/${DICTIONARY}/restore-draft`],
      ['POST', `/dictionaries/${DICTIONARY}/publish`],
    ] as const
    for (const [method, path] of routes) {
      expect(matchMockRoute(method, path), `${method} ${path}`).toBeDefined()
    }
    expect(
      matchMockRoute('GET', `/dictionaries/${DICTIONARY}/versions`)?.params,
    ).toEqual({ dictionary_id: DICTIONARY })
    expect(
      matchMockRoute('GET', `/dictionaries/${DICTIONARY}/versions/${VERSION_V1}`)
        ?.params,
    ).toEqual({ dictionary_id: DICTIONARY, version_id: VERSION_V1 })
    expect(
      matchMockRoute('POST', `/dictionaries/${DICTIONARY}/publish`)?.params,
    ).toEqual({ dictionary_id: DICTIONARY })
  })

  it('ответы несут X-Request-ID, Cache-Control и mock-маркер', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const result = await api.GET('/dictionaries/{dictionary_id}/versions', {
      params: { path: { dictionary_id: DICTIONARY } },
    })
    expect(result.response.status).toBe(200)
    expect(result.response.headers.get('Cache-Control')).toBe('no-store')
    expect(result.response.headers.get('X-Request-ID')).toMatch(
      /^request-mock-\d+$/,
    )
    expect(result.response.headers.get(MOCK_MARKER_HEADER)).toBe(MOCK_MODE)
  })
})

describe('mock publishing: publish success v2', () => {
  it('201 literal publish-atlas-general-v2 и обновление dictionary/version/RuleSet', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)

    const response = await drivePublishedV2(setupState, session)
    expect(response.status).toBe(201)
    const data = await readJson<PublishedDictionaryResponse>(response)

    expect(data).toEqual(getExample<PublishedDictionaryResponse>('publish-atlas-general-v2'))
    expectSchema('PublishedDictionaryResponse', data)

    // DictionaryStore обновлён literal-состоянием published-v2.
    expect(setupState.controller.getDictionaryStore().get(DICTIONARY)).toEqual(
      getExample<Dictionary>('dictionary-atlas-general-published-v2'),
    )
    // История версий: v2 добавлена к seed v1.
    expect(
      setupState.controller
        .getPublishingStore()
        .listVersions(DICTIONARY)
        .map((version) => version.version_id),
    ).toEqual([VERSION_V2, VERSION_V1])
    // Literal RuleSet активных версий.
    expect(
      setupState.controller
        .getPublishingStore()
        .getActiveRuleSet(ATLAS),
    ).toEqual(getExample<RuleSet>('rule-set-atlas-v2'))
  })

  it('publish не создаёт симуляцию и не меняет SimulationStore (сортировка не запускается)', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    // create-операция зафиксировала ревизию 2; publish её не пересоздаёт.
    expect(
      setupState.controller
        .getSimulationStore()
        .getCreatedRevision(FULL_SIM),
    ).toBe(SEED_REVISION + 1)
    expect(
      setupState.controller.getSimulationStore().get(FULL_SIM)?.base
        .draft_revision,
    ).toBe(SEED_REVISION + 1)
    // Публикация отдаёт RuleSet версий, а не партию/очередь.
    expect(
      setupState.controller
        .getPublishingStore()
        .getActiveRuleSet(ATLAS)?.members.length,
    ).toBeGreaterThan(0)
  })

  it('publish через транспорт сам ставит CSRF и Idempotency-Key', async () => {
    const setupState = setup()
    await loginWithCsrf(setupState.api)

    const saved = await putDraft(setupState.api, DICTIONARY, draftBody(SEED_REVISION))
    expect(saved.response.status).toBe(200)
    setupState.controller.setSimulationScenario('full')
    const simulated = await postSimulate(setupState.api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION + 1,
    })
    expect(simulated.response.status).toBe(201)

    const result = await setupState.api.POST(
      '/dictionaries/{dictionary_id}/publish',
      {
        params: {
          path: { dictionary_id: DICTIONARY },
          header: {
            'X-CSRF-Token': 'caller-placeholder',
            'Idempotency-Key': '00000000-0000-4000-8000-000000000000',
          },
        },
        body: publishBody(SEED_REVISION + 1),
      },
    )
    expect(result.response.status).toBe(201)
    expect(result.data).toEqual(
      getExample<PublishedDictionaryResponse>('publish-atlas-general-v2'),
    )
    expectSchema('PublishedDictionaryResponse', result.data)
  })
})

describe('mock publishing: publish success v3 (restore provenance)', () => {
  it('201 literal publish-atlas-general-v3, restored_from_version_id и history v3/v2/v1', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)

    const response = await drivePublishedV3(setupState, session)
    expect(response.status).toBe(201)
    const data = await readJson<PublishedDictionaryResponse>(response)

    expect(data).toEqual(getExample<PublishedDictionaryResponse>('publish-atlas-general-v3'))
    expect(data.published_version.restored_from_version_id).toBe(VERSION_V1)
    expect(data.dictionary.active_version_id).toBe('version-atlas-general-v3')
    expect(data.dictionary.versions_count).toBe(3)
    expectSchema('PublishedDictionaryResponse', data)

    // DictionaryStore и active RuleSet обновлены literal-состоянием v3.
    expect(setupState.controller.getDictionaryStore().get(DICTIONARY)).toEqual(
      getExample<Dictionary>('dictionary-atlas-general-published-v3'),
    )
    expect(
      setupState.controller.getPublishingStore().getActiveRuleSet(ATLAS),
    ).toEqual(getExample<RuleSet>('rule-set-atlas-v3'))

    // GET /versions после двух публикаций равен literal-примеру.
    const versions = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions',
      { params: { path: { dictionary_id: DICTIONARY } } },
    )
    expect(versions.response.status).toBe(200)
    expect(versions.data).toEqual(
      getExample<PageDictionaryVersion>('versions-atlas-general'),
    )
    expectSchema('PageDictionaryVersion', versions.data)
  })
})

describe('mock publishing: gates', () => {
  it('rule conflict → 409 RULE_CONFLICT без публикации', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)

    const saved = await putDraft(setupState.api, DICTIONARY, draftBody(SEED_REVISION))
    expect(saved.response.status).toBe(200)
    setupState.controller.setSimulationScenario('conflict')
    const simulated = await postSimulate(setupState.api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION + 1,
    })
    expect(simulated.response.status).toBe(201)

    const response = await setupState.mockFetch(
      publishRequest(
        DICTIONARY,
        publishBody(SEED_REVISION + 1, {
          simulation_id: 'simulation-atlas-general-conflict',
          comment: 'Публикация конфликтного теста.',
        }),
        { csrfToken: session.csrf_token, idempotencyKey: KEY_V2 },
      ),
    )
    expect(response.status).toBe(409)
    const error = await readError(response)
    expect(error.error.code).toBe('RULE_CONFLICT')
    expectSchema('ErrorResponse', error)

    // Версия не создана, активная версия не изменилась.
    expect(
      setupState.controller.getPublishingStore().listVersions(DICTIONARY),
    ).toHaveLength(1)
    expect(
      setupState.controller.getDictionaryStore().get(DICTIONARY)?.active_version_id,
    ).toBe(VERSION_V1)
  })

  it('NO_SCENARIO без ack → 409, с ack → 201', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)

    const saved = await putDraft(setupState.api, DICTIONARY, draftBody(SEED_REVISION))
    expect(saved.response.status).toBe(200)
    setupState.controller.setSimulationScenario('full')
    const simulated = await postSimulate(setupState.api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION + 1,
    })
    expect(simulated.response.status).toBe(201)

    const noAck = await setupState.mockFetch(
      publishRequest(
        DICTIONARY,
        publishBody(SEED_REVISION + 1, {
          acknowledge_no_scenario: false,
          comment: 'Публикация без подтверждения.',
        }),
        { csrfToken: session.csrf_token, idempotencyKey: KEY_V2 },
      ),
    )
    expect(noAck.status).toBe(409)
    expect((await readError(noAck)).error.code).toBe(
      'NO_SCENARIO_ACK_REQUIRED',
    )

    const ack = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION + 1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_V2,
      }),
    )
    expect(ack.status).toBe(201)
  })

  it('stale expected revision → 409 DRAFT_VERSION_CONFLICT', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    const stale = await setupState.mockFetch(
      publishRequest(
        DICTIONARY,
        publishBody(SEED_REVISION, {
          comment: 'Устаревшая ревизия черновика.',
        }),
        { csrfToken: session.csrf_token, idempotencyKey: KEY_V3 },
      ),
    )
    expect(stale.status).toBe(409)
    expect((await readError(stale)).error.code).toBe('DRAFT_VERSION_CONFLICT')
  })

  it('stale simulation (изменённая ревизия после create) → 409 STALE_SIMULATION', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    // Черновик изменён после create: simulation зафиксирована на ревизии 2.
    const saved = await putDraft(setupState.api, DICTIONARY, draftBody(SEED_REVISION + 1))
    expect(saved.response.status).toBe(200)
    expect(saved.data?.draft.draft_revision).toBe(SEED_REVISION + 2)

    const stale = await setupState.mockFetch(
      publishRequest(
        DICTIONARY,
        publishBody(SEED_REVISION + 2, {
          comment: 'Тест устарел: черновик изменён.',
        }),
        { csrfToken: session.csrf_token, idempotencyKey: KEY_V3 },
      ),
    )
    expect(stale.status).toBe(409)
    expect((await readError(stale)).error.code).toBe('STALE_SIMULATION')
  })

  it('истёкшая simulation (TTL) → 409 STALE_SIMULATION', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    setupState.controller.setPublishingNow('2031-05-10T10:00:00Z')
    const stale = await setupState.mockFetch(
      publishRequest(
        DICTIONARY,
        publishBody(SEED_REVISION + 1, {
          comment: 'Тест устарел по TTL.',
        }),
        { csrfToken: session.csrf_token, idempotencyKey: KEY_V3 },
      ),
    )
    expect(stale.status).toBe(409)
    expect((await readError(stale)).error.code).toBe('STALE_SIMULATION')
  })

  it('comment 0/501 → 422, comment 1/500 → 201 (границы 1..500)', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    for (const comment of ['', 'a'.repeat(501)]) {
      const invalid = await setupState.mockFetch(
        publishRequest(
          DICTIONARY,
          publishBody(SEED_REVISION + 1, { comment }),
          { csrfToken: session.csrf_token, idempotencyKey: KEY_V3 },
        ),
      )
      expect(invalid.status, `comment length ${comment.length}`).toBe(422)
      const error = await readError(invalid)
      expect(error.error.code).toBe('VALIDATION_ERROR')
      expect(error.error.field_errors.some((item) => item.field === 'comment')).toBe(
        true,
      )
    }

    for (const [index, comment] of ['a', 'b'.repeat(500)].entries()) {
      const valid = await setupState.mockFetch(
        publishRequest(
          DICTIONARY,
          publishBody(SEED_REVISION + 1, { comment }),
          {
            csrfToken: session.csrf_token,
            idempotencyKey: `44444444-4444-4444-8444-44444444444${index}`,
          },
        ),
      )
      expect(valid.status, `comment length ${comment.length}`).toBe(201)
    }
  })
})

describe('mock publishing: идемпотентность', () => {
  it('повтор того же key+body возвращает прежний результат без новой версии', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)

    const first = await drivePublishedV2(setupState, session)
    const firstData = await readJson<PublishedDictionaryResponse>(first)

    // «Потерянный ответ»: тот же ключ/тело повторяется.
    const replay = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION + 1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_V2,
      }),
    )
    expect(replay.status).toBe(201)
    expect(await readJson<PublishedDictionaryResponse>(replay)).toEqual(firstData)

    // Новая версия не создана: только v2 поверх seed v1.
    expect(
      setupState.controller
        .getPublishingStore()
        .listVersions(DICTIONARY)
        .map((version) => version.version_id),
    ).toEqual([VERSION_V2, VERSION_V1])
  })

  it('replay до проверки staleness: повтор принятой операции при устаревшем тесте', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    const first = await drivePublishedV2(setupState, session)
    const firstData = await readJson<PublishedDictionaryResponse>(first)

    // Черновик изменён после принятой публикации — simulation устарела.
    const saved = await putDraft(setupState.api, DICTIONARY, draftBody(SEED_REVISION + 1))
    expect(saved.response.status).toBe(200)

    const replay = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION + 1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_V2,
      }),
    )
    expect(replay.status).toBe(201)
    expect(await readJson<PublishedDictionaryResponse>(replay)).toEqual(firstData)
  })

  it('тот же key с другим телом → 409 IDEMPOTENCY_KEY_REUSED', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    const reused = await setupState.mockFetch(
      publishRequest(
        DICTIONARY,
        publishBody(SEED_REVISION + 1, {
          comment: 'Другое тело с тем же ключом.',
        }),
        { csrfToken: session.csrf_token, idempotencyKey: KEY_V2 },
      ),
    )
    expect(reused.status).toBe(409)
    const error = await readError(reused)
    expect(error.error.code).toBe('IDEMPOTENCY_KEY_REUSED')
    expectSchema('ErrorResponse', error)

    expect(
      setupState.controller.getPublishingStore().listVersions(DICTIONARY),
    ).toHaveLength(2)
  })

  it('новый явный key с другим телом — новая операция, не reuse', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    const newOperation = await setupState.mockFetch(
      publishRequest(
        DICTIONARY,
        publishBody(SEED_REVISION + 1, {
          comment: 'Новая операция с новым ключом.',
        }),
        { csrfToken: session.csrf_token, idempotencyKey: KEY_V3 },
      ),
    )
    expect(newOperation.status).toBe(201)
  })

  it('тот же ключ другого actor — новая операция (идемпотентность user-scoped)', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    const workerTwo = await loginWorkerTwo(setupState.api)
    const otherUser = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION + 1), {
        csrfToken: workerTwo.csrf_token,
        idempotencyKey: KEY_V2,
      }),
    )
    // Тот же UUID для другого user_id не наследует запись worker-one.
    expect(otherUser.status).toBe(201)
  })
})

describe('mock publishing: versions list/get', () => {
  it('list отдаёт literal и finite-страницы без дублей', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    const published = await drivePublishedV3(setupState, session)
    expect(published.status).toBe(201)

    const all = await setupState.api.GET('/dictionaries/{dictionary_id}/versions', {
      params: { path: { dictionary_id: DICTIONARY } },
    })
    expect(all.data).toEqual(
      getExample<PageDictionaryVersion>('versions-atlas-general'),
    )

    const first = await setupState.api.GET('/dictionaries/{dictionary_id}/versions', {
      params: { path: { dictionary_id: DICTIONARY }, query: { limit: 2 } },
    })
    expect(first.data?.items.map((version) => version.version_id)).toEqual([
      'version-atlas-general-v3',
      VERSION_V2,
    ])
    expect(first.data?.next_cursor).toBe('versions-offset-2')

    const second = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions',
      {
        params: {
          path: { dictionary_id: DICTIONARY },
          query: { limit: 2, cursor: first.data?.next_cursor ?? '' },
        },
      },
    )
    expect(second.data?.items.map((version) => version.version_id)).toEqual([
      VERSION_V1,
    ])
    expect(second.data?.next_cursor).toBeNull()
  })

  it('get возвращает literal версию, неизвестный dictionary/version → 404', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    const found = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions/{version_id}',
      { params: { path: { dictionary_id: DICTIONARY, version_id: VERSION_V2 } } },
    )
    expect(found.response.status).toBe(200)
    expect(found.data).toEqual(
      getExample<DictionaryVersion>('version-atlas-general-v2'),
    )
    expectSchema('DictionaryVersion', found.data)

    const unknownDictionary = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions',
      { params: { path: { dictionary_id: 'dictionary-nope' } } },
    )
    expect(unknownDictionary.response.status).toBe(404)

    const unknownVersion = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions/{version_id}',
      {
        params: {
          path: { dictionary_id: DICTIONARY, version_id: 'version-nope' },
        },
      },
    )
    expect(unknownVersion.response.status).toBe(404)
  })

  it('невалидный limit/cursor → 422 без правдоподобного успеха', async () => {
    const setupState = setup()
    await loginWorkerOne(setupState.api)

    const badLimit = await setupState.mockFetch(
      request(`/dictionaries/${DICTIONARY}/versions?limit=101`),
    )
    expect(badLimit.status).toBe(422)
    expect((await readError(badLimit)).error.code).toBe('VALIDATION_ERROR')

    const zeroLimit = await setupState.mockFetch(
      request(`/dictionaries/${DICTIONARY}/versions?limit=0`),
    )
    expect(zeroLimit.status).toBe(422)

    const badCursor = await setupState.mockFetch(
      request(`/dictionaries/${DICTIONARY}/versions?cursor=nope`),
    )
    expect(badCursor.status).toBe(422)
  })

  it('list/get без сессии → 401', async () => {
    const setupState = setup()
    const list = await setupState.api.GET('/dictionaries/{dictionary_id}/versions', {
      params: { path: { dictionary_id: DICTIONARY } },
    })
    expect(list.response.status).toBe(401)
    const get = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions/{version_id}',
      { params: { path: { dictionary_id: DICTIONARY, version_id: VERSION_V1 } } },
    )
    expect(get.response.status).toBe(401)
  })
})

describe('mock publishing: restore/provenance', () => {
  it('restore success → literal restored-v1, based_on_version_id и revision+1', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    const response = await setupState.mockFetch(
      restoreRequest(
        DICTIONARY,
        { version_id: VERSION_V1, expected_draft_revision: SEED_REVISION + 1 },
        { csrfToken: session.csrf_token },
      ),
    )
    expect(response.status).toBe(200)
    const data = await readJson<Dictionary>(response)

    expect(data).toEqual(
      getExample<Dictionary>('dictionary-atlas-general-restored-v1'),
    )
    expect(data.draft.draft_revision).toBe(SEED_REVISION + 2)
    expect(data.draft.based_on_version_id).toBe(VERSION_V1)
    expect(data.active_version_id).toBe(VERSION_V2)
    expectSchema('Dictionary', data)

    // GET /dictionary отражает восстановленное состояние.
    const reread = await setupState.api.GET('/dictionaries/{dictionary_id}', {
      params: { path: { dictionary_id: DICTIONARY } },
    })
    expect(reread.data?.draft.based_on_version_id).toBe(VERSION_V1)
    expect(reread.data?.draft.draft_revision).toBe(SEED_REVISION + 2)
    expect(
      setupState.controller.getPublishingStore().isRestoredDraft(DICTIONARY),
    ).toBe(true)

    // Нет «висячего» active: active v2 опубликована и доступна.
    const activeVersion = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions/{version_id}',
      { params: { path: { dictionary_id: DICTIONARY, version_id: VERSION_V2 } } },
    )
    expect(activeVersion.response.status).toBe(200)
  })

  it('canonical restore запрошенной v2 переносит content/based_on именно v2 (не canned v1)', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    // Текущее состояние: active v2, versions_count 2, draft_revision 2.
    const current = setupState.controller.getDictionaryStore().get(DICTIONARY)
    expect(current?.active_version_id).toBe(VERSION_V2)
    expect(current?.versions_count).toBe(2)
    expect(current?.draft.draft_revision).toBe(SEED_REVISION + 1)

    const response = await setupState.mockFetch(
      restoreRequest(
        DICTIONARY,
        { version_id: VERSION_V2, expected_draft_revision: SEED_REVISION + 1 },
        { csrfToken: session.csrf_token },
      ),
    )
    expect(response.status).toBe(200)
    const data = await readJson<Dictionary>(response)

    // Fallback берёт content именно запрошенной v2, а не canned v1.
    expect(data.draft.based_on_version_id).toBe(VERSION_V2)
    expect(data.draft.rules).toEqual(
      getExample<DictionaryVersion>(VERSION_V2).rules,
    )
    expect(data.draft.rules).toHaveLength(6)
    // active/versions_count не меняются; revision+1.
    expect(data.active_version_id).toBe(VERSION_V2)
    expect(data.versions_count).toBe(2)
    expect(data.draft.draft_revision).toBe(SEED_REVISION + 2)
    expect(data.name).toBe(getExample<DictionaryVersion>(VERSION_V2).name)
    expect(data.description).toBe(
      getExample<DictionaryVersion>(VERSION_V2).description,
    )
    expectSchema('Dictionary', data)

    // Store и история согласованы; v2 доступна.
    expect(setupState.controller.getDictionaryStore().get(DICTIONARY)).toEqual(
      data,
    )
    const version = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions/{version_id}',
      { params: { path: { dictionary_id: DICTIONARY, version_id: VERSION_V2 } } },
    )
    expect(version.response.status).toBe(200)
  })

  it('restore после save-без-publish не меняет active_version_id/versions_count и не создаёт висячий active', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)

    // seed rev 1, active v1, count 1 → save до rev 2 БЕЗ publish.
    const saved = await putDraft(setupState.api, DICTIONARY, draftBody(SEED_REVISION))
    expect(saved.response.status).toBe(200)
    expect(saved.data?.draft.draft_revision).toBe(SEED_REVISION + 1)
    expect(saved.data?.active_version_id).toBe(VERSION_V1)
    expect(saved.data?.versions_count).toBe(1)

    const response = await setupState.mockFetch(
      restoreRequest(
        DICTIONARY,
        { version_id: VERSION_V1, expected_draft_revision: SEED_REVISION + 1 },
        { csrfToken: session.csrf_token },
      ),
    )
    expect(response.status).toBe(200)
    const data = await readJson<Dictionary>(response)

    // Restore — не публикация (API §6): active/versions_count не меняются.
    expect(data.active_version_id).toBe(VERSION_V1)
    expect(data.versions_count).toBe(1)
    expect(data.draft.draft_revision).toBe(SEED_REVISION + 2)
    expect(data.draft.based_on_version_id).toBe(VERSION_V1)
    expect(data.draft.rules).toEqual(
      getExample<DictionaryVersion>(VERSION_V1).rules,
    )
    expectSchema('Dictionary', data)

    // История и store согласованы: v2 ещё не опубликована.
    expect(
      setupState.controller
        .getPublishingStore()
        .listVersions(DICTIONARY)
        .map((version) => version.version_id),
    ).toEqual([VERSION_V1])
    expect(setupState.controller.getDictionaryStore().get(DICTIONARY)).toEqual(
      data,
    )

    // Нет «висячего» active: active/выбранная версия доступна, v2 → 404.
    const activeVersion = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions/{version_id}',
      { params: { path: { dictionary_id: DICTIONARY, version_id: VERSION_V1 } } },
    )
    expect(activeVersion.response.status).toBe(200)

    const notPublished = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions/{version_id}',
      { params: { path: { dictionary_id: DICTIONARY, version_id: VERSION_V2 } } },
    )
    expect(notPublished.response.status).toBe(404)

    // Ручная правка такого черновика по-прежнему очищает provenance.
    const savedAfterRestore = await putDraft(
      setupState.api,
      DICTIONARY,
      draftBody(SEED_REVISION + 2),
    )
    expect(savedAfterRestore.response.status).toBe(200)
    expect(savedAfterRestore.data?.draft.based_on_version_id).toBeNull()
    expect(savedAfterRestore.data?.active_version_id).toBe(VERSION_V1)
    expect(savedAfterRestore.data?.versions_count).toBe(1)
  })

  it('ручная правка восстановленного черновика очищает based_on_version_id', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    const restored = await setupState.mockFetch(
      restoreRequest(
        DICTIONARY,
        { version_id: VERSION_V1, expected_draft_revision: SEED_REVISION + 1 },
        { csrfToken: session.csrf_token },
      ),
    )
    expect(restored.status).toBe(200)

    const manualRules = getExample<Dictionary>(
      'dictionary-atlas-general-manual-edit',
    ).draft.rules
    const saved = await putDraft(setupState.api, DICTIONARY, {
      expected_draft_revision: SEED_REVISION + 2,
      name: 'Общие правила Atlas',
      description: 'Синтетические общие правила Atlas.',
      rules: manualRules,
    })
    expect(saved.response.status).toBe(200)
    expect(saved.data?.draft.draft_revision).toBe(SEED_REVISION + 3)
    expect(saved.data?.draft.based_on_version_id).toBeNull()
    expectSchema('Dictionary', saved.data)
    expect(
      setupState.controller.getPublishingStore().isRestoredDraft(DICTIONARY),
    ).toBe(false)
  })

  it('restore stale revision → 409 DRAFT_VERSION_CONFLICT, unknown version → 404', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    const stale = await setupState.mockFetch(
      restoreRequest(
        DICTIONARY,
        { version_id: VERSION_V1, expected_draft_revision: SEED_REVISION },
        { csrfToken: session.csrf_token },
      ),
    )
    expect(stale.status).toBe(409)
    expect((await readError(stale)).error.code).toBe('DRAFT_VERSION_CONFLICT')

    const unknown = await setupState.mockFetch(
      restoreRequest(
        DICTIONARY,
        {
          version_id: 'version-atlas-general-does-not-exist',
          expected_draft_revision: SEED_REVISION + 1,
        },
        { csrfToken: session.csrf_token },
      ),
    )
    expect(unknown.status).toBe(404)
    expect((await readError(unknown)).error.code).toBe('NOT_FOUND')

    const unknownDictionary = await setupState.mockFetch(
      restoreRequest(
        'dictionary-nope',
        { version_id: VERSION_V1, expected_draft_revision: 0 },
        { csrfToken: session.csrf_token },
      ),
    )
    expect(unknownDictionary.status).toBe(404)
  })
})

describe('mock publishing: 401/403/422', () => {
  it('publish/restore без сессии → 401 (даже без CSRF)', async () => {
    const setupState = setup()
    const publish = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION), {
        csrfToken: null,
        idempotencyKey: KEY_V2,
      }),
    )
    expect(publish.status).toBe(401)
    expect((await readError(publish)).error.code).toBe('UNAUTHENTICATED')

    const restore = await setupState.mockFetch(
      restoreRequest(
        DICTIONARY,
        { version_id: VERSION_V1, expected_draft_revision: SEED_REVISION },
        { csrfToken: null },
      ),
    )
    expect(restore.status).toBe(401)
  })

  it('publish/restore без/с неверным CSRF → 403, store не меняется', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)

    const noCsrf = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION), {
        csrfToken: null,
        idempotencyKey: KEY_V2,
      }),
    )
    expect(noCsrf.status).toBe(403)
    expect((await readError(noCsrf)).error.code).toBe('CSRF_FAILED')

    setCsrfToken(`${session.csrf_token}-wrong`)
    const wrongCsrf = await setupState.mockFetch(
      restoreRequest(
        DICTIONARY,
        { version_id: VERSION_V1, expected_draft_revision: SEED_REVISION },
      ),
    )
    expect(wrongCsrf.status).toBe(403)
    expect(
      setupState.controller.getPublishingStore().listVersions(DICTIONARY),
    ).toHaveLength(1)
  })

  it('invalid body и отсутствие Idempotency-Key → 422 без успеха', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)

    const extra = await setupState.mockFetch(
      publishRequest(
        DICTIONARY,
        { ...publishBody(SEED_REVISION), extra: true },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_V2 },
      ),
    )
    expect(extra.status).toBe(422)
    expect((await readError(extra)).error.code).toBe('VALIDATION_ERROR')

    const missingKey = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION), {
        csrfToken: session.csrf_token,
      }),
    )
    expect(missingKey.status).toBe(422)
    const missingKeyError = await readError(missingKey)
    expect(
      missingKeyError.error.field_errors.some(
        (item) => item.field === 'Idempotency-Key',
      ),
    ).toBe(true)

    const broken = await setupState.mockFetch(
      request(`/dictionaries/${DICTIONARY}/publish`, {
        method: 'POST',
        headers: {
          'X-CSRF-Token': session.csrf_token,
          'Idempotency-Key': KEY_V2,
        },
        body: '{not-json',
      }),
    )
    expect(broken.status).toBe(422)

    const restoreExtra = await setupState.mockFetch(
      restoreRequest(
        DICTIONARY,
        {
          version_id: VERSION_V1,
          expected_draft_revision: SEED_REVISION,
          extra: true,
        },
        { csrfToken: session.csrf_token },
      ),
    )
    expect(restoreExtra.status).toBe(422)

    // Ни одна версия не создана, активная версия — seed.
    expect(
      setupState.controller.getPublishingStore().listVersions(DICTIONARY),
    ).toHaveLength(1)
    expect(
      setupState.controller.getDictionaryStore().get(DICTIONARY)?.active_version_id,
    ).toBe(VERSION_V1)
  })
})

describe('mock publishing: управляемые ошибки и reset', () => {
  it('failNext для publish расходуется один раз (объявленный код)', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)

    setupState.controller.failNext('publishDictionary', 'STALE_SIMULATION')
    const forced = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION + 1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_V3,
      }),
    )
    expect(forced.status).toBe(409)
    expect((await readError(forced)).error.code).toBe('STALE_SIMULATION')

    const normal = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION + 1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_V3,
      }),
    )
    expect(normal.status).toBe(201)
  })

  it('setError для getDictionaryVersion использует только VALIDATION_ERROR', async () => {
    const setupState = setup()
    await loginWorkerOne(setupState.api)
    setupState.controller.setError('getDictionaryVersion', 'VALIDATION_ERROR')

    const forced = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions/{version_id}',
      { params: { path: { dictionary_id: DICTIONARY, version_id: VERSION_V1 } } },
    )
    expect(forced.response.status).toBe(422)
    expect(forced.error?.error.code).toBe('VALIDATION_ERROR')

    setupState.controller.clearError('getDictionaryVersion')
    const normal = await setupState.api.GET(
      '/dictionaries/{dictionary_id}/versions/{version_id}',
      { params: { path: { dictionary_id: DICTIONARY, version_id: VERSION_V1 } } },
    )
    expect(normal.response.status).toBe(200)
  })

  it('reset восстанавливает seed, сценарий и очищает управляемые ошибки', async () => {
    const setupState = setup()
    const session = await loginWithCsrf(setupState.api)
    await drivePublishedV2(setupState, session)
    setupState.controller.setPublishingScenario('v3')
    setupState.controller.setPublishingNow('2031-05-10T10:00:00Z')
    setupState.controller.failNext('publishDictionary', 'RULE_CONFLICT')

    setupState.controller.reset()

    expect(setupState.controller.getPublishingScenario()).toBe('v2')
    expect(setupState.controller.getPublishingNow()).toBeNull()
    expect(
      setupState.controller.getPublishingStore().listVersions(DICTIONARY),
    ).toHaveLength(1)
    expect(
      setupState.controller.getDictionaryStore().get(DICTIONARY)?.draft
        .draft_revision,
    ).toBe(SEED_REVISION)
    expect(
      setupState.controller.getPublishingStore().getActiveRuleSet(ATLAS),
    ).toBeUndefined()

    resetSessionContext()
    const relogin = await loginWithCsrf(setupState.api)
    const normal = await setupState.mockFetch(
      publishRequest(DICTIONARY, publishBody(SEED_REVISION + 1), {
        csrfToken: relogin.csrf_token,
        idempotencyKey: KEY_V2,
      }),
    )
    // Без create simulation (seed rev 1) публикация упирается в stale-ревизию.
    expect(normal.status).toBe(409)
    expect((await readError(normal)).error.code).toBe('DRAFT_VERSION_CONFLICT')
  })
})
