# Контракт Frontend ↔ Backend

Редакция документа 2.0 от 09.09.2026. Владелец: Frontend. Основание: `01_PROJECT_TZ.md`. Статус: подробное основание для первой согласованной версии OpenAPI; сервер и OpenAPI по этому документу ещё не реализованы.

## 1. Правила совместной работы

Frontend в FE-01/02 переносит этот контракт в `contracts/openapi/memoza-demo-v1.yaml`, добавляет схемы всех DTO, ответов, параметров, ошибок и примеры. Backend проверяет реализуемость, QA — соответствие наблюдаемому поведению. После проверки версионированный YAML становится единственным источником структуры API, а это описание — источником семантики. Расхождения исправляются совместно.

Публичный префикс `/api/v1`, JSON, UTF-8. Имитация API и настоящий сервер используют одни методы, пути, статусы, тела и ошибки. Смена режима клиента не изменяет компоненты UI. Первые согласования: A — auth/config/roots/search, B — dictionaries/targets/sorting, C — batches/quarantine/audit. Backend начинает каждый раздел сразу после его согласования.

До слияния изменения контракта: обновлены request/response examples, сгенерированный клиент, проверка схем и затронутые тесты; Backend подтвердил реализуемость или написал конкретное ограничение; QA обновил ожидаемый результат. Готовый сервер не требуется для первичного согласования контракта. Удаление/переименование поля, новый обязательный параметр и изменение смысла/enum считаются несовместимым изменением. Добавление enum тоже требует обновить обработку UI.

## 2. Общие типы и транспорт

Все поля перечисленных DTO обязательны, если не отмечены `?`. `T|null` — ключ присутствует, значение может быть null. Неизвестные поля запросов отклоняются. Объекты имеют `additionalProperties: false` в OpenAPI. Сервер не возвращает пароли, стек исключения, физические пути, mount/UNC или секреты.

| Тип | Определение |
|---|---|
| `Id` | Непрозрачная строка ASCII `[A-Za-z0-9-]`, 1–96 символов; клиент не разбирает смысл |
| `Revision` | Целое число ≥0, монотонно растёт внутри объекта |
| `Instant` | RFC3339 в UTC с `Z`, например `2031-05-10T09:30:00Z` |
| `Count` | Целое 0…9007199254740991; безопасно и точно представимо клиентом |
| `RelativeDirectory` | Путь относительно логического корня с `/`, 1–4096 символов; нет пустых сегментов, `.`, `..`, начального/конечного `/`, обратного слеша, `:`, NUL и управляющих символов. Это каталог, не файл |
| `RelativeFilePath` | Те же ограничения, последний сегмент — имя файла. Кодирование URL не декодируется повторно в пути; невалидная попытка обхода не нормализуется в разрешённый путь |
| `Location` | `{root_id: Id, relative_path: RelativeFilePath, display_path: string}`; display_path только для показа/копирования |
| `Actor` | `{user_id: Id, login: string, display_name: string, role: WORKER\|ADMIN}` |
| `Page<T>` | `{items: T[], next_cursor: string\|null}`. Непрозрачный cursor связан с фильтрами и снимком; размер страницы ≤100 |

Путь самого логического корня не используется как цель сортировки: цель — существующий подкаталог из настроенного перечня. Ручной ввод display path обрабатывает отдельный resolver; он единственный превращает синтетическую строку отображения в `root_id + directory`. В остальных запросах display path не задаёт полномочий и не используется сервером как физический путь.

Все ответы имеют `X-Request-ID`; ошибки дополнительно содержат его в JSON. Пользовательские ответы — `Cache-Control: no-store`. API и UI рекомендуется обслуживать с одного origin. CORS при разных адресах разрешает только явно настроенный адрес UI, с credentials; wildcard недопустим.

### Сессия

`POST /auth/login` принимает `login` и `password`, устанавливает HttpOnly cookie `memoza_session`. Сервер хранит сессию и хеш пароля. Cookie — SameSite=Lax, Path=/, без Domain, Secure при HTTPS. Для loopback HTTP демо флаг Secure отключается настройкой. Тело ответа не содержит session ID.

В OpenAPI: `cookieAuth` типа `apiKey`, in=`cookie`, name=`memoza_session`; по умолчанию требуется для операций. Только `/health` и `/auth/login` имеют `security: []`.

Сессия возвращает CSRF-токен для заголовка `X-CSRF-Token` всех запросов, изменяющих состояние, после входа. Токен хранится только в памяти вкладки и меняется при новом входе. Сервер проверяет token и Origin; login также проверяет разрешённый Origin. Search и audit/query не изменяют состояние. Структура `Session`: `{actor: Actor, expires_at: Instant, csrf_token: string}`. Отсутствующая/истёкшая сессия — 401, а не успешный ответ с пустым пользователем.

### Идемпотентность

Публикация справочника, создание партии и возврат из карантина требуют `Idempotency-Key` (UUID). Сервер связывает ключ с user_id, операцией и хешем тела. Повтор того же ключа/тела возвращает прежний результат. Другое тело с тем же ключом — 409 `IDEMPOTENCY_KEY_REUSED`.

