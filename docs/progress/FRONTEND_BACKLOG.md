# WiseWay — frontend backlog

Дата обследования: 10.09.2026. Область: внешняя синтетическая Demo-MVP.

Это execution backlog: план декомпозиции и учёт подтверждённого прогресса, не доказательство готовой реализации сам по себе. Иерархия: **EPIC → EXECUTION UNIT → WORK PACKAGE → LEAF TASK**. В документе **10 EPIC, 32 WORK PACKAGE, 80 исходных leaf IDs**. Пять родителей WP-03 рекурсивно разделены на 10 дочерних leaf; дополнительно 33 слишком широких родителя E-02…E-09 заранее разделены на 71 исполняемый дочерний leaf; при исполнении E-02 родитель LT-06.2a дополнительно разделён ещё на 2 дочерних leaf (LT-06.2a-i/ii). Исходные IDs сохранены как traceability-parent; всего получается **124 исполняемых конечных leaf**. WP-31/32 и их два leaf — условное планирование, не обязательные функции внешней MVP.

## 1. Источники истины и решения пользователя

Сокращения раскрывают точные пути. Разделы, IDs требований и operationId в карточках относятся именно к этим файлам.

| Ключ | Источник |
|---|---|
| RULES | `AGENTS.md` + `.opencode/rules/frontend.md` |
| START | `docs/team/00_START_HERE.md` |
| TZ | `docs/team/01_PROJECT_TZ.md` |
| API | `docs/team/02_API_CONTRACT.md` |
| FE | `docs/team/03_FRONTEND.md` |
| BE | `docs/team/04_BACKEND.md` |
| QA | `docs/team/05_QA.md` |
| PLAN | `docs/team/06_EXECUTION_PLAN.md` |
| MATRIX | `docs/team/07_ACCEPTANCE_MATRIX.md`, Q-001…045 со всеми параметрами |
| OAS | `contracts/openapi/wiseway-v1.yaml`, OpenAPI 3.1.1, info.version=1.0.0 |
| SEM | `contracts/semantics.md` |
| README | `README.md` |

`OAS <operationId>` обозначает операцию в `paths`, названия DTO — `components/schemas`. Публичный префикс `/api/v1`. Frontend routes здесь намеренно не изобретаются.

### Долговременные решения пользователя

- **D-01 — название.** Текущее название WiseWay. Старое название, ссылки на контракт и cookie в Markdown ТЗ заменяются на WiseWay, `wiseway-v1.yaml`, `wiseway_session`. Второй контракт не создаётся.
- **D-02 — согласование.** Пользователь подтвердил проведённое совместное согласование контракта: в целом стороны его приняли. SEM и командные документы в части «ещё не согласован/не создан» устарели. Это подтверждение пользователя, **не свидетельство валидности схемы или прохождения тестов**.
- **D-03 — QA.** Отдельные человеческие QA-проверки до готовности MVP не выполняются. Промежуточные подписи QA из FE/PLAN не блокируют разработку. Разработчики готовят независимые от алгоритмов ожидаемые результаты и выполняют автоматические проверки; `frontend/reviewer` проверяет каждый leaf. Финальная человеческая приёмка сохранена. Никакого фиктивного QA PASS.
- **D-04 — изменения контракта.** Точечные исправления допустимы в рабочем порядке без повторного вопроса, с отчётом пользователю. Глобальные изменения и изменение бизнес-семантики требуют согласования. Worker brief должен назвать одобренную коррекцию, точные релевантные sources of truth и semantic scope по RULES; само планирование не изменяет OAS.
- **D-05 — порядок.** Принят порядок: коррекция схемы → контрактные проверки и согласованные примеры → generated client/mocks → shell/auth/search → dictionaries/sorting; real-интеграция посрезовая, а не только финальная.
- **D-06 — локальные checkpoints E-01 (решение пользователя в текущей сессии).** До полной готовности E-01 push не выполняется. Orchestrator делает только локальные commits после независимого review; пользователь сам публикует всю E-01 после своей проверки. Субагенты не выполняют staging/commit/push. Первая попытка публикации `7b0843b` и один повтор завершились отказом авторизации; успешной публикации не было. Для текущей E-01 локальная проверенность и публикация учитываются раздельно; общий критерий READY_FOR_HUMAN_REVIEW с commit/push ещё не выполнен, отсутствие push не маскируется. Блокер авторизации не препятствует локальной реализации по прямому решению пользователя.
- **D-07 — язык пользовательского интерфейса.** Весь пользовательский/product-facing интерфейс WiseWay должен быть на естественном русском языке, если конкретное требование явно не задаёт иное. Это presentation-требование frontend: transport/storage identifiers, API enum/status/error codes, `operationId`, raw filenames/paths/IDs не переводятся и не меняют публичный контракт ради локализации; frontend отображает для них русские labels/messages там, где они видимы пользователю.
- **D-08 — namespace frontend-агентов.** Корневой `AGENTS.md` содержит только общие правила репозитория, а frontend execution workflow задаётся `.opencode/rules/frontend.md`. Точные agent IDs frontend-контура: `frontend/orchestrator`, `frontend/worker`, `frontend/reviewer`. Будущий backend-контур может иметь собственные `backend/*` agents/rules и не должен зависеть от frontend-specific workflow.
- **D-09 — публикация только человеком (решение пользователя 11.09.2026, действует на E-02 и все последующие Execution Units).** Orchestrator **не выполняет push** завершённых leaf/WP/Execution Unit. Все изменения публикует только пользователь. Orchestrator по-прежнему владеет локальными reviewed checkpoints: после независимого reviewer PASS и фактической verification он stages только предназначенные изменения, создаёт локальный checkpoint commit в текущей feature branch и продолжает автономно. Отсутствие push **не блокирует** и не понижает статус: для E-02 и далее leaf/WP считается VERIFIED при выполнении локальных условий (реализация + независимый review PASS + фактическая verification + intended progress записан + локальный checkpoint commit), а push учитывается отдельно как действие пользователя. Это уточняет §3/§5 backlog и RULES в части push для последующих Execution Units; D-06 остаётся историческим частным случаем E-01. Force-push и переписывание опубликованной истории запрещены по-прежнему.

Противоречащие этим решениям формулировки о промежуточных согласованиях/QA не исполняются как gates и не объявляются выполненными. Остальные функциональные AC и safety-требования не ослабляются. Backlog не подменяет исходные ТЗ; уточнения зафиксированы явно здесь, execution workflow определяется текущим RULES.

## 2. Фактическая исходная точка на дату обследования

Исходное обследование охватило RULES, README, все восемь документов `docs/team/`, OAS и SEM, корень worktree, `docs/`, `contracts/`. Таблица фиксирует baseline планирования на 10.09.2026, а не неизменное состояние репозитория: перед исполнением WP orchestrator сверяет её и статусы с фактическими артефактами.

| Артефакт | Evidence | Вывод |
|---|---|---|
| ТЗ и 45 сценариев | START…MATRIX присутствуют; MATRIX содержит ожидаемые проверки, не протокол | План существует; выполнение не доказано |
| Контракт A/B/C | OAS содержит 33 operationId, DTO, security, errors, встроенные examples; SEM описывает семантику | Документальная часть FE-01/02 существенно подготовлена; не создавать заново |
| Согласование | Подтверждение пользователя D-02 | Не blocker; FE-01/02 целиком не DONE: клиент/mocks/проверки отсутствуют |
| UI, клиент, mocks, сервер | Нет `frontend/`, `backend/` и product code | Ни один AUTH/SRCH/DICT/QUEUE/FILE/AUD UI-сценарий не реализован |
| Корпус и отдельные examples | Нет `contracts/examples/`, `fixtures/synthetic/`; examples только в YAML | Примеры не равны исполняемому корпусу или golden tests |
| Тесты/сборка | Нет `tests/`, product manifest/lock/ADR, команд запуска приложения | Обещанные README проверки сейчас невоспроизводимы |
| `.opencode/` | Агентная инфраструктура и её зависимости | Не frontend scaffold и не тестовая инфраструктура продукта |

Наличие документа само по себе не переводит leaf в VERIFIED/DONE; IN_PROGRESS не применяется к ещё не начатой задаче. Согласование, schema verification, mock pass, real API pass и приёмка MVP — разные факты.

## 3. Статусы и общие критерии

- **TODO:** известный результат ожидает выполнения; обычные зависимости могут быть не готовы.
- **IN_PROGRESS:** исполнение leaf, WP или выбранного Execution Unit действительно началось; включает implementation, review, verification и подготовку checkpoint.
- **BLOCKED:** конкретный внешний отсутствующий вход или противоречие указан в dependencies. Не распространяется автоматически на всех транзитивных потребителей.
- **VERIFIED:** leaf реализован, независимый reviewer дал PASS, требуемая verification фактически выполнена и успешна, проверенный checkpoint успешно committed и pushed в текущую feature branch. Внутренний WP в Epic становится VERIFIED после VERIFIED всех обязательных leaf, полного package review с PASS, успешной package-level verification и commit/push итогового состояния. Одного reviewer PASS или локального commit недостаточно.
- **READY_FOR_HUMAN_REVIEW:** все обязательные работы выбранного Execution Unit завершены: leaf — VERIFIED, внутренние WP — VERIFIED, если применимо; выполнена полная verification, независимый финальный review всего Execution Unit дал PASS, итоговое состояние feature branch committed и pushed. Это финальный агентный статус выбранного Execution Unit (Epic или отдельно выбранного WP) до человеческой интеграции, а не каждого внутреннего WP.
- **DONE:** результат интегрирован в `main` либо человек явно подтвердил эквивалентное состояние интеграции. Завершение feature branch само по себе не DONE; DONE mock-пакета не означает готовую MVP.

Execution Unit — единица автономного выполнения от постановки человеком до финального человеческого review: одна feature branch, один worktree, один eventual PR и одна или несколько orchestrator-сессий по мере необходимости. По умолчанию выбирается целый Epic `E-XX`; его WP выполняются последовательно и автономно по готовности dependencies в одной ветке, без остановки для подтверждения человеком между пакетами. В исключительном случае отдельный `WP-XX` выбирается как Execution Unit, если Epic слишком велик, внешне блокирован или иначе не подходит для одной branch/PR. Launcher или человек создаёт branch/worktree выбранного Execution Unit **до старта OpenCode**. Переход между WP или leaf внутри него не создаёт отдельную branch/worktree/session/PR. За пределы выбранного Execution Unit orchestrator автоматически не переходит; при блокировке одного пути продолжает другую допустимую работу внутри него, если это возможно.

WP — связный внутренний implementation/review checkpoint в Execution Unit; несколько последовательных worker/reviewer runs допустимы. Leaf целиком передаётся одному `frontend/worker` и целиком проверяется свежим `frontend/reviewer`; код, тесты и handoff входят в тот же leaf. Родитель `LT-XX.Y` — `WP-XX`, заданный заголовком. Если для исходного leaf в разделе «Плановая рекурсивная декомпозиция» перечислены дочерние IDs, исходный ID становится traceability-parent и **не делегируется worker напрямую**: исполняются дочерние leaf, а parent считается технически завершённым после завершения всех обязательных детей. Ссылки Q/TZ/FE на parent наследуются его применимыми детьми. Перед исполнением составляется brief с точными релевантными sources of truth, semantic SCOPE, acceptance criteria, verification и уже разрешённым CONTEXT. Scope — смысловая граница задачи, а не хрупкий список ALLOWED/FORBIDDEN PATHS; защищённые control-plane пути и границы backend определяются RULES. Слишком широкий обнаруженный repair оформляется отдельным ограниченным результатом, не задачей «исправить всё».

Git lifecycle внутри выбранного Execution Unit по RULES:

1. `frontend/worker` реализует leaf в свежей child-session, но не выполняет staging/commit/push, не переключает ветки и не публикует checkpoints; `frontend/reviewer` независимо проверяет результат в свежей child-session и только инспектирует Git.
2. После reviewer PASS и успешной требуемой verification orchestrator проверяет текущую ветку (не `main`/`master`), status и точный diff, обновляет progress, stages только предназначенные изменения, создаёт checkpoint commit и делает push **текущей feature branch**. Чужие изменения, секреты и неожиданные изменения control plane не включаются.
3. Переход leaf в VERIFIED действителен только после успешного commit/push. При неуспехе checkpoint/push leaf не считается VERIFIED; orchestrator сохраняет фактический progress и устраняет сбой, не переходя к следующему leaf как будто публикация прошла. После успешного checkpoint он автономно продолжает следующий допустимый leaf того же WP.
4. После всех обязательных leaf WP orchestrator проводит полный package review и verification, фиксирует и публикует итоговое состояние. Внутренний WP выбранного Epic становится VERIFIED; orchestrator сразу продолжает следующий допустимый WP того же Epic в текущей ветке, не возвращая управление человеку только из-за завершения пакета.
5. После завершения всех обязательных работ выбранного Execution Unit orchestrator проводит финальный review всего Execution Unit и полную verification, фиксирует и публикует итоговое состояние и progress READY_FOR_HUMAN_REVIEW. Для отдельно выбранного WP это финальный review всего WP; для Epic — всего Epic после VERIFIED внутренних WP. Статус действителен только при выполнении всех условий выше. Затем orchestrator останавливается и не начинает другой Execution Unit автоматически.
6. Человек выполняет final PR review и merge в `main`; создание PR агентом требует отдельного явного запроса. Force-push и переписывание опубликованной истории запрещены.

### Общие acceptance criteria G — часть всех применимых карточек

- **G-1:** только синтетика, DTO из OAS, без ручных копий/generated edits. Matcher/ranking/readiness/totals/FS/snapshot membership — серверные алгоритмы. Нет скрытого преобразования несовместимых ответов.
- **G-2:** весь product-facing UI — на естественном русском языке, если исходное ТЗ явно не требует иного: навигация, заголовки, кнопки, labels, placeholders, validation, loading/empty/success/error/stale/disabled states, dialogs, notifications, таблицы/фильтры и accessibility labels. Ошибки безопасны и понятны; клавиатура и видимый фокус обязательны, ошибка не выражается только цветом. Desktop 1280×720, при меньшей ширине допустима прокрутка. Технические идентификаторы и transport/storage values (`operationId`, enum/status/error codes, `request_id`, `operation_id`), raw-имена файлов, пути и IDs не переводятся ради отображения; при необходимости рядом даётся русское пользовательское объяснение.
- **G-3:** API §11: 401 прекращает сессию; 403 не повторяет запись; 404 предлагает перечитать список; 409 — предметная реакция; 422 — поля/предел; 429 — Retry-After; 500/503/сеть — без ложного успеха. Безопасные request_id/operation_id доступны для разбора, тела/секреты не журналируются.
- **G-4:** старые ответы/данные предыдущего контекста не заменяют новые. Cursor только где предусмотрен OAS; counts не вычисляются по странице. Nullable не подменяется отсутствующим полем или выдуманным размещением.
- **G-5:** поиск/пути/ответы/CSRF не сохраняются в URL/history state/localStorage/sessionStorage/cookie/cache приложения. Межраздельное сохранение поиска только в памяти вкладки. Logout/401/смена пользователя очищают приватный state и старые requests/polls, не отменяя серверные партии.
- **G-6:** handoff по FE §7: IDs, diff, версии схемы/fixtures, точные команды/результаты, S/M/A/E, ограничения. Ни mock, ни схема не доказывают файловую безопасность. Промежуточная QA-подпись не нужна, финальная человеческая приёмка нужна.

### Verification expectations V

Это **будущие проверки**, не утверждение об уже выполненных командах. Имена runner/команд фиксируются в WP-02/04 и README, не придумываются заранее.

- **V-S:** OpenAPI 3.1 validation, refs/operationId/параметры/security, schema-validation examples, отклонение negative payload, семантические инварианты примеров.
- **V-C:** typecheck/lint, unit/component tests затронутого поведения, production build на закреплённых зависимостях; для клиента повторная генерация без diff.
- **V-M:** браузер со schema-valid mocks, все G-2 состояния, задержки/ошибки/races, network calls/focus/storage; отдельно проверяется отсутствие случайного англоязычного product-facing текста, кроме технических идентификаторов/raw-данных и явно оговорённых терминов. Не проверка настоящего FS.
- **V-E:** настоящий UI → настоящий API без mock fallback; independent golden expectations, версии FE/BE/OAS/seed/generation/RuleSet и команды; безопасные API/audit/FS evidence. Серверные/FS проверки предоставляет backend, финальный QA — человек.
- **V-H:** документарный review полноты, ссылок, границ и доказательств; не имитация исполнения тестов.

WP принимает объединение AC своих leaf + G и совместимость результатов. Q-ID означает все параметры строки MATRIX на применимом уровне, не один happy path. Реализация включает локальные тесты в сам leaf; поздняя регрессия их не заменяет.

## 4. Blockers, внешние зависимости и технические решения

| ID | Факт и источник | Решение, владелец и влияние |
|---|---|---|
| B-01 | OAS listSortingBatches/listQuarantineItems используют CompanyId `in: path`, но `/sorting/batches` и `/quarantine` не содержат `{company_id}`; API §8/9 требует query | LT-01.1: отдельный required query-параметр, настоящий path-параметр сохранить. Точечная коррекция одобрена; до неё валидность схемы/генерация не подтверждены |
| B-02 | README обещает `tests/contract/requirements.txt` и `tests/contract/verify_contract.py`; отсутствует весь `tests/` | WP-02: frontend создаёт исполняемые проверки и правдивую инструкцию; до появления runner обещание README не является evidence |
| B-03 | OAS createDictionarySimulation: в simulation_no_scenario/rule_conflict filename отличается от basename source; у conflict ссылка на вторую опубликованную версию отсутствует в base_rule_set. Связанные по selection_id examples selection/preview показывают 120/1 элемент | LT-01.2 и LT-02.2: согласовать конечные примеры и проверки; не runtime-transformation UI. Частный дефект контрактного пакета, не новая бизнес-функция |
| X-STACK | TZ §11 предлагает React+TypeScript; runtime/package manager/generator/test runners и обычный frontend toolchain предстоит закрепить в ADR/lock | **Неблокирующее техническое решение orchestrator в LT-04.1**, не человеческий blocker и не blocking dependency. Выбор внутри требований выполняется автономно, без отдельного согласования с человеком; инструменты не считать уже установленными |
| X-BE-A | Нет BE-01/02: auth/config, опубликованного индекса/search API | Backend; блокирует real-pass WP-25, не mock UI |
| X-BE-B | Нет BE-03/04a/b: drafts/matcher/simulation/publish/readiness/snapshots/preview | Backend; блокирует real-pass WP-26/27. BE-04a зависит от BE-01, simulation от READY BE-04a, BE-04b от BE-03+BE-04a; цикл не создавать |
| X-BE-C | Нет BE-05/06: sandbox executor/durable batches/quarantine/return/общего запуска; нет реализованного audit API BE-01 | Backend; блокирует WP-28/29/30, не mock-отображение |
| X-LAB | Нет стенда, controlled clocks/fault points, синхронизации гонок и безопасного FS-инвентаря | Backend предоставляет тестовые механизмы вне публичного API. Без них нельзя доказать races/restart/performance; случайная сетевая ошибка не замена |
| X-RECOVERY | SEM оставляет открытой процедуру доказательства размещения/записи результата/снятия claim; публичного recovery endpoint нет | Предложен технический серверный административный порядок без нового UI/endpoint. Backend и человек фиксируют механизм перед передачей. UI показывает факт RECOVERY_REQUIRED без слепого retry; этот UI не блокирован |
| X-HELP | FE-06 требует принятого UI и назначения backend; D-03 убирает промежуточные QA-прогоны | До явного принятия доступного UI человеком и назначения backend помощь не начинается. Ранний QA gate не выдумывается |
| X-INTERNAL | TZ §13: неизвестны реальные схема/SMB/FS/права/ресурсы/accounts/timezone/reserve/rollback | Человек и владельцы внутренней среды; WP-32 только уточнение scope, не реализация по догадке |

B-01/B-02 — два технических препятствия раннего пути; B-03 устраняется в том же контрактном потоке. X-RECOVERY — отдельный операционный вопрос, не причина остановить весь frontend. Историческое название и отсутствие промежуточных QA-подписей больше не blockers (D-01…03). Новые противоречия регистрируются явно.

## EPIC E-01 — Проверяемый контракт и эталоны

Status: READY_FOR_HUMAN_REVIEW (локально; публикация отложена решением пользователя D-06). Scope: FE-01/02; TZ §3/11/14; API §1–12. Существующий OAS — основа, не задача создания нового API.

Execution baseline 10.09.2026: `feat/e-01`, HEAD `c271587`, чистое рабочее дерево. После `git fetch origin`: `origin/main=558b9e0`, merge-base `6cdecda`; три исходных commits инфраструктуры/ТЗ унаследованы от launcher и ещё не интегрированы в main. Они не являются изменениями реализации E-01; control plane в этой сессии не изменяется. WP-01 → WP-02 → WP-03 dependency-ready последовательно; внешний backend не требуется для S/V-H. Начальных реализованных leaf E-01 не обнаружено.

### WP-01 — Точечная нормализация контракта

- **Status:** IN_PROGRESS. **Parent:** E-01. **Dependencies:** D-02/04/05; устраняет B-01/B-03.
- **Goal:** сделать схему и примеры пригодными для проверки без смены бизнес-семантики.
- **Sources of truth:** OAS listSortingBatches/listQuarantineItems/createDictionarySimulation/createSortingSelection/createSortingPreview; API §6–9; SEM правила/очередь.
- **Acceptance criteria:** правильные query/path parameters, согласованные примеры; новые продуктовые операции/поля не добавлены; исправления перечислены в handoff.
- **Verification expectations:** V-H точного diff параметров и таблицы связей examples достаточен для review этой документальной коррекции. Полная schema validation — самостоятельный результат WP-02, не обратная зависимость WP-01 и не уже пройденный этап.
- **Leaf tasks:** LT-01.1, LT-01.2. Будущий scope: OAS и контрактный handoff; не backend/UI.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-01.1 | IN_PROGRESS | D-04 | Исправить ровно B-01 | OAS CompanyId/listSortingBatches/listQuarantineItems; API §8/9 | Отдельный required query company_id со схемой Id в двух GET; CompanyId in:path для `/companies/{company_id}/…` сохранён; пути/ответы прежние | V-H parameter/path matching и всех ссылок на CompanyId/diff; executable regression добавляет LT-02.1 |
| LT-01.2 | IN_PROGRESS | D-04 | Устранить B-03 в examples | OAS Simulation/PlanRow/RuleSet/SelectionSnapshot/Preview/examples; API §6/7; QA §4 | filename/source согласованы; published references входят в RuleSet; snapshot/preview согласованы либо отдельные сценарии имеют разные IDs; без domain implementation | V-H таблицы связей, V-S после LT-02.1; regression LT-02.2 |

LT-01.1 evidence: независимый LEAF reviewer PASS; orchestrator повторил ad-hoc `node .../lt-01-1-verify/check.js contracts/openapi/wiseway-v1.yaml` — 25/25; точный OAS diff (3 hunks), `git diff --check` PASS. Handoff: `docs/team/E-01_CONTRACT_HANDOFF.md`. Локальный checkpoint `7b0843b`; push не прошёл, поэтому прежняя условная запись VERIFIED не вступила в силу и исправлена на IN_PROGRESS. Техническая зависимость B-01 устранена по фактическому коду; дальнейшее локальное исполнение разрешено D-06. V-S ещё не выполнена.

LT-01.2 evidence: LEAF reviewer сначала FAIL (имя NO_SCENARIO совпадало с маской; чужой опубликованный участник загрязнял общий RuleSet), после repair 1 полный re-review PASS. Orchestrator: ad-hoc `node .../lt-01-2-verify/check.js <oas>` — 56/56; точный diff и `git diff --check` PASS. Исправления и таблицы связей: тот же handoff. Технически leaf завершён; формальный статус IN_PROGRESS до публикации пользователем по D-06, локальный checkpoint создаётся с этой записью. B-03 исправлен; schema runner ещё не запускался.

WP-01 local package completion: commits `7b0843b`, `d64dfdb`; полный WORK_PACKAGE review `c271587..d64dfdb` — PASS. Orchestrator повторил оба ad-hoc набора (25/25 и 56/56) и `git diff --check c271587..HEAD` — PASS. Технические AC WP-01 завершены, зависимости WP-02 удовлетворены фактическим OAS. Формальный VERIFIED ожидает человеческой публикации (D-06); backend/M/A/E не запускались.

### WP-02 — Исполняемые контрактные проверки

- **Status:** IN_PROGRESS. **Parent:** E-01. **Dependencies:** WP-01; устраняет B-02.
- **Goal:** заменить обещание README воспроизводимым runner.
- **Sources of truth:** README проверка; FE-01/02; API §2/11/12; PLAN §7; Q-043; OAS целиком.
- **Acceptance criteria:** 33 операции, структура/examples/negative requests/инварианты проверяются; зависимости закреплены; README содержит выполненные команды. Backend и промежуточная QA-подпись не нужны.
- **Verification expectations:** V-S positive/negative; V-H инструкции/результатов.
- **Leaf tasks:** LT-02.1, LT-02.2. Scope: `tests/contract/`, README, контрактные examples.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-02.1 | IN_PROGRESS | WP-01 | OpenAPI 3.1 validation | OAS paths/components; API §2/11/12; README; Q-043 S | Unique operationId, refs, path matching, required/nullable/enums/oneOf/additionalProperties, security/CSRF/idempotency/HTTP responses и встроенные examples проверяются; README-команды существуют | V-S с invalid parameter/unknown field; версии, команды и фактический результат |
| LT-02.2 | IN_PROGRESS | LT-02.1 | Семантические инварианты examples | API §4/6–11; SEM поиск/планы/исходы/аудит; Q-011/017/024/029/038/043 S | filename/location, IDLE/total/returned_count/limited, PlanCounts без двойного счёта, completed_count/recovery, связи сценария/error.operation_id согласованы; страница не весь набор | V-S positive/negative fixtures каждого инварианта; без matcher/ranking алгоритма |

