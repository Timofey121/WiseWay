// LT-07.1a: контрактные mocks targets/dictionaries lifecycle без backend/FS.
//
// Проверки идут через `createApiClient({ mode: 'mock', fetch })` (тот же
// транспорт/CSRF/error-модель, что и real) и через mock-fetch напрямую для
// невалидных запросов, которые типизированный клиент не позволяет собрать.
// Все успешные ответы дополнительно валидируются по схемам OAS.
//
// Покрытие: list/resolve targets, list/get/create/replace dictionaries,
// name/revision conflict, границы Rule, 401/403/404/422, управляемые ошибки и
// reset. Никакой matcher/FS-алгоритм не проверяется.

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
  CreateDictionaryRequest,
  Dictionary,
  DictionaryListResponse,
  ErrorResponse,
  LoginRequest,
  ReplaceDictionaryDraftRequest,
  Rule,
  Session,
  TargetDirectory,
} from '@/mocks/types'
import { validateSchema } from '@/mocks/validate'

interface Setup {
  controller: MockController
  mockFetch: MockFetch
  api: WiseWayApiClient
  sleeps: number[]
}

function setup(): Setup {
  const sleeps: number[] = []
  const controller = new MockController({
    sleep: async (ms) => {
      sleeps.push(ms)
    },
  })
  const mockFetch = createMockFetch(controller)
  const api = createApiClient({
    mode: 'mock',
    baseUrl: 'http://localhost/api/v1',
    fetch: mockFetch,
  })
  return { controller, mockFetch, api, sleeps }
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

// Типизированный клиент требует объявленный header X-CSRF-Token; транспорт —
// единственный источник mutation-заголовков и подставляет реальный токен либо
// удаляет заголовок. Значение заглушки ни на что не влияет.
function postCreate(
  api: WiseWayApiClient,
  companyId: string,
  body: CreateDictionaryRequest,
) {
  return api.POST('/companies/{company_id}/dictionaries', {
    params: {
      path: { company_id: companyId },
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

const ATLAS = 'company-demo-atlas'
const NOVA = 'company-demo-nova'

const VALID_RULE: Rule = {
  rule_id: 'rule-test-1',
  priority: 10,
  match_field: 'BASENAME',
  mask: '*test*',
  target: {
    root_id: 'root-demo-atlas',
    relative_directory: 'Archive/Atlas/Orion_2031/Data',
  },
  target_stem: 'Test',
}

function draftBody(
  expectedDraftRevision: number,
  rules: Rule[] = [VALID_RULE],
): ReplaceDictionaryDraftRequest {
  return {
    expected_draft_revision: expectedDraftRevision,
    name: 'Общие правила Atlas',
    description: 'Синтетические общие правила Atlas.',
    rules,
  }
}

beforeEach(() => {
  resetSessionContext()
})

describe('mock-fetch: маршрутизация targets/dictionaries', () => {
  it('регистрирует 6 операций и извлекает path-параметры', () => {
    const routes = [
      ['GET', '/companies/company-demo-atlas/target-directories'],
      ['POST', '/companies/company-demo-atlas/target-directories/resolve'],
      ['GET', '/companies/company-demo-atlas/dictionaries'],
      ['POST', '/companies/company-demo-atlas/dictionaries'],
      ['GET', '/dictionaries/dictionary-atlas-general'],
      ['PUT', '/dictionaries/dictionary-atlas-general/draft'],
    ] as const
    for (const [method, path] of routes) {
      expect(matchMockRoute(method, path), `${method} ${path}`).toBeDefined()
    }
    expect(
      matchMockRoute('GET', '/companies/company-demo-atlas/dictionaries')
        ?.params,
    ).toEqual({ company_id: 'company-demo-atlas' })
    expect(
      matchMockRoute('PUT', '/dictionaries/dictionary-atlas-general/draft')
        ?.params,
    ).toEqual({ dictionary_id: 'dictionary-atlas-general' })
  })

  it('все ответы несут X-Request-ID, Cache-Control и mock-маркер', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const result = await api.GET('/companies/{company_id}/dictionaries', {
      params: { path: { company_id: ATLAS } },
    })
    expect(result.response.status).toBe(200)
    expect(result.response.headers.get('Cache-Control')).toBe('no-store')
    expect(result.response.headers.get('X-Request-ID')).toMatch(
      /^request-mock-\d+$/,
    )
    expect(result.response.headers.get(MOCK_MARKER_HEADER)).toBe(MOCK_MODE)
  })
})

describe('mock targets: list', () => {
  it('company-scope: Atlas 5 целей, Nova 4, каждая schema-valid', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const atlas = await api.GET('/companies/{company_id}/target-directories', {
      params: { path: { company_id: ATLAS } },
    })
    expect(atlas.response.status).toBe(200)
    expect(atlas.data?.items).toHaveLength(5)
    expect(
      atlas.data?.items.every((item) => item.root_id === 'root-demo-atlas'),
    ).toBe(true)
    expectSchema('PageTargetDirectory', atlas.data)

    const nova = await api.GET('/companies/{company_id}/target-directories', {
      params: { path: { company_id: NOVA } },
    })
    expect(nova.response.status).toBe(200)
    expect(nova.data?.items).toHaveLength(4)
    expect(
      nova.data?.items.every((item) => item.root_id === 'root-demo-nova'),
    ).toBe(true)
  })

  it('prefix фильтрует по регистронезависимому началу relative_directory', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const result = await api.GET('/companies/{company_id}/target-directories', {
      params: {
        path: { company_id: ATLAS },
        query: { prefix: 'archive/atlas/orion_2031/data' },
      },
    })
    expect(result.response.status).toBe(200)
    expect(result.data?.items).toEqual([
      {
        root_id: 'root-demo-atlas',
        relative_directory: 'Archive/Atlas/Orion_2031/Data',
        display_path: 'DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Data',
      },
    ])
  })

  it('limit/cursor дают finite-страницы без дублей', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const first = await api.GET('/companies/{company_id}/target-directories', {
      params: { path: { company_id: ATLAS }, query: { limit: 2 } },
    })
    expect(first.data?.items).toHaveLength(2)
    expect(first.data?.next_cursor).toBe('t2')

    const second = await api.GET('/companies/{company_id}/target-directories', {
      params: {
        path: { company_id: ATLAS },
        query: { limit: 2, cursor: first.data?.next_cursor ?? '' },
      },
    })
    expect(second.data?.items).toHaveLength(2)
    expect(second.data?.next_cursor).toBe('t4')

    const third = await api.GET('/companies/{company_id}/target-directories', {
      params: {
        path: { company_id: ATLAS },
        query: { limit: 2, cursor: second.data?.next_cursor ?? '' },
      },
    })
    expect(third.data?.items).toHaveLength(1)
    expect(third.data?.next_cursor).toBeNull()

    const ids = [
      ...(first.data?.items ?? []),
      ...(second.data?.items ?? []),
      ...(third.data?.items ?? []),
    ].map((item) => item.relative_directory)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('невалидный limit/cursor → 422 без правдоподобного успеха', async () => {
    const { api, mockFetch } = setup()
    await loginWorkerOne(api)

    const badLimit = await mockFetch(
      request('/companies/company-demo-atlas/target-directories?limit=101'),
    )
    expect(badLimit.status).toBe(422)
    expect((await readError(badLimit)).error.code).toBe('VALIDATION_ERROR')

    const zeroLimit = await mockFetch(
      request('/companies/company-demo-atlas/target-directories?limit=0'),
    )
    expect(zeroLimit.status).toBe(422)

    const badCursor = await mockFetch(
      request(
        '/companies/company-demo-atlas/target-directories?cursor=not-a-cursor',
      ),
    )
    expect(badCursor.status).toBe(422)
  })

  it('list без сессии → 401 UNAUTHENTICATED', async () => {
    const { api } = setup()
    const result = await api.GET('/companies/{company_id}/target-directories', {
      params: { path: { company_id: ATLAS } },
    })
    expect(result.response.status).toBe(401)
    expect(result.error?.error.code).toBe('UNAUTHENTICATED')
  })
})

describe('mock targets: resolve', () => {
  it('разрешённый display_path → 200 TargetDirectory из контрактного примера', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const expected = getExample<TargetDirectory>('target-atlas-reports')

    const result = await api.POST(
      '/companies/{company_id}/target-directories/resolve',
      {
        params: { path: { company_id: ATLAS } },
        body: { display_path: expected.display_path },
      },
    )
    expect(result.response.status).toBe(200)
    expect(result.data).toEqual(expected)
    expectSchema('TargetDirectory', result.data)
  })

  it('несуществующий каталог → 422 INVALID_TARGET, allowlist не меняется', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const result = await api.POST(
      '/companies/{company_id}/target-directories/resolve',
      {
        params: { path: { company_id: ATLAS } },
        body: {
          display_path:
            'DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/NoSuchDir',
        },
      },
    )
    expect(result.response.status).toBe(422)
    expect(result.error?.error.code).toBe('INVALID_TARGET')
    expectSchema('ErrorResponse', result.error)
  })

  it('выход за корень → 422 PATH_OUTSIDE_ROOT', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const result = await api.POST(
      '/companies/{company_id}/target-directories/resolve',
      {
        params: { path: { company_id: ATLAS } },
        body: { display_path: 'DEMO:/OtherSandbox/Archive/Atlas' },
      },
    )
    expect(result.response.status).toBe(422)
    expect(result.error?.error.code).toBe('PATH_OUTSIDE_ROOT')
  })

  it('малформед relative path → VALIDATION_ERROR; компьютерный путь → INVALID_TARGET', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const malformed = await api.POST(
      '/companies/{company_id}/target-directories/resolve',
      {
        params: { path: { company_id: ATLAS } },
        body: {
          display_path: 'DEMO:/SandboxRoot/Archive/Atlas//Reports',
        },
      },
    )
    expect(malformed.response.status).toBe(422)
    expect(malformed.error?.error.code).toBe('VALIDATION_ERROR')

    const arbitrary = await api.POST(
      '/companies/{company_id}/target-directories/resolve',
      {
        params: { path: { company_id: ATLAS } },
        body: { display_path: 'C:/Windows/System32' },
      },
    )
    expect(arbitrary.response.status).toBe(422)
    expect(arbitrary.error?.error.code).toBe('INVALID_TARGET')
  })

  it('цель другой компании → 422 INVALID_TARGET', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const result = await api.POST(
      '/companies/{company_id}/target-directories/resolve',
      {
        params: { path: { company_id: NOVA } },
        body: {
          display_path: 'DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Reports',
        },
      },
    )
    expect(result.response.status).toBe(422)
    expect(result.error?.error.code).toBe('INVALID_TARGET')
  })

  it('resolve без сессии → 401, невалидное тело → 422', async () => {
    const { api, mockFetch } = setup()

    const unauth = await api.POST(
      '/companies/{company_id}/target-directories/resolve',
      {
        params: { path: { company_id: ATLAS } },
        body: {
          display_path: 'DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Data',
        },
      },
    )
    expect(unauth.response.status).toBe(401)

    await loginWorkerOne(api)
    const extraField = await mockFetch(
      request('/companies/company-demo-atlas/target-directories/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          display_path: 'DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Data',
          extra: true,
        }),
      }),
    )
    expect(extraField.status).toBe(422)

    const broken = await mockFetch(
      request('/companies/company-demo-atlas/target-directories/resolve', {
        method: 'POST',
        body: '{not-json',
      }),
    )
    expect(broken.status).toBe(422)
  })
})