Проверка существующего ключа идёт **до** повторной проверки истечения snapshot/preview: потерянный ответ принятой партии должен восстановиться. Новая попытка после ошибки условий использует новый ключ. Ключ принятой операции не удаляется отдельно от самой операции в демо. До устойчивой фиксации партии сервер не возвращает 202. При сетевой неопределённости UI повторяет исходный ключ, а не создаёт новую операцию.

Для остальных мутаций автоматический retry после потери ответа не выполняется. После создания справочника клиент перечитывает список по уникальному имени; после save/restore — сам справочник и его revision, сохраняя локальный ввод до сверки. Simulation/selection/preview не перемещают файлы: если их ID потерян, пользователь явно создаёт новый расчёт/снимок; старый истечёт, а его аудит не удаляется. Повторный login — явная отправка формы; после неизвестного исхода logout клиент проверяет session и при необходимости повторяет выход. Заголовок идемпотентности не добавляется к неподдерживающим его операциям как фиктивная гарантия.

## 3. Вход, конфигурация и корни

| Метод и путь | Запрос | Успех | Особенности |
|---|---|---|---|
| GET `/health` | — | 200 `{status: "ok"}` | Без внутренних адресов и списка зависимостей |
| POST `/auth/login` | `{login: string, password: string}` | 200 `Session` + cookie | 401 LOGIN_FAILED, единая ошибка неверного логина/пароля |
| GET `/session` | — | 200 `Session` | Проверяет актуальную сессию, не продлевает абсолютный срок |
| POST `/auth/logout` | Пустое тело | 204 | Завершает текущую сессию и удаляет cookie |
| GET `/app-config` | — | 200 `AppConfig` | Конфигурация поведения UI, без физических путей |
| GET `/roots` | — | 200 `{items: Root[]}` | Только опубликованные поисковые корни |
| GET `/companies` | — | 200 `{items: Company[]}` | Все доступные компании; выбор одной обязателен для сортировки |

`AppConfig`: `{api_contract_version: string, display_timezone: string, search_result_limit: Count, max_batch_items: Count, max_query_length: Count, preview_ttl_seconds: Count, snapshot_ttl_seconds: Count, simulation_ttl_seconds: Count, batch_poll_interval_ms: Count, audit_poll_interval_ms: Count}`. Стартовые значения из ТЗ; max_query_length=512 для демо. Клиент не зашивает эти ограничения отдельно.

`Root`: `{root_id: Id, label: string, display_prefix: string, schema_set_version: Id, index_generation: Id, indexed_at: Instant}`. Корень в процессе первичной индексации не появляется в этом списке. Если выбранный ранее корень снят с публикации, поиск возвращает `ROOT_NOT_READY`.

`Company`: `{company_id: Id, name: string, incoming_source_ids: Id[]}`. Физические входящие пути в ответ не включаются; ID источника может отображаться человеку только через его безопасное название в карточке очереди.

## 4. Поиск и каскад

### POST `/search` → 200 `SearchResponse`

```json
{
  "request_state_id": "state-demo-1",
  "root_id": "root-demo-1",
  "schema_set_version": "schema-demo-1",
  "selected_marker_ids": [],
  "query_text": "atlas 2031",
  "sort": {"field": "RELEVANCE", "direction": "DESC"},
  "facet_prefix": ""
}
```

`request_state_id: Id` — созданный клиентом уникальный ID конкретной отправки, возвращается без изменения. При каждом разрешённом повторе, даже с теми же условиями, создаётся новый ID. Клиент принимает только ответ последней отправки в соответствующем scope (таблица или отдельный список уровня). Для дедупликации условий используется отдельный локальный ключ без request_state_id; кнопка «Повторить» обходит дедупликацию после ошибки. Это защита от устаревшего сетевого ответа, не средство авторизации. `selected_marker_ids: Id[]` — непрерывная цепочка выбранных raw-значений от первого уровня. Сервер проверяет корень, схему, принадлежность родителю, порядок и terminal marker.

`query_text` — исходный завершённый текст длиной ≤max_query_length. Грамматика строго из SRCH-07/08: нет логических OR/NOT, регулярных выражений и escape-последовательностей; кавычки только парные двойные. API ищет текущие filename и display_path; не содержимое и не прежние пути. Обычные слова могут совпасть в разных полях, фраза целиком в одном поле.

`sort.field`: RELEVANCE | PATH | NAME | MODIFIED_AT | SIZE. `direction`: ASC | DESC. RELEVANCE допустим только с непустым текстом и DESC. PATH по умолчанию ASC. Клиент явно передаёт контекстный порядок; сервер не полагается на предыдущий запрос.

`facet_prefix` фильтрует только значения следующего выпадающего списка, **не набор файлов и не total**. Prefix регистронезависим; counts каждого возвращённого значения остаются counts полного AND-пересечения. В ответе список может быть пуст при непустой таблице. В демо возвращаются все подходящие значения списка; размер списка измеряется перед внутренним пилотом, молчаливое усечение запрещено.

`SearchResponse`:

| Поле | Тип и смысл |
|---|---|
| request_state_id | Id из запроса |
| mode | IDLE или RESULTS |
| root_id, schema_set_version, index_generation, ranking_profile_version | Id каждого действующего контекста |
| applied_query_text | string; нормализованный пробельный формат без изменения смысла |
| selected_markers | Marker[]; серверные значения выбранной цепочки |
| total | Count или null; null только для IDLE |
| returned_count | Count; точно равно items.length и в RESULTS равно min(total, result_limit) |
| result_limit | Count; фактически применённый N |
| limited | boolean; в RESULTS ровно `total > result_limit`; в IDLE false |
| items | SearchItem[]; не более N, в IDLE пусто |
| next_facet | Facet или null |
| freshness | `{indexed_at: Instant, last_successful_sync_at: Instant, status: CURRENT\|UPDATING\|STALE}` |

Только корень при пустой строке/цепочке → IDLE, items=[], total=null, первый facet с точными корневыми counts. Так UI получает следующий шаг без массовой таблицы. Во всех остальных запросах → RESULTS, total — точное число, включая ноль. Ограничение выдачи не ошибка.

`Marker`: `{marker_id: Id, level_id: Id, level_name: string, raw_value: string|null, display_value: string, kind: VALUE|UNRECOGNIZED}`. Для UNRECOGNIZED raw_value=null, display_value="Не распознано". ID различает raw-варианты, даже если их lowercase равны.

`Facet`: `{level_id: Id, level_name: string, options: FacetOption[]}`; `FacetOption`: все поля Marker + `{count: Count}`. После UNRECOGNIZED/конечного уровня next_facet=null. После обычных значений UNRECOGNIZED всегда последний. Схема не задаёт фиксированную глубину в клиенте.

`SearchItem`: `{item_id: Id, location: Location, filename: string, markers: Marker[], extension: string, size_bytes: Count, modified_at: Instant, structure_status: VALID|UNRECOGNIZED, structure_issue: StructureIssue|null}`. extension включает точку или пустую строку. `StructureIssue`: `{level_id: Id|null, level_name: string, code: MISSING_REQUIRED_LEVEL|UNEXPECTED_DEPTH|INVALID_LEVEL_VALUE|INVALID_COMPOSITE_SEGMENT, message: string}`. В UI отклонений размер/технический код скрыты; данные не теряются из модели.

Ранжирование — версия серверного профиля. Для демо веса: filename=5, проект/год=4, компания=3, остальные уровни=1. Каждый уникальный обычный токен запроса даёт максимальное значение `вес поля × коэффициент совпадения` среди подходящих полей; коэффициент полного токена=2, prefix=1. Повторы в пути или запросе не прибавляют score. Каждая уникальная фраза даёт один вклад: `2 × число токенов фразы × максимальный вес поля`, в котором она целиком совпала. Итог — сумма вкладов обычных токенов и фраз; требование AND проверяется до ранжирования. Если фраза пересекает уровни пути, для её вклада используется вес 1; внутри одного уровня — вес этого уровня. Дублирование filename в display_path не суммируется. Логический корневой префикс не влияет на score. Это стартовый профиль демо; он не утверждает реальные бизнес-веса. FE/BE/QA фиксируют примеры порядка в golden tests; backend возвращает ranking_profile_version. При равном score: natural path ASC → raw path ASC → item_id ASC. Ручные сортировки имеют тот же вторичный порядок. Сам score в интерфейсе не обязателен.

Числовые примеры профиля: обычное слово `atlas` одновременно целиком в filename и компании даёт max(5×2,3×2)=10, а не 16; только prefix в filename даёт 5. Фраза `"atlas main"` и в filename, и в проекте даёт 2×2×max(5,4)=20 один раз; только через границу уровней пути — 2×2×1=4. К запросу из этой фразы и отдельного `2031` добавляется вклад отдельного токена по той же формуле.

### POST `/search/facet` → 200 `FacetResponse`

Для переоткрытия ранее выбранного уровня и поиска альтернатив клиент отправляет `{request_state_id: Id, root_id: Id, schema_set_version: Id, selected_marker_ids: Id[], query_text: string, facet_prefix: string}`. Цепочка содержит **только родителей** редактируемого уровня; текст — текущий применённый. Ответ: `{request_state_id: Id, root_id: Id, schema_set_version: Id, index_generation: Id, facet: Facet|null}`.

Это чтение отдельного списка: оно не меняет текущие selected markers, total, таблицу, сортировку или их freshness. Только выбор нового значения применяет укороченную цепочку плюс выбранное значение и отправляет обычный `/search`. У списка собственный scope/последний ID отправки; поздний ответ списка не влияет на таблицу. До применения counts открытого списка относятся к его явно показанным родителям и тексту; после применения все элементы основного search-ответа снова согласованы по одному поколению.

Ошибки обоих поисковых методов: 400 INVALID_QUERY, 422 INVALID_MARKER_SELECTION, 409 SCHEMA_VERSION_CHANGED или ROOT_NOT_READY, 503 SEARCH_UNAVAILABLE. Ошибка схемы требует перечитать корни и очистить несовместимые маркеры с уведомлением; текст можно сохранить для повторного запроса в том же корне. Успешный ответ `/search` всегда содержит один согласованный index_generation для items/total/facets.

## 5. Целевые каталоги

| Метод и путь | Запрос | Ответ |
|---|---|---|
| GET `/companies/{company_id}/target-directories` | `prefix?`, `cursor?`, `limit?≤100` | 200 Page<TargetDirectory> |
| POST `/companies/{company_id}/target-directories/resolve` | `{display_path: string}` | 200 TargetDirectory |