LT-02.1 local completion: полный LEAF re-review после repair 1 — PASS (устранены пропуск company_id, анонимная security-альтернатива и network fetch внешнего ref до guard). Orchestrator фактически выполнил `.venv-contract/Scripts/python.exe tests/contract/verify_contract.py` — 19 checks, 127 examples, PASS; `-m unittest discover -s tests/contract -p "test_*.py"` — 45 OK; `-m pip check` — no broken requirements; `git diff --check` PASS. Python 3.14.7, зависимости pinned в `tests/contract/requirements.txt`. B-02 устранён, README runner воспроизводим. IN_PROGRESS только из-за отложенной публикации D-06; техническая зависимость LT-02.2 удовлетворена.

LT-02.2 local completion: полный LEAF re-review после repair 1 — PASS. Orchestrator: `.venv-contract/Scripts/python.exe tests/contract/verify_contract.py` — 22 checks / 127 schema+semantic examples PASS; `-m unittest discover -s tests/contract -p "test_*.py"` — 72 OK; `-m pip check` и `git diff --check` PASS. 48 конечных payloads / 14 инвариантов плюс 2 linked cases; schema-only, не backend evidence. Исправлены vacuous return link, batch references, глобальная RuleSet consistency, overflow completed+recovery; полный handoff в `docs/team/E-01_CONTRACT_HANDOFF.md`. Локальный checkpoint; публикация отложена D-06.

WP-02 local package completion: `a2095d1`, `7c2b5e5`; полный WORK_PACKAGE review диапазона `dc26527..7c2b5e5` — PASS. Полная проверка orchestrator (22 checks, 127 examples, 72 tests, pip check) PASS; `git diff --check` PASS. Формальный VERIFIED ожидает публикации D-06; техническая зависимость WP-03 удовлетворена. Контракт 1.0.0, S/V-S; M/A/E не запускались.

### WP-03 — Независимые синтетические эталоны

- **Status:** IN_PROGRESS. **Parent:** E-01. **Dependencies:** WP-02, D-03.
- **Goal:** единый конечный набор A/B/C ожиданий для mocks и real-регрессии.
- **Sources of truth:** QA §4/5; TZ §6.3/12/14; FE-01/02; API §12; Q-001…045; OAS schemas/examples.
- **Acceptance criteria:** стабильные IDs, версия/seed, exact expectations независимо от тестируемых алгоритмов; общие публичные схемы. Не QA acceptance и не backend FS-генератор.
- **Verification expectations:** V-S/V-H таблиц; повторное использование в M/E.
- **Leaf tasks:** LT-03.1, LT-03.2, LT-03.3, LT-03.4, LT-03.5. Scope: `contracts/examples/`, `fixtures/synthetic/` — описания/fixtures, не executor. Каждый leaf создаёт свой конечный набор ожиданий, а не весь B/C-контур одним run.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-03.1 | TODO | WP-02 | Эталоны auth/search | AUTH-01…05/SRCH-01…25; TZ §12; API §3/4; QA §4; Q-001…014/042/043; OAS Session/SearchResponse/FacetResponse | Два корня, Atlas/Nova разной глубины, raw-case/unrecognized/optional tail; exact AND/prefix/phrase/token boundaries/ranking/ties; IDLE/zero/N=10 и 100 с >N; content-only/old-path отрицательные случаи, разные типы/нулевой размер; роли без встроенных секретов | V-S и ручная независимая сверка golden; параметры Q-007…014 перечислены |
| LT-03.2 | TODO | WP-02 | Эталоны целей, правил и публикаций | DICT-01…12; API §5/6; QA §4; Q-015…021/029 (publish)/044 (target); OAS TargetDirectory/Dictionary/Simulation/RuleSet | Две компании/два справочника одной/два актора; конечные пары rule→ожидание для полей/масок/суффиксов/приоритетов/одинаковых и разных целей; round-trip/revision/empty READY/full RuleSet/ack/TTL/restore/publication retry; значения независимы от matcher | V-S/V-H конечной таблицы Q-015…021 и отрицательных target/revision/ack cases; не реализация домена |
| LT-03.3 | TODO | WP-02, LT-03.2 | Эталоны очереди, снимков и preview | QUEUE-01…06/10; API §7; QA §4; Q-022…027; OAS QueueResponse/SelectionSnapshot/Preview | READY 0/120/1001, counts всей компании и filtered eligible отдельно; explicit/all matching/late arrivals/count change/expiry/owner scope; PlanRow использует принятые RuleSet references; все Prediction/CollisionDetails kinds, nullable цели; preflight ожидания различают DIRECT и PREVIEWED | V-S/V-H snapshot/preview links и finite входов/ошибок; membership задан таблицей, не вычисляется mock алгоритмом |
| LT-03.4 | TODO | WP-02, LT-03.3 | Эталоны фактических партий и файловых исходов | QUEUE-07…10, FILE-01…06/08/09; API §8; QA §4/8; Q-028…037/039/040/044; OAS Batch/Outcome/OutcomeCounts | Отдельные fixtures всех BatchState/Outcome/reasons, partial/recovery/null location, lost response/claim overlap/source change, обе коллизии/manual review/confirmed quarantine/restart; exact counts, attempts и expected placements независимы от executor; это описание, не физическое evidence | V-S/V-H каждого state/reason и сцепления с selection; expected inventory/hashes contract описан безопасно, FS-исполнение принадлежит BE |
| LT-03.5 | TODO | WP-02, LT-03.2, LT-03.4 | Эталоны карантина, возврата и журнала | FILE-07, AUD-01…05; API §9–11; QA §4/8; Q-029 (return)/038/041/043; OAS QuarantineItem/QuarantineReturnResponse/AuditEvent | Confirmed quarantine/can_return/recovery, все return conflicts/retry; BUSINESS/SYSTEM/nullable actor/blocked actors/cursor/new events; события связаны с dictionary/batch/return fixtures, request_id/operation_id/source_attempt_id согласованы; без реальных секретов | V-S/V-H конечных return/audit scenarios и nullable/links; не объявлять реальный аудит или возврат доказанным |

#### Рекурсивная декомпозиция WP-03 перед реализацией

Исходные LT-03.1…5 и все их AC/трассировка выше сохранены как родители. Конечные результаты разделены на данные/сценарии так, чтобы один worker/review не создавал весь предметный цикл. Общие G, источники и verification родителя обязательны для каждого применимого ребёнка. Формальный IN_PROGRESS после local PASS означает только отложенную публикацию D-06; техническое завершение фиксируется evidence отдельно.

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-03.1a | LT-03.1 | IN_PROGRESS | WP-02 | Версионированный синтетический корпус: два корня, Atlas/Nova разной глубины/годы/проекты, raw-case, optional tail/ошибки, все типы/zero, >100 совпадений, content-only/old-path и metadata lifecycle входы; два WORKER+ADMIN без секретов, auth/config API examples. Формат конечных fixtures для остальных детей и schema validation | V-S/V-H inventory, ID uniqueness, seed/version, schema-bound API examples, независимая сверка markers |
| LT-03.1b | LT-03.1 | IN_PROGRESS | LT-03.1a | Literal exact search/facet expectations Q-004…014/042/043: IDLE/zero/N10/N100, AND/prefix/все границы/phrase/mixed/ranking numeric/ties/сортировки/raw-case/unrecognized/freshness, auth/error/race сценарии Q-001…003/005/010; не matcher | V-S/V-H каждого параметра Q, literal IDs/order/counts/facets, negative mutations |
| LT-03.2a | LT-03.2 | IN_PROGRESS | WP-02, LT-03.1a | Две компании/два справочника одной/акторы, разрешённые targets; finite rule-input→expected-output для BASENAME/RELATIVE_PATH, масок/слешей/регистра/суффиксов/приоритетов/одинаковых и разных целей; invalid target/rule cases, round-trip всех полей | V-S/V-H Q-015/018/044, без matcher |
| LT-03.2b | LT-03.2 | IN_PROGRESS | LT-03.2a | Конечные revision/имя conflict, simulation full READY/empty/full RuleSet, ack/comment/TTL, publication retry/history/restore/manual edit происхождения сценарии Q-016…021/029 | V-S/V-H ссылок draft/version/simulation/publish, negative cases |
| LT-03.3a | LT-03.3 | IN_PROGRESS | LT-03.2b | Очередь/readiness и snapshot: 0/120/1001 READY, company counts vs filtered eligible/page, explicit/all matching, literal membership, late arrival/change count/expiry/owner scope | V-S/V-H Q-022/024/025 и часть Q-023/026, IDs/revisions не алгоритм |
| LT-03.3b | LT-03.3 | IN_PROGRESS | LT-03.3a | Preview: все Prediction/CollisionDetails kinds, nullable цели и принятые RuleSet refs; DIRECT/PREVIEWED preflight input/error pairs, stale dependencies до batch | V-S/V-H Q-023/026/027, snapshot/preview links |
| LT-03.4a | LT-03.4 | IN_PROGRESS | LT-03.3b | Конечные Batch всех состояний и Outcome/reasons, exact counts/attempts/placements, partial/known+unknown recovery, collisions/manual review/quarantine; expected inventory/hash evidence contract без FS исполнения | V-S/V-H Q-031…037/039; каждый enum/reason, selection links |
| LT-03.4b | LT-03.4 | IN_PROGRESS | LT-03.4a | Сценарии accepted lost response/idempotency, claim overlap двух акторов, source change, logout/reload continuation, поздняя коллизия/перестановка IDs, restart в трёх точках/containment; finite expected attempts/events/placements | V-S/V-H Q-028…030/032/040/044; не concurrency/FS evidence |
| LT-03.5a | LT-03.5 | IN_PROGRESS | LT-03.2b, LT-03.4b | Confirmed quarantine/can_return/recovery, возврат WAITING_READY, все return conflicts/comment/revision/key retry, exact source_attempt/return_operation/error.operation связи | V-S/V-H Q-029 return/038, без auto sorting |
| LT-03.5b | LT-03.5 | IN_PROGRESS | LT-03.5a | Связанный audit: все dictionary/batch/attempt/return events, BUSINESS/SYSTEM/nullable actor/blocked actor list, фильтры/UTC день/cursor/new events, безопасные request/operation/source_attempt IDs, отсутствие business read событий | V-S/V-H Q-041/043, сквозная сверка статических fixtures |

LT-03.1a local completion: полный reviewer PASS после repair 2; исправлены CRLF hash portability, root/parent-scoped marker IDs, lifecycle validation и path/raw-case consistency. Orchestrator: runner 26 checks PASS, 127 embedded + 15 public examples, 162 corpus files, 8 lifecycle payloads; unittest 114 OK, pip check PASS. Fixture version 1.1.1, seed `wiseway-demo-seed-2031`; handoff `docs/team/WP-03_SYNTHETIC_HANDOFF.md`. M/A/E NOT_RUN. Только локальный checkpoint, формальная публикация D-06 отложена.

LT-03.1b local completion: полный reviewer PASS после repair 1; независимо пересверены 57/57 literal search/facet результатов и scores по полному корпусу. Orchestrator: runner28 PASS, unittest159 OK; 51 search / 6 facet / 14 errors / 3 race / 3 format + ID tie profile; 164 corpus files, version1.2.0. Исправлены UNRECOGNIZED в item.markers и CSRF на читающей операции; добавлены freshness статусы. Родитель LT-03.1 технически завершён; M/A/E NOT_RUN, публикация D-06 отложена.

LT-03.2a local completion: LEAF re-review PASS после repair1 (исправлена whole-field cross-slash маска и отделены scenario версии от публичной истории). Reviewer независимо подтвердил26/26 rule ожиданий и17/17 invalid classifications; orchestrator runner30 PASS/unittest195 OK. 26 rule /8 target /17 invalid scenarios,49 public examples. Корпус1.2.0 без изменений. Локально завершено, D-06.

LT-03.2b local completion: LEAF re-review PASS после repair1. Исправлены user-scoped idempotency (без глобального key conflict), сохранение candidate invoices перед публикацией, комментарии версии и isolated revisions. Orchestrator runner33 PASS/unittest243 OK;19 timeline/16 failures/1 replay/7 simulation pages,77 public examples. Родитель LT-03.2 технически завершён, local checkpoint, D-06; M/A/E NOT_RUN.

LT-03.3a local completion: LEAF re-review PASS после repair1; удалено неверное обратное условие selectable, добавлен явный stability-вход и уникальный snapshot ID. Orchestrator runner36 PASS, targeted `test_queue_selections.py`44 OK; reviewer полная suite287 OK. 4 profiles/8 queries/3 selections/7 errors/5 readiness/4 ownership,97 public examples. Локально завершено, D-06; не реальные readiness/TTL evidence.

LT-03.3b local completion: LEAF reviewer PASS без repair; независимо проверены134/134 plan rows. Orchestrator runner39 PASS/targeted55 OK; reviewer full342 OK (672.948s), pip check PASS.6 previews/18 preflight/15 rejection/4 post-acceptance descriptions,110 public examples. Родитель LT-03.3 технически завершён. Handoff содержит исторические неточности счётчиков (15 mutations/49tests); фактически17 mutations/55tests. Только S, local checkpoint D-06.

LT-03.4a local completion: LEAF reviewer PASS; orchestrator runner42 PASS/targeted50 OK; reviewer full392 OK (341.657s).7 batches/9 pages/260 outcomes/7 summaries/23mutations,120 public examples; все5 BatchState/8OutcomeState/9reasons. Inventory — только логические ожидания, не измеренные hash/FS evidence. Полная CLI остаётся exhaustive; оптимизированы только OAS-corruption unit runs. Локальный checkpoint D-06.

LT-03.4b local completion: LEAF reviewer PASS; orchestrator runner45 PASS/targeted56 OK; reviewer full448 OK (497.789s).12 scenarios/4 replays/9 containment cases/18 audit expectations/23mutations,122 public examples. Родитель LT-03.4 технически завершён. Нет live FS/claim/restart evidence; M/A/E NOT_RUN. Локальный checkpoint D-06.

LT-03.5a local completion: LEAF re-review PASS после docs-only repair1 (добавлен обязательный FE§7 handoff). Orchestrator runner48 PASS/targeted52 OK; reviewer full500 OK (636.846s) до неизменяющего code/data handoff.2 quarantine records/11scenarios/2replays/2audit descriptors/22mutations,134 public examples. Source Archive — отдельная synthetic world configuration; не факт настроенного сервера. Только local checkpoint D-06, M/A/E NOT_RUN.

LT-03.5b local completion: первый независимый LEAF review — FAIL (dictionary-события хранили собственные литеральные `occurred_at` 07:00–08:12Z, не совпадавшие с авторитетной timeline `dictionary_lifecycle.json` 09:20–09:53Z; README ошибочно утверждал совпадение). После repair 1 полный свежий re-review — PASS: время всех 16 dictionary-событий выводится из lifecycle (`simulations[].created_at` для SIMULATED, `versions[].published_at` для PUBLISHED, иначе `states[after_state].updated_at`), литеральные дубли удалены, tautological-проверка заменена независимым чтением lifecycle, пересчитаны затронутые literal query/update ожидания. Orchestrator: runner 51 checks PASS, targeted 79 OK, regenerate/checksums idempotent, pip check и `git diff --check` PASS; reviewer независимо подтвердил 16/16 привязок времени, day-query и cursor-page2, 42 OK `test_synthetic_corpus`. 323 события/17 queries/4 actor pages/4 updates/24 mutations,142 public examples, корпус 1.2.0. Родитель LT-03.5 технически завершён; M/A/E NOT_RUN; публикация отложена D-06.

WP-03 local package completion: commits `4fe3e35`…`ee8e28e`; полный WORK_PACKAGE review диапазона `627db93..ee8e28e` — PASS. Reviewer независимо выполнил полный suite — 579 OK (1132.599s), runner 51 checks PASS, `git diff --check` чист, все 9 генераторов идемпотентны, manifest/checksums пересчитаны независимым скриптом (142 examples/9 fixtures, combined `013ef0f9…57afb8d`), spot-checks A/B/C и 16/16 dictionary-времён PASS. OAS/semantics не изменялись. Non-blocking замечания: дублирование времени изолированных `BATCH_ACCEPTED` между `batch_scenarios.json` и `audit_expectations.json` (кросс-проверяется, класс LT-03.5b не воспроизводится); `AUD-DICT-BLOCKED-SAVE` — осознанный explicit-литерал; ветка «descriptor не должен объявлять occurred_at» покрыта data-level assert без отдельной mutation. Технические AC WP-03 завершены, все 10 детей завершены; формальный VERIFIED ожидает человеческой публикации (D-06). S/V-S/V-H; M/A/E NOT_RUN.

E-01 final completion: финальный независимый EXECUTION_UNIT review продуктового состояния диапазона `6cdecda..2967764` (HEAD на момент review) — PASS. Reviewer выполнил полный suite — 579 OK (972.375s), runner 51 checks PASS, `git diff --check 6cdecda..2967764` чист, все 9 генераторов идемпотентны, независимый пересчёт corpus/142 example/9 fixture checksums и combined `013ef0f9…57afb8d` PASS. Независимая структурная сверка OAS `origin/main`→`2967764` (без `examples`) даёт ровно 3 изменения: два `$ref` swap на новый `CompanyIdQuery` и сам компонент; paths/33 operationId/93 schemas/security/responses/bodies идентичны, `contracts/semantics.md` не изменён; остальные правки OAS — только внутри example values (B-03). Проверено отсутствие backend/UI product-изменений, секретов и production-данных; LT-03.5b-класс дефекта исправлен и не повторяется. После PASS создан финальный progress commit `bd65bb3`. Последующая namespace-миграция agent control plane (`AGENTS.md`, `.opencode/**`, `opencode.json`, launcher и этот backlog) является отдельным development-tooling изменением после продуктового review и не выдаётся за evidence E-01. Non-blocking: формулировка handoff/README «без фильтр-движка» неточна (есть cross-check re-derivation), дублирование времени isolated `BATCH_ACCEPTED` кросс-проверяется, мелкие расхождения таймингов в handoff, `.gitignore` без завершающего newline (унаследован от `c271587`). Итог E-01 — только S/V-S/V-H (контракт + эталоны); M (mock/UI), A (реальный API/ФС), E (E2E) NOT_RUN и не заявляются. Публикация всей ветки — за пользователем (D-06).

## EPIC E-02 — Toolchain, generated client, транспорт и mocks

Status: READY_FOR_HUMAN_REVIEW. Scope: FE-02; TZ §11/14; NFR-02/05. Браузерная сборка — frontend, backend/infra здесь не реализуются.

