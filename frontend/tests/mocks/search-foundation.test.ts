// LT-06.2a-i: golden search/facet data foundation.
//
// Проверки доказывают, что materializer раскрывает корпус детерминированно,
// а resolver отдаёт literal golden-ответы без matcher/ranking/парсинга:
// 51 search + 6 facet сценариев schema-valid, totals/order/item_ids/facets
// совпадают с эталоном, cohort раскрыт, неизвестный request → undefined.

import corpusFixture from '@fixtures/synthetic/corpus.json'
import searchExpectationsFixture from '@fixtures/synthetic/search_expectations.json'
import { describe, expect, it } from 'vitest'

import {
  getSearchItem,
  getUnrecognizedMarker,
  inventorySize,
  listInventoryItemIds,
  listMarkerIds,
  markerCatalogById,
} from '@/mocks/search/corpus'
import {
  facetScenarioCount,
  listFacetScenarioIds,
  listSearchScenarioIds,
  resolveFacetScenario,
  resolveSearchScenario,
  searchScenarioCount,
} from '@/mocks/search/expectations'
import { validateSchema } from '@/mocks/validate'

interface GoldenSearchScenario {
  scenario_id: string
  request: {
    request_state_id: string
    root_id: string
    selected_marker_ids: string[]
    query_text: string
    sort: { field: string; direction: string }
    facet_prefix: string
  }
  expected: {
    mode: 'IDLE' | 'RESULTS'
    total: number | null
    returned_count: number
    result_limit: number
    limited: boolean
    applied_query_text: string
    item_ids: string[]
    next_facet: {
      level_id: string
      level_name: string
      options: { marker_id: string; count: number }[]
    } | null
  }
  freshness_profile?: 'CURRENT' | 'UPDATING' | 'STALE'
}

interface GoldenFacetScenario {
  scenario_id: string
  request: {
    request_state_id: string
    root_id: string
    selected_marker_ids: string[]
    query_text: string
    facet_prefix: string
  }
  expected: {
    facet_level_id: string | null
    options: { marker_id: string; count: number }[]
  }
}

interface GoldenConstants {
  ranking_profile_version: string
  freshness_profiles: Record<
    string,
    { indexed_at: string; last_successful_sync_at: string; status: string }
  >
  roots: Record<string, { schema_set_version: string; index_generation: string }>
  level_names: Record<string, string>
}

interface GoldenFile {
  constants: GoldenConstants
  search_scenarios: GoldenSearchScenario[]
  facet_scenarios: GoldenFacetScenario[]
}

interface RawCorpusForTest {
  files: { item_id: string; relative_path: string }[]
  cohorts: { count: number }[]
  marker_model: { contexts: { root_id: string; path: string[] }[] }
}

const golden = searchExpectationsFixture as unknown as GoldenFile
const corpus = corpusFixture as unknown as RawCorpusForTest

function optionKeys(
  options: { marker_id: string; count: number }[],
): { marker_id: string; count: number }[] {
  return options.map((option) => ({
    marker_id: option.marker_id,
    count: option.count,
  }))
}

describe('materialized inventory', () => {
  it('раскрывает files + cohorts и совпадает по размеру', () => {
    const expectedFiles =
      corpus.files.length +
      corpus.cohorts.reduce((sum, cohort) => sum + cohort.count, 0)
    expect(inventorySize()).toBe(expectedFiles)
    expect(listInventoryItemIds()).toHaveLength(expectedFiles)
  })

  it('строит каталог всех контекстных marker_id', () => {
    // marker_id уникален для root + цепочки value_id.
    const expectedMarkerIds = new Set<string>()
    for (const context of corpus.marker_model.contexts) {
      for (let length = 1; length <= context.path.length; length += 1) {
        expectedMarkerIds.add(
          `${context.root_id}|${context.path.slice(0, length).join('|')}`,
        )
      }
    }
    expect(listMarkerIds()).toHaveLength(expectedMarkerIds.size)
    expect(expectedMarkerIds.size).toBeGreaterThan(0)
  })

  it('каждый SearchItem schema-valid и VALUE-маркеры равны ведущим сегментам пути', () => {
    for (const itemId of listInventoryItemIds()) {
      const item = getSearchItem(itemId)
      expect(item, itemId).toBeDefined()
      if (!item) {
        continue
      }
      const validation = validateSchema('SearchItem', item)
      expect(validation.valid, `${itemId}: ${JSON.stringify(validation.errors)}`).toBe(
        true,
      )
      const leading = item.location.relative_path.split('/').slice(0, -1)
      expect(item.markers.length, itemId).toBeLessThanOrEqual(leading.length)
      item.markers.forEach((marker, index) => {
        expect(marker.kind, `${itemId} marker ${marker.marker_id}`).toBe('VALUE')
        expect(marker.raw_value, `${itemId} marker ${marker.marker_id}`).toBe(
          leading[index],
        )
      })
    }
  })

  it('раскрывает cohort literal-подстановкой {index} и index_pad', () => {
    const first = getSearchItem('file-atlas-orion-report-0001')
    const last = getSearchItem('file-atlas-orion-report-0103')
    expect(first).toBeDefined()
    expect(last).toBeDefined()
    expect(first?.location.relative_path).toBe(
      'Archive/Atlas/Orion_2031/Reports/Atlas-Orion-Report-0001.pdf',
    )
    expect(first?.location.display_path).toBe(
      'DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Reports/Atlas-Orion-Report-0001.pdf',
    )
    expect(first?.filename).toBe('Atlas-Orion-Report-0001.pdf')
    expect(last?.location.relative_path).toBe(
      'Archive/Atlas/Orion_2031/Reports/Atlas-Orion-Report-0103.pdf',
    )
    expect(getSearchItem('file-atlas-orion-report-0104')).toBeUndefined()
  })
})