describe('mock dictionaries: list/get', () => {
  it('listDictionaries company-scoped и schema-valid', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const atlas = await api.GET('/companies/{company_id}/dictionaries', {
      params: { path: { company_id: ATLAS } },
    })
    expect(atlas.response.status).toBe(200)
    expect(atlas.data?.items.map((item) => item.dictionary_id)).toEqual([
      'dictionary-atlas-general',
      'dictionary-atlas-invoices',
    ])
    expect(atlas.data).toEqual(
      getExample<DictionaryListResponse>('dictionary-atlas-general-list'),
    )
    expectSchema('DictionaryListResponse', atlas.data)

    const nova = await api.GET('/companies/{company_id}/dictionaries', {
      params: { path: { company_id: NOVA } },
    })
    expect(nova.data?.items.map((item) => item.dictionary_id)).toEqual([
      'dictionary-nova-general',
    ])
  })

  it('getDictionary → 200 Dictionary; неизвестный → 404 NOT_FOUND', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const expected = getExample<Dictionary>('dictionary-atlas-general')

    const found = await api.GET('/dictionaries/{dictionary_id}', {
      params: { path: { dictionary_id: 'dictionary-atlas-general' } },
    })
    expect(found.response.status).toBe(200)
    expect(found.data).toEqual(expected)
    expectSchema('Dictionary', found.data)

    const missing = await api.GET('/dictionaries/{dictionary_id}', {
      params: { path: { dictionary_id: 'dictionary-does-not-exist' } },
    })
    expect(missing.response.status).toBe(404)
    expect(missing.error?.error.code).toBe('NOT_FOUND')
  })

  it('list/get без сессии → 401 UNAUTHENTICATED', async () => {
    const { api } = setup()
    const list = await api.GET('/companies/{company_id}/dictionaries', {
      params: { path: { company_id: ATLAS } },
    })
    const get = await api.GET('/dictionaries/{dictionary_id}', {
      params: { path: { dictionary_id: 'dictionary-atlas-general' } },
    })
    expect(list.response.status).toBe(401)
    expect(get.response.status).toBe(401)
  })
})

