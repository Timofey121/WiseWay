// Разбор JSON-тела mock-запроса без исключений и логирования.
//
// Тело читается один раз; невалидный JSON или пустое тело возвращаются как
// неуспех, чтобы handler отдал контрактную 422 вместо ложного успеха. Значения
// тела не логируются.

export interface JsonBodyResult {
  ok: boolean
  value?: unknown
}

/** Читает JSON-тело `Request`; безопасный неуспех при пустом/битом теле. */
export async function readJsonBody(request: Request): Promise<JsonBodyResult> {
  let text: string
  try {
    text = await request.text()
  } catch {
    return { ok: false }
  }
  if (text.trim().length === 0) {
    return { ok: false }
  }
  try {
    return { ok: true, value: JSON.parse(text) }
  } catch {
    return { ok: false }
  }
}