describe('golden search scenarios', () => {
  it('загружает ровно 51 search-сценарий', () => {
    expect(searchScenarioCount()).toBe(51)
    expect(listSearchScenarioIds()).toHaveLength(51)
    expect(golden.search_scenarios).toHaveLength(51)
  })

  it.each(golden.search_scenarios.map((scenario) => [scenario.scenario_id, scenario] as const))(
    'разрешает %s в literal schema-valid SearchResponse',
    (_scenarioId, scenario) => {
      const response = resolveSearchScenario(scenario.request)
      expect(response, scenario.scenario_id).toBeDefined()
      if (!response) {
        return
      }

      const validation = validateSchema('SearchResponse', response)
      expect(
        validation.valid,
        `${scenario.scenario_id}: ${JSON.stringify(validation.errors)}`,
      ).toBe(true)

      expect(response.request_state_id).toBe(scenario.request.request_state_id)
      expect(response.mode).toBe(scenario.expected.mode)
      expect(response.root_id).toBe(scenario.request.root_id)
      expect(response.schema_set_version).toBe(
        golden.constants.roots[scenario.request.root_id].schema_set_version,
      )
      expect(response.index_generation).toBe(
        golden.constants.roots[scenario.request.root_id].index_generation,
      )
      expect(response.ranking_profile_version).toBe(
        golden.constants.ranking_profile_version,
      )
      expect(response.applied_query_text).toBe(scenario.expected.applied_query_text)
      expect(response.total).toBe(scenario.expected.total)
      expect(response.returned_count).toBe(scenario.expected.returned_count)
      expect(response.result_limit).toBe(scenario.expected.result_limit)
      expect(response.limited).toBe(scenario.expected.limited)
      expect(response.items.map((item) => item.item_id)).toEqual(
        scenario.expected.item_ids,
      )
      expect(response.selected_markers.map((marker) => marker.marker_id)).toEqual(
        scenario.request.selected_marker_ids,
      )
      expect(response.freshness).toEqual(
        golden.constants.freshness_profiles[
          scenario.freshness_profile ?? 'CURRENT'
        ],
      )

      if (scenario.expected.next_facet === null) {
        expect(response.next_facet).toBeNull()
      } else {
        expect(response.next_facet?.level_id).toBe(
          scenario.expected.next_facet.level_id,
        )
        expect(response.next_facet?.level_name).toBe(
          scenario.expected.next_facet.level_name,
        )
        expect(optionKeys(response.next_facet?.options ?? [])).toEqual(
          scenario.expected.next_facet.options,
        )
      }
    },
  )

  it('каждый golden marker_id присутствует в materialized-каталоге', () => {
    const referenced = new Set<string>()
    for (const scenario of golden.search_scenarios) {
      for (const markerId of scenario.request.selected_marker_ids) {
        referenced.add(markerId)
      }
      for (const option of scenario.expected.next_facet?.options ?? []) {
        referenced.add(option.marker_id)
      }
    }
    for (const scenario of golden.facet_scenarios) {
      for (const markerId of scenario.request.selected_marker_ids) {
        referenced.add(markerId)
      }
      for (const option of scenario.expected.options) {
        referenced.add(option.marker_id)
      }
    }
    expect(referenced.size).toBeGreaterThan(0)
    for (const markerId of referenced) {
      expect(markerCatalogById.has(markerId), markerId).toBe(true)
    }
  })

  it('selected_markers и options обогащаются полями из каталога', () => {
    const scenario = golden.search_scenarios.find(
      (candidate) => candidate.request.selected_marker_ids.length > 0,
    )
    expect(scenario).toBeDefined()
    if (!scenario) {
      return
    }
    const response = resolveSearchScenario(scenario.request)
    expect(response).toBeDefined()
    response?.selected_markers.forEach((marker, index) => {
      expect(marker).toEqual(
        markerCatalogById.get(scenario.request.selected_marker_ids[index]),
      )
    })
    response?.next_facet?.options.forEach((option) => {
      const catalogMarker = markerCatalogById.get(option.marker_id)
      expect(catalogMarker).toBeDefined()
      expect(option).toEqual({ ...catalogMarker, count: option.count })
    })
  })
})

