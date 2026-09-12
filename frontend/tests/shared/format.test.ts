// LT-08.2: чистые форматы представления (FE §4, Q-042).
//
// Проверяются точная форма даты-времени `ДД.ММ.ГГГГ ЧЧ:ММ` в разных IANA-поясах
// и на переходе через полночь UTC, десятичные размеры B/KB/MB/GB/TB с
// делителем 1000 и максимум одним дробным знаком, точные целые количества без
// научной нотации, а также безопасная обработка невалидного входа.

import { describe, expect, it } from 'vitest'

import {
  formatCount,
  formatDateTime,
  formatSize,
  INVALID_COUNT_TEXT,
  INVALID_DATE_TIME_TEXT,
  INVALID_SIZE_TEXT,
} from '@/shared/index'

describe('formatDateTime — ДД.ММ.ГГГГ ЧЧ:ММ в заданном поясе', () => {
  it('форматирует UTC-инстант в Europe/Moscow', () => {
    expect(formatDateTime('2031-05-10T09:30:00Z', 'Europe/Moscow')).toBe(
      '10.05.2031 12:30',
    )
  })

  it('корректно переходит на следующие сутки в Europe/Moscow', () => {
    expect(formatDateTime('2031-05-10T23:30:00Z', 'Europe/Moscow')).toBe(
      '11.05.2031 02:30',
    )
  })

  it('даёт другое значение для America/Los_Angeles на том же инстанте', () => {
    expect(
      formatDateTime('2031-05-10T23:30:00Z', 'America/Los_Angeles'),
    ).toBe('10.05.2031 16:30')
  })

  it('показывает полночь как 00:00, а не 24:00', () => {
    expect(formatDateTime('2031-05-10T21:00:00Z', 'Europe/Moscow')).toBe(
      '11.05.2031 00:00',
    )
  })

  it('не содержит секунд и суффикса зоны', () => {
    const value = formatDateTime('2031-05-10T09:30:45Z', 'Europe/Moscow')
    expect(value).toMatch(/^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$/)
    expect(value).not.toMatch(/сек|UTC|GMT|\+\d/)
  })

  it('безопасно обрабатывает невалидный вход', () => {
    expect(formatDateTime('', 'Europe/Moscow')).toBe(INVALID_DATE_TIME_TEXT)
    expect(formatDateTime('not-a-date', 'Europe/Moscow')).toBe(
      INVALID_DATE_TIME_TEXT,
    )
    expect(formatDateTime('2031-13-45T00:00:00Z', 'Europe/Moscow')).toBe(
      INVALID_DATE_TIME_TEXT,
    )
    expect(formatDateTime('2031-05-10T09:30:00Z', 'Invalid/Zone')).toBe(
      INVALID_DATE_TIME_TEXT,
    )
    expect(formatDateTime('2031-05-10T09:30:00Z', '')).toBe(
      INVALID_DATE_TIME_TEXT,
    )
  })
})

describe('formatSize — десятичные B/KB/MB/GB/TB по 1000', () => {
  it('форматирует граничные значения', () => {
    expect(formatSize(0)).toBe('0 B')
    expect(formatSize(999)).toBe('999 B')
    expect(formatSize(1000)).toBe('1 KB')
    expect(formatSize(1500)).toBe('1,5 KB')
    expect(formatSize(999999)).toBe('1000 KB')
    expect(formatSize(1000000)).toBe('1 MB')
    expect(formatSize(1e9)).toBe('1 GB')
    expect(formatSize(1e12)).toBe('1 TB')
  })

  it('показывает не более одного дробного знака', () => {
    expect(formatSize(1234567)).toBe('1,2 MB')
    expect(formatSize(1048576)).toBe('1 MB')
    expect(formatSize(2500)).toBe('2,5 KB')
  })

  it('не переходит за старшую единицу TB', () => {
    expect(formatSize(1e15)).toBe('1000 TB')
  })

  it('безопасно обрабатывает невалидный вход', () => {
    expect(formatSize(-1)).toBe(INVALID_SIZE_TEXT)
    expect(formatSize(Number.NaN)).toBe(INVALID_SIZE_TEXT)
    expect(formatSize(Number.POSITIVE_INFINITY)).toBe(INVALID_SIZE_TEXT)
    expect(formatSize(Number.NEGATIVE_INFINITY)).toBe(INVALID_SIZE_TEXT)
  })
})

describe('formatCount — точное целое без научной нотации', () => {
  it('форматирует значения объявленного диапазона', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(1)).toBe('1')
    expect(formatCount(1000)).toBe('1000')
    expect(formatCount(1000000)).toBe('1000000')
    expect(formatCount(9007199254740991)).toBe('9007199254740991')
  })

  it('не использует научную нотацию и разделители групп', () => {
    const value = formatCount(9007199254740991)
    expect(value).not.toMatch(/e/i)
    expect(value).not.toMatch(/[\s,]/)
  })

  it('безопасно обрабатывает невалидный вход', () => {
    expect(formatCount(Number.NaN)).toBe(INVALID_COUNT_TEXT)
    expect(formatCount(Number.POSITIVE_INFINITY)).toBe(INVALID_COUNT_TEXT)
    expect(formatCount(Number.NEGATIVE_INFINITY)).toBe(INVALID_COUNT_TEXT)
  })
})