Execution baseline 11.09.2026: branch `feat/e-02`, HEAD `78bbeeb` (= `origin/main` после merge PR #1 E-01); `frontend/` отсутствует, продуктовых артефактов E-02 нет. Dependencies WP-04: WP-02 удовлетворён фактическим состоянием (runner/эталоны E-01 в `tests/contract/`, `contracts/examples/`, `fixtures/synthetic/`). WP-04 → WP-05 → WP-06/WP-07. X-STACK закрывается инженерным решением LT-04.1a. По D-09 push выполняет только пользователь; orchestrator делает локальные reviewed checkpoints и продолжает автономно, VERIFIED в E-02 не зависит от push.

### WP-04 — Воспроизводимая браузерная основа

- **Status:** VERIFIED. **Parent:** E-02. **Dependencies:** WP-02.
- **Goal:** одна собираемая frontend-структура и generated client.
- **Sources of truth:** TZ §11/NFR-02; FE §2/3, FE-02; PLAN §2/3/7; OAS целиком.
- **Acceptance criteria:** toolchain/ADR/lock закреплены; typecheck/lint/component/browser/build доступны; поддержка OpenAPI 3.1, без ручных DTO.
- **Verification expectations:** V-C/V-S, повторная генерация без diff, чистая установка.
- **Leaf tasks:** LT-04.1, LT-04.2. Scope: frontend bootstrap/config/generated/tests, согласованный frontend ADR/README.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-04.1 | VERIFIED | — | Scaffold с runner | TZ §11/NFR-02; FE §3; PLAN §2/3/7 | Orchestrator принимает X-STACK внутри требований: runtime/package manager/generator/test runners и обычный frontend toolchain; решение закреплено в ADR, runtime/dependencies/lock зафиксированы; одна структура features/api/generated/mocks/tests; реальные typecheck/lint/component/browser/build команды; без лишних экранов/design system | V-C smoke/build/установки по lock; V-H ADR/README; React+TS не объявлены уже установленными |
| LT-04.2 | VERIFIED | LT-04.1, WP-02 | Клиент единственного OAS | Все 33 OAS operationId/schemas; API §12; FE-02; Q-043 S | Generated types/client в `frontend/src/api/generated`; nullable/unions/oneOf/headers/query/body корректны; генерация документирована, без ручных DTO/правок output | V-C usage tests A/B/C, DIRECT/PREVIEWED/query company_id; повторная генерация без diff |

WP-04 package completion: commits `579883c`, `14e2fb7`, `7fa35dc`; полный WORK_PACKAGE review диапазона `78bbeeb..7fa35dc` — PASS. Reviewer фактически на интегрированном состоянии: `npm ci` exit 0 (lock SHA256 неизменён), `typecheck`/`lint`/`build` exit 0, `test` 41 PASS, `test:browser` 1 PASS (`msedge`), `generate:api` и `generate:api:check` exit 0, `git diff --exit-code -- src/api/generated` чист, OAS 33 operationId / 93 схем присутствуют в `schema.ts`/`openapi.json`, ручных DTO нет, `git diff --check 78bbeeb..HEAD` PASS. Диапазон содержит только `frontend/**` и progress backlog; `contracts/**`, control plane, root tests, fixtures не изменялись. Non-blocking: browser-канал `msedge` как условие среды; устаревшая фраза ADR о scripts (добавлены в LT-04.1b); 6/33 операций без runtime-теста (deferred WP-05). M/A/E NOT_RUN. D-09: публикация — за пользователем.

LT-04.2 completion: сгенерированы `frontend/src/api/generated/schema.ts` (openapi-typescript 7.13.0, все 33 operationId, 93/93 component-схемы), `frontend/src/api/generated/openapi.json` (JSON OAS, deep-equal YAML), типизированный клиент `frontend/src/api/generated/client.ts` (`createClient<paths>`, настраиваемые baseUrl/fetch, без ручных DTO). Команды `generate:api` / `generate:api:check`; `frontend/.gitattributes` (`eol=lf`) для байт-стабильности. Независимый LEAF reviewer PASS. Reviewer фактически: повторная генерация даёт идентичные SHA256 (`schema.ts` `D3ED40AA…536F8C`, `openapi.json` `F09F4A08…E030C5`), `generate:api:check` exit 0; `typecheck`/`lint`/`build` exit 0; `test` 41 PASS (client 29, generated-types 9, fixture-imports 2, App 1); type-assertions доказанно не no-op (мутационный probe падает TS2344). Не-blocking: runtime-тестами покрыты 27/33 операций (не покрыты `getAppConfig`, `listCompanies`, `getDictionaryVersion`, `listDictionaryVersions`, `restoreDictionaryDraft`, `logout`); расширение — в WP-05. `contracts/**` не изменён; M/A/E NOT_RUN.

LT-04.1b completion: создан минимальный scaffold `frontend/src/{features/{auth,search,dictionaries,sorting,quarantine,audit},api/generated,mocks}` + `frontend/tests`, `index.html`, `main.tsx`, `App.tsx` (без продуктовых экранов/design system), `tsconfig.json`, `vite.config.ts` (Vite+Vitest, alias `@fixtures`/`@examples`, `server.fs.allow`), `eslint.config.js` (flat), `playwright.config.ts`, `frontend/README.md`; в `frontend/package.json` добавлены scripts `dev/build/preview/typecheck/lint/test/test:browser`. Независимый LEAF reviewer PASS. Orchestrator + reviewer фактически: `npm ci` exit 0, `typecheck` exit 0, `lint` exit 0, `test` 3 PASS, `build` exit 0 (`dist/index.html`), `test:browser` 1 PASS (канал `msedge`, стабильно при повторе), `dev` стартует (5173), импорт JSON из `fixtures/`/`contracts/examples` подтверждён тестом. Исправлен дефект прерванной сессии: `vite preview` слушал `localhost` (IPv6 `::1`) при Playwright-probe по `127.0.0.1`; preview и baseURL приведены к `127.0.0.1`. Браузерный канал `msedge` — условие среды (скачивание Chromium CDN недоступно), задокументировано в README. M/A/E NOT_RUN.

LT-04.1a completion: X-STACK закрыт инженерным решением (Node 24.x/npm 11.x, React 19 + TypeScript 5.9, Vite 7, Vitest 3 + Testing Library + jsdom, Playwright 1.x, ESLint 9 + typescript-eslint, openapi-typescript 7 + openapi-fetch 0.14, ajv 8 + yaml 2). ADR `frontend/docs/ADR-0001-frontend-toolchain.md`; `frontend/package.json` с exact-пинами, `engines`, `packageManager`; committed `package-lock.json` (lockfileVersion 3); `frontend/.npmrc` (`save-exact=true`), `frontend/.gitignore` (`/node_modules/`). Независимый LEAF reviewer PASS. Orchestrator фактически: `npm ci` → exit 0; `npm ls --depth=0` → exit 0 без unmet peer; `npm audit --omit=dev` → 0 vulnerabilities; pinned `openapi-typescript 7.13.0` против OAS 3.1.1 → exit 0 (132291 bytes, `/auth/login`, `/sorting/batches`); `git diff --check` PASS. Полный `npm audit` даёт 2 moderate только в dev-цепочке Vitest 3.x (fix — Vitest 5, вне решения), записано в ADR §8. Application scaffold/scripts/generated/mocks в этом leaf намеренно отсутствуют (LT-04.1b). M/A/E NOT_RUN.

WP-05 package completion: commits `73b3f0f`, `bc44d9c`, `2f79d37`, `6fb266a`; полный WORK_PACKAGE review диапазона `eadae6b..6fb266a` — PASS. Reviewer фактически на интегрированном состоянии: `npm ci` exit 0, `typecheck`/`lint`/`build` exit 0, `test` 181 PASS (transport 37, transport-error 35, idempotency 31, retry 37, client 29, generated-types 9, fixture-imports 2, App 1), `generate:api:check` без diff, независимый разбор OAS подтвердил 10 CSRF/3 idempotency, `git diff --check eadae6b..HEAD` PASS, forbidden paths и generated/package не изменены. AC WP-05 (credentials/CSRF/no-store, safe errors, строго ограниченные retry, отсутствие хранения чувствительных данных и скрытой адаптации) — выполнены. Non-blocking: неиспользуемая `createWiseWayClient` в generated (вне scope); гонка одной pending-ячейки idempotency при разных телах; хрупкая классификация retry по `csrf`; `clearSession` не очищает пользовательский store; `Retry-After` HTTP-date; full-jitter 0мс. M/A/E NOT_RUN; публикация — за пользователем (D-09).

LT-05.1a completion: добавлены generated `frontend/src/api/generated/operation-meta.ts` (карта `METHOD path → {operationId, csrf, idempotencyKey}`, 33 операции; csrf ровно 10: `logout/createDictionary/replaceDictionaryDraft/restoreDictionaryDraft/createDictionarySimulation/publishDictionary/createSortingSelection/createSortingPreview/createSortingBatch/returnQuarantineItem`; idempotencyKey ровно 3: `publishDictionary/createSortingBatch/returnQuarantineItem`), in-memory `frontend/src/api/session-context.ts` (CSRF токен без storage, unauthorized listeners), `frontend/src/api/transport.ts` (`createApiClient` на openapi-fetch: real `credentials:'include'`, `cache:'no-store'`, CSRF/Idempotency-Key только на объявленных операциях и только в headers, capture `X-Request-ID`, 401 сигнал очистки, 403 без auto-retry, mock-mode через переданный fetch). Независимый LEAF reviewer PASS: независимый разбор OAS подтвердил 10/3 наборы; повторная генерация без diff (`operation-meta.ts`/`schema.ts`/`openapi.json`); `typecheck`/`lint`/`build` exit 0; `test` 78 PASS (transport 37); `git diff --check` PASS. Non-blocking (deferred LT-05.1b): blanket-401 сейчас вызывает очистку и для `LOGIN_FAILED`; в LT-05.1b различать `LOGIN_FAILED`/`UNAUTHENTICATED`. M/A/E NOT_RUN.

LT-05.1b completion: добавлен `frontend/src/api/transport-error.ts` (`TransportError` с `kind/status/code/message/requestId/operationId/retryable/fieldErrors/retryAfterSeconds`, разбор `ErrorResponse`, синтез безопасного кода по статусу при битом теле, network→`NETWORK_ERROR`, `throwIfError`). `transport.ts` теперь вызывает сигнал очистки только при `UNAUTHENTICATED` (не `LOGIN_FAILED`), через `Response.clone()`; `X-Request-ID` capture сохранён, 403 без auto-retry. Независимый LEAF reviewer PASS: `test` 113 PASS (transport-error 35); `typecheck`/`lint`/`build` exit 0; `generate:api:check` без diff; generated/зависимости не изменены; `git diff --check` PASS. Проверены 200/204, 401 `UNAUTHENTICATED` vs `LOGIN_FAILED`, 403 `FORBIDDEN`/`CSRF_FAILED`, 404, 409 (`STALE_PREVIEW`/`DRAFT_VERSION_CONFLICT`/`RECOVERY_REQUIRED`), 422 с `field_errors`, 429 с `Retry-After`, 500 с `request_id`, 503, network/abort; утечки тел/секретов нет. Non-blocking: README-пример не показывает конвертацию network-ошибки; `Retry-After` HTTP-date без теста. M/A/E NOT_RUN.

LT-05.2a completion: добавлен `frontend/src/api/idempotency.ts` (session-scoped in-memory `IdempotencyStore`: key↔body fingerprint, `begin/complete/retain/clear`, UUID); транспорт для 3 объявленных операций (`publishDictionary`/`createSortingBatch`/`returnQuarantineItem`) автоматически ставит `Idempotency-Key`, связанный с телом; 2xx/non-retryable → release, network/429/503 → retain; `clearSession`/`emitUnauthorized` очищают store. Независимый LEAF reviewer PASS: `test` 144 PASS (idempotency 31); `typecheck`/`lint`/`build` exit 0; `generate:api:check` без diff; forbidden paths не тронуты; зависимостей нет. Non-blocking: generated-тип требует от caller заглушку `Idempotency-Key` (транспорт перезаписывает); `createSortingBatch` без path-параметров имеет одну pending-ячейку; FNV-1a некриптографичен. M/A/E NOT_RUN.

LT-05.2b completion: добавлен `frontend/src/api/retry.ts` (`RetryConfig` с инъекцией `sleep`/`now`; `computeRetryDelay` — `Retry-After` приоритетно и с cap, иначе экспонента с jitter; `shouldRetry` — только безопасные чтения и 3 идемпотентные операции, никаких прочих mutation и `login`; `createRetryFetch` повторяет тот же `Request` (тело/`Idempotency-Key`), WeakMap-метаданные не уходят в заголовки; `createPollRegistry` single-flight). Транспорт обёрнут retry-fetch; session cleanup очищает poll/retry state. Независимый LEAF reviewer PASS: `test` 181 PASS (retry 37); `typecheck`/`lint`/`build` exit 0; `generate:api:check` без diff; generated/зависимости не тронуты; классификация 33 операций подтверждена. Non-blocking: `shouldRetry` использует `csrf=false`+исключение `login` (хрупко при будущем изменении контракта); poll-registry пока без feature-потребителя; full-jitter может дать 0мс. M/A/E NOT_RUN.

### WP-05 — Безопасный HTTP-транспорт

- **Status:** VERIFIED. **Parent:** E-02. **Dependencies:** WP-04.
- **Goal:** единое mock/real-подключение с корректными ошибками/повторами.
- **Sources of truth:** API §2/11; SEM транспорт/повторы; AUTH-02/04, NFR-05/07; OAS security/headers/errors.
- **Acceptance criteria:** credentials/CSRF/no-store, safe errors, строго ограниченные retry; нет сохранения чувствительных данных/скрытой адаптации ответа.
- **Verification expectations:** V-C HTTP tests; V-M с feature UI; G-1/3/5.
- **Leaf tasks:** LT-05.1, LT-05.2. Scope: `frontend/src/api/` вне generated output, tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-05.1 | VERIFIED | WP-04 | Session headers и safe errors | API §2/11; OAS cookieAuth/XCSRFToken/RequestId/NoStore/RetryAfter/ErrorResponse; Q-001/003/043 | Cookie обслуживает браузер, CSRF в памяти; заголовок на объявленных мутациях, включая simulation/selection/preview; читающие POST не мутации; 401 сигнал очистки, 403 без retry; failure не success; request_id/operation_id/field_errors доступны без утечки | V-C 200/204/401/403/404/409/422/429/500/503/сеть, состав requests/очистка token; режим меняет transport config |
| LT-05.2 | VERIFIED | LT-05.1 | Политика безопасного повтора | API §2 «Идемпотентность», §11; SEM повторы; QUEUE-09; Q-003/029/030 | Publish/batch/return удерживают UUID+исходное тело в памяти; новый ключ — новое явное действие; прочие мутации без auto retry/фиктивного ключа; retryable не отменяет ограничения; Retry-After/backoff, без одинаковых параллельных polls; session scope | V-C lost response, тело/ключ, запрет слепого нового ключа, controlled clocks; feature reconciliation в своих leaf |

### WP-06 — Контрактные mocks A

- **Status:** VERIFIED. **Parent:** E-02. **Dependencies:** WP-03, WP-05.
- **Goal:** воспроизводимые auth/search сценарии без backend.
- **Sources of truth:** FE-02; API §3/4/12; QA §4/5; Q-001…014/043; OAS A-операции.
- **Acceptance criteria:** requests/responses schema-valid, delay/error/reset управляемы; нет клиентского поиска/ranking по dataset; mock указан в evidence.
- **Verification expectations:** V-S/V-C handlers/negative payload; V-M потребителей позднее.
- **Leaf tasks:** LT-06.1, LT-06.2. Scope: mocks/tests/общие fixtures.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-06.1 | VERIFIED | WP-03, WP-05 | Mock bootstrap/session/config | OAS getHealth/login/getSession/logout/getAppConfig/listRoots/listCompanies; API §2/3; Q-001…004/043 | Session/401/403, empty roots/companies, разные limits/timezone, сеть/delay воспроизводимы; requests валидируются; реальных credentials нет; mock не защищённый auth backend | V-S/V-C всех handlers/headers/reset/invalid fields |
| LT-06.2 | VERIFIED | LT-06.1, LT-03.1 | Mock выдачи/facets/races | OAS searchFiles/getSearchFacet; API §4; Q-004…014 | IDLE/zero/limited/unrecognized/freshness, schema/marker/503 ошибки, управляемый порядок ответов таблицы/dropdown; request_state_id конкретной отправки; totals/order из эталона, не matcher | V-S/V-C handlers/delays; invalid request не даёт правдоподобный успех |

WP-06 package completion: commits `ecab4df`, `43c17c5`, `5950787`, `e92469d`, `62e9641`; полный WORK_PACKAGE review диапазона `a3ed646..62e9641` — PASS. Reviewer фактически: `npm ci` exit 0, `typecheck`/`lint`/`build` exit 0, `test` 329 PASS, `generate:api:check` без diff; независимая сверка через реальный mock-fetch HTTP-слой — 51+6 golden search/facet literal, bootstrap-ответы deep-equal `contracts/examples/**`, все ответы schema-valid; нет storage/logging секретов; forbidden/generated/lock не изменены. AC WP-06 (schema-valid, управляемые delay/error/reset, отсутствие клиентского matcher/ranking, mock явно указан) — выполнены. Non-blocking: freshness fallback; `result_limit` не из config-профиля; scope-имена `search`/`facet` vs fixture `table`/`level-list`; retry interplay с 503; один timezone; root/schema 409 только через управляемую ошибку. M/A/E NOT_RUN; публикация — за пользователем (D-09).

LT-06.1 completion: создана mock-инфраструктура `frontend/src/mocks/**` (`router`/`validate` (ajv 2020-12 по `generated/openapi.json`)/`controller`/`data` (примеры через manifest)/`responses`/`handlers`) и 7 операций (`getHealth/login/getSession/logout/getAppConfig/listRoots/listCompanies`); mock-fetch совместим с `createApiClient({mode:'mock'})`. WIP checkpoint `ecab4df`; после него независимый LEAF reviewer PASS: `test` 211 PASS (bootstrap 30); `typecheck`/`lint`/`build` exit 0; `generate:api:check` без diff; ответы schema-valid из `contracts/examples`, session/401/403, empty roots/companies, профили N=100/N=10, delay/reset, unknown route 404; невалидный payload → 422 без успеха; реальных секретов нет. Non-blocking: оба config-примера имеют один timezone (различие только в limit); network-failure injection отсутствует (search-ошибки — LT-06.2b); login не ставит `Set-Cookie` (mock не auth backend); 204-body не покрыт отдельной ассерцией. M/A/E NOT_RUN.

LT-06.2a-i completion: созданы `frontend/src/mocks/search/corpus.ts` (детерминированный materializer `corpus.json` → 164 `SearchItem`, 61 files + 103 cohort; 37 уникальных `marker_id`, схема `marker-<root_id>-<value_id>…` совпадает с `tests/contract/contractlib/synthetic.py`; UNRECOGNIZED-терминал в каталоге, не в `item.markers`) и `frontend/src/mocks/search/expectations.ts` (literal-resolver 51 search + 6 facet сценариев; unknown request → `undefined`; freshness CURRENT/UPDATING/STALE). Независимый LEAF reviewer PASS: `test` 286 PASS (search-foundation 75); `typecheck`/`lint`/`build` exit 0; независимый дамп resolver'а совпал с golden 57/57 (order/totals/facets/marker enrichment/freshness), path-marker consistency 164/164, 0 mismatches; нет matcher/ranking. Non-blocking: order-sensitive `selected_marker_ids`; молчаливый fallback профиля freshness; mutable internals за ReadonlyMap. M/A/E NOT_RUN.

LT-06.2a-ii completion: добавлен `frontend/src/mocks/handlers/search.ts` (`POST /search`, `POST /search/facet`) с сессионной защитой (401), OAS-валидацией тела (422 без успеха), lookup foundation (unknown → 400 `INVALID_QUERY`), echo `request_state_id`, freshness-профилем контроллера; foundation не дублируется, matcher/ranking нет. Независимый LEAF reviewer PASS: `test` 305 PASS (search-handlers 19); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; независимая сквозная сверка через mock transport 57/57 literal golden. Non-blocking: `result_limit` из сценария, не из config-профиля; `schema_set_version`/`ROOT_NOT_READY`/`SCHEMA_VERSION_CHANGED` (409) не проверяются — к LT-06.2b. M/A/E NOT_RUN.

LT-06.2b completion: расширены `MockController` (scope-delay `search`/`facet`, per-send очереди, managed errors, `reset`) и handlers search/facet (delay+error до lookup, точный echo `request_state_id`); добавлен `frontend/src/mocks/search/errors.ts` — 8 объявленных кодов строго из `contracts/examples/errors/*` (400/422/409/429/500/503), без выдуманных. Независимый LEAF reviewer PASS: `test` 329 PASS (search-error-race 24); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; независимая сверка набора ошибок с OAS/примерами; controlled-clock без реальных таймеров; race-порядок детерминирован. Non-blocking: тест набора частично самореферентный; one-shot `failNext` 503 маскируется retry; scope-имена `search`/`facet` vs fixture `table`/`level-list`. M/A/E NOT_RUN.

SESSION CHECKPOINT (11.09.2026, orchestrator context-limit stop): точка возобновления E-02 после LT-06.1. Дальше: LT-06.2a-i → LT-06.2a-ii → LT-06.2b, затем package review WP-06. Публикация — за пользователем (D-09).

### WP-07 — Контрактные mocks B/C

- **Status:** VERIFIED. **Parent:** E-02. **Dependencies:** WP-03, WP-05, LT-06.1.
- **Goal:** finite сценарии операционных экранов без файловых действий.
- **Sources of truth:** FE-02/04; API §5–12; Q-015…041/043/044; OAS B/C operations.
- **Acceptance criteria:** revisions/stale/TTL/access/lost responses/все исходы; mocks не domain backend; схемы общие с real.
- **Verification expectations:** V-S/V-C трёх групп handlers, M-smoke с UI.
- **Leaf tasks:** LT-07.1, LT-07.2, LT-07.3. Scope: mocks/tests/fixtures, не backend.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-07.1 | VERIFIED | LT-03.2, WP-05, LT-06.1 | Mock targets/dictionaries lifecycle | OAS target/dictionary/simulation operations; API §5/6; Q-015…021 | Canned responses разрешённой/невалидной цели, create/save/revision/lost response, simulation READY/empty/stale/conflict/no-scenario, publish retry/restore/history; schemas, без правил/FS алгоритма | V-S/V-C handlers/error/cursor/references/reset |
| LT-07.2 | VERIFIED | LT-03.3, LT-03.4, WP-05, LT-06.1 | Mock sorting lifecycle | OAS sorting operations; API §7/8; Q-022…037/039/040 | EXPLICIT/ALL_MATCHING, 0/120/1001, late arrivals, stale/expiry, DIRECT/PREVIEWED/lost response/retry; все BatchState/Outcome/reasons/progress/cursor; scripted scenarios, не claim/snapshot алгоритмы | V-S/V-C finite scenarios/таймеров/request variants; mock race не доказательство реальной гонки |
| LT-07.3 | VERIFIED | LT-03.5, WP-05, LT-06.1 | Mock quarantine/audit | OAS quarantine/audit operations; API §9–11; Q-029/038/041/043 | Confirmed quarantine/can_return/recovery/return conflicts; BUSINESS/SYSTEM/nullable actor/заблокированные авторы; cursor/new events/operation_id/source_attempt_id; без recovery endpoint | V-S/V-C handlers/null/cursor/reset/late responses/errors |

LT-07.1a completion: добавлены mock handlers targets/dictionaries (`listTargetDirectories`, `resolveTargetDirectory`, `listDictionaries`, `createDictionary`, `getDictionary`, `replaceDictionaryDraft`), in-memory `DictionaryStore` (seed/reset, trim+casefold), allowlist целей из `rule_expectations.json`, общий CSRF-guard, router `{param}`, объявленные ошибки. Независимый LEAF reviewer PASS: `test` 362 PASS (dictionaries-draft 33); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; независимый набор 12/12 через mock transport. Non-blocking: README-формулировка про guard переобобщает (`resolveTargetDirectory` — чтение без CSRF); `decodeURIComponent` может бросить URIError на malformed escape; casefold ≈ toLowerCase; managed-ошибки без 429/500/503. M/A/E NOT_RUN.

LT-07.1b completion: добавлены `createDictionarySimulation`/`getSimulation` (canned `SimulationStore`: full page1/page2, empty, conflict, same-target, no-scenario; full RuleSet references; counts без двойного счёта). Первый независимый LEAF review — FAIL: (1) undeclared 409 `STALE_SIMULATION` на `getSimulation` (OAS 409 не объявляет; oracle `tests/contract/contractlib/expectations.py` его исключает), (2) противоречивая revision-семантика (сценарий vs store). После repair 1 полный свежий re-review — PASS: `getSimulation` не возвращает 409 ни при каких изменениях черновика; create валидирует `expected_draft_revision` против текущей ревизии `DictionaryStore` и возвращает canned-сценарий с `draft_revision` = этой ревизии (GET dictionary ↔ simulate согласованы); managed errors ограничены объявленными кодами (`DRAFT_VERSION_CONFLICT`/`VALIDATION_ERROR`; `STALE_SIMULATION` недоступен); vacuous-ассерции заменены. Orchestrator/reviewer: `test` 387 PASS (simulations 25); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; независимые probes P1–P5 PASS. Non-blocking: error-restriction через типы, не runtime; `getSimulation` 403 объявлен, но не возвращается; `sim-offset` за пределами строк даёт пустую страницу. M/A/E NOT_RUN.

LT-07.1c completion: добавлены `publishDictionary`/`listDictionaryVersions`/`getDictionaryVersion`/`restoreDictionaryDraft` (canned publish v2/v3, versions paging, restore/provenance; gates RULE_CONFLICT/NO_SCENARIO_ACK_REQUIRED/STALE_SIMULATION/DRAFT_VERSION_CONFLICT/comment; idempotent replay до staleness + reuse; manual edit очищает `based_on_version_id`). Первый review — FAIL (restore в неканоническом состоянии фабриковал `active_version_id`/`versions_count`); repair 1 исправил, но re-review — FAIL (canonical canned игнорировал запрошенный `version_id`); repair 2 добавил проверку `canned.based_on_version_id === requested` → финальный свежий re-review PASS. Orchestrator/reviewer: `test` 419 PASS (publishing 32); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; независимые probes подтвердили restore v2 (content/based_on v2, active/count неизменны), canned v1, non-canonical restore без «висячего» active. Non-blocking: canned restore не учитывает actor; порядок 404/422 в versions; `getDictionaryVersion` 422 только через managed error; cursor за пределами истории → пустая страница. Родитель LT-07.1 технически завершён. M/A/E NOT_RUN.

LT-07.2a completion: добавлены `querySortingQueue`/`createSortingSelection` (canned queue 0/120/1001/all-active/missing/query-text, EXPLICIT/ALL_MATCHING snapshots, EMPTY_SELECTION/BATCH_LIMIT_EXCEEDED/SELECTION_CHANGED, foundation `SelectionStore.resolve` для owner/expiry/unknown на preview/batch). Первый review — FAIL: undeclared `SEARCH_UNAVAILABLE` 503 для sorting-операций (OAS `ServiceUnavailable` допускает только `SERVICE_UNAVAILABLE`) и отсутствие per-operation ограничения managed-кодов; repair 1 исправил (503 синтезируется как `SERVICE_UNAVAILABLE`, typed+runtime per-operation guard) → свежий re-review PASS. Orchestrator/reviewer: `test` 460 PASS (sorting-queue-selection 41); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; независимый probe подтвердил 503=SERVICE_UNAVAILABLE и no-op для undeclared кодов. Non-blocking: cursor → 422 (page2 нет); `CSRF_FAILED` не в managed-наборе; ALL_MATCHING использует 120-named snapshot; TTL boundary inclusive; 403 только через managed. M/A/E NOT_RUN.

LT-07.2b completion: добавлены `createSortingPreview`/`getSortingPreview` (canned preview explicit-one/multiple/allmatching-120/hetero/conflict; все 4 Prediction и 3 CollisionDetails.kind с nullable; paging page1; owner/unknown/expiry через `SelectionStore.resolve`; чтение не продлевает TTL; movement/batch не выполняются; `STALE_PREVIEW` не возвращается create/get). Независимый LEAF reviewer PASS: `test` 486 PASS (sorting-preview 26); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; declared statuses сверены с OAS/`expectations.py`; per-operation runtime enforcement подтверждён. Non-blocking: `declaredSortingErrorResponse` для shared-кодов отдаёт preview-пример (тело FORBIDDEN иное); `getSortingPreview` не проверяет owner (403 объявлен, но не enforced); `limit` валидируется, но не применяется; comment про INVALID_STATE-сообщение неточен. M/A/E NOT_RUN.

LT-07.2c completion: добавлены `createSortingBatch`/`getSortingBatch`/`listSortingBatches` (canned DIRECT/PREVIEWED, idempotent replay до staleness + reuse, gates 404/403/409 INVALID_STATE/SELECTION_EXPIRED/SELECTION_CHANGED/STALE_PREVIEW/422, фазы прогресса без таймеров, все BatchState/Outcome/reasons/recovery, list order/cursor). Независимый LEAF reviewer PASS: `test` 523 PASS (sorting-batch 37); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; независимые probes: 9 canned pages schema-valid, per-operation declared-error matrix 0 mismatches, undeclared коды no-op, replay до expiry, list paging/order; 422 limit = VALIDATION_ERROR + field_error BATCH_LIMIT_EXCEEDED (соответствует объявленному `ValidationError`). Non-blocking: `limit` не применяется к canned-страницам; Idempotency-Key не проверяется как UUID; 403 объявлен, но не эмитится на чтениях; SELECTION_CHANGED/limit — только через gate; unknown preview использует selection-not-found сообщение; list order через localeCompare. Родитель LT-07.2 технически завершён. M/A/E NOT_RUN.

LT-07.3a completion: добавлены `listQuarantineItems`/`returnQuarantineItem` (canned confirmed/ambiguous/returned; company-scoped paging; `can_return=false` ⇔ `recovery_operation_id`; return success WAITING_READY без auto-sort; conflicts NOT_FOUND/INVALID_STATE/QUARANTINE_VERSION_CONFLICT/ORIGINAL_PATH_OCCUPIED/RECOVERY_REQUIRED с operation_id/IDEMPOTENCY_KEY_REUSED; comment 1..500; idempotent replay без второго перемещения). Независимый LEAF reviewer PASS: `test` 551 PASS (quarantine 28); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; независимая сверка per-operation declared-кодов с generated OAS — точное совпадение. Non-blocking: field_errors комментария из ajv (code LENGTH → MIN/MAX_LENGTH); Idempotency-Key без UUID-проверки; 429 без Retry-After; `ambiguous` доступен как managed-сценарий; README-нит. M/A/E NOT_RUN.

LT-07.3b completion: добавлены `queryAuditEvents`/`getAuditUpdates`/`listAuditActors` (canned day/issue/batch-accepted/cursor-page2/empty; BUSINESS vs BUSINESS+SYSTEM для WORKER/ADMIN; null actor только SYSTEM; actors с blocked; updates true/false/empty; literal связи request/operation/source_attempt/batch/version). Независимый LEAF reviewer PASS: `test` 581 PASS (audit 30); `typecheck`/`lint`/`build`/`generate:api:check` exit 0; независимый probe 20/20 (declared-коды точны, ADMIN composition schema-valid, order/null-actor). Non-blocking: `limit` не применяется; неизвестный cursor → пустая страница; окно грубее; `company_id=nova` → пустая страница; ADMIN-композиция шире oracle; 429 без Retry-After. Родитель LT-07.3 технически завершён. M/A/E NOT_RUN.

E-02 final completion: финальный независимый EXECUTION_UNIT review диапазона `78bbeeb..280a22c` (HEAD на момент review) — PASS. Reviewer выполнил полную verification: `npm ci` exit 0 (lock неизменён), `typecheck`/`lint`/`build` exit 0, `test` 581 PASS (20 файлов), `test:browser` 1 PASS (`msedge`), `generate:api:check` без diff (SHA256 `schema.ts`/`openapi.json`/`operation-meta.ts` стабильны), `git diff --check 78bbeeb..HEAD` PASS. Независимо подтверждено: generated `openapi.json` deep-equal OAS (33 operationId/93 схемы, OpenAPI 3.1.1); 33/33 mock-операций; нет storage/console/секретов; `contracts/**`, `fixtures/**`, root `tests/**`, backend, control plane, `docs/team/**` не изменялись. WP-04/05/06/07 все VERIFIED. Итог E-02 — S (OAS 3.1.1, generated types, ajv-валидация) и M (mock HTTP/transport, unit/component, 1 browser smoke); **A (real API) и E (E2E) NOT_RUN** и не заявляются. Non-blocking: устаревшая фраза ADR о scripts; browser-канал `msedge` как условие среды; managed-ограничение у dictionaries/simulations/publishing только типовое; unguarded `decodeURIComponent`; `getSortingPreview` не enforced owner; `limit` не применяется к canned-страницам; cursor только page1; Idempotency-Key без UUID; 429 без Retry-After (позже подтверждён BLOCKING_E02 и исправлен в E02-F7-REPAIR); `Retry-After` только delta-seconds. Публикация всей ветки — за пользователем (D-09); локальные checkpoints, push не выполнялся после `579883c`.

E02-F7-REPAIR completion (targeted residual-risk validation после финального review): finding F7 подтверждён как BLOCKING_E02 — обычные managed mock-сценарии отдавали HTTP 429 без обязательного `Retry-After`, что нарушает OAS `components.responses.RateLimited`/`components.headers.RetryAfter` (`required: true`, `type: string`, `pattern: ^[0-9]+$`, первая версия — delta-seconds) и G-3. Repair минимальный и mock-only: единый общий путь `frontend/src/mocks/responses.ts` (`responseHeaders`/`jsonResponse`) добавляет контрактный delta-seconds `Retry-After` (`'30'`, значение из OAS-примера) строго при `status === 429`; handlers заголовок не дублируют, прочие статусы его не получают. Добавлен фокусный тест `frontend/tests/mocks/responses-retry-after.test.ts` (429 present + valid; 200/201/202/400/401/403/404/409/422/500/503/204 absent) и интеграционные ассерты managed 429/503 в `sorting-batch.test.ts`/`quarantine.test.ts`; shared-константы экспортированы из `frontend/src/mocks/index.ts`. Независимый fresh LEAF reviewer — PASS; mutation probe (снятие guard) дал ровно 4 падения и был восстановлен байт-в-байт. Orchestrator фактически: `npm run typecheck`/`npm run lint` exit 0, `npm test` 595 PASS (21 файл; +14 к прежним 581), `generate:api:check` без diff, `git diff --check` PASS. `contracts/**`, generated client, `frontend/src/api/**` (transport/retry/idempotency), backend, control plane, `docs/team/**` не изменялись. Остальные findings F1–F6/F8/F9 остаются non-blocking/DOC_ONLY; E-02 сохраняет READY_FOR_HUMAN_REVIEW.

WP-07 package completion: commits `3d45665`, `bfa0f33`, `bac5715`, `fe300eb`, `f8965f1`, `a99406c`, `9a2c07b`, `1587708`; полный WORK_PACKAGE review диапазона `0cf0ee6..1587708` — PASS. Reviewer фактически: `npm ci` exit 0, `typecheck`/`lint`/`build` exit 0, `test` 581 PASS, `generate:api:check` без diff; независимый probe 12/12 deep-compare с `contracts/examples/**`; enum coverage 5/5 BatchState, 8/8 OutcomeState, 9/9 reasons, 4/4 Prediction, 3/3 Collision; нет storage/console; forbidden/generated/lock не изменены; 24 B/C-операции + 9 A-операций = все 33 OAS operationId. AC WP-07 (revisions/stale/TTL/access/lost responses/все исходы; mocks не domain backend; общие схемы) — выполнены. Non-blocking: managed-ограничение у dictionaries/simulations/publishing только типовое (без runtime-guard); unguarded `decodeURIComponent`; `getSortingPreview` не enforced owner; `limit` не применяется; cursor-покрытие ограничено page1; publishing seed history только v1; README-нит; shared-code тела иногда из другого примера; Idempotency-Key без UUID; 429 без Retry-After. M/A/E NOT_RUN; публикация — за пользователем (D-09).

## EPIC E-03 — Оболочка и сессия

Status: READY_FOR_HUMAN_REVIEW. Scope: FE-03; AUTH-01…05, SRCH-18, TZ §4, NFR-01/05.

Execution baseline 12.09.2026: branch `feat/e-03`, HEAD `9daad51` (= `origin/main` после merge PR #2 E-02), чистое рабочее дерево; `frontend/` содержит scaffold E-02 (transport WP-05, mocks WP-06/07), продуктовых экранов E-03 нет. Dependencies WP-08 (WP-05, WP-06) удовлетворены фактическим состоянием. WP-08 → WP-09 последовательно; external backend не требуется (mock pass). По D-09 push выполняет только пользователь; orchestrator делает локальные reviewed checkpoints, VERIFIED не зависит от push. Рекурсивная декомпозиция E-03 не предписана (§4A её не содержит); leaf LT-08.1/08.2/09.1/09.2 исполняются как есть.

### WP-08 — Оболочка и app-config

- **Status:** VERIFIED. **Parent:** E-03. **Dependencies:** WP-05, WP-06.
- **Goal:** одна русская оболочка разделов с настройками сервера.
- **Sources of truth:** TZ §4/12; FE §4 navigation; API §3 AppConfig; Q-004/042/043.
- **Acceptance criteria:** нет dashboard/лишних функций; старт — пустой поиск; навигация не search/mutations; limits/timezone не зашиты в components; G-2/5.
- **Verification expectations:** V-C/V-M bootstrap/navigation/config/keyboard.
- **Leaf tasks:** LT-08.1, LT-08.2. Scope: frontend shell/shared config/UI/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-08.1 | VERIFIED | WP-06 | Доступные разделы без скрытых действий | TZ §3/4, SRCH-18/NFR-01; FE §4 navigation; Q-042 | Поиск/справочники/очередь/карантин/журнал; shell/focus/keyboard; старт поиск, память без URL/storage; переходы не search/mutations; общий reset private state для LT-09.2; accounts UI не нужен | V-C/V-M навигации/focus/network; незавершённые экраны не изображают рабочий продукт |
| LT-08.2 | VERIFIED | LT-08.1, LT-05.1 | Config и единые форматы | OAS getAppConfig/AppConfig/Count/Instant; API §3; SRCH-16, TZ §12; Q-042 | Config loading/error без фиктивных defaults; N/query/batch/TTL/polls из config; даты ДД.ММ.ГГГГ ЧЧ:ММ в display_timezone, B…TB по 1000 ≤1 знака; целые bytes точны; demo timezone не корпоративное решение | V-C 0/1000/границы единиц/Count/timezone/разные config; V-M форматов |

LT-08.1 completion: создана русская оболочка `frontend/src/app/` (`sections.ts`, `AppShell.tsx`, `shell.css`, `index.ts`) и модульный in-memory реестр приватного состояния `private-state-registry.ts` (`registerPrivateStateReset`/`resetPrivateState`); `App.tsx`/`main.tsx` подключены к оболочке. Ровно пять разделов в порядке «Поиск», «Справочники», «Очередь сортировки», «Карантин», «Журнал»; старт — «Поиск»; навигация клавиатурой/мышью (`nav` + нативные кнопки, `aria-current="page"`, видимый `:focus-visible`), честные заглушки «Раздел ещё не реализован» без выдуманных данных; активный раздел только в React-state, без router/URL/history/storage/cookie и без сети при переключении. Добавлена dev-зависимость `@testing-library/user-event@14.6.1` (точный пин) для реальной клавиатурной активации. Независимый LEAF reviewer — PASS: `typecheck`/`lint`/`build` exit 0, `npm test` 610 PASS (23 файла; +15 к 595), собственный probe подтвердил ноль fetch/XHR и отсутствие записи в URL/history/storage при навигации, а также контракт реестра; `git diff --check` PASS. `contracts/**`, generated client, `frontend/src/api/**`, `frontend/src/mocks/**`, `fixtures/**`, root `tests/**` и control plane не изменялись. Non-blocking: focus-visible проверен статически/CSS в jsdom, не в реальном браузере (перенесено на browser-проверки LT-08.2); `Set`-реестр не различает повторную регистрацию одной и той же ссылки; `aria-current="page"` для in-app разделов допустим. M/A/E NOT_RUN.

LT-08.2 completion: добавлены `frontend/src/app/app-api.ts` (единая фабрика `createAppApiClient`; ровно `VITE_API_MODE='mock'` → mock-fetch, иначе real, без молчаливого fallback), `session-state.ts` (in-memory `anonymous|authenticated`, без токенов, зарегистрирован в реестре LT-08.1), `app-config-store.ts`/`app-config-context.ts`/`app-config-provider.tsx` (`GET /app-config` только при аутентификации; `idle/loading/ready/error`; при ошибке нет выдуманных defaults, есть русская ошибка и «Повторить»; поздние ответы отсекаются; сброс в `idle`), `frontend/src/shared/format.ts` (`formatDateTime` → `ДД.ММ.ГГГГ ЧЧ:ММ` в переданном поясе, `formatSize` → десятичные B/KB/MB/GB/TB ÷1000 ≤1 знака, `formatCount` — точное целое); `App.tsx` создаёт транспорт и монтирует провайдер. Независимый LEAF reviewer — PASS: `typecheck`/`lint`/`build` exit 0, `npm test` 647 PASS (27 файлов; +37 к 610), `npm run test:browser` 4 PASS на `msedge` (реальная навигация мышью/клавиатурой и отсутствие `/app-config` при анонимной сессии); probe 7/7 подтвердил форматы (3 пояса + переход через полночь UTC), границы размера, гейтинг config и сброс `resetPrivateState()`→anonymous. Восстановлен сломанный LT-08.1 browser smoke (ожидал старый h1). `contracts/**`, generated, `frontend/src/api/**`, `frontend/src/mocks/**`, `fixtures/**`, root `tests/**`, control plane не изменялись; новых зависимостей нет. Non-blocking: `formatSize(999999)` → `1000 KB` (соответствует формулировке TZ/Q-042, косметика без промоушена в MB); README-опечатка в имени `app-config-context`; mock-код попадает в production bundle из-за статического импорта (bundle hygiene); browser negative-тест использует `waitForTimeout(500)`. M/A/E NOT_RUN.

WP-08 package completion: commits `e847581` (LT-08.1), `3d80472` (LT-08.2) и repair-commit LT-08.2. Первый полный WORK_PACKAGE review диапазона `9daad51..3d80472` — FAIL по одному blocking finding: `formatSize` отдавал дробную часть через запятую (`1,5 KB`), тогда как независимые Q-042 golden-значения `fixtures/synthetic/search_expectations.json` → `format_samples` (`FORMAT-Q042-SIZE`, root `README.md` §format_samples) требуют точку (`1500 → "1.5 KB"`, `4096 → "4.1 KB"`, `1500000 → "1.5 MB"`); это нарушало согласованность форматов FE §3.4. Repair cycle 1 (LT-08.2, same-leaf): `formatDecimal` сохраняет точку, обновлены локальные ожидания и README, добавлен регрессионный golden-кросс-чек, читающий `format_samples` через `@fixtures` и проверяющий все size- и date-кейсы. Свежий полный WORK_PACKAGE re-review — PASS: независимая сверка 9/9 size и 3/3 date literal совпала; доказана невакуозность (старая comma-реализация даёт 3/9 mismatch); `npm ci` (lock неизменён), `typecheck`/`lint`/`build` exit 0, `npm test` 650 PASS (27 файлов), `npm run test:browser` 4 PASS (`msedge`), `generate:api:check` без diff, `git diff --check` PASS; forbidden paths и фикстура не изменены. Технические AC WP-08 (одна русская оболочка без dashboard; старт — «Поиск»; навигация без search/mutations; limits/timezone из config, не зашиты; G-2/G-5) выполнены. Non-blocking: `formatSize(999999) → 1000 KB` без промоушена (в golden нет такого кейса); README-неточность в имени `app-config-context`; mock статически попадает в production bundle; browser negative-тест использует `waitForTimeout(500)`. M/A/E NOT_RUN; публикация — за пользователем (D-09).

### WP-09 — Вход и прекращение контекста

- **Status:** VERIFIED. **Parent:** E-03. **Dependencies:** WP-08.
- **Goal:** auth-flow и прекращение запросов от прежнего пользователя.
- **Sources of truth:** AUTH-01…05/NFR-05; API §2/3/11; SEM session; Q-001…003/030/042.
- **Acceptance criteria:** login/session/logout, без self-registration/reset; private context/polls очищаются; batch не отменяется; credentials не сохраняются.
- **Verification expectations:** V-C/V-M network/storage; реальные hash/cookie/Origin отдельно LT-25.1.
- **Leaf tasks:** LT-09.1, LT-09.2. Scope: auth/session/shell/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-09.1 | VERIFIED | WP-08 | Login/session bootstrap | OAS login/getSession/Session; API §2/3; AUTH-01/02/04/05; Q-001 | Required login/password, submitting/общая LOGIN_FAILED/error; 401 отличается от недоступности; actor/role серверные, actor_id в мутациях нет; без регистрации/reset/сохранения секретов; успех — пустой поиск | V-C/V-M WORKER/ADMIN/failure/explicit resubmit/network/focus/storage |
| LT-09.2 | VERIFIED | LT-09.1, LT-05.2 | Logout/expiry/block/reset | OAS logout/getSession; API §2/3; AUTH-03/SRCH-18; SEM idle/absolute/expires_at; Q-002/003/030/042 | Logout/401 очищают search/draft/selection/preview/session/polls; late success не возвращает их; неизвестный logout → session перед повтором; без выдуманного session backend; accepted batch с прежним actor | V-C/V-M logout/401/block/reload/user switch/delayed responses; новые features подключаются к G-5 |

LT-09.1 completion: добавлен `frontend/src/features/auth/**` (auth-gate, login-screen, session-bootstrap-store, auth-api, session-states), `frontend/src/app/roles.ts` (`WORKER`→«Рабочий», `ADMIN`→«Администратор») и `use-session.ts`; `session-state.ts` расширен серверными `actor`/`expires_at` без CSRF (токен только в `session-context`). Bootstrap `GET /session` до оболочки с состояниями `checking`/`anonymous`/`authenticated`/`unavailable`; только подтверждённый `401 UNAUTHENTICATED` → вход, сеть/5xx → русская недоступность с «Повторить» (не ложный logout). Форма входа отправляет ровно `{login,password}`, `LOGIN_FAILED` → одно общее русское сообщение без раскрытия поля и без очистки сессии; успех → `setCsrfToken`, серверный actor в памяти, пустой «Поиск», пароль удалён (хранится только в DOM-`useRef`). Саморегистрации/сброса пароля нет; `actor_id` в запросы не добавляется. Для browser-проверок добавлен mock-mode build (`frontend/.env.browser`, `build:browser`, `test:browser` через него) и документированный mock-only тест-шов `__WISEWAY_TEST_FETCH__` (в real-режиме игнорируется); `defaultAppBaseUrl()` даёт абсолютный same-origin `<origin>/api/v1`. Независимый LEAF reviewer — PASS: `typecheck`/`lint`/`build` exit 0, `npm test` 676 PASS (30 файлов; +26), `npm run test:browser` 5 PASS на `msedge` (anonymous→login, неверный пароль, WORKER/ADMIN, session-unavailable); независимые probes 6/6 подтвердили различение `LOGIN_FAILED`/`UNAUTHENTICATED`/сети, тело ровно из двух ключей, отсутствие storage/cookie/URL-записей, очистку пароля и инертность шва в real-режиме. `contracts/**`, generated, `frontend/src/api/**`, `frontend/src/mocks/**`, `fixtures/**`, root `tests/**`, control plane не изменялись; новых runtime-зависимостей нет. Non-blocking: `markAuthenticated()` без аргумента оставлен для тестов app-config (продовые пути всегда передают серверную сессию); комментарий store про «нечитаемый 401» неточен (transport синтезирует `UNAUTHENTICATED`); mock-only шов был бы доступен при mock-деплое; mock-код в production bundle (унаследовано WP-08). M/A/E NOT_RUN; реальные cookie/CSRF/Origin — LT-25.1 (BLOCKED, backend отсутствует).

LT-09.2 completion: добавлены `frontend/src/features/auth/{auth-lifecycle.ts,logout.ts,use-logout.ts,logout-control.tsx}`; `auth-gate`/`use-session-bootstrap`/`AppShell` получили реактивный выход и `headerActions`. Logout: `POST /auth/logout` пустым телом, CSRF через транспорт, без `Idempotency-Key`; на 204 — `clearSession()` (CSRF/idempotency/polls) + `markAnonymous()` + `resetPrivateState()` + вход без перезагрузки. `401 UNAUTHENTICATED` из любого вызова: транспорт очищает session-scope, `onUnauthorized` добавляет `resetPrivateState()`, гейт реактивно показывает вход; `LOGIN_FAILED` не затрагивается. Неизвестный исход logout → `GET /session`: активная сессия сохраняется с русским «Повторить выход», 401 → выход, иначе успех не заявляется; `logout`/`403` не auto-retry. UI не отменяет принятые партии и не подменяет автора. Независимый LEAF reviewer — PASS: `typecheck`/`lint`/`build` exit 0, `npm test` 690 PASS (33 файла; +14), `npm run test:browser` 7 PASS на `msedge` (logout→вход, reload→вход без storage/cookie), `generate:api:check` без diff; probes 5/5 подтвердили отсутствие placeholder-CSRF, одну попытку logout при сбое, реактивный переход без reload, очистку probe-reset при 401 и поздний ответ без восстановления. `contracts/**`, generated, `frontend/src/api/**`, `frontend/src/mocks/**`, `fixtures/**`, root `tests/**`, control plane и зависимости не изменялись. Non-blocking: латентная гонка `checking`→`completeLogout` недостижима в текущем UI (защитное замечание); идемпотентный повтор `clearSession()` на пути logout→401; browser-тест не отличает реактивный переход от reload (jsdom-тест отличает); 403 показывает общее сообщение; `GET /session` при сверке не обновляет CSRF/actor. M/A/E NOT_RUN; реальные cookie/CSRF/Origin/expiry — LT-25.1 (BLOCKED).

WP-09 package completion: commits `d23bd4c` (LT-09.1), `6dc4f61` (LT-09.2); полный WORK_PACKAGE review диапазона `537a353..6dc4f61` — PASS. Reviewer фактически: `npm ci` exit 0 (lock hash `930cb624…4533` неизменён), `typecheck`/`lint`/`build` exit 0, `npm test` 690 PASS (33 файла), `npm run test:browser` 7 PASS на `msedge`, `generate:api:check` без diff, `git diff --check` PASS; независимые probes 4/4 (сквозной bootstrap→login(worker)→logout→login(admin) со сбросом probe-состояния; `LOGIN_FAILED` при активной сессии не трогает session/CSRF/actor; `403 CSRF_FAILED` на bootstrap → `unavailable`, не anonymous; тело logout — ровно один `POST /auth/logout`, пустое тело, актуальный CSRF, без `Idempotency-Key`). Статические проверки: нет `console.*`, storage/cookie/URL-записей, `actor_id` в запросах, саморегистрации/сброса пароля. AC WP-09 (login/session/logout без саморегистрации; очистка приватного контекста и polls; принятая партия не отменяется и сохраняет автора; секреты не сохраняются; `LOGIN_FAILED`/`UNAUTHENTICATED`/недоступность различаются; actor/role только с сервера) — выполнены на доступном mock-уровне. Non-blocking: `markAuthenticated()` без аргумента (только тесты); mock/шов в production bundle (унаследовано); `expires_at` без проактивного таймера (реактивный 401 по контракту); сообщения не-`LOGIN_FAILED` берутся из безопасного `error.message`; browser-тест logout не отличает реактивность от reload; 2 moderate advisory (pre-existing). M/A/E NOT_RUN; реальные cookie/CSRF/Origin/hash/expiry и серверная судьба принятой партии — LT-25.1 (BLOCKED, backend отсутствует) и backend.

E-03 final completion: финальный независимый EXECUTION_UNIT review продуктового состояния диапазона `9daad51..06b097c` (HEAD на момент review) — PASS. Reviewer фактически: `npm ci` exit 0 (lock неизменён), `typecheck`/`lint`/`build` exit 0, `npm test` 690 PASS (33 файла), `npm run test:browser` 7 PASS на `msedge`, `generate:api:check` без diff, `git diff --check` PASS; диапазон — 47 файлов (46 `frontend/**` + progress backlog), forbidden paths/control plane не тронуты. Независимый probe 6/6: сквозной bootstrap→login(worker)→app-config `ready`→logout→login(admin); неверный пароль при активной сессии сохраняет CSRF/actor; `401 UNAUTHENTICATED` очищает приватное состояние; ровно пять разделов с default `search` и русскими подписями; `formatSize` 9/9 и `formatDateTime` 3/3 совпали с `fixtures/synthetic/search_expectations.json` → `format_samples`; цикл не пишет в storage/history/cookie/URL. WP-08 (commits `e847581`, `3d80472`, `537a353`) и WP-09 (`d23bd4c`, `6dc4f61`) VERIFIED; все четыре leaf LT-08.1/08.2/09.1/09.2 VERIFIED. Итог E-03 — **S/V-S** (generated-артефакты воспроизводимы) и **M/V-C + V-M** (unit/component 690, real-browser mock 7); **A (real API) и E (E2E) NOT_RUN** и не заявляются: реальные HttpOnly/SameSite/Secure cookie, серверные CSRF/Origin, хеширование пароля, expiry/block и серверная судьба принятой партии — LT-25.1 (BLOCKED, backend отсутствует) и backend. Non-blocking (final review): README неточен в деталях (имя `app-config-context`, состав `App.tsx`, завышенное описание browser-покрытия keyboard/`page.route` — клавиатура и анонимный гейтинг покрыты jsdom-тестами, browser-набор использует мышь); `formatSize(999999) → 1000 KB` без промоушена; mock-код в production bundle; mock-only шов `__WISEWAY_TEST_FETCH__`; `markAuthenticated()` без аргумента только в тестах; `expires_at` без проактивного таймера (реактивный 401 по контракту); сообщения не-`LOGIN_FAILED` из безопасного `error.message`; латентная `checking`-гонка недостижима; идемпотентный повтор `clearSession()` на пути logout→401. Публикация всей ветки (`feat/e-03` впереди `origin/main` на 6 локальных commits, push не выполнялся) — за пользователем (D-09). Следующий Execution Unit — E-04 (WP-10) или отдельный WP по решению человека.

### E-03 human-validation visual repair (LT-E03-VR1)

- **Status:** VERIFIED. **Parent:** E-03 (повторная человеческая проверка UI). **Dependencies:** WP-08, WP-09; D-07; human feedback 12.09.2026.
- **Goal:** системный visual/UI repair входа и оболочки без изменения функционального scope E-03. Текущий shell/login воспринимаются как технический прототип; нужна единая сдержанная современная admin-система.
- **Sources of truth:** human feedback 12.09.2026; D-07; FE §4 navigation; TZ §4; G-2; NFR-01; фактическое состояние `frontend/src/app/**` и `frontend/src/features/auth/**`.
- **Scope:** небольшой reusable visual foundation (typography, colors/tokens, spacing, surface/background, borders/radius, buttons, inputs, navigation/tabs, status/error/info, focus/hover/active states) + применение его к login и application shell. Без API/generated/mocks/contracts/backend/control-plane, без новых runtime-зависимостей/внешнего design framework, без будущих функций E-04+ и без изменения auth/session/app-config семантики.
- **Acceptance criteria:** login центрирован относительно viewport и в той же системе; текст «Введите логин и пароль.»; сохранены auth/error/focus/keyboard semantics; shell даёт ясную иерархию header/navigation/content, современную явно интерактивную навигацию, читаемый active tab (не только цветом), единые header/buttons/user-role/content surface; placeholder/empty content — намеренно спроектированное состояние, а не незавершённый HTML; весь product-facing UI на русском; accessibility/keyboard/focus не ухудшены; существующие tests не ослаблены.
- **Verification expectations:** V-C (typecheck/lint/unit/build), V-M (browser smoke + центрирование входа), `generate:api:check` без diff, `git diff --check`.

Статус E-03 остаётся READY_FOR_HUMAN_REVIEW: repair не меняет функциональный scope и не закрывает человеческую приёмку. LT-E03-VR1 становится VERIFIED после реализации, независимого reviewer PASS, фактической verification и локального checkpoint commit (push — за пользователем, D-09).

LT-E03-VR1 completion: добавлен `frontend/src/styles/foundation.css` (дизайн-токены `--ww-*`, базовый reset, общие примитивы: buttons/inputs/surfaces/badges/alerts/status/nav-tabs/empty) и применён к `AppShell`/`shell.css`, login/session, logout-control и app-config без изменения их ролей/текстов/логики. Login центрирован относительно viewport 1280×720, интро-текст заменён на «Введите логин и пароль.»; shell получил header-card, современные вкладки с читаемым active (фон+рамка+accent-индикатор+bold, `aria-current` сохранён), рабочую поверхность на всю высоту и намеренно спроектированное пустое состояние без цифр. Первый независимый LEAF review — PASS (non-blocking: контраст границы input 1.8:1); repair cycle 1 (same-leaf) заменил `--ww-color-border-strong` `#b7c1cb` → `#8b95a1` (независимо пересчитанный контраст к white 3.04:1, ≥ WCAG 2.1 SC 1.4.11) и добавил non-vacuous contrast guard; свежий полный re-review — PASS (три mutation probe подтвердили невакуозность центрирования/копии/контраста, файлы восстановлены байт-в-байт). Orchestrator фактически: `npm run typecheck`/`npm run lint` exit 0, `npm test` 699 PASS (34 файла; +9 к 690), `npm run build` exit 0, `npm run test:browser` 8 PASS на `msedge` (+1 центрирование), `npm run generate:api:check` без diff, `git diff --check` PASS. `contracts/**`, `frontend/src/api/**` (включая generated), `frontend/src/mocks/**`, `fixtures/**`, root `tests/**`, backend, control plane и зависимости не изменялись. Non-blocking: `--ww-color-border-strong` к `--ww-color-surface-muted` даёт 2.88:1 (затрагивает border бейджа и декоративный индикатор, не control boundary); неиспользуемые `--ww-shadow-md`/success-токены; отсутствует `prefers-reduced-motion`; pre-existing mock-код в production bundle. Оценка «спокойный современный enterprise» — качественная, на основе токенов/скриншотов, не формальный design-spec; browser-доказательства mock-класса. Публикация — за пользователем (D-09).

## EPIC E-04 — Иерархический поиск и контекст отклонений

Status: TODO. Scope: FE-03; SRCH-01…25; NFR-01/03/04/06. UI не вычисляет поисковую семантику и не реализует индексатор; real-доказательства в WP-25/30.

### WP-10 — Корень и применение поискового текста

- **Status:** TODO. **Parent:** E-04. **Dependencies:** WP-09, LT-06.2.
- **Goal:** пользователь задаёт допустимый поиск в одном опубликованном корне.
- **Sources of truth:** SRCH-01/03/07…11/18; API §4 SearchRequest/IDLE; FE §4 поиск; Q-004/005/007…010.
- **Acceptance criteria:** без корня нет поиска; root-only IDLE; введённый/применённый текст разделены; quotes/triggers/dedup/reset точны, без fuzzy/ослабления условий.
- **Verification expectations:** V-C/V-M запросов, triggers, clear/reset и памяти; полная таблица подключается WP-12.
- **Leaf tasks:** LT-10.1, LT-10.2. Scope: `frontend/src/features/search/`, frontend tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-10.1 | TODO | WP-09, LT-06.2 | Выбор одного корня и IDLE | SRCH-01/03/10/11/18; OAS listRoots/searchFiles/SearchResponse; API §3/4; Q-004/005 | Только опубликованные roots; без root disabled с причиной, root-only search возвращает IDLE/первый facet/пустую таблицу/total=null; root switch очищает оба текста/markers/results/sort/open lists; full reset снимает root; память только вкладки | V-C/V-M без корня, empty roots, root-only, switch/reset; network не получает запрос всех файлов или глобальный поиск |
| LT-10.2 | TODO | LT-10.1 | Точные текстовые triggers | SRCH-07…11; API §4 request_state_id/query_text; FE §4 ввод; Q-007…010 | Пробел завершённого слова, Enter/«Найти» применяют текст; незакрытая кавычка не отправляется, focus и «Закройте кавычку»; max_query_length; отдельные draft/applied text и dedup key; новый ID каждой разрешённой отправки; clear сохраняет root/markers; новый текст сбрасывает manual sort | V-C/V-M пробел внутри цитаты, повтор условий, закрытие цитаты, empty/length limits; слова/фразы передаются серверу без клиентского matcher/нормализации смысла |

### WP-11 — Последовательные уровни и альтернативы

- **Status:** TODO. **Parent:** E-04. **Dependencies:** WP-10.
- **Goal:** динамический каскад серверных уровней, включая редактирование родителей.
- **Sources of truth:** SRCH-02…06/10/19/20/25; API §4 searchFiles/getSearchFacet; FE §4 маркеры; Q-005/006/012.
- **Acceptance criteria:** одно raw-значение на уровень, произвольная глубина схемы, точные counts и порядок сервера; отдельный список не меняет выдачу до выбора; G-4.
- **Verification expectations:** V-C/V-M вариантов глубины, prefix, независимых запросов dropdown/table.
- **Leaf tasks:** LT-11.1, LT-11.2. Scope: search/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-11.1 | TODO | WP-10 | Динамический последовательный каскад | SRCH-02/04/05/06/10/19/20; OAS Marker/Facet/SearchResponse; Q-005/006/012 | Выбранные уровни над таблицей, только следующий доступный; цепочка непрерывна, можно остановиться на любом уровне; raw-case не объединяется; text AND markers; серверные nonzero counts/order; смена родителя очищает потомков/manual sort, сохраняет текст; UNRECOGNIZED последний и terminal, без hardcoded глубины | V-C/V-M Atlas/Nova/optional tail, raw-case/zero options/terminal; UI не пересортировывает серверные значения |
| LT-11.2 | TODO | LT-11.1 | Переоткрытие уровня и prefix | SRCH-06/17/25; API §4 getSearchFacet/FacetRequest/FacetResponse; FE §4 «Не распознано»; Q-005/006/012 | Запрос только с родителями редактируемого уровня и applied text; prefix серверный, включая «Не распознано»; показан контекст counts; только выбор применяет цепочку; отдельный last request ID, late dropdown не меняет table/total/sort/freshness; пустой список возможен при непустой таблице | V-C/V-M keyboard/filter/reopen, задержки двух списков, изменение root; отдельные scope не смешиваются |

### WP-12 — Выдача, порядок и контекст отклонений

- **Status:** TODO. **Parent:** E-04. **Dependencies:** WP-11, LT-08.2.
- **Goal:** прочитать файл/ветку, копировать путь, увидеть структурную причину.
- **Sources of truth:** SRCH-12…16/19…22; API §4 SearchItem/SearchSort/StructureIssue; FE §4 выдача; Q-006/012/013/042.
- **Acceptance criteria:** только файлы, полные поля/пути, точный total/N/limited; нет search pagination; ручной sort отправляется серверу; quality view контекстный, не очередь исправления.
- **Verification expectations:** V-C/V-M long paths/format/clipboard/sort/zero/limit/quality; G-2/4.
- **Leaf tasks:** LT-12.1, LT-12.2, LT-12.3. Scope: search/shared formatting/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-12.1 | TODO | WP-11, LT-08.2 | Таблица и копирование display path | SRCH-12/14/15/16; OAS SearchItem/SearchResponse; Q-013/042 | Имя/полный путь/markers/extension/bytes→size/modified/structure; одна строка пути без ellipsis с горизонтальной прокруткой; копируется только display_path с кратким подтверждением, без открытия файла; точный total/первые N/limited с просьбой уточнить; zero сохраняет условия/clear/reset; без страниц/infinite scroll/автодогрузки | V-C/V-M N=10/100 и >N, 0 bytes/no extension/длинные пути, clipboard success/failure без ложного подтверждения; нет download/open/export network calls |
| LT-12.2 | TODO | LT-12.1 | Серверная сортировка выдачи | SRCH-10/13; API §4 SearchSort/ранжирование; SEM поиск; Q-005/006/011 | Text → RELEVANCE DESC, markers-only → PATH ASC; первый NAME ASC, MODIFIED_AT/SIZE DESC, повтор переключает primary; reset при новом тексте/marker/root; natural/raw path/ID tie-break остаётся серверным; score не вычисляется UI | V-C/V-M request bodies/default/direction/reset; порядок строк ровно ответ API, без локальной пересортировки |
| LT-12.3 | TODO | LT-12.1 | Контекст «Не распознано» | SRCH-19/20/21; OAS SearchItem/StructureIssue; API §4; FE §4 quality view; Q-012 | Контекст через unrecognized: root/name/path/recognized parents/первый проблемный уровень/понятная причина/дата; UNEXPECTED_DEPTH допускает level_id=null; размер/технический код скрыты в quality view, модель не теряет их; нет глобальной страницы/закрытия/экспорта; исправленный сервером файл исчезает после обновления | V-C/V-M четыре StructureIssue.code, глубина/nullable level, новый response без отклонения; нет клиентского parser/исправления пути |

### WP-13 — Свежесть и устойчивость поискового состояния

- **Status:** TODO. **Parent:** E-04. **Dependencies:** WP-12.
- **Goal:** ошибки/гонки/обновление схемы не делают выдачу ложной.
- **Sources of truth:** SRCH-17/18/23…25; API §4/11; SEM поиск; FE §4 freshness; Q-003/005/010/011/042.
- **Acceptance criteria:** таблица/total/next facet атомарны по response; last-send победитель; прежняя выдача при ошибке помечена stale со временем/старыми условиями; Retry и context errors понятны.
- **Verification expectations:** V-C/V-M контролируемых задержек/ошибок и памяти; real generation/freshness отдельно WP-25.
- **Leaf tasks:** LT-13.1, LT-13.2. Scope: search/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-13.1 | TODO | WP-12 | Атомарная актуальность и stale/retry | SRCH-17/25; OAS SearchResponse/SearchFreshness; API §4 request scopes; Q-003/005/010/011 | Items/total/next facet одного ответа применяются вместе; поздний table response игнорируется; CURRENT/UPDATING/STALE отображаются без блокировки завершённого поколения; ошибка сохраняет предыдущий успех со временем и явной связью с прежними условиями; без него error panel; Retry текущих условий обходит dedup и получает новый ID | V-C/V-M A→B с ответами B→A, ошибка после успеха/без успеха, explicit Retry; ошибка не превращается в zero |
| LT-13.2 | TODO | LT-13.1, LT-09.2 | Смена схемы/корня и память поиска | API §4/11 SCHEMA_VERSION_CHANGED/ROOT_NOT_READY/INVALID_MARKER_SELECTION; SEM поиск; SRCH-18/19; Q-005/042 | Перечитываются roots/значения, несовместимые markers очищаются с уведомлением; текст можно сохранить для того же root; снятый root не выдаётся за доступный; навигация сохраняет search только в памяти и сама не ищет; reload/logout/user switch очищают, старые responses не возвращают данные | V-C/V-M три context errors, уход/возврат раздела без search call, reload/storage/network и session reset |

## EPIC E-05 — Справочники компании

Status: TODO. Scope: FE-04; DICT-01…12, FILE-08, NFR-01/05. Никакого выбора правил, конфликтов или итоговых целей вместо backend.

### WP-14 — Список и создание справочников

- **Status:** TODO. **Parent:** E-05. **Dependencies:** WP-09, LT-07.1.
- **Goal:** выбрать компанию, увидеть её независимые справочники, создать пустой общий draft.
- **Sources of truth:** DICT-01/02; API §3/6; OAS listCompanies/listDictionaries/createDictionary/getDictionary; Q-003/015/016.
- **Acceptance criteria:** стабильные IDs/active version/draft/history metadata; company-scoped список; создание с уникальным именем, без silent retry/ложного успеха; нет delete/deactivate endpoint.
- **Verification expectations:** V-C/V-M loading/empty/error/conflict/lost-response; G-2/3/5.
- **Leaf tasks:** LT-14.1, LT-14.2. Scope: `frontend/src/features/dictionaries/`, tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-14.1 | TODO | WP-09, LT-07.1 | Компания и список справочников | DICT-01/02; API §3/6 Dictionary; OAS listCompanies/listDictionaries/getDictionary; Q-015/016 | Несколько справочников одной компании, draft revision/active version/updated actor/time; общий рабочий доступ, не exclusive editor; при смене компании старые responses не подставляются; правила не управляют поисковыми маркерами | V-C/V-M две компании, empty/failed lists, nullable active_version, navigation |
| LT-14.2 | TODO | LT-14.1, LT-05.2 | Создать справочник без дубликата при сбое | DICT-01; OAS createDictionary/CreateDictionaryRequest; API §2 retry/§6; Q-003/016 | Name 1–128, description 0–1000; DICTIONARY_NAME_CONFLICT понятен, trim+casefold уникальность решает сервер; успех — returned Dictionary с revision=0; lost response → перечитать список по уникальному имени, не auto POST; локальный ввод до сверки сохранён | V-C/V-M boundary/409/lost response, отсутствие фиктивного Idempotency-Key/повторной записи |

### WP-15 — Таблица правил и безопасное сохранение draft

- **Status:** TODO. **Parent:** E-05. **Dependencies:** WP-14, LT-08.2.
- **Goal:** редактировать типизированные правила и цель, не перезаписав коллегу.
- **Sources of truth:** DICT-03…08; API §5/6; OAS Rule/TargetReference/DictionaryDraft/replaceDictionaryDraft; Q-003/015/016/044.
- **Acceptance criteria:** resolver/list целей, fixed stem/простая маска, атомарное сохранение с expected revision; conflicts/lost response сохраняют локальный текст; нет auto-merge/создания каталогов.
- **Verification expectations:** V-C/V-M typed round-trip и конкуренции; серверные matcher/FS проверки WP-26/28.
- **Leaf tasks:** LT-15.1, LT-15.2, LT-15.3. Scope: dictionaries/target picker/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-15.1 | TODO | WP-14 | Выбор и ручной resolver цели | DICT-07/FILE-08; API §5; OAS listTargetDirectories/resolveTargetDirectory/TargetDirectory; Q-015/044 | Выбор существующего каталога из разрешённого списка с cursor; ручной полный synthetic display_path через resolver; Rule получает root_id+relative_directory, не display_path как полномочие; INVALID_TARGET/PATH_OUTSIDE_ROOT/validation не обходятся; ни произвольного FS, ни mkdir | V-C/V-M valid/manual/invalid/cursor/late response; prefix/логические значения в запросах |
| LT-15.2 | TODO | LT-15.1 | Typed rule editor | DICT-03…06; API §6 Rule; SEM fixed stem/extension; OAS Rule; Q-015 | Add/edit/remove rule в локальном draft, уникальные rule_id, priority 1–1000, BASENAME/RELATIVE_PATH, mask 1–512 без `**`, target, target_stem 1–200; whole-field `*`/`?`/slash и fixed stem объяснены, без regex/OR/DSL; показан явно иллюстративный пример имени с исходным последним суффиксом, точки основы не обрезаются; реальные планы — только серверные | V-C/V-M typed round-trip/boundaries/пустой rules; примеры README/name./archive.tar.gz/скрытый dotfile/регистр suffix, без локального matcher/проверки занятости |
| LT-15.3 | TODO | LT-15.2, LT-05.2 | Revision-aware save и reconciliation | DICT-08; OAS replaceDictionaryDraft/ReplaceDictionaryDraftRequest; API §2/6; Q-003/016 | Имя/описание/полный rules + expected_draft_revision одним PUT; DRAFT_VERSION_CONFLICT предлагает перечитать, сохраняя локальный текст для сравнения; нет auto-merge/overwrite; name conflict/field errors отображены; lost response → GET Dictionary/revision, не auto PUT; cleanup по session | V-C/V-M два drafts одной ревизии, conflict/500/timeout-after-save, отсутствие ложного «сохранено»/потери ввода |

### WP-16 — Тест draft и публикация

- **Status:** TODO. **Parent:** E-05. **Dependencies:** WP-15.
- **Goal:** безопасный цикл server simulation → осознанная публикация.
- **Sources of truth:** DICT-02/09/10/12; API §6 PlanRow/Simulation/publish; OAS createDictionarySimulation/getSimulation/publishDictionary; Q-017…020/029.
- **Acceptance criteria:** тест всех READY независимо от фильтров, полный RuleSet; total/counts не из страницы; conflicts блокируют, NO_SCENARIO подтверждается по simulation_id, EMPTY_READY_SET warning; stale не публикуется, комментарий обязателен.
- **Verification expectations:** V-C/V-M paging/empty/stale/ack/conflict/lost publish response; реальные правила WP-26.
- **Leaf tasks:** LT-16.1, LT-16.2, LT-16.3. Scope: dictionaries/shared plan presentation/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-16.1 | TODO | WP-15 | Читаемый server plan | API §6 PlanRow/PlanCounts/RuleReference/FileMetadata; OAS Simulation/PlanRow; DICT-09; Q-017/018 | Таблица показывает source name/path/company, references с version_id=null для draft, target/prediction/reason; null не выдумывает цель; server totals и четыре основных counts отдельно от rule_conflicts/no_scenario; next_cursor не меняет totals; явно прогноз, не выполненная операция | V-C/V-M всех Prediction/null/page/error состояний на fixtures; без пересчёта правил/счётчиков |
| LT-16.2 | TODO | LT-16.1, LT-15.3 | Запуск/чтение simulation и свежесть | DICT-09/10/12; OAS createDictionarySimulation/getSimulation/Simulation; API §6; Q-017/018 | Отправляется saved expected revision, не UI filter/selection; показан полный base RuleSet/READY scope/TTL; все READY, EMPTY_READY_SET предупреждает об отсутствии доказанного покрытия; изменение draft/зависимостей или STALE_SIMULATION требует явного нового теста; потерянный simulation ID не auto retry | V-C/V-M zero READY/невидимые rows/revision/expiry/lost response; никакой файловой mutation |
| LT-16.3 | TODO | LT-16.2, LT-05.2 | Публикация конкретного свежего теста | DICT-10/11/12; OAS publishDictionary/PublishDictionaryRequest; API §2/6; Q-018…020/029 | Rule conflicts блокируют; NO_SCENARIO требует явный ack именно simulation_id, смена теста его снимает; comment 1–500; occupied targets сами не блокируют; пустые rules публикуются через те же проверки; stale/revision/ack errors не обходятся; idempotent retry старого тела/ключа, success обновляет dictionary/version/RuleSet без запуска сортировки | V-C/V-M 0/1/500/501 comment, conflict/ack/stale/empty/occupied, потеря publish response; сохранённый batch не перепланируется |

### WP-17 — История и откат версии справочника

- **Status:** TODO. **Parent:** E-05. **Dependencies:** WP-16.
- **Goal:** читать неизменяемую историю и восстановить старую версию новым циклом публикации.
- **Sources of truth:** DICT-01/11/12; API §6 versions/restore; OAS listDictionaryVersions/getDictionaryVersion/restoreDictionaryDraft; Q-020/021.
- **Acceptance criteria:** версии с actor/time/comment/provenance read-only; restore меняет draft, требует нового теста/публикации, не возвращает файлы.
- **Verification expectations:** V-C/V-M history paging/restore/conflict/lost response/manual edit provenance; реальные гарантии WP-26.
- **Leaf tasks:** LT-17.1, LT-17.2. Scope: dictionaries/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-17.1 | TODO | WP-16 | Неизменяемые версии | DICT-01/11; OAS listDictionaryVersions/getDictionaryVersion/DictionaryVersion; Q-020 | Cursor history, номер/ID/author/time/comment/restored_from_version_id/правила; active version отличима от draft; нет редактирования исторической записи; 404/empty/error понятны | V-C/V-M multiple versions/paging/null provenance, после правки draft прежняя версия отображается неизменной |
| LT-17.2 | TODO | LT-17.1, LT-15.3, LT-16.3 | Restore → новый test → новая publish | DICT-11/12; API §2/6; OAS restoreDictionaryDraft; Q-003/021 | version_id+expected revision, нет direct activation; conflict/lost response сохраняют local input и перечитывают объект без auto POST; только новый simulation/publish создаёт версию с provenance; ручная правка снимает based_on_version_id по серверному ответу; без файлового undo | V-C/V-M restore/редактирование/конфликт/потеря ответа; history/accepted batch неизменны |

## EPIC E-06 — Очередь, снимки, ручные партии

Status: TODO. Scope: FE-04; QUEUE-01…10, FILE-01…09 UI projection, NFR-07. Физическую безопасность реализует backend и доказывает real-контур, не этот UI epic.

### WP-18 — Чтение очереди одной компании

- **Status:** TODO. **Parent:** E-06. **Dependencies:** WP-09, LT-07.2, LT-08.2.
- **Goal:** видеть входящие файлы, серверные состояния и счётчики компании.
- **Sources of truth:** QUEUE-01/02/10; API §7 QueueResponse/QueueFilters; OAS querySortingQueue; Q-022.
- **Acceptance criteria:** без компании нет общей очереди; counts из одного server generation; один фильтр статуса, отдельная очередь pagination; G-2/4.
- **Verification expectations:** V-C/V-M counters/statuses/paging/context races, без client-readiness.
- **Leaf tasks:** LT-18.1, LT-18.2. Scope: `frontend/src/features/sorting/`, tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-18.1 | TODO | WP-09, LT-07.2, LT-08.2 | Компания, очередь и counts | QUEUE-01/02; OAS listCompanies/querySortingQueue/QueueResponse/QueueItem; API §7; Q-022 | Company required; source_name вместо физических путей, metadata/status/reason/selectable; ready/processing/attention/status_counts серверные по всей компании, matching/eligible по фильтру; DISCOVERED/WAITING_READY не READY, RECOVERY не обычный retry; generation согласован | V-C/V-M все QueueState/counters/empty/error, server selectable; браузер не решает готовность файла |
| LT-18.2 | TODO | LT-18.1 | Фильтр и cursor очереди | QUEUE-02/10; OAS QueueFilters/QueueQueryRequest; API §7; Q-022/024/025 | Один подробный статус в UI (передаётся массивом по OAS), default active без MISSING, MISSING явный; query_text — подстрока, не search grammar; cursor pages ≤100, смена фильтра начинает новый query context; company switch очищает selection/preview и stale responses, не отменяет batch | V-C/V-M filter/query/paging/late responses, totals не из страницы, cleanup hooks для WP-19/20 |

### WP-19 — Серверный снимок выбора

- **Status:** TODO. **Parent:** E-06. **Dependencies:** WP-18.
- **Goal:** закрепить один/несколько/все подходящие файлы в server snapshot.
- **Sources of truth:** QUEUE-03/09/10; API §7 SelectionRequest/SelectionSnapshot; OAS createSortingSelection; Q-023…026.
- **Acceptance criteria:** EXPLICIT IDs/revisions, ALL_MATCHING все страницы с expected count; immutable server selection и TTL, без silent truncation/пересборки по новому фильтру.
- **Verification expectations:** V-C/V-M zero/limit/120 items/changed/late arrivals; real membership WP-27.
- **Leaf tasks:** LT-19.1, LT-19.2. Scope: sorting selection/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-19.1 | TODO | WP-18 | EXPLICIT snapshot | QUEUE-03; OAS ExplicitSelectionRequest/SelectionSnapshot; API §7; Q-023 | Выбор одного/нескольких только selectable; точные уникальные IDs/item_revision одной компании, лимит из config; server selected_count/selection_id/expiry отображаются; пустое/over limit не усекается; lost response требует нового явного snapshot, не auto mutation | V-C/V-M одного/нескольких/disabled/stale revision/EMPTY_SELECTION/BATCH_LIMIT_EXCEEDED; очистка по company/session |
| LT-19.2 | TODO | LT-19.1 | ALL_MATCHING, не текущая страница | QUEUE-03/10; OAS AllMatchingSelectionRequest; API §7; Q-024/025/026 | Отправляются filters+expected_eligible_count, не IDs загруженной страницы; server 120 при видимых ≤100 сохраняется; SELECTION_CHANGED требует refresh/явного выбора; поздние поступления и новый UI filter не меняют созданный snapshot; expired требует новый выбор; лимит 1000 не обходится | V-C/V-M 0/120/1001, count change до создания, arrival/filter после, TTL/owner 403; не вычислять membership |

### WP-20 — Необязательный preview и коллизии

- **Status:** TODO. **Parent:** E-06. **Dependencies:** WP-19, LT-16.1.
- **Goal:** видеть прогноз серверного плана и сравнить занятое назначение без перемещения.
- **Sources of truth:** QUEUE-04…06/10, FILE-02/03/05; API §6/7; OAS createSortingPreview/getSortingPreview/Preview/CollisionDetails; Q-023/026/031/032/035.
- **Acceptance criteria:** preview привязан к selection/RuleSet/TTL; полные per-file predictions/reasons, metadata comparison; stale только через явный пересчёт; отсутствие preview не запрещает DIRECT.
- **Verification expectations:** V-C/V-M plan/paging/collision/expiry/lost response, отсутствие run при просмотре.
- **Leaf tasks:** LT-20.1, LT-20.2. Scope: sorting/plan presentation/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-20.1 | TODO | WP-19, LT-16.1 | «Проверить» и сравнение коллизии | QUEUE-04/05; API §6/7 Preview/CollisionDetails; OAS createSortingPreview/getSortingPreview; Q-023/031/032/035 | По selection_id создаётся server preview; source/company/dictionary/version/rule/target/prediction/reason, full RuleSet, totals/cursor; comparison source/existing metadata только по collision; DUPLICATE_PLAN_TARGET с conflicting IDs и nullable existing; MANUAL_REVIEW_NAME отличим; нет выбора одного справочника/замены/движения | V-C/V-M все collision kinds/null/paging, predictions не outcomes; network без batch POST |
| LT-20.2 | TODO | LT-20.1 | Stale preview и явный пересчёт | QUEUE-06/10, DICT-12; API §7/8/11; OAS Preview/expires_at/PreviewConflict/BatchConflict; Q-026/027 | Показывается expiry, чтение не продлевает selection; изменённый источник/правила/цель/TTL → stale, старый PREVIEWED не обходится; SELECTION_EXPIRED/CHANGED требуют обновить выбор; lost preview ID → явный новый расчёт; company/session очищают preview; DIRECT остаётся отдельным явным режимом, не авто-fallback от stale | V-C/V-M controlled clocks/409/публикация новой версии/смена компании; server error решающий даже до client timer |

### WP-21 — Ручной запуск и независимый результат партии

- **Status:** TODO. **Parent:** E-06. **Dependencies:** WP-20, LT-05.2.
- **Goal:** принять запуск один раз, наблюдать progress/outcomes и найти его после reload.
- **Sources of truth:** QUEUE-04/07…10, AUTH-03, FILE-01…09, NFR-07; API §8; OAS batch operations; Q-027…040.
- **Acceptance criteria:** DIRECT/PREVIEWED только кнопкой, 202 ≠ завершение; idempotent retry без двойного запуска, server progress/все outcomes, polling/backoff, history; нет cancel/replace/undo/автоматического повтора файла.
- **Verification expectations:** V-C/V-M lifecycle/lost response/partial/recovery/reload; физический результат и concurrency только WP-28.
- **Leaf tasks:** LT-21.1, LT-21.2, LT-21.3, LT-21.4. Scope: sorting batch/transport consumers/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-21.1 | TODO | WP-20, LT-05.2 | Явный DIRECT/PREVIEWED submit | QUEUE-04/06/09; OAS createSortingBatch/BatchCreateRequest; API §2/8; Q-027/029 | DIRECT без preview_id, PREVIEWED с текущим preview; только «Рассортировать», без selector RuleSet; 202 показывает batch ID/actor/time/принятие; повтор неопределённого ответа с исходным ключом/телом, double click не новый batch; новые условия/ручная попытка — новый ключ; 409/403/404 до принятия не ложный успех | V-C/V-M double submit/lost 202/expiry/changed source/IDEMPOTENCY_KEY_REUSED; нет auto DIRECT fallback |
| LT-21.2 | TODO | LT-21.1 | Все фактические исходы файла | FILE-01…09, QUEUE-07/10; OAS Batch/Outcome/OutcomeCounts; API §8 матрица; Q-028/031…039 | PENDING/PROCESSING/SORTED/MANUAL_REVIEW/REQUIRES_DECISION/QUARANTINED/SKIPPED/RECOVERY_REQUIRED и все OutcomeReasonCode различимы по-русски; source/planned/actual не смешаны, unknown actual=null; counts серверные, recovery не завершён; одинаковая цель не даёт UI-победителя; нет replace/undo/cancel/manual-review workflow/слепого retry | V-C/V-M всех state/reason сочетаний, mixed outcomes, nullable location/rule/time; per-file issue при HTTP 200 не общая ошибка партии |
| LT-21.3 | TODO | LT-21.2 | Polling прогресса без зависания UI | QUEUE-08/10, NFR-07; OAS getSortingBatch/BatchState; API §8, TZ §12; Q-030/039 | Интервал из config (demo 1с), без одинаковых параллельных polls, backoff/Retry-After; counts/selected/completed с сервера, cursor outcomes не полный результат; error не стирает batch; terminal отличим от RECOVERY_REQUIRED с finished_at=null; polls прекращаются при session cleanup, old responses игнорируются | V-C/V-M fake timers/slow response/429/503/recovery/terminal/unmount-session cleanup; UI остаётся интерактивным |
| LT-21.4 | TODO | LT-21.3 | История и восстановление просмотра batch | QUEUE-08/10, AUTH-03; OAS listSortingBatches/getSortingBatch/BatchSummary; API §8; Q-030/040 | Общий company-scoped список по created_at DESC/batch_id DESC, cursor; после reload/login найти принятую партию без browser persistence/повторного POST; actor первоначальный, новый viewer не автор; смена компании/selection не отменяет batch | V-C/V-M reload/different user/history pages/company switch; G-5, никаких отмен/новых операций при просмотре |

## EPIC E-07 — Карантин и ручной возврат

Status: TODO. Scope: FE-04; FILE-06/07/09, QUEUE-01, AUD-01/02. Не UI операторского разрешения RECOVERY_REQUIRED.

### WP-22 — Подтверждённый карантин и безопасный возврат

- **Status:** TODO. **Parent:** E-07. **Dependencies:** WP-09, LT-07.3, LT-08.2, LT-05.2.
- **Goal:** увидеть подтверждённую ошибку и явно вернуть файл во входящие.
- **Sources of truth:** FILE-06/07/09; API §9/11; OAS listQuarantineItems/returnQuarantineItem; Q-036…038/029.
- **Acceptance criteria:** только confirmed quarantine, причина/original/current paths/return availability; комментарий/revision/idempotency, success WAITING_READY без сортировки; recovery не ложный успех.
- **Verification expectations:** V-C/V-M всех return outcomes и потерянного ответа; real FS return WP-29.
- **Leaf tasks:** LT-22.1, LT-22.2. Scope: `frontend/src/features/quarantine/`, tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-22.1 | TODO | WP-09, LT-07.3, LT-08.2 | Список подтверждённого карантина | FILE-06/07; API §9 QuarantineItem; OAS listQuarantineItems; Q-036/037 | Компания обязательна, cursor ≤100; filename/current/original location/reason/time/source_attempt_id; can_return=false и recovery_operation_id объясняют недоступность; MANUAL_REVIEW и unknown location не выдаются за quarantine; нет удаления | V-C/V-M empty/error/paging/company races/can_return/recovery; реальные гарантии списка не доказываются mock |
| LT-22.2 | TODO | LT-22.1, LT-05.2 | Возврат с revision/comment/idempotency | FILE-07/09, QUEUE-01; OAS returnQuarantineItem/QuarantineReturnRequest/QuarantineReturnResponse; API §9/11; Q-029/038 | Явное подтверждение, comment 1–500, expected_revision и ключ; успех показывает WAITING_READY/return_operation_id, без batch POST; ORIGINAL_PATH_OCCUPIED/QUARANTINE_VERSION_CONFLICT/NOT_FOUND/INVALID_STATE/RECOVERY_REQUIRED различимы; error.operation_id при RECOVERY_REQUIRED сохранён и can_return перечитан; повтор потерянного ответа с прежним ключом, не второе перемещение | V-C/V-M boundary/revision/occupied/returned/new key/ambiguous/lost response; нет recovery endpoint или auto-sort |

## EPIC E-08 — Общий журнал

Status: TODO. Scope: FE-04; AUD-01…05; NFR-01/05. Запись/неизменяемость audit принадлежат серверу.

### WP-23 — Фильтруемая лента журнала

- **Status:** TODO. **Parent:** E-08. **Dependencies:** WP-09, LT-07.3, LT-08.2.
- **Goal:** читать доступные события по дате/автору/типу/результату/имени/пути.
- **Sources of truth:** AUD-01/02/04/05; API §10; OAS queryAuditEvents/listAuditActors; Q-041/042/043.
- **Acceptance criteria:** текущий день в config timezone → UTC [from,to), WORKER BUSINESS/ADMIN SYSTEM тоже; exact server order/cursor, allowed actors; нет экспорта/infinite scroll.
- **Verification expectations:** V-C/V-M timezone/filters/roles/null/paging, G-2/4/5.
- **Leaf tasks:** LT-23.1, LT-23.2. Scope: `frontend/src/features/audit/`, tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-23.1 | TODO | WP-09, LT-07.3, LT-08.2 | Лента, даты и «Показать ещё» | AUD-04/05; OAS queryAuditEvents/AuditQueryRequest/Response/Event; API §10; Q-041 | Default текущий день display_timezone, UTC [from,to); сохраняется server occurred_at DESC/event_id DESC; cursor≤100 с фиксированной верхней границей, «Показать ещё», без infinite scroll/export; null actor допустим для SYSTEM, не выдумывается пользователь; BUSINESS/SYSTEM определяет server role access | V-C/V-M UTC boundary/day/timezone/empty/null/roles/cursor/no duplicates; late pages не смешиваются с новым query |
| LT-23.2 | TODO | LT-23.1 | Фильтры и допустимые авторы | AUD-04; OAS listAuditActors/queryAuditEvents/AuditAction/AuditResult; API §10; Q-041 | Период/actor/action/result/name-path и company_id в query body; ключ company_id обязателен, null означает отсутствие ограничения; actor prefix/cursor с сервера, включая заблокированных с событиями, не каталог аккаунтов; actor_id фильтра не автор мутации; новый фильтр сбрасывает cursor, условия не URL/storage/log | V-C/V-M всех фильтров/combination, invalid interval/field errors, actor pages/blocked actor, network bodies |

### WP-24 — Новые события и детали связанной операции

- **Status:** TODO. **Parent:** E-08. **Dependencies:** WP-23, LT-21.4, WP-17, WP-22.
- **Goal:** замечать новые события без сдвига ленты и понимать связь с batch/version/return.
- **Sources of truth:** AUD-01…05; API §10/11; OAS getAuditUpdates/AuditEvent и операции чтения batch/version; Q-041.
- **Acceptance criteria:** индикатор новых событий ≤60с, manual refresh сохраняет фильтры; безопасные связи/детали без выдуманных endpoints и BUSINESS-событий чтения.
- **Verification expectations:** V-C/V-M timers/filter refresh/nullable links; real audit attribution WP-29.
- **Leaf tasks:** LT-24.1, LT-24.2. Scope: audit/links to existing features/tests.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-24.1 | TODO | WP-23, LT-05.2 | Индикатор новых событий | AUD-05; OAS getAuditUpdates; API §10; TZ §12; Q-041 | Config polling demo 30с, без параллельных polls, с backoff при ошибках; empty journal → after_event_id отсутствует; событие вне фильтра может дать индикатор; новые записи не вставляются сами; «Есть новые события» перечитывает первую порцию с прежними фильтрами; session cleanup | V-C/V-M empty/nonempty, контролируемые 30/60с, outside filter/new pages/error; сеть не содержит query text в updates URL |
| LT-24.2 | TODO | LT-24.1, LT-21.4, WP-17, WP-22 | Детали события и переходы к существующим данным | AUD-01/02/03; OAS AuditEvent/getSortingBatch/getDictionaryVersion; API §8–11; Q-041 | Детали показывают применимые actor/time/request/company/dictionary/version/RuleSet/batch/attempt/item/source/target/reason/comment; return operation_id/source_attempt_id связаны; nullable links не ведут к выдуманным объектам; batch/version открываются существующими API, отдельного audit-details/attempt/recovery endpoint нет; просмотры/копирование не мутации | V-C/V-M всех AuditAction и nullable links, NOT_FOUND, G-3; никаких BUSINESS-write calls от чтения |

## EPIC E-09 — Реальная интеграция, регрессия и передача MVP

Status: BLOCKED (X-BE-A/B/C, X-LAB). Scope: FE-05; TZ §14, NFR-01…07; PLAN посрезовая интеграция. Эти WP реализуют ограниченные интеграционные проверки/подключение, **не** повторную реализацию экранов и **не** автоматическое «исправить все найденные дефекты». Ошибка API/FS назначается backend, schema contradiction регистрируется, UI defect получает отдельный bounded repair. Тестовые механизмы не добавляются как новые публичные endpoints.

### WP-25 — Вход и поиск на настоящем API

- **Status:** BLOCKED. **Parent:** E-09. **Dependencies:** WP-13, X-BE-A; LT-25.3 дополнительно X-LAB.
- **Goal:** первый real vertical slice без ожидания всего FE-04.
- **Sources of truth:** FE-05 посрезовые зависимости; BE-01/02; API §2–4/11; AUTH/SRCH; Q-001…014/042/043.
- **Acceptance criteria:** транспорт переключается без переписывания UI, auth/search без mock fallback; exact IDs/order/total/facets по независимому корпусу, freshness/metadata updates подтверждены; серверные гарантии не приписаны frontend.
- **Verification expectations:** V-E и V-S ответов, версии/seed/generation/среда; нет промежуточной подписи QA.
- **Leaf tasks:** LT-25.1, LT-25.2, LT-25.3. Scope: frontend transport configuration, `tests/e2e/`, frontend tests/контрактные assertions и handoff; без backend edits.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-25.1 | BLOCKED | WP-09, X-BE-A | Реальный auth/config transport | AUTH-01…05/NFR-05; OAS login/getSession/logout/getAppConfig/listRoots; API §2/3; BE-01; Q-001…003/043 | Настоящие synthetic WORKER/ADMIN; 401/403/CSRF/Origin/no-store/X-Request-ID, HttpOnly/SameSite/Secure по среде; logout/expiry/block/private cleanup; real mode не запускает mock; hash/blocked-user evidence предоставляет BE, без секретов в отчёте | V-E auth/config/roles/network/storage, schema assertions; безопасное серверное evidence AUTH-04/05 отдельно от браузерного PASS |
| LT-25.2 | BLOCKED | LT-25.1, WP-13, LT-03.1, X-BE-A | Exact search flow на сервере | SRCH-01…20/25; API §4 ranking/facets; BE-02; Q-004…013 | Все параметры root/AND/prefix/token delimiters/quotes/trigger/reset/raw-case/depth/zero/limit/sort/races; exact IDs/order/total/facets совпадают с independent golden, включая числовые ranking примеры и tie-break; нет клиентского ослабления запроса | V-E UI→real API + V-S, N=10/100, >N, два корня/варианты глубины; сохраняются generation/ranking_profile_version |
| LT-25.3 | BLOCKED | LT-25.2, X-BE-A, X-LAB | Метаданные, публикация поколения и quality updates | SRCH-21…25, NFR-04/06; API §3/4 freshness; BE-02; Q-011/012/014 | Создание/change/rename/move/delete синтетики отражаются ≤5мин; старые пути/content-only не находятся; любые расширения/no extension/нулевой файл, исключение service dirs; quality исчезает после исправления; во время публикации читается завершённое поколение, items/total/facets едины | V-E с контролируемыми backend-изменениями/поколениями и measured delay; публикация root после обхода проверяется также LT-30.3; без UI удаления/индексатора |

### WP-26 — Справочники на настоящем API

- **Status:** BLOCKED. **Parent:** E-09. **Dependencies:** WP-17, LT-25.1, X-BE-B.
- **Goal:** доказать editing/simulation/publication/version flow, а не только формы на mocks.
- **Sources of truth:** FE-05; BE-03 и READY BE-04a; DICT-01…12; API §5/6; Q-003/015…021/029/044.
- **Acceptance criteria:** реальные revisions/targets/rules/RuleSet/READY snapshots, conflict/stale/ack/restore/idempotency; нет UI-domain обходов; физические файлы при simulate/publish не перемещаются.
- **Verification expectations:** V-E + V-S, independent rule examples, фиксированные versions/RuleSet/seed, safe inventory до/после.
- **Leaf tasks:** LT-26.1, LT-26.2. Scope: E2E/contract assertions/frontend integration/handoff, без matcher/backend реализации.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-26.1 | BLOCKED | WP-15, LT-25.1, X-BE-B | Реальные targets/rule round-trip/draft conflict | DICT-01/03…08; API §5/6; Q-003/015/016/044; OAS targets/replaceDictionaryDraft | Resolver allowed/nonexistent/outside root, поля/маски/приоритет/суффиксы по эталону, пустые rules; два редактора не перезаписывают ревизию; name collision; lost create/save response → reconciliation, локальный текст сохранён | V-E two sessions и controlled response loss, V-S; backend проверяет filesystem profile, не browser validation вместо сервера |
| LT-26.2 | BLOCKED | LT-26.1, WP-17, X-BE-B | Реальные simulation/publish/restore | DICT-02/09…12; API §6; Q-017…021/029; OAS simulation/publish/versions/restore | Все READY, включая невидимые, замена только своего member; empty READY warning; equal/different min-priority targets; stale draft/RuleSet/READY/TTL; exact ack/comment; immutable versions/restore provenance и manual edit; lost publish response с прежним ключом — без новой версии; ни simulate, ни publish не сортирует | V-E parameterized scenarios + safe inventory; сверка server RuleSet/versions/ожиданий, V-S; влияние на accepted batch дополнительно LT-28.1 |

### WP-27 — Реальные очередь, снимки и preview

- **Status:** BLOCKED. **Parent:** E-09. **Dependencies:** WP-20, LT-25.1, X-BE-B; controlled inputs X-LAB.
- **Goal:** подтвердить готовность и точный набор расчёта до физических запусков.
- **Sources of truth:** FE-05; BE-04a/b; QUEUE-01…06/10; API §7; Q-022…026.
- **Acceptance criteria:** readiness/counters, EXPLICIT/ALL_MATCHING и late arrivals не зависят от страницы; preview — серверный прогноз без mutation. Stale enforcement при запуске проверяется в WP-28, не приписывается одному GET preview.
- **Verification expectations:** V-E с controllable incoming и safe inventory до/после, V-S.
- **Leaf tasks:** LT-27.1, LT-27.2, LT-27.3. Scope: E2E/frontend integration/handoff.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-27.1 | BLOCKED | WP-18, LT-25.1, X-BE-B, X-LAB | Настоящие readiness/counters | QUEUE-01/02; API §7; BE-04a; Q-022 | Незавершённое поступление/два стабильных наблюдения с интервалом demo 5с/изменение/rename; UI использует server selectable; counters/status_counts поколения не завышают ready и не меняют scope при фильтре; без компании нет общей очереди | V-E controlled incoming, generation/counters/точные ожидания; backend проверяет readiness, UI только отражает |
| LT-27.2 | BLOCKED | LT-27.1, WP-19, X-BE-B, X-LAB | Реальное snapshot membership | QUEUE-03; API §7 selections; Q-024/025/026 | 120 eligible при странице ≤100; 0/1001 без усечения/мутаций; count change до snapshot → SELECTION_CHANGED; late arrivals/filter change после не меняют IDs; EXPLICIT сохраняет revisions; scope другого user запрещён, той же user допустим | V-E с серверным evidence состава снимка/selected_count и контролем arrivals; eventual batch composition дополнительно LT-28.1 |
| LT-27.3 | BLOCKED | LT-27.2, WP-20, X-BE-B | Реальный preview без движения | QUEUE-04/05/06, DICT-02; API §6/7; Q-023/026 | Plan source/target/references/full RuleSet/counts/коллизии из real API, все страницы; preview не продлевает snapshot TTL; UI expiry/clear company корректны; inventory до/после неизменен; отсутствие preview не объявлено запретом DIRECT | V-E + V-S plan/inventory/cursor/expiry; enforcement STALE_PREVIEW до batch отдельно LT-28.1 |

### WP-28 — Запуски, файловые исходы, гонки и восстановление

- **Status:** BLOCKED. **Parent:** E-09. **Dependencies:** WP-21, WP-26, WP-27, X-BE-C, X-LAB.
- **Goal:** доказать безопасное взаимодействие UI с реальными ручными операциями, без присвоения FE серверной логики.
- **Sources of truth:** FE-05; BE-05/06; QUEUE-04…10, FILE-01…09, NFR-06/07; API §8; Q-027…040.
- **Acceptance criteria:** no-replace/partial outcomes/фиксированные версии/идемпотентность/overlap/restart; UI+API+audit+inventory согласованы; доказательство гонки действительно содержит временное перекрытие; recovery не мнимый quarantine.
- **Verification expectations:** V-E с точками отказа/барьерами backend, независимым инвентарём/контрольными суммами, без физических путей в пользовательском evidence.
- **Leaf tasks:** LT-28.1, LT-28.4, LT-28.5, LT-28.6, LT-28.7, LT-28.2, LT-28.3 — порядок выполнения указан по зависимостям, исходные IDs сохранены. Scope: `tests/e2e/`, frontend integration/handoff; backend executor/FS hooks меняет только backend. WP объединяет готовые проверочные срезы реальных ручных запусков, не реализацию executor.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-28.1 | BLOCKED | WP-21, WP-26, WP-27, X-BE-C, X-LAB | Граница принятия и фиксированный план | QUEUE-03/04/06/08, DICT-12; API §8 строки 219–236; Q-020/024/025/026/027 | DIRECT берёт свежий RuleSet/цели, изменённый или исчезнувший источник до принятия → SELECTION_CHANGED; PREVIEWED при изменении source/rules/target/TTL → STALE_PREVIEW; expired selection → SELECTION_EXPIRED; чужой claim отдельный per-file исход. DIRECT occupied target не общий stale reject, а TARGET_OCCUPIED. После принятия SOURCE_CHANGED без mutation, принятый RuleSet неизменен; 120 snapshot items дают полный paged outcome набор | V-E с controlled clocks/source changes/publication и inventory до принятия; исключены коллизии/manual-review/recovery проверки, вынесенные в отдельные leaf |
| LT-28.4 | BLOCKED | LT-28.1, X-LAB | No-replace и коллизии назначения | FILE-01/02/03, QUEUE-10; API §8 outcome matrix; Q-031/032/033 | Свободная разрешённая цель → один SORTED с rename и сохранным содержимым; occupied до запуска и после preflight → source/target нетронуты; несколько выбранных на одну цель — все остаются, без победителя, независимо от порядка IDs; отдельный safe item проходит; no copy/delete fallback | V-E + BE atomicity evidence; hook создаёт target перед write; independent hashes/locations/audit, нет UI replace/cancel/undo; post-move search сверяется LT-25.3 |
| LT-28.5 | BLOCKED | LT-28.1, X-LAB | Передача в ручной разбор и занятое имя | FILE-04/05; API §8 matrix; Q-034/035 | NO_SCENARIO/RULE_CONFLICT отдельно дают MANUAL_REVIEW в плоской папке компании с исходным basename целиком; при занятом имени source и existing target сохранны, REQUIRES_DECISION/MANUAL_REVIEW_NAME_OCCUPIED; без suffix/rename/subfolder/quarantine/overwrite | V-E двух причин при свободном/занятом имени, safe hashes/inventory/audit; нет UI дальнейшего ручного разбора |
| LT-28.6 | BLOCKED | LT-28.4, LT-28.5, X-LAB | Подтверждённый карантин и смешанный batch | FILE-06, QUEUE-10; API §8; Q-036/039 | Known technical failure при доказанном доступном source и quarantine → подтверждённый QUARANTINED/TECHNICAL_ERROR; mixed batch safe/occupied/no-scenario/technical выдаёт четыре независимых фактических исхода и точные counts/progress; ошибка не отменяет safe move | V-E controlled known-error hook, source/quarantine inventory/hashes/actor/audit, всё содержимое сохранно; ambiguous outcome отдельно LT-28.3 |
| LT-28.7 | BLOCKED | LT-28.1, X-LAB | Публичная граница IDs/путей и source identity | FILE-08, DICT-07, AUTH-02; API §2/5/8/11; Q-044 | Unknown ID → NOT_FOUND; чужая company/selection pair → INVALID_STATE, чужой user snapshot → FORBIDDEN; invalid relative path → VALIDATION_ERROR, invalid target/outside → INVALID_TARGET/PATH_OUTSIDE_ROOT по причине; ссылки/source substitution между проверками отклоняются; вне sandbox нет чтения/записи; общий доступ WORKER к roots/companies не считается нарушением | V-S/V-E negative requests, controlled BE symlink/identity hook и безопасный access/inventory report; без OS/FS обходов из frontend и без нового endpoint |
| LT-28.2 | BLOCKED | LT-28.4, X-LAB | Overlap, idempotency и потерянный ответ batch | QUEUE-07/09, AUTH-03, NFR-07; API §2/8; Q-028/029/030 | Два актора с пересечением: один claim, проигравший SKIPPED/ALREADY_PROCESSING, safe remainder продолжается; повтор старого ключа/тела после lost response и TTL возвращает batch, другое тело → IDEMPOTENCY_KEY_REUSED; новый ручной запуск — новая попытка; logout/reload/new viewer не меняют author | V-E синхронизированных запросов, доказанное overlap, safe hashes/attempt/audit; отдельно polling/backoff, без fake sequential race |
| LT-28.3 | BLOCKED | LT-28.6, X-BE-C, X-LAB | Restart и неопределённый физический исход | FILE-06/09, NFR-06; API §8, SEM recovery; Q-037/040 | Restart до mutation/после доказанной фиксации/при неопределённости: сохранены batch/results/history; доказанный исход без второго move; неизвестное размещение или недоступный quarantine → RECOVERY_REQUIRED, не успех; UI не предлагает слепой запуск; old key возвращает зарегистрированный исход | V-E controlled restart/fault points, persisted intent/phase evidence от BE, API/UI/audit/inventory; X-RECOVERY процедура отдельно к LT-30.4 |

### WP-29 — Реальные возврат и сквозной журнал

- **Status:** BLOCKED. **Parent:** E-09. **Dependencies:** WP-22, WP-24, WP-28, X-BE-C, X-LAB.
- **Goal:** связать подтверждённый return и действия пользователей с неизменяемым общим журналом.
- **Sources of truth:** FILE-07, AUD-01…05, AUTH-02; API §9–11; Q-029/038/041/043/044; BE-01/05.
- **Acceptance criteria:** return безопасен/идемпотентен, WAITING_READY без auto-sort; actor/correlation/return links и cursor/update/roles подтверждены real API, чтение не пишет BUSINESS.
- **Verification expectations:** V-E всех return outcomes и audit scenarios, inventory/links/period/updates; V-S.
- **Leaf tasks:** LT-29.1, LT-29.2. Scope: E2E/frontend integration/handoff.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-29.1 | BLOCKED | WP-22, LT-28.6, X-BE-C, X-LAB | Реальный quarantine return | FILE-07/09, QUEUE-01; API §9; Q-029/038; OAS returnQuarantineItem | Valid comment/revision/free original → WAITING_READY/operation ID, inventory подтверждён; invalid length/revision/occupied/already returned/new key/ambiguous дают точные ошибки без повторной mutation; lost response+same key восстанавливает return; can_return=false при recovery, журнал содержит link; нет auto-sort | V-E 0/1/500/501 comment и параметров Q-038, safe hashes, return_operation_id/error.operation_id; неоднозначность воспроизводит backend hook |
| LT-29.2 | BLOCKED | LT-29.1, WP-24, WP-26, WP-28, X-BE-C | Настоящий сквозной audit | AUD-01…05; API §10; Q-041/043/044; OAS audit operations | Dictionary/create/save/simulate/publish/restore, batch принятие и попытки, return связаны с actor/request/company/version/batch/item по применимости; нет duplicate phase событий; return operation_id/source_attempt_id точны; WORKER BUSINESS/ADMIN SYSTEM, blocked actors в фильтре; поиск/копирование/просмотр без BUSINESS; день/фильтры/cursor≤100/new indicator≤60с корректны | V-E двух акторов/UTC boundaries/новых событий/paging/отсутствия лишнего audit; безопасное серверное evidence no logs bodies/paths, без экспорта |

### WP-30 — Нефункциональная регрессия и пакет передачи MVP

- **Status:** BLOCKED. **Parent:** E-09. **Dependencies:** WP-25…29, X-BE-C, X-LAB; для передачи X-RECOVERY.
- **Goal:** воспроизводимый кандидат обеих функций с честным комплектом проверок для финальной приёмки человеком.
- **Sources of truth:** TZ §12/14, NFR-01…07; FE-05/§7; QA §5/8; PLAN §7/8; Q-042…045.
- **Acceptance criteria:** все 45 строк учтены по уровням, нет скрытых NOT_RUN/FAIL/BLOCKED; accessibility/privacy/performance/чистый запуск проверены; критические дефекты блокируют сдачу. Решение QA принимает человек, не leaf-исполнитель.
- **Verification expectations:** V-C/V-E/V-H, реальные версии среды/схемы/seed, инструкции frontend в составе общей BE-06 сборки; никаких фиктивных command PASS или подписей.
- **Leaf tasks:** LT-30.1, LT-30.2, LT-30.3, LT-30.4. Scope: frontend/E2E checks и docs/handoff; infra/migrations/backup implementation — backend.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-30.1 | TODO | WP-13/17/21/22/24 | Общая browser accessibility/state регрессия | NFR-01, TZ §4, SRCH-15/16; FE §4; Q-042 | На шести экранах keyboard/labels/focus/ошибка не только цветом/loading/empty/error/disabled reason; пути целиком одной строкой, horizontal scroll, clipboard/format; 1280×720 и меньшая ширина; список выявленных дефектов, не «fix everything» | V-C/V-M browser checks и визуальный ручной review доказательств; V-E smoke на кандидатной сборке в LT-30.4 |
| LT-30.2 | TODO | WP-13/17/21/22/24 | Privacy/network regression всех features | AUTH-03/04, SRCH-18, AUD-03, NFR-05; FE §4; API §2/11; Q-001…003/042/043 | Ни условий/paths/ответов/CSRF в URL/history/storage/app cache, ни тел/секретов в frontend logs; logout/401/reload/user switch/late response не восстанавливают state; отсутствуют неожиданные мутации от навигации/просмотра/копирования; prohibited actions не появляются | V-C/V-M instrumented network/storage tests, без публикации credentials в traces; real headers/серверные логи дополняются V-E LT-25.1/29.2 |
| LT-30.3 | BLOCKED | WP-25, X-BE-C, X-LAB | Демонстрационные performance/index guarantees | SRCH-23, NFR-02/03/04/06; BE-02/06; TZ §12; Q-014/045 | Объявлены dataset size/cardinalities/resources/выборка; p95 типового поиска ≤2с, широкой ветки ≤5с; metadata freshness ≤5мин; первичный обход/checkpoint/restart/progress/ETA после замера, root опубликован только после сверки/явной техкоманды. Нет нового UI индексации или обещания SLA реального архива | V-E measured search/freshness + серверное S/A evidence обхода от BE; команды/среда/выборка/лимиты сохранены, mocks не performance evidence |
| LT-30.4 | BLOCKED | WP-25…29, LT-30.1/30.2/30.3, X-BE-C, X-RECOVERY | Чистый запуск и финальный handoff | TZ §14/NFR-02; FE §7; QA §5/QA-05; PLAN §8; Q-045 | Новый участник запускает кандидат по README на свежей разрешённой среде: login/search/draft/test/publish/run/quarantine/audit; dependencies/lock/generation/seed/схема/реальные команды, frontend test reports и links BE migrations/backup/transfer инструкции присутствуют; 45 Q статусов отдельно S/M/A/E с дефектами; UI critical debt закрыт evidence; технический recovery порядок документирован; готово к решению человека, не самоприсвоенный QA PASS | V-C/V-E/V-H clean install/build/run без создания агентом чужого worktree; regression/protocol безопасны; только человек ставит итоговую приёмку/DONE |

## EPIC E-10 — Условная помощь и следующий внутренний этап

Status: BLOCKED (X-HELP/X-INTERNAL). Scope: FE-06, TZ §13. Не расширяет внешний MVP и не содержит выдуманной реализации без API/критериев.

### WP-31 — Подготовка одного назначенного FE-06 handoff

- **Status:** BLOCKED. **Parent:** E-10. **Dependencies:** X-HELP; принятое человеком доступное UI, отсутствие критичного UI-долга, назначение backend. WP-30 целиком не техническая предпосылка FE-06; но D-03 не позволяет выдумать раннюю QA-приёмку.
- **Goal:** использовать свободную frontend-ёмкость только на конкретный ограниченный вспомогательный результат.
- **Sources of truth:** FE-06; PLAN FE-06/§5; D-03; RULES frontend responsibility.
- **Acceptance criteria:** оформлен один bounded brief с точными путями/AC/verification и владельцем backend; реализации auth/FS/recovery/production infra не назначены frontend; помощь не отнимает доступность для FE-05.
- **Verification expectations:** V-H handoff и явного решения владельца. Неназначенные работы не оцениваются и не объявляются готовыми.
- **Leaf tasks:** LT-31.1. Scope: документация назначения; будущий разрешённый код только в FE-06 каталогах после отдельной декомпозиции.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-31.1 | BLOCKED | X-HELP | Подготовить проверяемое назначение помощи | FE-06, FE §7; PLAN §5; D-03 | Для одного выбранного backend результата (synthetic test data, adapter contract test, integration check либо docs) записаны goal/allowed files/AC/commands/owner; пути только fixtures/synthetic, tests/contract, tests/e2e, docs/team; неизвестную работу не выдавать за готовый implementation leaf; при назначении добавить отдельные bounded implementation leaf | V-H полный brief и явное принятие назначения человеком/backend; без product implementation в этой planning-карточке |

### WP-32 — Уточнение frontend scope внутреннего пилота

- **Status:** BLOCKED. **Parent:** E-10. **Dependencies:** X-INTERNAL, отдельное решение начать внутреннее проектирование после внешней демо.
- **Goal:** сохранить известные будущие требования без добавления запрещённых функций в demo.
- **Sources of truth:** TZ §2/13, FILE-02 и границы демо; FE §2; SEM профиль/открытые решения.
- **Acceptance criteria:** ограничения/открытые вопросы и будущие пользовательские процессы связаны с источниками; новые поля/API/права/политики не придуманы; перед реализацией потребуется новая утверждённая декомпозиция.
- **Verification expectations:** V-H реестра решений с человеком/BE/владельцами внутренней среды; ни mock/real PASS, ни обещаний production SLA.
- **Leaf tasks:** LT-32.1. Scope: документация уточнения, не backend/production настройки.

| Leaf ID | Status | Dependencies | Goal | Конкретные sources of truth | Acceptance criteria | Verification expectations |
|---|---|---|---|---|---|---|
| LT-32.1 | BLOCKED | X-INTERNAL | Реестр требований/входов внутреннего этапа | TZ §2/13; FE §2; SEM последний раздел | Учтены корпоративные accounts/timezone/схема, real storage/rights/ID/case/Unicode semantics; confirmed replacement с reserve, обычная компенсация и полный rollback замены с проверкой путей/comment/audit, deletion/cleanup только по политике и правам; до решения нет автоудаления журнала/резерва; UI менять только после согласованного API; масштаб/ресурсы/окна/восстановление — внешние измерения, не frontend обещание | V-H таблицы вопросов/owner/недостающих решений; нет домыслов об endpoints/кнопках/ролях/сроках хранения |

## 4A. Плановая рекурсивная декомпозиция E-02…E-09

Эта декомпозиция подготовлена до будущих worker-run на основе фактической стоимости E-01: отдельные fresh worker-сессии работали корректно, но несколько семантически широких leaf давали длинные tool/model trajectories и десятки миллионов cache-read tokens. Поэтому здесь разрезаны только родители, у которых есть естественная граница между независимо реализуемыми и независимо проверяемыми результатами.

Число тестовых сценариев или размер diff сами по себе не являются причиной разреза. Если parent перечислен ниже, worker получает **только один дочерний leaf за вызов**. Все sources of truth, G-критерии и нераспределённые ограничения parent наследуются его детьми; вместе дети обязаны полностью покрыть исходные AC. Parents, не перечисленные ниже, остаются исполняемыми leaf как есть.

### E-02 / WP-04 — toolchain

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-04.1a | LT-04.1 | VERIFIED | — | Выбран и зафиксирован обычный frontend toolchain: runtime, package manager, OpenAPI generator, unit/component/browser runners; ADR объясняет решение, версии и lock policy. X-STACK закрывается инженерным решением без человеческого gate | Clean tool versions/install resolution; V-H ADR и pinned choices |
| LT-04.1b | LT-04.1 | VERIFIED | LT-04.1a | Создан минимальный scaffold `features/api/generated/mocks/tests` и реально работающие scripts для typecheck/lint/component/browser/build; без лишних экранов/design system | Clean install по lock, smoke каждого script, production build |

### E-02 / WP-05 — transport

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-05.1a | LT-05.1 | VERIFIED | WP-04 | Базовый request/session security transport: browser cookie credentials, CSRF только для объявленных мутаций, no-store и request headers; читающие POST не получают mutation semantics | Request composition tests для read/mutation, CSRF lifecycle и no-store |
| LT-05.1b | LT-05.1 | VERIFIED | LT-05.1a | Единая безопасная модель transport errors: 401/403/404/409/422/429/500/503/network, `request_id`/`operation_id`/`field_errors` доступны UI без утечки тел/секретов и без ложного success | Табличные HTTP/network tests всех кодов и безопасных metadata |
| LT-05.2a | LT-05.2 | VERIFIED | LT-05.1 | In-memory idempotency state для publish/batch/return: UUID связан с исходным телом, потерянный ответ повторяет тот же key/body, новое явное действие получает новый key; прочие мутации не получают фиктивную идемпотентность | Lost-response/body-key tests, reused-body mismatch и explicit new action |
| LT-05.2b | LT-05.2 | VERIFIED | LT-05.2a | Общая retry/backoff policy: Retry-After/backoff только там, где разрешено; нет blind retry неидемпотентных mutation и одинаковых параллельных polls; состояние ограничено session | Controlled clocks, 429/503/network, no-parallel-poll и cleanup tests |

### E-02 / WP-06 — search mocks

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-06.2a | LT-06.2 | VERIFIED | LT-06.1, LT-03.1 | Traceability-parent: исходный AC «canned schema-valid search/facet ответы из golden» исполняется детьми LT-06.2a-i/ii | — |
| LT-06.2a-i | LT-06.2a | VERIFIED | LT-06.1, LT-03.1 | Golden search/facet data foundation: детерминированный materializer `fixtures/synthetic/corpus.json` → полные `SearchItem`/`Marker`/`Facet`; загрузчик и разрешение `fixtures/synthetic/search_expectations.json` (51 search + 6 facet сценариев) по request; literal totals/order/facets/item_ids; schema-valid; НЕ matcher/ranking | V-S/V-C: каждый сценарий разрешается в schema-valid `SearchResponse`/`FacetResponse`; literal totals/order/facets совпадают; item_ids ⊆ materialized inventory; нет алгоритма поиска |
| LT-06.2a-ii | LT-06.2a | VERIFIED | LT-06.2a-i | Mock HTTP handlers `searchFiles`/`getSearchFacet` над foundation: роутинг в mock-fetch, echo `request_state_id`, `index_generation`/`ranking_profile_version`/freshness из root, request validation, IDLE/zero/limited/unrecognized/freshness success-состояния | V-C: клиент через mock transport получает literal golden ответы; invalid request не даёт правдоподобный success; UI-потребители не нужны |
| LT-06.2b | LT-06.2 | VERIFIED | LT-06.2a-ii | Управляемые delay/error/race сценарии search и facet: отдельные request scopes, 503/schema errors, порядок table/dropdown responses и конкретный `request_state_id` | Deterministic delay/error/race tests; invalid request не даёт правдоподобный success |

### E-02 / WP-07 — B/C mocks

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-07.1a | LT-07.1 | VERIFIED | LT-03.2, WP-05, LT-06.1 | Target + dictionary draft finite handlers: allowed/invalid targets, create/save/revision/name conflict/lost-response reconciliation; без FS/rule алгоритмов | V-S/V-C target/draft handlers, errors, reset |
| LT-07.1b | LT-07.1 | VERIFIED | LT-07.1a | Simulation finite handlers: READY/empty/stale/conflict/no-scenario, paging и full RuleSet references; canned expectations, не matcher | V-S/V-C simulation pages/errors/references |
| LT-07.1c | LT-07.1 | VERIFIED | LT-07.1b | Publish/version/restore finite handlers: ack/comment/TTL, idempotent retry, history/provenance/restore и lost responses | V-S/V-C publish/history/restore/idempotency cases |
| LT-07.2a | LT-07.2 | VERIFIED | LT-03.3, WP-05, LT-06.1 | Queue/readiness/selection scripted scenarios: 0/120/1001, filters, EXPLICIT/ALL_MATCHING, late arrivals, count change, expiry/owner scope | V-S/V-C queue/selection variants and request bodies |
| LT-07.2b | LT-07.2 | VERIFIED | LT-07.2a | Preview scripted scenarios: DIRECT/PREVIEWED inputs, stale/expiry, predictions/collisions, paging; preview не выполняет movement | V-S/V-C preview lifecycle/errors/collision kinds |
| LT-07.2c | LT-07.2 | VERIFIED | LT-07.2b, LT-03.4 | Batch scripted scenarios: submit/lost response/retry, progress/polling, все BatchState/Outcome/reasons/cursor/recovery; без claim/executor алгоритмов | V-S/V-C batch lifecycle, timers, outcomes, retries |
| LT-07.3a | LT-07.3 | VERIFIED | LT-03.5, WP-05, LT-06.1 | Quarantine/return finite handlers: confirmed items, `can_return`, recovery, return conflicts/idempotency и late responses | V-S/V-C quarantine/list/return/error/reset |
| LT-07.3b | LT-07.3 | VERIFIED | LT-07.3a | Audit finite handlers: BUSINESS/SYSTEM/null actor, allowed/blocked actors, filters/cursor/new events и linked request/operation/source-attempt IDs | V-S/V-C audit feed/actor/update/link cases |

### E-04 / WP-12–13 — search presentation and state

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-12.1a | LT-12.1 | TODO | WP-11, LT-08.2 | Search results table/summary: fields, exact total, N/limited/zero, full-path layout and server-provided order; no pagination/autoload | V-C/V-M N=10/100/>N, zero, format/long-path layout |
| LT-12.1b | LT-12.1 | TODO | LT-12.1a | Clipboard interaction copies only `display_path`, gives truthful success/failure feedback and never opens/downloads/exports a file | Clipboard success/failure and no-prohibited-network checks |
| LT-13.1a | LT-13.1 | TODO | WP-12 | Atomic response scope: items/total/next facet from one response apply together; latest sent request wins and late table response cannot mutate current state | Deterministic A→B / B→A race tests |
| LT-13.1b | LT-13.1 | TODO | LT-13.1a | Freshness/error/retry UX: CURRENT/UPDATING/STALE, previous successful result remains explicitly stale on failure, no-success error panel, explicit Retry bypasses dedup with new request ID | Error-after-success/no-success/retry/freshness tests |
| LT-13.2a | LT-13.2 | TODO | LT-13.1, LT-09.2 | Recovery from SCHEMA_VERSION_CHANGED/ROOT_NOT_READY/INVALID_MARKER_SELECTION: reread server context, clear incompatible markers, preserve text only where valid, removed root not shown as available | V-C/V-M three context errors and resulting requests/state |
| LT-13.2b | LT-13.2 | TODO | LT-13.2a, LT-09.2 | Memory-only search lifecycle across navigation/reload/logout/user switch: navigation itself performs no search; old responses cannot restore cleared private state | Storage/network/session-reset and delayed-response tests |

### E-05 / WP-16–17 — publish and restore lifecycle

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-16.3a | LT-16.3 | TODO | LT-16.2, LT-05.2 | Publication eligibility UI/state: rule conflicts block, NO_SCENARIO ack bound to current simulation, comment boundaries, stale/revision/ack errors, empty rules and occupied-target semantics | V-C/V-M gates/ack/comment/stale/occupied/empty |
| LT-16.3b | LT-16.3 | TODO | LT-16.3a | Publish submit/reconciliation: idempotent key/body reuse on lost response; success refreshes Dictionary/version/RuleSet and never starts sorting | Lost-response/idempotency/version-refresh tests |
| LT-17.2a | LT-17.2 | TODO | LT-17.1, LT-15.3 | Restore request safely replaces draft from historical version with expected revision; conflict/lost response preserve local input and reconcile object; no direct activation/file undo | Restore/revision/lost-response/provenance tests |
| LT-17.2b | LT-17.2 | TODO | LT-17.2a, LT-16.3 | Post-restore lifecycle requires a new simulation then publish; provenance/new immutable version is correct, manual edit clears `based_on_version_id` according to server response, prior history/accepted batch unchanged | New-test/new-publish/manual-edit/history assertions |

### E-06 / WP-20–21 — preview and batch projection

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-20.1a | LT-20.1 | TODO | WP-19, LT-16.1 | Preview create/read plan: source/company/dictionary/version/rule/target/prediction/reason/full RuleSet/totals/cursor; predictions are not outcomes and no batch POST occurs | V-C/V-M preview pages/references/null target/no batch network |
| LT-20.1b | LT-20.1 | TODO | LT-20.1a | Collision/manual-review presentation: metadata comparison only for collision, DUPLICATE_PLAN_TARGET conflicting IDs/nullable existing, MANUAL_REVIEW_NAME distinct; no winner/replace/movement controls | Collision-kind/null/comparison tests |
| LT-21.2a | LT-21.2 | TODO | LT-21.1 | Per-file outcome taxonomy/rendering: every OutcomeState/OutcomeReasonCode is distinct in Russian; source/planned/actual are not conflated and unknown actual stays null | State/reason/null/location/rule/time matrix |
| LT-21.2b | LT-21.2 | TODO | LT-21.2a | Batch summary semantics: server counts, mixed outcomes, recovery not complete, per-file issue under HTTP 200 not global failure; no UI winner/replace/undo/cancel/manual-review workflow/blind retry | Mixed-outcome/count/recovery and prohibited-action tests |

### E-07 / WP-22 — return transaction

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-22.2a | LT-22.2 | TODO | LT-22.1, LT-05.2 | Explicit return form/submit: comment 1–500, expected revision/key, WAITING_READY success without batch POST; occupied/version/not-found/invalid-state conflicts are distinct | Boundary/conflict/success/no-auto-sort tests |
| LT-22.2b | LT-22.2 | TODO | LT-22.2a | Lost-response/recovery reconciliation: same key reuses original operation, RECOVERY_REQUIRED preserves `error.operation_id`, refreshes `can_return`, never performs second blind movement | Lost response/new key/ambiguous/recovery tests |

### E-08 / WP-24 — audit details

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-24.2a | LT-24.2 | TODO | LT-24.1, LT-21.4, WP-17, WP-22 | Event details projection renders only applicable actor/time/request/company/dictionary/version/RuleSet/batch/attempt/item/source/target/reason/comment fields and preserves nullable links | All AuditAction/nullable-field presentation tests |
| LT-24.2b | LT-24.2 | TODO | LT-24.2a | Existing-data navigation resolves batch/version through existing APIs, handles NOT_FOUND, keeps return/source-attempt links truthful, and introduces no audit-details/attempt/recovery endpoint or BUSINESS write on read/copy | Navigation/404/no-extra-endpoint/no-write network tests |

### E-09 / WP-25 — real auth/search

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-25.1a | LT-25.1 | BLOCKED | WP-09, X-BE-A | Real transport/login/config smoke with synthetic WORKER/ADMIN; mock fallback is off; cookie/CSRF/Origin/no-store/X-Request-ID and schema behaviour are observed without exposing secrets | V-E network/schema/roles/config; environment/version recorded |
| LT-25.1b | LT-25.1 | BLOCKED | LT-25.1a | Real logout/expiry/block/private-cleanup lifecycle and safe separation of browser evidence from BE hash/blocked-user evidence | V-E session cleanup/storage/401/403/block plus BE evidence links |
| LT-25.2a | LT-25.2 | BLOCKED | LT-25.1, WP-13, LT-03.1, X-BE-A | Exact real query semantics and ranking: root/AND/token boundaries/quotes/zero/limit, exact IDs/order/total, numeric examples and tie-break across two roots | V-E + V-S golden comparison, N=10/100/>N, ranking profile recorded |
| LT-25.2b | LT-25.2 | BLOCKED | LT-25.2a | Real facets/hierarchy/raw-case/depth/sort/reset/race behaviour matches golden and server semantics; frontend does not reorder or weaken request | V-E facet/count/order/depth/sort/race assertions with generation metadata |
| LT-25.3a | LT-25.3 | BLOCKED | LT-25.2, X-BE-A, X-LAB | Controlled create/change/rename/move/delete metadata lifecycle reaches search within measured freshness; old path/content-only disappear, type/no-extension/zero/service-dir boundaries match expectations | V-E controlled mutations + measured delay and exact search checks |
| LT-25.3b | LT-25.3 | BLOCKED | LT-25.3a, X-LAB | Generation publication consistency and quality update: reads stay on a completed generation, items/total/facets agree, corrected quality issue disappears; root publication boundary evidence is recorded for LT-30.3 | V-E generation switch/quality/inventory evidence |

### E-09 / WP-26 — real dictionaries

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-26.1a | LT-26.1 | BLOCKED | WP-15, LT-25.1, X-BE-B | Real target resolution and rule round-trip: allowed/nonexistent/outside targets, masks/priorities/suffixes/empty rules match independent expectations; browser does not replace server FS validation | V-E/V-S target/rule scenarios and safe BE profile evidence |
| LT-26.1b | LT-26.1 | BLOCKED | LT-26.1a | Real draft concurrency/reconciliation: two editors, revision/name conflicts and lost create/save responses preserve local text and do not silently overwrite | V-E two sessions + controlled response loss/conflict assertions |
| LT-26.2a | LT-26.2 | BLOCKED | LT-26.1, WP-17, X-BE-B | Real simulation semantics: all READY including unseen rows, empty READY, equal/different min-priority targets, full RuleSet and stale draft/RuleSet/READY/TTL behaviour; no movement | V-E parameterized simulation + safe inventory + V-S |
| LT-26.2b | LT-26.2 | BLOCKED | LT-26.2a | Real publish gates/idempotency: exact ack/comment, stale rejection, lost publish response with same key creates no duplicate version; publish still performs no sorting | V-E publish/error/idempotency/version assertions + inventory |
| LT-26.2c | LT-26.2 | BLOCKED | LT-26.2b | Real versions/restore provenance: immutable history, restore then required new simulation/publish, manual edit provenance and accepted-batch independence | V-E restore/history/provenance/new-version flow |

### E-09 / WP-28 — real batch safety

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-28.1a | LT-28.1 | BLOCKED | WP-21, WP-26, WP-27, X-BE-C, X-LAB | Pre-acceptance boundary: DIRECT uses fresh RuleSet/targets; source/rule/target/TTL changes produce exact SELECTION_CHANGED/STALE_PREVIEW/SELECTION_EXPIRED semantics; occupied target is per-file TARGET_OCCUPIED, not global stale rejection | V-E controlled clocks/source/publication/inventory before acceptance |
| LT-28.1b | LT-28.1 | BLOCKED | LT-28.1a | Post-acceptance fixed plan: accepted RuleSet remains immutable, later source change becomes per-file SOURCE_CHANGED without mutation, foreign claim is per-file outcome, 120-item snapshot exposes complete paged outcome set | V-E fixed-version/claim/paging/inventory assertions |
| LT-28.4a | LT-28.4 | BLOCKED | LT-28.1, X-LAB | Free target succeeds exactly once; target occupied before run or injected after preflight never replaces/copies/deletes source/target | V-E atomicity hook + hashes/locations/audit |
| LT-28.4b | LT-28.4 | BLOCKED | LT-28.4a | Multiple selected items targeting one destination all remain unresolved with no winner independent of ID order; unrelated safe item still succeeds; post-move search linkage retained | V-E duplicate-plan collision + independent safe item + LT-25.3 link |
| LT-28.6a | LT-28.6 | BLOCKED | LT-28.4, LT-28.5, X-LAB | Known technical failure with available source/quarantine produces confirmed QUARANTINED/TECHNICAL_ERROR with preserved content and audit evidence | V-E controlled failure, source/quarantine hashes/inventory/actor/audit |
| LT-28.6b | LT-28.6 | BLOCKED | LT-28.6a | Mixed batch independently yields safe/occupied/no-scenario/technical outcomes with exact counts/progress; one error does not cancel safe movement | V-E mixed-batch outcomes/counts/progress/inventory |
| LT-28.7a | LT-28.7 | BLOCKED | LT-28.1, X-LAB | Public ID/scope boundary: unknown ID, foreign company/selection pair and foreign user snapshot produce exact NOT_FOUND/INVALID_STATE/FORBIDDEN semantics; shared WORKER roots/companies remain allowed | V-S/V-E negative ID/scope requests |
| LT-28.7b | LT-28.7 | BLOCKED | LT-28.7a | Path/target/source identity boundary rejects invalid relative path, outside target, link/source substitution and controlled symlink/identity changes; no read/write outside sandbox | V-E controlled BE identity hook + safe access/inventory report |
| LT-28.2a | LT-28.2 | BLOCKED | LT-28.4, X-LAB | Real overlap race between two actors proves temporal overlap: one claim wins, loser gets SKIPPED/ALREADY_PROCESSING and safe remainder continues | V-E synchronized barrier, attempts/audit/hashes; no sequential fake race |
| LT-28.2b | LT-28.2 | BLOCKED | LT-28.2a | Batch idempotency/recovery of lost response: old key+same body after loss/TTL returns same batch, different body conflicts, new manual run is new attempt; logout/reload/new viewer do not change author | V-E key/body/loss/TTL/viewer/author assertions |
| LT-28.3a | LT-28.3 | BLOCKED | LT-28.6, X-BE-C, X-LAB | Controlled restart before physical mutation and after proven committed result preserves batch/history and never executes a second move for a proven outcome | V-E restart fault points + persisted phase/inventory/audit |
| LT-28.3b | LT-28.3 | BLOCKED | LT-28.3a | Ambiguous physical outcome or unavailable quarantine becomes RECOVERY_REQUIRED, never success; UI offers no blind rerun and old key returns registered state | V-E ambiguous fault point + API/UI/audit/inventory + recovery linkage |

### E-09 / WP-29 — real return/audit

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-29.1a | LT-29.1 | BLOCKED | WP-22, LT-28.6, X-BE-C, X-LAB | Real valid/conflict return transaction: comment/revision/free original → WAITING_READY + operation ID; length/revision/occupied/already-returned/new-key conflicts cause no extra mutation and no auto-sort | V-E boundary/conflict/safe hashes/inventory/operation link |
| LT-29.1b | LT-29.1 | BLOCKED | LT-29.1a | Lost-response/ambiguous return reconciliation: same key restores one return, RECOVERY_REQUIRED makes `can_return=false`, operation/error links and audit remain consistent | V-E controlled response loss/ambiguity + return/audit links |
| LT-29.2a | LT-29.2 | BLOCKED | LT-29.1, WP-24, WP-26, WP-28, X-BE-C | Cross-operation audit linkage for dictionary create/save/simulate/publish/restore, batch acceptance/attempts and return: actor/request/company/version/batch/item IDs correlate and duplicate phase events are absent | V-E two actors + exact correlation/link assertions |
| LT-29.2b | LT-29.2 | BLOCKED | LT-29.2a | Real audit access/query semantics: WORKER BUSINESS vs ADMIN SYSTEM, blocked actors, UTC day/filters/cursor≤100/new indicator≤60s | V-E roles/blocked actors/UTC/filter/paging/update tests |
| LT-29.2c | LT-29.2 | BLOCKED | LT-29.2b | Negative audit/privacy evidence: search/view/copy do not create BUSINESS events; server evidence does not expose request bodies/secret/path material in unsafe logs/reports | V-E absence assertions + safe log/evidence review |

### E-09 / WP-30 — release regression/handoff

| Leaf ID | Parent | Status | Dependencies | Наблюдаемый результат и AC | Verification |
|---|---|---|---|---|---|
| LT-30.1a | LT-30.1 | TODO | WP-13, WP-17, WP-21, WP-22, WP-24 | Cross-screen accessibility/state semantics: keyboard, labels, focus, non-color errors, loading/empty/error/disabled reason on all six screens | V-C/V-M browser accessibility/state checks |
| LT-30.1b | LT-30.1 | TODO | LT-30.1a | Cross-screen layout/format/clipboard regression: full single-line paths with horizontal scroll, formatting, 1280×720 and narrower width; produce bounded defect inventory, not “fix everything” | Browser/layout/clipboard evidence + visual review |
| LT-30.2a | LT-30.2 | TODO | WP-13, WP-17, WP-21, WP-22, WP-24 | Storage/private-state regression: no search/path/response/CSRF in URL/history/storage/app cache; logout/401/reload/user-switch/late response cannot restore cleared state | Instrumented storage/history/session tests |
| LT-30.2b | LT-30.2 | TODO | LT-30.2a | Network/log/side-effect regression: no sensitive frontend logs/traces, navigation/view/copy cause no unexpected mutation and prohibited actions remain absent | Instrumented network/log/mutation assertions |
| LT-30.3a | LT-30.3 | BLOCKED | WP-25, X-BE-C, X-LAB | Measured demo search performance/freshness with declared dataset/cardinalities/resources/sample: p95 typical ≤2s, broad branch ≤5s, metadata freshness ≤5min | V-E measured samples, commands/environment/limits recorded |
| LT-30.3b | LT-30.3 | BLOCKED | LT-30.3a | Index bootstrap/operability evidence: first crawl, checkpoint/restart/progress/ETA and root publication only after verification/explicit technical action; no user indexing UI/SLA claim | Backend S/A evidence + reproducible commands and restart/progress records |
| LT-30.4a | LT-30.4 | BLOCKED | WP-25, WP-26, WP-27, WP-28, WP-29, LT-30.1, LT-30.2, LT-30.3, X-BE-C, X-RECOVERY | Fresh allowed environment can install/build/start candidate strictly from README with pinned dependencies/lock/generation/seed/schema and linked BE setup instructions | V-C/V-E clean install/build/start with exact versions/commands |
| LT-30.4b | LT-30.4 | BLOCKED | LT-30.4a | Candidate walkthrough on that environment completes login→search→draft→test→publish→run→quarantine→audit using real services and existing regression reports | V-E end-to-end walkthrough; no mock fallback |
| LT-30.4c | LT-30.4 | BLOCKED | LT-30.4b | Final handoff/evidence package: all 45 Q rows explicitly S/M/A/E with defects/NOT_RUN/BLOCKED, frontend reports + BE migration/backup/transfer/recovery links, critical UI debt evidence; ready for human decision without self-awarded QA PASS | V-H completeness/traceability + safe protocol review |


## 5. Порядок реализации и reviewable границы

1. **WP-01 → WP-02 → WP-03:** исправить два query parameters и inconsistent examples, получить настоящий runner и независимые сценарные эталоны. OAS не переписывается с нуля; совместное согласование уже подтверждено.
2. **WP-04 → WP-05:** закрепить toolchain/генерацию/транспорт. Анализ вариантов toolchain допустим параллельно WP-01/02; техническое решение X-STACK orchestrator принимает и фиксирует в LT-04.1 без человеческого gate. WP-04 имеет статус TODO и выполняется при удовлетворённой WP-02; generated client только после исправленного проверяемого OAS.
3. **WP-06 → WP-08/09 → WP-10…13:** auth/search mock slice. WP-07 B/C можно готовить параллельно A-UI: он не зависит от готового поиска.
4. **WP-25 начинается по готовности BE-01/02**, не ждёт dictionaries/sorting. Подпись QA в середине не требуется, exact tests требуются.
5. **WP-14 → WP-15 → WP-16 → WP-17:** компания/draft → targets/rules/revisions → simulation/publish → history/restore. Каждый WP имеет отдельный читаемый пользовательский результат; нет одного огромного «FE-04» worker run.
6. **WP-18 → WP-19 → WP-20 → WP-21:** read queue → immutable selection → необязательный preview → ручные durable batches. WP-18/19 можно делать независимо от полного dictionaries UI. WP-20 использует проверенную plan presentation LT-16.1. Четыре leaf WP-21 отделяют submit/outcomes/polling/history в пределах одного WP.
7. **WP-22 и WP-23** независимы от готовой физической сортировки. WP-24 добавляет существующие links к batch/version/return после появления их экранов; LT-24.1 polling может выполняться раньше LT-24.2.
8. **WP-26/27/28/29 — real integration по backend-срезам.** BE-04a и matcher/simulation не создают цикл. Файловые операции только после безопасного BE-05 sandbox и воспроизводимых test hooks, не через mock fallback.
9. **WP-30:** сквозная регрессия, измерения/чистый запуск, комплект evidence, финальная человеческая приёмка обеих функций. LT-30.1/30.2 могут выполняться на полном UI раньше real-сервера; результат M не переносится в E.
10. **WP-31/32 условные:** FE-06 только по конкретному назначению/принятому UI; внутренний этап после отдельного решения. Они не входят в dependency chain внешнего MVP.

Если исходный parent leaf имеет детей в §4A, в execution dependency-графе его результат означает объединение обязательных дочерних leaf; сам parent worker'у не назначается. Dependencies на WP означают завершение его применимых исполняемых leaf на заявленном уровне с условиями VERIFIED из §3; dependencies на LT-parent допускают зависимость от полного результата его детей, а dependencies на конкретный child — ранний независимый срез внутри parent/WP. Ссылки с диапазоном включают каждый ID диапазона. Внешние блокирующие X-* снимаются конкретным артефактом/средой, не изменением статуса в плане; X-STACK — исключение по типу записи: неблокирующее техническое решение LT-04.1, не внешний вход. Branch/worktree выбранного Execution Unit создаёт launcher/человек до сессии; checkpoint commit/push текущей ветки выполняет `frontend/orchestrator` по §3. Внутренние WP и leaf не создают отдельные branch/worktree/PR; каждый исполняемый leaf получает fresh `frontend/worker` и fresh `frontend/reviewer` child sessions по RULES, а root `frontend/orchestrator`-сессия может быть заменена/продолжена в том же worktree без смены Execution Unit. Порядок выше описывает зависимости всего backlog, а автономное выполнение ограничено выбранным Execution Unit.

## 6. Трассировка всего frontend-ТЗ и общих требований

### 6.1. Исходные FE-пакеты

| Исходное требование | Новая декомпозиция | Что не выдано за готовность |
|---|---|---|
| FE-01 | WP-01/02, LT-03.1, контрактный handoff G-6 | OAS A существует, но schema/fixture tests не исполнялись |
| FE-02 | WP-01/02/03/04/05/06/07 | B/C схемы существуют; generated client/mocks отсутствуют |
| FE-03 | WP-08…13, A mocks WP-06; real WP-25 | Ни shell/auth, ни поиск не реализованы |
| FE-04 | WP-14…24, B/C mocks WP-07 | DICT/QUEUE/FILE/AUD UI не реализован |
| FE-05 | WP-25…30, локальные проверки в каждом feature leaf | Backend/среда отсутствуют, real-pass BLOCKED |
| FE-06 | WP-31 + новый bounded leaf после назначения | Нет выдуманного backend задания/промежуточного QA PASS |

### 6.2. Requirements TZ (все 73 numbered requirements)

| IDs | Frontend leaf/WP | Серверная/внешняя граница и real evidence |
|---|---|---|
| AUTH-01/02/04/05 | WP-05/06/09; LT-25.1 | Сессия/автор/хеши/cookie/создание двух workers+admin/блокировка — BE-01; UI не создаёт auth backend |
| AUTH-03 | LT-09.2, LT-13.2, LT-21.3/21.4; G-5 | Принятый batch не теряется, actor стабилен — LT-28.2/28.3 |
| SRCH-01/03/09/10/11 | WP-10, LT-11.1, LT-12.2 | Запрос/IDLE/default/reset — LT-25.2 |
| SRCH-02/04/05/06 | WP-11; LT-13.1 | Exact counts/order/AND/raw values — BE-02 и LT-25.2, не browser counting |
| SRCH-07/08 | LT-03.1, LT-10.2, LT-25.2 | Tokenization/AND/phrases/ranking выполняет BE-02; UI управляет только вводом/отправкой |
| SRCH-12/13/14/15/16 | LT-12.1/12.2, LT-08.2; LT-30.1 | Limited response/порядок с сервера; no search pagination |
| SRCH-17/18 | WP-13, LT-09.2, LT-30.2 | Memory-only, last-request scope, stale/retry; real WP-25 |
| SRCH-19/20/21 | WP-11, LT-12.3/13.2; LT-25.2/25.3 | Схему и parser задаёт сервер; контекст качества, не очередь исправления |
| SRCH-22/24/25 | LT-12.1/13.1/25.3 | Metadata-only/index exclusions/change detection/поколения — BE-02 |
| SRCH-23 | LT-10.1/25.3/30.3 | Progress/checkpoint/ETA/техническая публикация корня — BE-02/06, не новый пользовательский экран |
| DICT-01/02 | WP-14/17; LT-16.1/16.2; WP-26 | Уникальность, общий draft/active versions/RuleSet — BE-03 |
| DICT-03/04/05/06/07 | LT-15.1/15.2, LT-16.1, LT-26.1/26.2 | Matcher/приоритеты/суффиксы/target resolution — BE-03; frontend не вычисляет реальный план |
| DICT-08 | LT-15.3/17.2/26.1 | Server revision проверяется атомарно, UI сохраняет local input |
| DICT-09/10 | WP-16; LT-26.2 | All READY и full RuleSet freshness — BE-03+BE-04a |
| DICT-11 | WP-17; LT-26.2 | Restore → новая immutable версия, не файловый undo |
| DICT-12 | LT-16.2/16.3/20.2/21.2/28.1 | Старый preview stale, accepted RuleSet/plan неизменны — BE-03/05 |
| QUEUE-01/02 | WP-18; LT-27.1; WP-22 | Recursive discovery/readiness/counters — BE-04a; returned item WAITING_READY |
| QUEUE-03 | WP-19; LT-27.2/28.1 | Immutable membership/revisions/all pages — BE-04b |
| QUEUE-04/05/06 | WP-20, LT-21.1; LT-27.3/28.1 | Server calculation/preflight/stale enforcement, preview не обязателен |
| QUEUE-07/09 | LT-05.2/21.1/21.2/28.2 | Atomic claim и durable idempotency — BE-05 |
| QUEUE-08/10 | LT-18.2/21.2/21.3/21.4; LT-28.1/28.2 | History/partial outcomes/polling, company switch не отмена |
| FILE-01/02/03/04/05 | LT-20.1/21.2/28.4/28.5 | No-replace/две коллизии/manual review/basename/FS atomicity — BE-05 и inventory/hashes |
| FILE-06/07 | WP-22; LT-21.2/28.6/28.3/29.1 | Confirmed quarantine, ambiguous recovery, safe return — BE-05; UI не перемещает |
| FILE-08/09 | LT-15.1/21.2/22.2/26.1/28.7/28.3/29.1 | Boundary/type/link/source identity/intent/recovery — BE-05; real tests, не клиентская security validation |
| AUD-01/02/03 | WP-24; LT-29.2/30.2 | Append-only events/attribution/system category/no sensitive logging — BE-01/05 |
| AUD-04/05 | WP-23/24; LT-29.2 | Shared journal/filterable actors/cursor/new events/timezone |
| NFR-01 | G-2; WP-08/12; LT-30.1 | Keyboard/focus/Russian/long paths/desktop browser |
| NFR-02 | WP-02/03/04; LT-30.4 | Общая сборка/migrations/sandbox generator/backup/transfer — BE-06; frontend build/docs/tests — FE |
| NFR-03/04 | LT-25.3/30.3 | Измерения на объявленном стенде, p95 2/5с и freshness≤5мин; не гарантия на реальном архиве |
| NFR-05 | WP-05/09; LT-25.1/29.2/30.2 | Cookie/Origin/CSRF/no-store/HTTPS — server+transport, не только UI |
| NFR-06/07 | LT-13.1/21.3/25.3/28.2/28.3/30.3 | Consistent generations/durable state/concurrency/progress — BE+FE real evidence |

### 6.3. Все 45 сценариев MATRIX

В таблице указаны основные владельцы проверки; локальные UI tests входят и в предыдущие feature leaf. Ни один статус PASS здесь не присвоен. Все параметры соответствующей строки MATRIX обязательны; S/M/A/E учитываются раздельно, backend-only assertions предоставляет backend.

| Q-ID | Основные leaf проверки |
|---|---|
| Q-001 | LT-09.1, LT-25.1, LT-30.2 |
| Q-002 | LT-09.2, LT-25.1, LT-28.2 |
| Q-003 | LT-13.1, LT-14.2, LT-15.3, LT-17.2, LT-25.1, LT-26.1 |
| Q-004 | LT-10.1, LT-25.2 |
| Q-005 | LT-10.1/10.2, LT-11.1/11.2, LT-13.1, LT-25.2 |
| Q-006 | LT-11.2, LT-12.2, LT-25.2 |
| Q-007/008/009 | LT-03.1, LT-06.2, LT-10.2, LT-25.2 |
| Q-010 | LT-10.2, LT-13.1, LT-25.2 |
| Q-011 | LT-02.2, LT-03.1, LT-13.1, LT-25.2/25.3 |
| Q-012 | LT-11.1, LT-12.3, LT-25.2/25.3 |
| Q-013 | LT-12.1, LT-25.2 |
| Q-014 | LT-25.3, LT-30.3 |
| Q-015 | LT-15.1/15.2, LT-26.1/26.2 |
| Q-016 | LT-14.2, LT-15.3, LT-26.1 |
| Q-017/018 | LT-16.1/16.2/16.3, LT-26.2 |
| Q-019 | LT-16.3, LT-26.2 |
| Q-020/021 | LT-17.1/17.2, LT-26.2, LT-28.1 |
| Q-022 | LT-18.1/18.2, LT-27.1 |
| Q-023 | LT-19.1, LT-20.1, LT-27.3 |
| Q-024/025 | LT-19.2, LT-27.2, LT-28.1 |
| Q-026 | LT-20.2, LT-27.2/27.3, LT-28.1 |
| Q-027 | LT-21.1, LT-28.1 |
| Q-028 | LT-21.2, LT-28.2 |
| Q-029 | LT-05.2, LT-16.3, LT-21.1, LT-22.2, LT-26.2/28.2/29.1 |
| Q-030 | LT-21.3/21.4, LT-28.2 |
| Q-031/032 | LT-20.1, LT-21.2, LT-28.4 |
| Q-033 | LT-21.2, LT-28.4; индекс после move — LT-25.3 |
| Q-034/035 | LT-21.2, LT-28.5 |
| Q-036 | LT-21.2, LT-28.6 |
| Q-037 | LT-21.2, LT-28.3 |
| Q-038 | LT-22.2, LT-29.1 |
| Q-039 | LT-21.2/21.3, LT-28.6 |
| Q-040 | LT-21.4, LT-28.3 |
| Q-041 | WP-23/24, LT-29.2 |
| Q-042 | LT-08.1/08.2, LT-12.1/13.2, LT-30.1/30.2 |
| Q-043 | WP-02/04/05/06/07, LT-25.1/29.2/30.2 |
| Q-044 | LT-15.1, LT-26.1, LT-28.7; server-owned scope/link/identity assertions |
| Q-045 | LT-30.3/30.4 |

### 6.4. API surface: ни одного выдуманного endpoint

| Операции OAS | Основные consumers |
|---|---|
| getHealth, login, getSession, logout, getAppConfig, listRoots, listCompanies | WP-05/06/08/09/10/14/18/22; getHealth технический smoke, не отдельный экран |
| searchFiles, getSearchFacet | WP-10…13 |
| listTargetDirectories, resolveTargetDirectory | LT-15.1 |
| listDictionaries, createDictionary, getDictionary, replaceDictionaryDraft | WP-14/15 |
| listDictionaryVersions, getDictionaryVersion, restoreDictionaryDraft | WP-17; version links LT-24.2 |
| createDictionarySimulation, getSimulation, publishDictionary | WP-16 |
| querySortingQueue, createSortingSelection | WP-18/19 |
| createSortingPreview, getSortingPreview | WP-20 |
| createSortingBatch, getSortingBatch, listSortingBatches | WP-21, batch links LT-24.2 |
| listQuarantineItems, returnQuarantineItem | WP-22 |
| queryAuditEvents, getAuditUpdates, listAuditActors | WP-23/24 |

### 6.5. Исключённые функции и будущие входы

По TZ §2/13, FE §4 и SEM в demo **не добавляются**: карта/геопоиск, content/OCR/ИИ, upload/open/download/edit файла, saved queries/export, global search по всем дискам, расписание сортировки, regex/сложный DSL, создание целей, замена/резерв/удаление/cleanup, cancel batch и файловый undo, отдельный manual-review workflow. Account CRUD screen необязателен и здесь не запланирован: synthetic users/блокировка — серверные команды. Это не удаление обязательного scope, а сохранение явных границ ТЗ.

Внутренние оценки TZ §13 (93 ТБ физически/195 ТБ логически, аудитория 30–40 и тест до 50 одновременно, рабочие окна, восстановление ≤4 рабочих часов и потеря служебных данных ≤1 часа) — входы будущего обследования/нагрузки/инфраструктуры, не demo frontend AC. Корпоративные схема/SMB/OS/права/case/Unicode/ID/change channel/metadata throughput/timezone/accounts/backup/dependency transfer уточняются в WP-32. Demo не подтверждает совместимость с ними.

## 7. Самопроверка декомпозиции и ведение evidence

Перед передачей backlog проверяется целиком: все FE-01…06 и numbered TZ requirements имеют ссылки в §6; все Q-001…045 и 33 операции имеют consumers/проверки; серверные гарантии отделены от UI; conditional/internal scope не замаскирован под готовый leaf реализации.

Каждый **исполняемый конечный leaf** имеет один наблюдаемый результат, status/dependencies/goal/точный source/AC/verification; исходный ID с дочерними leaf является traceability-parent и worker'у напрямую не назначается. Декомпозиция сохраняет границу по независимому observable outcome, а не по числу файлов/строк/тестов. Mock handlers разделены по предметным группам, UI lifecycle — по независимо проверяемым состояниям/операциям, real-check — по отдельным видам доказательств/гонок/интеграционных срезов. Если фактический объём конкретного run всё ещё окажется шире, дальнейшая декомпозиция делается до назначения worker, без потери AC.

Порядок зависимостей ацикличен: platform → mock/auth → feature slices → real slices → release; ссылки на готовый prerequisite leaf допускают параллельность пакетов. При уточнении декомпозиции IDs сохраняются, поэтому порядок исполнения определяется dependencies, не арифметикой ID (см. WP-28). Финальная QA-приёмка не является зависимостью intermediate UI/real разработки. Условная помощь FE-06 не включена в критический путь MVP.

Документарные/структурные проверки backlog не заменяют product build, V-S runner или M/A/E сценарии. После исполнения к каждой карточке добавляются реальные commands/results/versions/evidence и статус по §3; этот план сам по себе ничего не переводит в VERIFIED, READY_FOR_HUMAN_REVIEW или DONE.

### Сохранённые результаты структурной проверки

- Исторический planning-review исходных 80 IDs сохранён как baseline traceability, но не является утверждением, что каждый исходный parent достаточно мал для одного worker-run. Фактический E-01 показал корректные fresh child sessions и одновременно слишком длинные trajectories у нескольких семантически широких задач; поэтому WP-03 и 33 родителей E-02…E-09 имеют явную рекурсивную execution-декомпозицию при сохранённых parent IDs/AC.
- Текущая структура: **10 EPIC / 32 WP / 80 исходных leaf IDs / 123 исполняемых конечных leaf**. Parent-ссылки в §6 сохраняют исходную трассировку **73 TZ requirements / 45 Q-сценариев / 33 operationId**; применимые children наследуют traceability parent. После изменения декомпозиции structural checker должен повторно валидировать уникальность child IDs, parents/dependencies и отсутствие циклов до начала соответствующего Epic.
- Фиксированная сводка количества TODO/BLOCKED leaf больше не считается долговременной истиной: runtime-статусы E-01 уже изменяются, а child leaf наследуют стартовый статус parent до фактического execution. Актуальный статус читается из карточек/дочерних таблиц, не из исторического счётчика.
- При последующих изменениях повторно проверяются counts/IDs/parents/leaf lists, ссылки и ацикличность dependencies (включая диапазоны и ранние LT-срезы), полнота §6, точный diff и whitespace. Evidence документарной проверки хранится отдельно от результатов product tests/builds и OpenAPI runner.