describe('mock dictionaries: create', () => {
  it('create success → 201 Dictionary с пустым черновиком revision=0', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)

    const result = await postCreate(api, ATLAS, {
      name: 'Новый справочник',
      description: 'Описание нового справочника.',
    })

    expect(result.response.status).toBe(201)
    expect(result.data?.draft.draft_revision).toBe(0)
    expect(result.data?.draft.rules).toEqual([])
    expect(result.data?.draft.based_on_version_id).toBeNull()
    expect(result.data?.active_version_id).toBeNull()
    expect(result.data?.versions_count).toBe(0)
    expect(result.data?.company_id).toBe(ATLAS)
    expectSchema('Dictionary', result.data)

    const list = await api.GET('/companies/{company_id}/dictionaries', {
      params: { path: { company_id: ATLAS } },
    })
    expect(list.data?.items).toHaveLength(3)
    expect(
      controller
        .getDictionaryStore()
        .list(ATLAS)
        .some((item) => item.name === 'Новый справочник'),
    ).toBe(true)
  })

  it('name conflict после trim+casefold → 409, store не растёт', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const conflict = await postCreate(api, ATLAS, {
      name: '  СЧЕТА ATLAS  ',
      description: 'Попытка дубликата имени.',
    })
    expect(conflict.response.status).toBe(409)
    expect(conflict.error?.error.code).toBe('DICTIONARY_NAME_CONFLICT')
    expectSchema('ErrorResponse', conflict.error)

    const list = await api.GET('/companies/{company_id}/dictionaries', {
      params: { path: { company_id: ATLAS } },
    })
    expect(list.data?.items).toHaveLength(2)
  })

  it('то же имя в другой компании → успех (уникальность внутри компании)', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const result = await postCreate(api, NOVA, {
      name: 'Счета Atlas',
      description: 'Проверка отсутствия межкомпанийного конфликта имён.',
    })
    expect(result.response.status).toBe(201)
    expect(result.data?.company_id).toBe(NOVA)
  })

  it('границы name 1/128 валидны, 129 → 422; description 0/1000 валидны, 1001 → 422', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const okName1 = await postCreate(api, ATLAS, {
      name: 'A',
      description: '',
    })
    expect(okName1.response.status).toBe(201)

    const okName128 = await postCreate(api, ATLAS, {
      name: 'B'.repeat(128),
      description: 'd'.repeat(1000),
    })
    expect(okName128.response.status).toBe(201)

    const badName129 = await postCreate(api, ATLAS, {
      name: 'C'.repeat(129),
      description: 'ok',
    })
    expect(badName129.response.status).toBe(422)
    expect(badName129.error?.error.code).toBe('VALIDATION_ERROR')

    const badDescription = await postCreate(api, ATLAS, {
      name: 'Описание слишком длинное',
      description: 'e'.repeat(1001),
    })
    expect(badDescription.response.status).toBe(422)
  })

  it('create без/с неверным CSRF → 403, store не меняется', async () => {
    const { api, controller } = setup()
    const session = await loginWorkerOne(api)

    const noToken = await postCreate(api, ATLAS, {
      name: 'Без CSRF',
      description: 'Описание.',
    })
    expect(noToken.response.status).toBe(403)
    expect(noToken.error?.error.code).toBe('CSRF_FAILED')

    setCsrfToken(`${session.csrf_token}-wrong`)
    const wrongToken = await postCreate(api, ATLAS, {
      name: 'Неверный CSRF',
      description: 'Описание.',
    })
    expect(wrongToken.response.status).toBe(403)
    expect(controller.getDictionaryStore().list(ATLAS)).toHaveLength(2)
  })

  it('create без сессии → 401 (даже без CSRF)', async () => {
    const { api } = setup()
    const result = await postCreate(api, ATLAS, {
      name: 'Без сессии',
      description: 'Описание.',
    })
    expect(result.response.status).toBe(401)
    expect(result.error?.error.code).toBe('UNAUTHENTICATED')
  })

  it('invalid body (лишнее поле/битый JSON) → 422 без создания', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const extra = await mockFetch(
      request('/companies/company-demo-atlas/dictionaries', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: JSON.stringify({
          name: 'Лишнее поле',
          description: 'Описание.',
          extra: true,
        }),
      }),
    )
    expect(extra.status).toBe(422)

    const broken = await mockFetch(
      request('/companies/company-demo-atlas/dictionaries', {
        method: 'POST',
        headers: { 'X-CSRF-Token': session.csrf_token },
        body: '{not-json',
      }),
    )
    expect(broken.status).toBe(422)
    expect(controller.getDictionaryStore().list(ATLAS)).toHaveLength(2)
  })
})

