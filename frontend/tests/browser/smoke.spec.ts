import { expect, test } from '@playwright/test'

test('отображает заголовок-заглушку приложения', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'WiseWay — рабочая основа интерфейса',
  )
})
