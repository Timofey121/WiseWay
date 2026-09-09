# Эксплуатация одного сервера

Этот документ описывает текущую синтетическую поставку для одного Linux-сервера и не более 50 пользователей. Запускайте API и worker отдельными постоянно перезапускаемыми службами от выделенного непривилегированного пользователя. Он один владеет каталогами состояния и sandbox; другие процессы и пользователи не должны менять файлы внутри sandbox.

## Развёртывание

На сервере нужны Python 3.11+ и `uv`. Разместите зафиксированную ревизию в `/opt/wiseway` (код доступен сервису только для чтения). Из корня репозитория:

```sh
uv sync --frozen --no-dev
sudo useradd --system --home /var/lib/wiseway --shell /usr/sbin/nologin wiseway
sudo install -d -o wiseway -g wiseway -m 0700 /var/lib/wiseway/state /srv/wiseway/sandbox /var/backups/wiseway
sudo install -d -o root -g wiseway -m 0750 /etc/wiseway
sudo install -o root -g wiseway -m 0640 infra/env/wiseway.env.example /etc/wiseway/wiseway.env
sudo install -m 0644 infra/systemd/wiseway-* /etc/systemd/system/
```

В `/etc/wiseway/wiseway.env` замените origin на настоящий HTTPS-домен. Настройте сертификат и proxy по `infra/nginx/wiseway.conf.example`; проверьте конфигурацию через `nginx -t`. Инициализируйте синтетические данные и запустите службы:

```sh
sudo -u wiseway sh -c 'set -a; . /etc/wiseway/wiseway.env; set +a; exec /opt/wiseway/.venv/bin/wiseway init-demo'
sudo systemctl daemon-reload
sudo systemctl enable --now wiseway-api.service wiseway-worker.service wiseway-backup.timer
sudo -u wiseway sh -c 'set -a; . /etc/wiseway/wiseway.env; set +a; exec /opt/wiseway/.venv/bin/wiseway doctor'
```

Дальнейшие команды `wiseway` выполняйте от этого же пользователя с тем же env-файлом. В примерах ниже `uv run` предполагает такое окружение и рабочий каталог `/opt/wiseway`. Журналы служб доступны через `journalctl -u wiseway-api -u wiseway-worker`; проверяйте также ошибки `wiseway-backup.service`. Срабатывание timer само по себе не подтверждает успешную копию.

`WISEWAY_TRUST_PROXY_HEADERS=true` допустим только при loopback-привязке API и reverse proxy на том же сервере. Proxy завершается TLS, передаёт только ожидаемые forwarded headers (включая `X-Forwarded-For`) и не предоставляет API напрямую извне. Без него приложение не принимает proxy headers. Worker запускается отдельно: `uv run wiseway worker`.

Перед открытием доступа проверьте `uv run wiseway doctor`; после запуска worker он должен показывать `ready: true`. Порог устаревания heartbeat задаёт `WISEWAY_WORKER_STALE_SECONDS` (минимум 60, по умолчанию 900). `wiseway status` показывает failed indexes и незавершённые recovery; `wiseway recover ATTEMPT_ID` применяют только после проверки фактического расположения файла.

Локальные учётные записи управляются только оператором сервера: `create-user`, `reset-password`, `block-user`, `unblock-user`, каждый с `--actor` активного ADMIN. Пароль читается из prompt или через `--password-stdin`, не из аргумента командной строки. Смена пароля и блокировка отзывают сессии; разблокировка не оживляет старые сессии.

Вход ограничен 10 попытками в минуту для пары IP + логин и 100 для одного IP. Это позволяет работать нескольким пользователям за общим NAT. Превышение возвращает `429 RATE_LIMITED`; повторяют запрос после указанной задержки.

## Резервное копирование и восстановление

Каждый час создавайте новую резервную копию SQLite вне state и sandbox, например `uv run wiseway backup /var/backups/wiseway/wiseway-YYYYMMDDHH.sqlite3`. Команда создаёт новый файл и проверяет его целостность. Она не архивирует sandbox: для восстановления бизнес-состояния резервируйте sandbox согласованно с базой и проверяйте процедуру на отдельном хосте.

Для каждой резервной копии запускайте `uv run wiseway restore-check BACKUP DESTINATION` с новым пустым destination. Команда проверяет копию базы; она не переключает рабочий сервер и не восстанавливает файлы. Автоматического retention нет: оператор определяет срок, шифрование, доступ и удаление копий.

Периодически проверяйте восстановление на отдельном хосте: используйте согласованную копию базы и sandbox, до запуска worker проверьте незавершённые операции и расположение файлов. Не запускайте worker со старой базой над текущими файлами: он может продолжить записанные задания. `restore-check` проверяет только базу; последующий `doctor` не доказывает согласованность файлов. Полное восстановление требует отдельного проверенного сценария резервирования файлов.

Цель процесса — RPO до 1 часа и RTO до 4 рабочих часов. Эти значения достижимы только при успешных почасовых backup и проверенной процедуре восстановления sandbox вместе с базой; они не являются встроенной гарантией.

## Границы текущей поставки

SQLite, локальные аккаунты, filesystem executor и sandbox остаются синтетической демонстрацией. Перед подключением реального хранилища или реальных пользователей требуется отдельная фаза: модель владения данными, резервирование согласованных файлов, мониторинг, TLS/proxy review, политика retention и проверка аварийного восстановления. Не переносите рабочие данные в demo sandbox и не используйте shared/network filesystem: перемещения требуют одной локальной файловой системы и атомарного no-replace rename.
