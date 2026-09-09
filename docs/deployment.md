# Docker и CI/CD

Профиль: один Linux-сервер, локальная файловая система, до 50 пользователей. Это инфраструктура текущего синтетического backend; она не подключает корпоративное хранилище или SSO.

## Устройство

`gateway` завершает TLS; `api` слушает `127.0.0.1:8000` в сетевом пространстве gateway. Наружу опубликован только HTTPS. `worker` и административный `cli` работают без сети. Такое разделение сохраняет проверку локального proxy в приложении; nginx заменяет входящие forwarded headers.

Все сервисы работают как UID/GID `10001:10001`, с read-only rootfs и без Linux capabilities. API и worker получают только state и sandbox; backup доступен только CLI. Весь sandbox должен быть одним bind mount на одной локальной файловой системе. Другие процессы не должны менять его содержимое.

Образы Python/Alpine, uv и nginx закреплены digest; Python-зависимости — `uv.lock`, setuptools — точной версией. В runtime нет pip, setuptools, uv, тестов, Git или исходных документов. Лимиты Compose: API/worker по 1 GiB RAM и 2 CPU, gateway 128 MiB и 0,5 CPU; это ограничения контейнеров, не подтверждение пропускной способности сервера.

## Первый запуск

Нужны Docker Engine с Compose v2, Python 3.11+ для host-скриптов и действующий TLS-сертификат. Выполняйте команды из одной фиксированной установки `/opt/wiseway`. Оператор с доступом к Docker имеет привилегии администратора сервера.

```sh
cp infra/env/compose.env.example .env
chmod 600 .env
sudo install -d -o 10001 -g 10001 -m 0700 /var/lib/wiseway/state /srv/wiseway/sandbox /var/backups/wiseway
sudo install -d -o root -g 10001 -m 0750 /etc/wiseway/tls
```

Разместите сертификат как `/etc/wiseway/tls/fullchain.pem` и ключ как `privkey.pem`: владелец root, группа 10001, права 0640. Каталог с сертификатами монтируется целиком, чтобы обновление файлов было видно nginx. Не храните ключи в Git.

В `.env` укажите реальные абсолютные пути и `WISEWAY_ORIGINS`: сначала HTTPS-origin API, затем при необходимости отдельный origin frontend через запятую, без пути и завершающего slash. Укажите точный образ `ghcr.io/OWNER/REPOSITORY@sha256:DIGEST`, полученный из release workflow. Для локальной сборки можно оставить `wiseway:local`:

```sh
docker build --tag wiseway:local .
docker compose config --quiet
docker compose run --rm cli init-demo
docker compose up -d --wait --wait-timeout 150 api worker
python3 infra/scripts/compose_ops.py check
```

Для опубликованного образа вместо build выполните `docker compose pull`. Для приватного GHCR предварительно войдите в registry с токеном только на чтение пакетов через `docker login --password-stdin`. Пароль аккаунтов вводится интерактивно в `init-demo`; не передавайте его через `.env` или аргументы процесса. Инициализация создаёт только синтетические данные и не запускается автоматически при рестарте.

`docker compose run --rm cli` позволяет выполнять `status`, `doctor`, `create-user`, `reset-password`, `block-user`, `unblock-user` и `recover`. Управление аккаунтами требует `--actor` активного ADMIN. Для автоматизированного ввода пароля предусмотрен `--password-stdin`.

## Проверки и журналирование

```sh
docker compose ps
docker compose logs --tail 100 api worker gateway
python3 infra/scripts/compose_ops.py check
docker compose run --rm cli status
```

HTTP `/api/v1/health` проверяет доступность API. Полная локальная проверка `doctor` дополнительно проверяет SQLite, файловый адаптер, failed indexes и heartbeat worker; при `ready: false` exit code равен 1. Контейнерный healthcheck сочетает HTTP и doctor. `unhealthy` сам по себе не перезапускает контейнер: политика `unless-stopped` перезапускает завершившийся процесс. Разбирайте причину, а не добавляйте бесконечный autoheal.

Контейнерные логи ротируются драйвером `local`: 5 файлов по 10 MiB на сервис. HTTP access log отключён; ошибки приложения содержат request ID и класс ошибки. Бизнес-аудит хранится отдельно в SQLite и автоматически не удаляется. `status` показывает операции, требующие ручного восстановления; один только healthy не означает их отсутствие.

Для периодической проверки и почасовых полных копий можно установить host timers:

```sh
sudo install -m 0644 infra/systemd/wiseway-compose-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wiseway-compose-check.timer wiseway-compose-backup.timer
sudo journalctl -u wiseway-compose-check -u wiseway-compose-backup
```

Timers используют `/opt/wiseway/.env`. Подключите уведомления о failed units к принятой системе мониторинга. Проверяйте свободное место state/sandbox/backups, возраст последней успешной копии, heartbeat и RECOVERY_REQUIRED. Одновременные операции защищены lock-файлом установки; проверка во время backup может сообщить о занятом lock — учитывайте окно обслуживания.

## Полная резервная копия

```sh
python3 infra/scripts/compose_ops.py snapshot snapshot-20260909T120000Z
```

