# WiseWay — frontend

Минимальная рабочая основа (scaffold) frontend-приложения WiseWay. Сейчас в
каталоге находятся только конфигурация инструментов, точка входа и smoke-тесты.
Продуктовые экраны, навигация, дизайн-система, generated API-клиент и
mock-сценарии появятся в следующих leaf-задачах (EPIC E-02, WP-04/WP-05/WP-06/WP-07).

Выбранный toolchain, точные версии и политика lock-файла закреплены в
[ADR-0001. Frontend toolchain WiseWay](docs/ADR-0001-frontend-toolchain.md).

## Требования

- Node.js `>=22 <25` (проверено на `v24.20.0`).
- npm `>=11 <12` (проверено на `11.19.0`).

## Установка

Из каталога `frontend/`:

```powershell
npm ci
```

`npm ci` устанавливает ровно дерево зависимостей из `package-lock.json`.
Lock-файл коммитится; повторная установка не должна изменять его.

## Команды

| Команда | Назначение |
|---|---|
| `npm run dev` | Запускает dev-сервер Vite (по умолчанию `http://localhost:5173`). |
| `npm run build` | Production-сборка Vite в `frontend/dist`. |
| `npm run preview` | Локальный просмотр собранного `frontend/dist` (по умолчанию `http://localhost:4173`). |
| `npm run typecheck` | Проверка типов `tsc --noEmit` без эмита. |
| `npm run lint` | ESLint 9 (flat config) по проекту. |
| `npm run test` | Unit/component smoke-тесты: Vitest + Testing Library в jsdom. |
| `npm run test:browser` | Browser smoke-тест Playwright; сначала выполняет `npm run build`. |

## Структура

```text
frontend/
  index.html
  src/
    main.tsx            точка входа React
    App.tsx             минимальный placeholder (без экранов продукта)
    features/{auth,search,dictionaries,sorting,quarantine,audit}/
    api/                placeholder; api/generated — генерация в LT-04.2
    mocks/              placeholder для schema-valid mocks (WP-06/WP-07)
  tests/
    App.test.tsx        component smoke-тест
    fixture-imports.test.ts  проверка alias-импорта JSON вне frontend/
    support/            технические модули scaffold
    browser/            Playwright smoke-тест
  docs/ADR-0001-frontend-toolchain.md
```

Структура соответствует обязательной карте monorepo из
`docs/team/03_FRONTEND.md` §2/§3 и `docs/team/06_EXECUTION_PLAN.md` §3.
Generated-клиент из OAS создаётся отдельно в LT-04.2 и не редактируется вручную.

## Импорт JSON вне `frontend/`

Alias-и `@fixtures` → `../fixtures` и `@examples` → `../contracts/examples`
настроены в `vite.config.ts` (`resolve.alias` + `server.fs.allow`), а также в
`tsconfig.json` (`paths`). Это позволяет будущим mock-сценариям импортировать
синтетические фикстуры и публичные примеры контракта без копирования внутрь
`frontend/`. Работоспособность подтверждается тестом `tests/fixture-imports.test.ts`.

## Browser-тест и браузерный канал

`npm run test:browser` использует Playwright. В обычной среде браузерный
бинарник Chromium устанавливается отдельно:

```powershell
npx playwright install chromium
```

**Условие текущей среды:** скачивание Chromium из CDN Playwright недоступно
(сетевой таймаут при `npx playwright install chromium`). Поэтому
`playwright.config.ts` запускает тест в системном канале Microsoft Edge
(`channel: 'msedge'`, Chromium-based) — Edge установлен в среде. Если в среде
доступен скачанный Chromium, проект можно вернуть на bundled-браузер, убрав
`channel` из `playwright.config.ts`; для Google Chrome используется
`channel: 'chrome'`. Выбранный для проверки канал указывается в отчёте о
выполнении; сам тест обязан реально проходить в текущей среде.

`playwright.config.ts` запускает preview с явным хостом `--host 127.0.0.1` и
использует тот же хост в `baseURL`. Это обязательно: `vite preview` по
умолчанию слушает только IPv6-loopback `::1`, из-за чего probe Playwright по
`127.0.0.1` получал `connection refused`. Привязка сервера и `baseURL` к одному
адресу делает browser-тест детерминированным при повторных запусках и в CI.

## Проверки (V-C)

Полный набор локальных проверок scaffold:

```powershell
npm ci
npm run typecheck
npm run lint
npm run test
npm run build
npm run test:browser
```

Ожидаемый результат: все команды завершаются успешно, `npm run build` создаёт
`frontend/dist/index.html`, unit/component и browser smoke-тесты проходят.