describe('golden facet scenarios', () => {
  it('загружает ровно 6 facet-сценариев', () => {
    expect(facetScenarioCount()).toBe(6)
    expect(listFacetScenarioIds()).toHaveLength(6)
  })

  it.each(golden.facet_scenarios.map((scenario) => [scenario.scenario_id, scenario] as const))(
    'разрешает %s в literal schema-valid FacetResponse',
    (_scenarioId, scenario) => {
      const response = resolveFacetScenario(scenario.request)
      expect(response, scenario.scenario_id).toBeDefined()
      if (!response) {
        return
      }

      const validation = validateSchema('FacetResponse', response)
      expect(
        validation.valid,
        `${scenario.scenario_id}: ${JSON.stringify(validation.errors)}`,
      ).toBe(true)

      expect(response.request_state_id).toBe(scenario.request.request_state_id)
      expect(response.root_id).toBe(scenario.request.root_id)
      expect(response.schema_set_version).toBe(
        golden.constants.roots[scenario.request.root_id].schema_set_version,
      )
      expect(response.index_generation).toBe(
        golden.constants.roots[scenario.request.root_id].index_generation,
      )

      if (scenario.expected.facet_level_id === null) {
        expect(response.facet).toBeNull()
      } else {
        expect(response.facet?.level_id).toBe(scenario.expected.facet_level_id)
        expect(response.facet?.level_name).toBe(
          golden.constants.level_names[scenario.expected.facet_level_id],
        )
        expect(optionKeys(response.facet?.options ?? [])).toEqual(
          scenario.expected.options,
        )
      }
    },
  )
  it('facet options обогащаются полями из каталога', () => {
    const scenario = golden.facet_scenarios[0]
    const response = resolveFacetScenario(scenario.request)
    expect(response?.facet).toBeDefined()
    response?.facet?.options.forEach((option) => {
      const catalogMarker = markerCatalogById.get(option.marker_id)
      expect(catalogMarker).toBeDefined()
      expect(option).toEqual({ ...catalogMarker, count: option.count })
    })
  })
})

describe('отсутствие matcher/fallback', () => {
  it('неизвестный search request → undefined даже при совпадении с файлами', () => {
    // В корпусе есть файлы с сегментом Archive, но такого golden-сценария нет:
    // resolver не вычисляет membership.
    const response = resolveSearchScenario({
      request_state_id: 'request-unknown-search',
      root_id: 'root-demo-atlas',
      selected_marker_ids: [],
      query_text: 'archive',
      sort: { field: 'RELEVANCE', direction: 'DESC' },
      facet_prefix: '',
    })
    expect(response).toBeUndefined()
  })

  it('неизвестный facet request → undefined', () => {
    const response = resolveFacetScenario({
      request_state_id: 'request-unknown-facet',
      root_id: 'root-demo-atlas',
      selected_marker_ids: [],
      query_text: '',
      facet_prefix: '',
    })
    expect(response).toBeUndefined()
  })

  it('изменение corpus не меняет уже разрешённые literal item_ids', () => {
    const scenario = golden.search_scenarios.find(
      (candidate) => candidate.expected.item_ids.length > 0,
    )
    expect(scenario).toBeDefined()
    if (!scenario) {
      return
    }
    const before = resolveSearchScenario(scenario.request)
    expect(before).toBeDefined()

    const originalPath = corpus.files[0].relative_path
    corpus.files[0].relative_path = 'Mutated/Path/that/should/not/matter.pdf'
    try {
      const after = resolveSearchScenario(scenario.request)
      expect(after).toEqual(before)
    } finally {
      corpus.files[0].relative_path = originalPath
    }
  })
})