`TargetDirectory`: `{root_id: Id, relative_directory: RelativeDirectory, display_path: string}`. Выбор ограничен настроенными целями компании. Полный вымышленный путь `DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Reports` допустим только если соответствующий каталог существует в sandbox и разрешён. Несуществующая/недопустимая цель — 422 INVALID_TARGET; выход за корень — 422 PATH_OUTSIDE_ROOT. Resolver не создаёт каталоги.

## 6. Справочники и тестирование

`Rule`: `{rule_id: Id, priority: integer[1..1000], match_field: BASENAME|RELATIVE_PATH, mask: string[1..512], target: TargetReference, target_stem: string[1..200]}`. `TargetReference`: `{root_id: Id, relative_directory: RelativeDirectory}`. target_stem не является шаблоном и не содержит расширения по отдельному полю; при сохранении UI показывает пример итогового имени. Сервер проверяет допустимые символы, длину итогового basename и ограничения настроенного filesystem profile; не обрезает строку автоматически.

Для RELATIVE_PATH сопоставление идёт с путём относительно входящего источника, включая basename. Слеши обоих видов в **маске и match-значении** приводятся к `\` для matcher. Это отдельная семантика от API-путей, где канонический разделитель `/`. case-folding версионирован, без NFC/NFKC. `**` отклоняется, не считается вторым названием `*`.

`Dictionary`: `{dictionary_id: Id, company_id: Id, name: string, description: string, draft: DictionaryDraft, active_version_id: Id|null, versions_count: Count, updated_at: Instant, updated_by: Actor}`.

`DictionaryDraft`: `{draft_revision: Revision, rules: Rule[], based_on_version_id: Id|null}`. Имена/описание редактируются вместе с черновиком и тоже меняют draft_revision. `DictionaryVersion`: `{version_id: Id, dictionary_id: Id, version_number: Count, name: string, description: string, rules: Rule[], published_at: Instant, published_by: Actor, comment: string, restored_from_version_id: Id|null}`.

`RuleSet`: `{rule_set_id: Id, company_id: Id, members: [{dictionary_id: Id, version_id: Id}]}`. Список членов сортирован по dictionary_id; ID однозначно обозначает весь набор версий. В запросе партии клиент не выбирает members.

| Метод и путь | Запрос | Ответ / действие |
|---|---|---|
| GET `/companies/{company_id}/dictionaries` | — | 200 `{items: Dictionary[]}` |
| POST `/companies/{company_id}/dictionaries` | `{name: string[1..128], description: string[0..1000]}` | 201 Dictionary с пустым черновиком revision=0 |
| GET `/dictionaries/{dictionary_id}` | — | 200 Dictionary |
| PUT `/dictionaries/{dictionary_id}/draft` | `{expected_draft_revision: Revision, name: string, description: string, rules: Rule[]}` | 200 Dictionary; единая атомарная замена черновика, revision+1 |
| GET `/dictionaries/{dictionary_id}/versions` | cursor?, limit? | 200 Page<DictionaryVersion> |
| GET `/dictionaries/{dictionary_id}/versions/{version_id}` | — | 200 DictionaryVersion |
| POST `/dictionaries/{dictionary_id}/restore-draft` | `{version_id: Id, expected_draft_revision: Revision}` | 200 Dictionary; содержимое старой версии переносится в черновик, revision+1 |
| POST `/dictionaries/{dictionary_id}/simulate` | `{expected_draft_revision: Revision}` | 201 Simulation; без файловых операций |
| GET `/simulations/{simulation_id}` | cursor?, limit? | 200 Simulation с очередной страницей plan rows |
| POST `/dictionaries/{dictionary_id}/publish` | `{expected_draft_revision: Revision, simulation_id: Id, acknowledge_no_scenario: boolean, comment: string[1..500]}` | 201 `{dictionary: Dictionary, published_version: DictionaryVersion, rule_set: RuleSet}`; Idempotency-Key обязателен |

Имя уникально внутри компании после trim+casefold; конфликт — 409 DICTIONARY_NAME_CONFLICT. В черновике rule_id уникальны. Пустой набор rules допустим, но его эффект проверяется simulation и тем же подтверждением NO_SCENARIO. Delete/deactivate справочника как отдельные операции в демо отсутствуют; при необходимости убрать его правила публикуется пустая версия с явной проверкой последствий.

Simulation фиксирует ревизию черновика, полный текущий набор других версий и точный набор всех READY-файлов компании. Новый/изменённый READY-набор, изменение любого участника RuleSet или черновика инвалидируют результат. Ноль READY-файлов — валидный результат с warning `EMPTY_READY_SET`; он доказывает только структурную валидность правил, а не покрытие. UI явно показывает это перед публикацией.

`Simulation`: `{simulation_id: Id, dictionary_id: Id, draft_revision: Revision, base_rule_set: RuleSet, ready_snapshot_id: Id, created_at: Instant, expires_at: Instant, total: Count, counts: PlanCounts, warnings: string[], rows: PlanRow[], next_cursor: string|null}`. Тест охватывает весь набор, даже если rows показаны страницей. READY snapshot внутренних тестов не подменяется пользовательским selection snapshot.

`PlanRow`: `{item_id: Id, item_revision: Revision, source: Location, filename: string, company_id: Id, predicted_state: Prediction, reason_code: string|null, target: Location|null, matched_rules: RuleReference[], selected_rule: RuleReference|null, collision: CollisionDetails|null}`. `RuleReference`: `{dictionary_id: Id, version_id: Id|null, rule_id: Id}`; version_id=null только для тестируемого черновика. `Prediction`: WILL_MOVE | WILL_MANUAL_REVIEW | REQUIRES_DECISION | NOT_READY. `PlanCounts`: `{will_move: Count, will_manual_review: Count, requires_decision: Count, not_ready: Count, rule_conflicts: Count, no_scenario: Count}`; первые четыре образуют total, последние два — дополнительные счётчики причин, не прибавляются повторно.

`CollisionDetails`: `{kind: EXISTING_TARGET|DUPLICATE_PLAN_TARGET|MANUAL_REVIEW_NAME, source_metadata: FileMetadata, existing_target_metadata: FileMetadata|null, conflicting_item_ids: Id[]}`; `FileMetadata`: `{filename: string, location: Location, size_bytes: Count, modified_at: Instant}`. UI раскрывает метаданные только в сравнении коллизии. При повторяющейся цели внутри выбранной партии все участники коллизии остаются во входящих.

Конфликт правил всегда учитывается в counts.rule_conflicts и блокирует publish, даже если физическое действие в плановой строке — передача в ручной разбор. NO_SCENARIO требует acknowledge_no_scenario=true, связанное именно с simulation_id. Занятые цели показываются, но сами по себе не блокируют публикацию правил. Для отката версии используются restore-draft → simulate → publish; published_version.restored_from_version_id сохраняет происхождение. Любая ручная правка восстановленного черновика очищает based_on_version_id и превращает его в обычный новый кандидат.

## 7. Очередь, снимок выбора и preview

| Метод и путь | Запрос | Ответ |
|---|---|---|
| POST `/sorting/queue/query` | `{company_id: Id, filters: QueueFilters, cursor: string\|null, limit: integer[1..100]}` | 200 QueueResponse |
| POST `/sorting/selections` | SelectionRequest | 201 SelectionSnapshot |
| POST `/sorting/previews` | `{selection_id: Id}` | 201 Preview |
| GET `/sorting/previews/{preview_id}` | cursor?, limit? | 200 Preview с очередной страницей plan rows |

`QueueFilters`: `{statuses: QueueState[], query_text: string}`; пустой statuses означает все активные состояния очереди. query_text — case-insensitive подстрока имени/отображаемого входящего пути, не сложная поисковая грамматика. `QueueState`: DISCOVERED | WAITING_READY | READY | PROCESSING | REQUIRES_DECISION | RECOVERY_REQUIRED | MISSING. QUARANTINED, SORTED и MANUAL_REVIEW видны в своих списках/истории, не в обычной активной очереди. MISSING показывается только по явному фильтру.

`QueueItem`: `{item_id: Id, item_revision: Revision, company_id: Id, incoming_source_id: Id, source_name: string, source: Location, filename: string, size_bytes: Count, modified_at: Instant, status: QueueState, reason_code: string|null, selectable: boolean, active_attempt_id: Id|null}`. selectable=true только READY или REQUIRES_DECISION с подтверждённой стабильностью источника и без active claim. Клиент использует этот флаг, но сервер проверяет его повторно.

`QueueResponse`: `{queue_generation: Id, items: QueueItem[], matching_count: Count, eligible_count: Count, counters: {ready: Count, processing: Count, attention: Count}, status_counts: [{status: QueueState, count: Count}], next_cursor: string|null}`. counters и status_counts относятся ко всей выбранной компании; matching_count/eligible_count — к фильтрам. attention = REQUIRES_DECISION + RECOVERY_REQUIRED. Все значения одного ответа читаются из одного queue_generation. DISCOVERED/WAITING_READY отражаются в status_counts, но не завышают счётчик «Готовы».

`SelectionRequest` — oneOf:

```json
{"company_id":"company-demo-1","mode":"EXPLICIT","items":[{"item_id":"file-demo-1","item_revision":3}]}
```

```json
{"company_id":"company-demo-1","mode":"ALL_MATCHING","filters":{"statuses":["READY"],"query_text":""},"expected_eligible_count":120}
```

Для EXPLICIT items содержит 1…max_batch_items уникальных элементов одной компании. Для ALL_MATCHING сервер выбирает все доступные к запуску элементы по фильтрам, включая невидимые на странице. expected_eligible_count сверяет число, показанное оператору: расхождение при создании даёт 409 SELECTION_CHANGED и требует обновить выбор. После успешного создания новый приход не меняет снимок и не инвалидирует его сам по себе. Ноль элементов — 422 EMPTY_SELECTION; превышение лимита — 422 BATCH_LIMIT_EXCEEDED без усечения.

`SelectionSnapshot`: `{selection_id: Id, company_id: Id, mode: EXPLICIT|ALL_MATCHING, selected_count: Count, created_at: Instant, expires_at: Instant, queue_generation: Id}`. Полный список IDs/revisions хранит сервер; браузер не обязан пересылать его при запуске.

`Preview`: `{preview_id: Id, selection_id: Id, company_id: Id, rule_set: RuleSet, created_at: Instant, expires_at: Instant, total: Count, counts: PlanCounts, rows: PlanRow[], next_cursor: string|null}`. Preview привязан к снимку, ревизиям/метаданным исходников, RuleSet, рассчитанным целям и состоянию занятости. Он никогда не перемещает файлы. Материализация preview не продлевает истёкший selection; фактический expiry — минимум ограничений.

## 8. Запуск и результат партии

### POST `/sorting/batches` → 202 `Batch`

Idempotency-Key обязателен. Тело oneOf:

```json
{"selection_id":"selection-demo-1","execution_mode":"PREVIEWED","preview_id":"preview-demo-1"}
```

```json
{"selection_id":"selection-demo-1","execution_mode":"DIRECT"}
```

PREVIEWED требует свежий preview. DIRECT означает нажатое оператором «Рассортировать» без просмотра: сервер сам рассчитывает свежий план и preflight. Это не обход проверки и не автоматическая сортировка. Для DIRECT клиент не передаёт preview_id.

Просроченный снимок, изменение содержательных ревизий выбранных источников, неизвестные/чужие IDs или устаревший просмотр отклоняют запрос **до создания партии и любых файловых операций**. Изменение claim другим запуском рассматривается отдельно: сохраняется пофайловый ALREADY_PROCESSING, а остальные элементы могут быть приняты. Захват файла не меняет его содержательную item_revision. Для DIRECT опубликованный набор берётся на момент принятия, для PREVIEWED должен совпадать с preview.

После принятия состояние источника/цели всё равно проверяется непосредственно перед перемещением. Появившаяся занятая цель даёт пофайловый TARGET_OCCUPIED, а не перезапись. Файл, изменившийся после принятия партии, получает SOURCE_CHANGED без физической операции и возвращается к WAITING_READY.

Ошибки до принятия партии:

| Условие | HTTP / код |
|---|---|
| Неизвестный selection/preview ID | 404 NOT_FOUND |
| Selection/preview другой компании, чем их связанный запрос/пара | 409 INVALID_STATE |
| Существующий объект недоступен роли/профилю сессии | 403 FORBIDDEN |
| Истёк selection | 409 SELECTION_EXPIRED |
| Изменился или исчез выбранный источник в DIRECT | 409 SELECTION_CHANGED |
| В PREVIEWED изменились источники, правила, цели или истёк preview | 409 STALE_PREVIEW |
| preview относится к другому selection | 409 INVALID_STATE |
| Иной запуск уже claim-ит элемент, его метаданные не изменились | Принятие остальных допустимо; по этому элементу SKIPPED / ALREADY_PROCESSING |

Снимки и preview привязаны к создавшему пользователю: их использование другой сессией того же user_id допустимо, другим пользователем — 403 FORBIDDEN. Это защита персонального подтверждения запуска, не ограничение общего чтения очереди/партий и не ACL по компаниям.

`Batch`: `{batch_id: Id, company_id: Id, actor: Actor, selection_id: Id, preview_id: Id|null, rule_set: RuleSet, status: BatchState, created_at: Instant, started_at: Instant|null, finished_at: Instant|null, selected_count: Count, completed_count: Count, counts: OutcomeCounts, outcomes: Outcome[], next_cursor: string|null}`.

`BatchState`: ACCEPTED | RUNNING | COMPLETED | COMPLETED_WITH_ISSUES | RECOVERY_REQUIRED. Завершённая партия имеет completed_count=selected_count. При неизвестном результате хотя бы одного файла статус партии RECOVERY_REQUIRED, finished_at=null до ручного разрешения; completed_count учитывает только файлы с установленным итогом.

`OutcomeCounts`: `{sorted: Count, manual_review: Count, requires_decision: Count, quarantined: Count, skipped: Count, recovery_required: Count}`. Первые пять суммируются в completed_count; recovery_required — незавершённые неоднозначные исходы. Остаток selected_count включает ещё ожидающие/выполняющиеся файлы.

`Outcome`: `{attempt_id: Id, item_id: Id, item_revision: Revision, state: OutcomeState, reason_code: string|null, source: Location, planned_target: Location|null, actual_location: Location|null, matched_rule: RuleReference|null, started_at: Instant|null, finished_at: Instant|null}`. `OutcomeState`: PENDING | PROCESSING | SORTED | MANUAL_REVIEW | REQUIRES_DECISION | QUARANTINED | SKIPPED | RECOVERY_REQUIRED. actual_location=null если размещение не установлено. QUARANTINED допустим только после подтверждённого переноса в карантин.

Пофайловые reason_code: NO_SCENARIO, RULE_CONFLICT, TARGET_OCCUPIED, MANUAL_REVIEW_NAME_OCCUPIED, TECHNICAL_ERROR, ALREADY_PROCESSING, SOURCE_CHANGED, SOURCE_MISSING, RECOVERY_REQUIRED. Они описывают результат файла внутри принятой партии; HTTP-ответ на чтение партии остаётся 200.

| Метод и путь | Запрос | Ответ |
|---|---|---|
| GET `/sorting/batches/{batch_id}` | cursor?, limit? | 200 Batch с текущим прогрессом и страницей outcomes |
| GET `/sorting/batches` | company_id, cursor?, limit? | 200 Page<BatchSummary> |

`BatchSummary`: batch_id, company_id, actor, status, created_at, finished_at, selected_count, completed_count, counts — те же типы, что Batch. Список сортирован created_at DESC, batch_id DESC. Полный результат не зависит от текущего выделения в UI. Нет endpoint отмены партии, замены файла или общего undo в демо.

### Матрица фактических исходов

| Причина/ситуация | Файловый результат | Outcome.state |
|---|---|---|
| Единственная свободная разрешённая цель | Переименование + no-replace move | SORTED |
| Нет правила / конфликт правил | Move в плоский ручной разбор с исходным basename | MANUAL_REVIEW |
| Цель занята / совпала у выбранных файлов | Источник остаётся во входящих | REQUIRES_DECISION |
| Имя в ручном разборе занято | Источник остаётся во входящих | REQUIRES_DECISION |
| Другой запуск уже захватил файл | Этот запуск ничего не перемещает | SKIPPED, ALREADY_PROCESSING |
| Файл изменён/исчез после принятия | Нет операции со старой идентичностью | SKIPPED, SOURCE_CHANGED/SOURCE_MISSING |
| Технический сбой, источник найден, карантин доступен | Подтверждённый move в карантин | QUARANTINED |
| Положение файла неизвестно / безопасный карантин невозможен | Остановка этого файла, без слепого retry | RECOVERY_REQUIRED |

## 9. Карантин

| Метод и путь | Запрос | Ответ |
|---|---|---|
| GET `/quarantine` | company_id, cursor?, limit? | 200 Page<QuarantineItem> |
| POST `/quarantine/{quarantine_id}/return` | `{expected_revision: Revision, comment: string[1..500]}` + Idempotency-Key | 200 `{return_operation_id: Id, item: QueueItem}` |

`QuarantineItem`: `{quarantine_id: Id, revision: Revision, item_id: Id, company_id: Id, filename: string, location: Location, original_location: Location, reason_code: string, quarantined_at: Instant, source_attempt_id: Id, recovery_operation_id: Id|null, can_return: boolean}`. Хранение внутри карантина организует сервер, например отдельным attempt ID; это не плоский manual_review. Перед возвратом он заново проверяет исходный путь и идентичность файла. Если возврат стал неоднозначным, can_return=false, recovery_operation_id содержит зарегистрированную операцию.

Успешный item.status=WAITING_READY. Занятый исходный путь — 409 ORIGINAL_PATH_OCCUPIED без мутаций. Устаревшая expected_revision — 409 QUARANTINE_VERSION_CONFLICT, неизвестный ID — 404 NOT_FOUND, известная уже возвращённая запись при новом ключе — 409 INVALID_STATE. Неоднозначный сбой возврата — 409 RECOVERY_REQUIRED с ID зарегистрированной операции в error.operation_id; повтор ключа не вызывает второе перемещение. В демо нет API удаления и автоматического повторного запуска.

## 10. Журнал

POST `/audit/query` принимает `{company_id: Id|null, from: Instant, to: Instant, actor_id: Id|null, action: string|null, result: SUCCESS|ISSUE|FAILED|null, query_text: string, cursor: string|null, limit: integer[1..100]}`. Интервал `[from,to)`. Клиент превращает выбранные локальные даты в UTC по app-config; сервер проверяет порядок и допустимость интервала. query_text — подстрока имени/логического display path; чувствительные фильтры идут в теле и не журналируются.

Ответ 200: `{items: AuditEvent[], next_cursor: string|null, newest_event_id: Id|null}`. Cursor фиксирует верхнюю границу ленты и фильтры; новые записи не сдвигают выдачу. GET `/audit/updates?after_event_id=...` возвращает `{has_new_events: boolean}` без текстов фильтров; индикатор может сообщать о новых событиях вне текущего фильтра, обновление повторяет текущий query. Первичный пустой журнал передаёт null как отсутствие нижней границы через отсутствие параметра.

GET `/audit/actors?prefix=...&cursor=...&limit=...` → 200 Page<Actor>. Это источник вариантов фильтра по автору, включая заблокированных пользователей, у которых есть доступные вызывающему события. prefix — начало login/отображаемого имени без учёта регистра, limit≤100. Полный каталог аккаунтов и административные полномочия через этот метод не предоставляются. В фильтре передаётся actor.user_id; Actor в событии хранит снимок отображаемого имени на момент действия.

`AuditEvent`: `{event_id: Id, occurred_at: Instant, actor: Actor|null, category: BUSINESS|SYSTEM, action: string, result: SUCCESS|ISSUE|FAILED, request_id: Id, operation_id: Id|null, source_attempt_id: Id|null, company_id: Id|null, dictionary_id: Id|null, version_id: Id|null, rule_set_id: Id|null, batch_id: Id|null, attempt_id: Id|null, item_id: Id|null, source: Location|null, target: Location|null, reason_code: string|null, comment: string|null}`. actor=null допустим только для системного события без пользовательского инициатора, никогда для принятия партии/публикации/возврата. Для возврата operation_id равен return_operation_id, source_attempt_id связывает его с исходной попыткой сортировки. Для обычной пофайловой операции operation_id может совпадать с attempt_id; соответствие фиксируется сервером и неизменно.

action — закрытый enum OpenAPI: DICTIONARY_CREATED, DRAFT_SAVED, DICTIONARY_SIMULATED, DICTIONARY_PUBLISHED, DICTIONARY_RESTORED, BATCH_ACCEPTED, FILE_ATTEMPT_STARTED, FILE_ATTEMPT_FINISHED, QUARANTINE_RETURNED, RECOVERY_REQUIRED, LOGIN_SUCCEEDED, LOGIN_FAILED, LOGOUT, ACCOUNT_BLOCKED. Рабочей роли сервер возвращает только BUSINESS; администратор видит обе категории.

Одна партия имеет событие принятия; каждая попытка — начало и конечный результат либо RECOVERY_REQUIRED. Unique event key по attempt/phase предотвращает дубли событий при восстановлении. Последующее разрешение неопределённости добавляет событие, не исправляет исходное. Просмотр/копирование/поиск не создают BUSINESS-событий.

## 11. Единый формат ошибок

```json
{
  "error": {
    "code": "STALE_PREVIEW",
    "message": "Данные изменились. Выполните проверку повторно.",
    "request_id": "request-demo-1",
    "operation_id": null,
    "retryable": false,
    "field_errors": []
  }
}
```

`field_errors`: `{field: string, code: string, message: string}[]`; без эха сырого пароля, пути хоста или полного запроса. `operation_id: Id|null` обязателен: null, если операция не была создана; ID зарегистрированной операции при неоднозначном возврате/восстановлении. retryable означает возможность технически повторить безопасный запрос без изменения условий; новый расчёт/ручное решение — false. После сетевого таймаута мутации применяется политика §2: поддерживающая идемпотентность операция повторяется с прежним ключом; для остальных сначала перечитывается состояние, автоматической повторной записи нет.

| HTTP | error.code | Реакция клиента |
|---|---|---|
| 400 | INVALID_QUERY | Сохранить ввод, подсветить синтаксис |
| 401 | LOGIN_FAILED | Общее сообщение формы входа |
| 401 | UNAUTHENTICATED | Очистить приватное состояние, открыть вход |
| 403 | FORBIDDEN / CSRF_FAILED | Не повторять запись автоматически; показать безопасную причину |
| 404 | NOT_FOUND | Перечитать соответствующий список |
| 409 | DRAFT_VERSION_CONFLICT / DICTIONARY_NAME_CONFLICT / QUARANTINE_VERSION_CONFLICT | Не перезаписывать; показать конфликт и обновить данные |
| 409 | STALE_SIMULATION / STALE_PREVIEW / SELECTION_EXPIRED / SELECTION_CHANGED | Повторить выбор/тест/расчёт по явному действию |
| 409 | SCHEMA_VERSION_CHANGED / ROOT_NOT_READY | Обновить корни и несовместимую навигацию |
| 409 | RULE_CONFLICT / NO_SCENARIO_ACK_REQUIRED | Исправить правила либо подтвердить отсутствие покрытия точного теста |
| 409 | ORIGINAL_PATH_OCCUPIED / RECOVERY_REQUIRED | Оставить файл, показать причину и ручной порядок действий |
| 409 | IDEMPOTENCY_KEY_REUSED / INVALID_STATE | Не повторять с новым телом/состоянием вслепую |
| 422 | VALIDATION_ERROR / INVALID_MARKER_SELECTION / INVALID_TARGET / PATH_OUTSIDE_ROOT / EMPTY_SELECTION / BATCH_LIMIT_EXCEEDED | Показать ошибку поля или допустимый предел |
| 429 | RATE_LIMITED | Учесть Retry-After, не повторять немедленно |
| 503 | SEARCH_UNAVAILABLE / SERVICE_UNAVAILABLE | Сохранить условия, обозначить устаревшие данные, предложить повтор |
| 500 | INTERNAL_ERROR | Без технических подробностей; request_id для разбора |

Сессия/CSRF, формат запроса и безопасная ошибка применяются ко всем подходящим операциям, даже если не повторены в каждой строке таблиц. HTTP 200/201/202 не используются для замаскированной ошибки запроса. Пер-файловая ошибка после принятой партии остаётся Outcome, а не отменяет историю всей партии.

## 12. Что Frontend сдаёт как контракт

- OpenAPI с operationId, required/nullability, enums, oneOf, security, Idempotency-Key, pagination и всеми HTTP-ответами.
- `contracts/examples/`: валидный запрос/ответ успеха и каждого значимого отрицательного исхода для каждого экрана; синтетические значения согласованы между файлами.
- `frontend/src/api/generated/`: сгенерированные типы и клиент; воспроизводимая команда генерации.
- `frontend/src/mocks/`: сценарии загрузки, нуля, ограничения, ошибки, истечения сессии, устаревшего preview, конкуренции и всех исходов файла.
- `tests/contract/`: проверка схем примеров и реального API, отсутствие неразрешённых ссылок и дублирующихся operationId, negative request cases.
- Запись версии контракта и краткий журнал изменений. В функциональных компонентах нет вручную дублированных DTO или скрытых преобразований несовместимого ответа.

Критерий готовности: QA может сопоставить каждое действие экрана с операцией, полями и ожидаемым исходом; Backend реализует API без догадок; при переключении имитации на сервер меняется только настройка транспорта. Проверка синтаксиса YAML сама по себе этот критерий не закрывает.
