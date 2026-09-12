# WiseWay frontend

React-приложение WiseWay работает с API из
`../contracts/openapi/wiseway-v1.yaml`. Клиентские типы и метаданные в
`src/api/generated/` создаются из этого контракта и коммитятся вместе с ним.

## Требования

- Node.js `>=22 <25`
- npm `>=11 <12`

## Запуск

```bash
cd frontend
npm ci
npm run dev
```

По умолчанию приложение использует реальный API по относительным URL. Для
локальной работы со встроенными mock-ответами запустите:

```bash
VITE_API_MODE=mock npm run dev
```

Файл `.env.browser` включает mock-режим только для браузерных тестов и не
содержит секретов.

## Проверки

```bash
npm run generate:api:check
npm run typecheck
npm run lint
npm test
npm run build
```

`npm run test:browser` собирает приложение в mock-режиме и запускает Playwright
через системный канал Microsoft Edge. Для выполнения теста Edge должен быть
установлен в системе.

## Контракт API

После изменения OpenAPI обновите генерируемые файлы и проверьте результат:

```bash
npm run generate:api
npm run generate:api:check
```

Не редактируйте файлы в `src/api/generated/` вручную. Mock-сценарии используют
общие данные из `../contracts/examples/` и `../fixtures/synthetic/`; эти
каталоги являются частью тестового контура проекта.

## Основные каталоги

- `src/app/` — оболочка, сессия и конфигурация приложения;
- `src/api/` — транспорт, обработка ошибок и сгенерированный клиент;
- `src/features/` — продуктовые разделы;
- `src/mocks/` — контрактные mock-обработчики;
- `tests/` — модульные, компонентные и браузерные тесты.
