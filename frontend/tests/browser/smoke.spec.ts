import { expect, test } from '@playwright/test'

test('отображает русскую оболочку приложения', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { level: 1 })).toHaveText('WiseWay')
  await expect(
    page.getByRole('navigation', { name: 'Разделы приложения' }),
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { level: 2, name: 'Поиск' }),
  ).toBeVisible()
})

test('переключает разделы мышью', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Справочники' }).click()

  await expect(
    page.getByRole('button', { name: 'Справочники' }),
  ).toHaveAttribute('aria-current', 'page')
  await expect(
    page.getByRole('heading', { level: 2, name: 'Справочники' }),
  ).toBeVisible()
})

test('переключает разделы клавиатурой', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Поиск' }).focus()
  await page.keyboard.press('Tab')
  await expect(
    page.getByRole('button', { name: 'Справочники' }),
  ).toBeFocused()

  await page.keyboard.press('Enter')
  await expect(
    page.getByRole('button', { name: 'Справочники' }),
  ).toHaveAttribute('aria-current', 'page')
  await expect(
    page.getByRole('heading', { level: 2, name: 'Справочники' }),
  ).toBeVisible()
})

test('не запрашивает app-config, пока пользователь анонимен', async ({
  page,
}) => {
  const configRequests: string[] = []
  await page.route('**/app-config', (route) => {
    configRequests.push(route.request().url())
    return route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: '{}',
    })
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('WiseWay')

  // Даём приложению время на потенциальный запрос конфигурации: при анонимной
  // сессии его быть не должно.
  await page.waitForTimeout(500)
  expect(configRequests).toEqual([])
})