Команда останавливает API/worker, создаёт согласованную копию `data/` и `sandbox/` в новом подкаталоге backups, затем возвращает только ранее работавшие сервисы. **Во время копирования API недоступен.** Snapshot проверяет SQLite, завершённую инициализацию, файлы и пустые каталоги; manifest содержит SHA-256. Ссылки, специальные файлы, существующее назначение и незавершённые durable-операции отклоняются. При таком отказе разберите `status`, завершите обработку и повторите копирование под новым именем.

Прямой `snapshot.py` не блокирует приложения: вызывайте его только через orchestration либо после самостоятельной остановки всех писателей. После аварийного прерывания host-команды убедитесь, что временный CLI-контейнер больше не копирует файлы, прежде чем запускать API/worker.

Копии не удаляются автоматически. Переносите завершённые snapshot в отдельное защищённое хранилище и проверяйте восстановление оттуда. Хэши обнаруживают повреждение, но не заменяют шифрование и защиту от администратора, способного переписать и данные, и manifest. Почасовой timer не гарантирует RPO ≤1 часа при failed backup; RTO ≤4 рабочих часов требуется измерить на реальном объёме.

## Восстановление и обновление

Восстановление всегда идёт в новый каталог, исходные данные сохраняются:

```sh
docker compose stop api worker
python3 infra/scripts/compose_ops.py restore snapshot-20260909T120000Z restored-20260909
```

После проверки выберите в `.env` пути `/var/backups/wiseway/restored-20260909/data` и `/var/backups/wiseway/restored-20260909/sandbox`. Для длительной эксплуатации можно сначала перенести эти каталоги в отдельное рабочее место; сохраните права 10001:10001 и не размещайте рабочие данные внутри исходного snapshot. Запускайте совместимый образ:

```sh
docker compose up -d --force-recreate --wait --wait-timeout 150 api worker
python3 infra/scripts/compose_ops.py check
```

Восстановление возвращает состояние аккаунтов и сессий на момент копии. При восстановлении после компрометации сбросьте пароли/заблокируйте затронутые аккаунты до открытия доступа. Worker заново проверяет метаданные; незавершённые операции намеренно запрещены при создании snapshot, поскольку копирование меняет inode.

Обновление: сначала загрузите новый образ по digest, остановите API/worker, создайте snapshot приведённой командой — уже остановленные сервисы она не запустит. Сохраните старый digest. Измените `WISEWAY_IMAGE` в `.env`, выполните `up --force-recreate --wait`, затем check и короткий тест входа/поиска. Миграции выполняются при запуске.

При неудаче остановите новые API/worker. Не откатывайте только образ поверх изменившейся схемы без подтверждённой совместимости. Безопасный путь — восстановить предшествующий snapshot в новые каталоги, выбрать старый digest и проверить запуск. Изменения после момента snapshot при таком откате будут потеряны. Gateway и API разделяют сетевое пространство: при обновлении gateway обязательно пересоздавайте API вместе с ним.

## Pipeline

- `ci.yml`: push/PR вызывает `verify.yml` на Ubuntu 24.04.
- Verify: frozen install, Ruff, весь pytest/JUnit, wheel/sdist, аудит runtime/dev/build-зависимостей, сборка образа, Trivy HIGH/CRITICAL для ОС и библиотек обоих образов (приложение и gateway) и настоящий TLS Compose smoke с сортировкой, рестартом и полным восстановлением. Ошибка сканирования тоже блокирует выпуск; отчёты сохраняются как artifacts.
- `release.yml`: ручной запуск с версией из `pyproject.toml`; сначала выполняется verify, затем образ публикуется в GHCR с version/SHA refs, SBOM/provenance и выводом digest. Production использует digest. Релиз не выполняет SSH/deploy на сервер.

Для `main` включите обязательные успешные checks из `verify.yml` после первого запуска CI. Для повторного выпуска увеличьте версию: workflow запрещает перезаписывать опубликованные refs. GitHub-hosted проверки и публикация выполнятся после отправки изменений и запуска workflow; наличие YAML не означает успешный remote run.

`.github/CODEOWNERS` назначает `@Timofey121` владельцем всех файлов. После добавления файла в `main` включите в правилах ветки `Require a pull request before merging`, минимум одно одобрение, `Require review from Code Owners` и `Dismiss stale pull request approvals when new commits are pushed`. Сам файл CODEOWNERS только назначает reviewer; обязательность обеспечивает правило GitHub. Для собственных PR владельца оставьте административный bypass разрешённым: `Do not allow bypassing the above settings` выключен. Права Admin должны оставаться только у `Timofey121`; остальным участникам достаточно Write. Тогда чужие PR требуют его review, а свои он может объединять административным обходом — автор не может одобрить собственный PR. Эти настройки GitHub не применяются автоматически локальным коммитом. [Документация CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).

Локальное воспроизведение контейнерной проверки:

```sh
docker build --tag wiseway:ci .
bash infra/scripts/container-smoke.sh wiseway:ci
```

Скрипт создаёт собственные временные каталоги, self-signed сертификат и отдельный Compose project, а затем удаляет их. Он не использует `.env` рабочей установки. Self-signed TLS предназначен только для этого теста.

Справка по использованным механизмам: [Compose services](https://docs.docker.com/reference/compose-file/services/), [uv в Docker](https://docs.astral.sh/uv/guides/integration/docker/). Альтернативный запуск без Docker описан в [operations.md](operations.md); не запускайте оба варианта над одной рабочей БД одновременно.