describe('UNRECOGNIZED-отклонения', () => {
  const cases = [
    {
      itemId: 'file-atlas-issue-invalid-value',
      code: 'INVALID_LEVEL_VALUE',
      levelId: 'level-category',
      markerId:
        'marker-root-demo-atlas-archive-atlas-orion-unrecognized-category',
    },
    {
      itemId: 'file-atlas-issue-invalid-composite',
      code: 'INVALID_COMPOSITE_SEGMENT',
      levelId: 'level-project',
      markerId: 'marker-root-demo-atlas-archive-atlas-unrecognized-project',
    },
    {
      itemId: 'file-nova-issue-missing-area',
      code: 'MISSING_REQUIRED_LEVEL',
      levelId: 'level-area',
      markerId: 'marker-root-demo-nova-archive-nova-polaris-unrecognized-area',
    },
  ] as const

  it.each(cases)(
    '$itemId несёт structure_issue и VALUE-маркеры, терминал в каталоге',
    ({ itemId, code, levelId, markerId }) => {
      const item = getSearchItem(itemId)
      expect(item, itemId).toBeDefined()
      expect(item?.structure_status).toBe('UNRECOGNIZED')
      expect(item?.structure_issue).toEqual(
        expect.objectContaining({ code, level_id: levelId }),
      )
      // SearchItem.markers содержит только VALUE-родителей (LT-03.1b).
      expect(item?.markers.every((marker) => marker.kind === 'VALUE')).toBe(true)

      const terminal = getUnrecognizedMarker(itemId)
      expect(terminal).toBeDefined()
      expect(terminal).toEqual(
        expect.objectContaining({
          marker_id: markerId,
          kind: 'UNRECOGNIZED',
          raw_value: null,
          display_value: 'Не распознано',
          level_id: levelId,
        }),
      )
      expect(markerCatalogById.get(markerId)).toEqual(terminal)
    },
  )

  it('UNEXPECTED_DEPTH не имеет терминального уровня', () => {
    const item = getSearchItem('file-atlas-issue-unexpected-depth')
    expect(item?.structure_status).toBe('UNRECOGNIZED')
    expect(item?.structure_issue?.level_id).toBeNull()
    expect(getUnrecognizedMarker('file-atlas-issue-unexpected-depth')).toBeUndefined()
  })

  it('facet UNRECOGNIZED-опция идёт последней и совпадает с golden', () => {
    const response = resolveFacetScenario({
      request_state_id: 'facet-q012-atlas-orion-category',
      root_id: 'root-demo-atlas',
      selected_marker_ids: [
        'marker-root-demo-atlas-archive',
        'marker-root-demo-atlas-archive-atlas',
        'marker-root-demo-atlas-archive-atlas-orion',
      ],
      query_text: '',
      facet_prefix: '',
    })
    expect(response?.facet?.options.at(-1)).toEqual(
      expect.objectContaining({
        marker_id:
          'marker-root-demo-atlas-archive-atlas-orion-unrecognized-category',
        kind: 'UNRECOGNIZED',
        raw_value: null,
        display_value: 'Не распознано',
        count: 1,
      }),
    )
  })
})

describe('freshness-профили', () => {
  it('CURRENT по умолчанию, UPDATING/STALE выбираются явно', () => {
    const conditions = {
      request_state_id: 'freshness-arbitrary-id',
      root_id: 'root-demo-nova',
      selected_marker_ids: [],
      query_text: 'atlas',
      sort: { field: 'RELEVANCE', direction: 'DESC' },
      facet_prefix: '',
    }
    const current = resolveSearchScenario(conditions)
    const updating = resolveSearchScenario(conditions, {
      freshnessProfile: 'UPDATING',
    })
    const stale = resolveSearchScenario(conditions, {
      freshnessProfile: 'STALE',
    })

    expect(current?.freshness.status).toBe('CURRENT')
    expect(updating?.freshness.status).toBe('UPDATING')
    expect(stale?.freshness.status).toBe('STALE')
    expect(updating?.freshness).toEqual(
      golden.constants.freshness_profiles.UPDATING,
    )
    expect(stale?.freshness).toEqual(golden.constants.freshness_profiles.STALE)
    // items/total те же: UPDATING/STALE доступны на предыдущем поколении.
    expect(updating?.items.map((item) => item.item_id)).toEqual(
      current?.items.map((item) => item.item_id),
    )
    expect(stale?.total).toBe(current?.total)
  })
})
