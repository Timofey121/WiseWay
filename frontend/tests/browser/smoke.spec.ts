// LT-09.1: браузерные проверки входа и bootstrap-сессии.
//
// Приложение собирается в mock-режиме (`frontend/.env.browser`,
// `npm run build:browser`) и работает против schema-valid mocks. Проверяются:
// анонимный старт → вход; неверный пароль → общее сообщение; успешный вход
// worker/admin → оболочка с именем и русской ролью и пустой «Поиск»;
// недоступность `GET /session` (5xx) → безопасное сообщение с повтором, а не
// форма входа.

import { expect, test, type Page } from '@playwright/test'

const PASSWORD = 'synthetic-placeholder-not-a-real-credential'

async function fillAndSubmit(
  page: Page,
  login: string,
  password: string,
): Promise<void> {
  await page.getByLabel('Логин').fill(login)
  await page.getByLabel('Пароль').fill(password)
  await page.getByRole('button', { name: 'Войти' }).click()
}

test('без сессии показывает экран входа, а не оболочку', async ({ page }) => {
  await page.goto('/')

  await expect(
    page.getByRole('heading', { name: 'Вход в WiseWay' }),
  ).toBeVisible()
  await expect(page.getByLabel('Логин')).toBeVisible()
  await expect(page.getByLabel('Пароль')).toBeVisible()
  await expect(
    page.getByRole('navigation', { name: 'Разделы приложения' }),
  ).toHaveCount(0)
})

test('неверный пароль даёт общее сообщение и сохраняет логин', async ({
  page,
}) => {
  await page.goto('/')
  await fillAndSubmit(page, 'worker.one', 'wrong-password')

  await expect(page.getByRole('alert')).toContainText(
    'Неверный логин или пароль.',
  )
  await expect(page.getByLabel('Логин')).toHaveValue('worker.one')
  await expect(
    page.getByRole('navigation', { name: 'Разделы приложения' }),
  ).toHaveCount(0)
})

test('вход worker.one показывает пустой «Поиск» и рабочую навигацию', async ({
  page,
}) => {
  await page.goto('/')
  await fillAndSubmit(page, 'worker.one', PASSWORD)

  await expect(
    page.getByRole('heading', { level: 1, name: 'WiseWay' }),
  ).toBeVisible()
  await expect(page.getByText('Иван Рабочий')).toBeVisible()
  await expect(page.getByText('Рабочий', { exact: true })).toBeVisible()
  await expect(
    page.getByRole('heading', { level: 2, name: 'Поиск' }),
  ).toBeVisible()
  await expect(page.getByText('Раздел ещё не реализован')).toBeVisible()

  await page.getByRole('button', { name: 'Справочники' }).click()
  await expect(
    page.getByRole('button', { name: 'Справочники' }),
  ).toHaveAttribute('aria-current', 'page')
})

test('вход admin.one показывает роль «Администратор»', async ({ page }) => {
  await page.goto('/')
  await fillAndSubmit(page, 'admin.one', PASSWORD)

  await expect(page.getByText('Администратор Демо')).toBeVisible()
  await expect(page.getByText('Администратор', { exact: true })).toBeVisible()
})

test('недоступность сессии показывает сообщение с повтором, а не вход', async ({
  page,
}) => {
  // Тестовый шов mock-сборки: любой запрос получает 503, поэтому bootstrap
  // `GET /session` не может быть выдан за анонимную сессию.
  await page.addInitScript(() => {
    ;(window as unknown as Record<string, unknown>).__WISEWAY_TEST_FETCH__ =
      () =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              error: {
                code: 'SERVICE_UNAVAILABLE',
                message: 'Сервис временно недоступен.',
                request_id: 'request-browser-unavailable',
                operation_id: null,
                retryable: true,
                field_errors: [],
              },
            }),
            {
              status: 503,
              headers: {
                'Content-Type': 'application/json',
                'X-Request-ID': 'request-browser-unavailable',
              },
            },
          ),
        )
  })

  await page.goto('/')

  await expect(
    page.getByRole('heading', { name: 'Не удалось проверить сессию' }),
  ).toBeVisible()
  await expect(page.getByText('Сервис временно недоступен.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Повторить' })).toBeVisible()
  await expect(page.getByLabel('Логин')).toHaveCount(0)
})
