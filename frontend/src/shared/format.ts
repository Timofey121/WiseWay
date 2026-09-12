// Единые форматы представления значений WiseWay (FE §4, Q-042).
//
// Контракт:
// - дата-время: `ДД.ММ.ГГГГ ЧЧ:ММ` в переданном IANA timezone, без секунд и
//   суффикса зоны; сервер хранит UTC, а пояс отображения приходит из
//   `AppConfig.display_timezone`;
// - размер: десятичные единицы B/KB/MB/GB/TB с делителем 1000, максимум один
//   дробный знак; сервер хранит точное целое число байт;
// - количество: точное целое без научной нотации и разделителей групп.
//
// Timezone здесь никогда не зашивается: он всегда параметр вызова. Функции
// чистые, не зависят от React и не выполняют сетевых запросов. Невалидный вход
// обрабатывается безопасно: возвращается нейтральный прочерк, а не выдуманное
// значение.

/** Нейтральный текст для невалидной/недоступной даты-времени. */
export const INVALID_DATE_TIME_TEXT = '—'

/** Нейтральный текст для невалидного/недоступного размера. */
export const INVALID_SIZE_TEXT = '—'

/** Нейтральный текст для невалидного/недоступного количества. */
export const INVALID_COUNT_TEXT = '—'

const DATE_TIME_LOCALE = 'ru-RU'

/** Десятичные единицы размера: делитель 1000, единицы остаются латиницей. */
const SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const

const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER

/**
 * Форматирует `Instant` (RFC3339, обычно UTC `Z`) как `ДД.ММ.ГГГГ ЧЧ:ММ` в
 * заданном IANA-поясе.
 *
 * Используются явные числовые части `Intl.DateTimeFormat`, а строка собирается
 * вручную: это гарантирует точную форму без секунд, миллисекунд и суффикса
 * зоны независимо от locale-шаблонов. Некорректная дата или неизвестный пояс
 * дают `INVALID_DATE_TIME_TEXT`; пояс по умолчанию не подставляется.
 */
export function formatDateTime(instant: string, timeZone: string): string {
  if (
    typeof instant !== 'string' ||
    instant.length === 0 ||
    typeof timeZone !== 'string' ||
    timeZone.length === 0
  ) {
    return INVALID_DATE_TIME_TEXT
  }

  const date = new Date(instant)
  if (Number.isNaN(date.getTime())) {
    return INVALID_DATE_TIME_TEXT
  }

  try {
    const parts = new Intl.DateTimeFormat(DATE_TIME_LOCALE, {
      timeZone,
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      // `h23` фиксирует часы 00–23, чтобы полночь не отображалась как «24».
      hourCycle: 'h23',
    }).formatToParts(date)

    const day = readPart(parts, 'day')
    const month = readPart(parts, 'month')
    const year = readPart(parts, 'year')
    const hour = readPart(parts, 'hour')
    const minute = readPart(parts, 'minute')

    if (!day || !month || !year || !hour || !minute) {
      return INVALID_DATE_TIME_TEXT
    }

    return `${day}.${month}.${year} ${hour}:${minute}`
  } catch {
    return INVALID_DATE_TIME_TEXT
  }
}

/**
 * Форматирует размер в байтах десятичными единицами B/KB/MB/GB/TB (делитель
 * 1000) максимум с одним дробным знаком. Единица выбирается по величине
 * значения, затем значение округляется до одного знака; дробная часть
 * разделяется запятой (русская презентация), единицы остаются латиницей.
 * Например `999999 B` → `1000 KB`, `1000000 B` → `1 MB`.
 *
 * Невалидный вход (не число, `NaN`, `±Infinity`, отрицательное) даёт
 * `INVALID_SIZE_TEXT`.
 */
export function formatSize(bytes: number): string {
  if (typeof bytes !== 'number' || !Number.isFinite(bytes) || bytes < 0) {
    return INVALID_SIZE_TEXT
  }

  if (bytes < 1000) {
    return `${Math.trunc(bytes)} B`
  }

  let value = bytes
  let unitIndex = 0
  while (value >= 1000 && unitIndex < SIZE_UNITS.length - 1) {
    value /= 1000
    unitIndex += 1
  }

  return `${formatDecimal(roundToSingleDecimal(value))} ${SIZE_UNITS[unitIndex]}`
}

/**
 * Форматирует `Count` как точное целое без научной нотации и разделителей
 * групп. Безопасен на всём объявленном диапазоне 0…9007199254740991.
 * Невалидный вход (`NaN`, `±Infinity`, не число) даёт `INVALID_COUNT_TEXT`.
 */
export function formatCount(count: number): string {
  if (typeof count !== 'number' || !Number.isFinite(count)) {
    return INVALID_COUNT_TEXT
  }

  const integer = Math.trunc(count)
  if (Math.abs(integer) <= MAX_SAFE_INTEGER) {
    return String(integer)
  }

  try {
    return BigInt(integer).toString()
  } catch {
    return INVALID_COUNT_TEXT
  }
}

function readPart(
  parts: Intl.DateTimeFormatPart[],
  type: string,
): string | null {
  const value = parts.find((part) => part.type === type)?.value
  return value !== undefined && value.length > 0 ? value : null
}

function roundToSingleDecimal(value: number): number {
  return Math.round(value * 10) / 10
}

function formatDecimal(value: number): string {
  const fixed = value.toFixed(1)
  const trimmed = fixed.endsWith('.0') ? fixed.slice(0, -2) : fixed
  return trimmed.replace('.', ',')
}