describe('mock dictionaries: replace draft', () => {
  it('success сохраняет черновик и увеличивает revision', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const result = await putDraft(
      api,
      'dictionary-atlas-general',
      draftBody(1),
    )

    expect(result.response.status).toBe(200)
    expect(result.data?.draft.draft_revision).toBe(2)
    expect(result.data?.draft.rules).toEqual([VALID_RULE])
    expectSchema('Dictionary', result.data)
  })

  it('неверная expected revision → 409, store не перезаписывается', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)

    const conflict = await putDraft(
      api,
      'dictionary-atlas-general',
      draftBody(99, []),
    )
    expect(conflict.response.status).toBe(409)
    expect(conflict.error?.error.code).toBe('DRAFT_VERSION_CONFLICT')
    expectSchema('ErrorResponse', conflict.error)

    const stored = controller
      .getDictionaryStore()
      .get('dictionary-atlas-general')
    expect(stored?.draft.draft_revision).toBe(1)
    expect(stored?.draft.rules.length).toBe(4)

    const reread = await api.GET('/dictionaries/{dictionary_id}', {
      params: { path: { dictionary_id: 'dictionary-atlas-general' } },
    })
    expect(reread.data?.draft.draft_revision).toBe(1)
    expect(reread.data?.draft.rules).toHaveLength(4)
  })

  it('replace без/с неверным CSRF → 403, revision не меняется', async () => {
    const { api, controller } = setup()
    const session = await loginWorkerOne(api)

    const noToken = await putDraft(
      api,
      'dictionary-atlas-general',
      draftBody(1),
    )
    expect(noToken.response.status).toBe(403)
    expect(noToken.error?.error.code).toBe('CSRF_FAILED')

    setCsrfToken(`${session.csrf_token}-wrong`)
    const wrong = await putDraft(api, 'dictionary-atlas-general', draftBody(1))
    expect(wrong.response.status).toBe(403)
    expect(
      controller.getDictionaryStore().get('dictionary-atlas-general')?.draft
        .draft_revision,
    ).toBe(1)
  })

  it('replace неизвестного dictionary → 404; без сессии → 401', async () => {
    const { api } = setup()
    const unauth = await putDraft(
      api,
      'dictionary-atlas-general',
      draftBody(1),
    )
    expect(unauth.response.status).toBe(401)

    await loginWithCsrf(api)
    const missing = await putDraft(api, 'dictionary-nope', draftBody(0))
    expect(missing.response.status).toBe(404)
    expect(missing.error?.error.code).toBe('NOT_FOUND')
  })

  it('границы Rule (priority 0/1001, mask **, пустая mask, target_stem 201, mask 513) → 422', async () => {
    const cases: Array<[string, Rule]> = [
      ['priority 0', { ...VALID_RULE, rule_id: 'rule-p0', priority: 0 }],
      ['priority 1001', { ...VALID_RULE, rule_id: 'rule-p1001', priority: 1001 }],
      ['mask **', { ...VALID_RULE, rule_id: 'rule-star', mask: 'a**b' }],
      ['пустая mask', { ...VALID_RULE, rule_id: 'rule-empty-mask', mask: '' }],
      [
        'target_stem 201',
        { ...VALID_RULE, rule_id: 'rule-stem201', target_stem: 's'.repeat(201) },
      ],
      [
        'mask 513',
        { ...VALID_RULE, rule_id: 'rule-mask513', mask: 'm'.repeat(513) },
      ],
    ]

    for (const [label, rule] of cases) {
      const { api } = setup()
      await loginWithCsrf(api)
      const result = await putDraft(
        api,
        'dictionary-atlas-general',
        draftBody(1, [rule]),
      )
      expect(result.response.status, label).toBe(422)
      expect(result.error?.error.code, label).toBe('VALIDATION_ERROR')
    }

    // Границы, которые валидны: target_stem 200 и mask 512.
    const { api } = setup()
    await loginWithCsrf(api)
    const valid = await putDraft(
      api,
      'dictionary-atlas-general',
      draftBody(1, [
        {
          ...VALID_RULE,
          rule_id: 'rule-boundary',
          target_stem: 's'.repeat(200),
          mask: 'm'.repeat(512),
        },
      ]),
    )
    expect(valid.response.status).toBe(200)
  })

  it('target вне allowlist компании → 422 INVALID_TARGET', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const missingDir = await putDraft(
      api,
      'dictionary-atlas-general',
      draftBody(1, [
        {
          ...VALID_RULE,
          rule_id: 'rule-bad-target',
          target: {
            root_id: 'root-demo-atlas',
            relative_directory: 'Archive/Atlas/Orion_2031/NoSuchDir',
          },
        },
      ]),
    )
    expect(missingDir.response.status).toBe(422)
    expect(missingDir.error?.error.code).toBe('INVALID_TARGET')

    const otherCompany = await putDraft(api, 'dictionary-nova-general', {
      ...draftBody(1, [
        {
          ...VALID_RULE,
          rule_id: 'rule-other-company',
          target: {
            root_id: 'root-demo-atlas',
            relative_directory: 'Archive/Atlas/Orion_2031/Data',
          },
        },
      ]),
      name: 'Общие правила Nova',
      description: 'Синтетические общие правила Nova.',
    })
    expect(otherCompany.response.status).toBe(422)
    expect(otherCompany.error?.error.code).toBe('INVALID_TARGET')
  })

  it('дубли rule_id и лишнее поле → 422 без записи', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const duplicate = await putDraft(
      api,
      'dictionary-atlas-general',
      draftBody(1, [
        { ...VALID_RULE, rule_id: 'rule-dup' },
        { ...VALID_RULE, rule_id: 'rule-dup' },
      ]),
    )
    expect(duplicate.response.status).toBe(422)

    const extra = await mockFetch(
      request('/dictionaries/dictionary-atlas-general/draft', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: JSON.stringify({ ...draftBody(1), extra: true }),
      }),
    )
    expect(extra.status).toBe(422)
    expect(
      controller.getDictionaryStore().get('dictionary-atlas-general')?.draft
        .draft_revision,
    ).toBe(1)
  })
})

