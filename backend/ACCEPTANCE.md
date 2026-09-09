# Матрица приёмки синтетического демо

Первичный scope: `07_ACCEPTANCE_MATRIX.md`. Уровни: `S` — схема/статическая проверка; `M` — mock/UI; `A` — настоящий API и серверная/файловая проверка; `E` — сквозной UI → настоящий API. Статусы: `NOT_RUN/PASS/FAIL/BLOCKED`. `PASS` допустим лишь при полном точном сценарии; частичное покрытие не повышает статус строки. Frontend, mock и browser/E2E отсутствуют: требуемые `M`/`E` — `NOT_RUN`; для UI-only это неприменимость backend, не его отказ.

| ID / исходный scope / уровни | S | M | A | E | Доказательство или причина |
|---|---:|---:|---:|---:|---|
| Q-001 · AUTH-01/02/04/05, NFR-05 · S/M/A/E | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | `test_api.py`, `test_storage_auth.py` покрывают части; полный параметрический вход/авторство не пройден |
| Q-002 · AUTH-03, AUD-01/02 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Части logout/block: `test_api.py`, `test_storage_auth.py`; единый сценарий не пройден |
| Q-003 · AUTH-03, SRCH-17, AUD-03, NFR-06 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Нет единого сценария expiry + 503/500 + потеря ответа сохранения |
| Q-004 · SRCH-01 · S/M/A/E | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | Части IDLE: `test_search.py`; два корня и UI/API параметры не пройдены |
| Q-005 · SRCH-02/10/11/17 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | UI request_state и сбросы не проверены |
| Q-006 · SRCH-03/04/06/13 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Unit-покрытие не заменяет UI/API параметрический сценарий |
| Q-007 · SRCH-04/07 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Эталон ID/порядка проверен через функцию и API (`test_search_golden.py`); полная исходная комбинация параметров отдельно не оформлена |
| Q-008 · SRCH-08 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Фразы и смешанные запросы проверены через API (`test_search_golden.py`); требуется отдельная фиксация всего исходного приёмочного сценария |
| Q-009 · SRCH-07 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | `test_search.py` покрывает части; полный набор разделителей/API/golden не пройден |
| Q-010 · SRCH-09 · S/M/A/E | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | UI-дедупликация/request_state не проверены |
| Q-011 · SRCH-04/13/25, NFR-06 · A/E | — | — | NOT_RUN | NOT_RUN | Ranking/порядок проверены эталоном и тестами поколений; совмещённый протокол исходного сценария не оформлен |
| Q-012 · SRCH-05/19/20/21 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Части: `test_search.py`; требуемые уровни не пройдены |
| Q-013 · SRCH-12/14 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Нет корпуса `L+3` и UI-проверки полей |
| Q-014 · SRCH-22/24, NFR-04 · A/E | — | — | NOT_RUN | NOT_RUN | `test_indexer_regressions.py` покрывает части; весь внешний набор не пройден |
| Q-015 · DICT-01…07 · S/M/A/E | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | `test_rules.py` покрывает части; полный typed Rule round-trip не пройден |
| Q-016 · DICT-01/08 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | `test_dictionaries.py` покрывает конфликт; UI сценарий не пройден |
| Q-017 · DICT-02/09/10 · A/E | — | — | NOT_RUN | NOT_RUN | Simulation покрыта частично; полный READY-набор/параметры не пройдены |
| Q-018 · DICT-03/06/10/12 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Части conflict/stale: `test_dictionaries.py`; весь сценарий не пройден |
| Q-019 · DICT-10 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Acknowledge покрыт частично; UI/границы комментария не единым прогоном |
| Q-020 · DICT-01/11/12 · S/M/A/E | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | Нет полного publish/history/accepted-batch сценария |
| Q-021 · DICT-11, FILE-09 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Части restore: `test_dictionaries.py`; restore→simulate→publish не пройден |
| Q-022 · QUEUE-01/02/04 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | `test_indexer.py` покрывает готовность; UI/счётчики не единым сценарием |
| Q-023 · QUEUE-03/05/10 · S/M/A/E | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | Preview покрыт частично; полный scope не пройден |
| Q-024 · QUEUE-03 · A/E | — | — | PASS | NOT_RUN | `test_bulk_acceptance.py`: 120 файлов со всех страниц выбраны и реально обработаны; точные ID/outcomes, 0 и 1001 отклоняются без частичной записи/перемещения |
| Q-025 · QUEUE-03 · A/E | — | — | PASS | NOT_RUN | `test_bulk_acceptance.py`: SELECTION_CHANGED при устаревшем count; поздний файл и новый запрос с другим фильтром не меняют snapshot; исходные 120 ID доходят до итогов |
| Q-026 · QUEUE-06, DICT-12 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Части stale: `test_final_review.py`; все зависимости/TTL не пройдены |
| Q-027 · QUEUE-04/06, FILE-08 · S/M/A/E | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | Части DIRECT/source changed: `test_worker.py`; полный scope не пройден |
| Q-028 · QUEUE-07/10, NFR-07 · A/E | — | — | NOT_RUN | NOT_RUN | `test_concurrent_batches.py` частичный: доказательство требуемого полного сценария не оформлено |
| Q-029 · QUEUE-09, AUD-01/02 · S/A/E | NOT_RUN | — | NOT_RUN | NOT_RUN | Части: `test_processes.py`, `test_quarantine.py`; три операции/потеря ответа не пройдены |
| Q-030 · QUEUE-08, AUTH-03, NFR-07 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Части restart/logout: `test_processes.py`; UI polling/зритель не пройдены |
| Q-031 · FILE-03, QUEUE-10 · A/E | — | — | NOT_RUN | NOT_RUN | Нет mixed-batch с повтором порядка ID |
| Q-032 · FILE-01/02/08 · A/E | — | — | NOT_RUN | NOT_RUN | Части no-replace: `test_filesystem.py`; оба параметра не пройдены |
| Q-033 · FILE-01, SRCH-24, AUD-01 · A/E | — | — | NOT_RUN | NOT_RUN | Части: `test_workflows.py`; полный индекс/поиск/аудит не пройден |
| Q-034 · FILE-04 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Manual review покрыт частично; два исхода/UI не пройдены |
| Q-035 · FILE-05 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Occupied manual target покрыт частично; UI/параметры не пройдены |
| Q-036 · FILE-06, AUD-01/02 · A/E | — | — | PASS | NOT_RUN | `test_mixed_acceptance.py`: контролируемый технический отказ, реальный карантин, исходник отсутствует, checksum сохранён; TECHNICAL_ERROR и автор в исходе/аудите |
| Q-037 · FILE-06/09, AUD-01 · A/E | — | — | NOT_RUN | NOT_RUN | Recovery покрыт частично; все варианты размещения не пройдены |
| Q-038 · FILE-07, QUEUE-01 · M/A/E | — | NOT_RUN | NOT_RUN | NOT_RUN | Return покрыт частично; весь набор параметров не пройден |
| Q-039 · QUEUE-10, FILE-02/04/06, AUD-01 · A/E | — | — | PASS | NOT_RUN | `test_mixed_acceptance.py`: четыре исхода/точные причины в одной партии, counts и завершение, checksum, одно начало/завершение на попытку; повтор worker без мутаций |
| Q-040 · FILE-09, NFR-06 · A/E | — | — | NOT_RUN | NOT_RUN | `test_processes.py` — restart; `test_mixed_acceptance.py` — rollback записи завершения/аудита после rename, затем recovery без второго move. Все исходные процессные failpoints вместе не пройдены |
| Q-041 · AUD-01…05 · S/A/E | NOT_RUN | — | NOT_RUN | NOT_RUN | `test_audit_updates.py`, `test_processes.py` покрывают части; полный журнал/фильтры не пройдены |
| Q-042 · SRCH-15/16/18, NFR-01 · M/E | — | NOT_RUN | — | NOT_RUN | Только UI/браузер; backend неприменим |
| Q-043 · AUTH-02, NFR-05; контракт 02 целиком · S/M/A | NOT_RUN | NOT_RUN | NOT_RUN | — | Части: `test_contract.py`, `test_api.py`; mock/полная контрактная приёмка не пройдены |
| Q-044 · FILE-08, DICT-07, AUTH-02 · S/A/E | FAIL | — | FAIL | NOT_RUN | `test_filesystem_race_review.py`: post-check symlink подмена может переместить entry внутри открытого каталога; `RECOVERY_REQUIRED` защищает восстановление, но строгий инвариант «ссылки не допускаются» не доказан |
| Q-045 · SRCH-23, NFR-02/03/04/06 · S/A/E | NOT_RUN | — | FAIL | NOT_RUN | Повторно 250/250 успешных HTTP; p95 типового поиска 2231,308 мс > 2000 мс. Оптимизация исключена пользователем, SLA остаётся незакрытым (VALIDATION.md) |

Новые backend-regression тесты не перенумеровывают исходные Q-ID: `test_pagination_retention.py`, `test_read_concurrency.py`, `test_response_validation_cache.py`, `test_auth_hardening.py`, `test_index_read_cache.py`, `test_index_failure_review.py`, `test_matching_review.py`, `test_review_regressions.py`.