describe('mock dictionaries: управляемые ошибки и reset', () => {
  it('failNext для createDictionary расходуется один раз', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.failNext('createDictionary', 'DICTIONARY_NAME_CONFLICT')

    const first = await postCreate(api, ATLAS, {
      name: 'Первая попытка',
      description: 'Описание.',
    })
    expect(first.response.status).toBe(409)

    const second = await postCreate(api, ATLAS, {
      name: 'Первая попытка',
      description: 'Описание.',
    })
    expect(second.response.status).toBe(201)
  })

  it('setError для resolver переопределяет успешный lookup до clearError', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setError('resolveTargetDirectory', 'PATH_OUTSIDE_ROOT')

    const body = {
      display_path: 'DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Reports',
    }
    const forced = await api.POST(
      '/companies/{company_id}/target-directories/resolve',
      { params: { path: { company_id: ATLAS } }, body },
    )
    expect(forced.response.status).toBe(422)
    expect(forced.error?.error.code).toBe('PATH_OUTSIDE_ROOT')

    controller.clearError('resolveTargetDirectory')
    const normal = await api.POST(
      '/companies/{company_id}/target-directories/resolve',
      { params: { path: { company_id: ATLAS } }, body },
    )
    expect(normal.response.status).toBe(200)
  })

  it('reset восстанавливает seed и очищает управляемые ошибки', async () => {
    const { api, controller } = setup()
    const session = await loginWithCsrf(api)

    const created = await postCreate(api, ATLAS, {
      name: 'Временный',
      description: 'Описание.',
    })
    expect(created.response.status).toBe(201)
    const createdId = created.data?.dictionary_id ?? ''

    controller.failNext('createDictionary', 'DICTIONARY_NAME_CONFLICT')
    controller.reset()

    expect(controller.getDictionaryStore().list(ATLAS)).toHaveLength(2)
    expect(controller.getDictionaryStore().get(createdId)).toBeUndefined()

    resetSessionContext()
    const relogin = await loginWithCsrf(api)
    const list = await api.GET('/companies/{company_id}/dictionaries', {
      params: { path: { company_id: ATLAS } },
    })
    expect(list.data?.items).toHaveLength(2)
    expect(list.data?.items.map((item) => item.draft.draft_revision)).toEqual([
      1, 1,
    ])

    expect(relogin.csrf_token).toBe(session.csrf_token)
    const afterReset = await postCreate(api, ATLAS, {
      name: 'После reset',
      description: 'Описание.',
    })
    expect(afterReset.response.status).toBe(201)
  })
})
