# Фаза 5 — Деплой на VPS

Решение человека 2026-09-23: Streamlit Community Cloud не подходит (репозиторий
организации требует admin и одобрения владельца организации; репозиторий
приватный → приложение приватное, одно на аккаунт, жюри по приглашениям;
Python 3.9 недоступен; сон через 12 ч). Разворачиваем на VPS человека
(Linux + Docker, свой домен), интерфейс остаётся на Streamlit.

По AGENTS.md конфиги деплоя и файлы окружения меняются только с согласия
человека — согласие получено (утверждён план деплоя).

**Порядок:** фаза делается **последней** (решение человека 2026-09-23) —
после фазы 3 (включая задачу R) и README. Не начинать без отдельной команды.

## Схема

```
браузер ──https──► caddy (80/443, Let's Encrypt, basic_auth) ──► app:8501 (Streamlit)
                   └─ docker compose, сеть по умолчанию, порт app наружу не публикуется
```

Код на сервер попадает через `rsync` с Mac (серверу не нужен доступ к
приватному GitHub). Секреты — только в `deploy/.env` на сервере.

## Файлы

| Файл | Содержание |
|---|---|
| `Dockerfile` | `FROM python:3.12-slim`; `WORKDIR /app`; сначала `COPY requirements.txt` + `pip install --no-cache-dir -r requirements.txt` (кэш слоёв); затем **отдельная строка на каждый каталог** (`COPY app ./app`, `COPY data ./data`, `COPY tests ./tests`, `COPY .streamlit ./.streamlit`, `COPY pytest.ini ./`) — несколько каталогов в одном `COPY` склеиваются в одну кучу и ломают структуру; `EXPOSE 8501`; `CMD ["streamlit", "run", "app/ui/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]` |
| `.dockerignore` | `.venv`, `.git`, `__pycache__`, `.pytest_cache`, `deploy/`, `*.pyc` |
| `.streamlit/config.toml` | `[server]` `headless = true`; `[browser]` `gatherUsageStats = false` |
| `deploy/docker-compose.yml` | `app`: `build: ..` (контекст — корень репозитория), `restart: unless-stopped`, **без `ports`**. `caddy`: `image: caddy:2`, `ports: ["80:80", "443:443"]`, `volumes: ./Caddyfile:/etc/caddy/Caddyfile:ro`, `caddy_data:/data`, `caddy_config:/config`, `env_file: .env`, `depends_on: [app]`, `restart: unless-stopped`. Тома `caddy_data`, `caddy_config` объявить. |
| `deploy/Caddyfile` | `{$DOMAIN} {` / `basic_auth {` / `{$BASIC_AUTH_USER} {$BASIC_AUTH_HASH}` / `}` / `reverse_proxy app:8501` / `}` |
| `deploy/.env.example` | `DOMAIN=autozakaz.example.com`, `BASIC_AUTH_USER=jury`, `BASIC_AUTH_HASH='...'` + комментарии: хэш — `docker run --rm caddy:2 caddy hash-password --plaintext '<пароль>'`; **значение в одинарных кавычках** (в bcrypt-хэше есть `$`); сам пароль в файл не писать |
| `deploy/deploy.sh` | запускается на Mac из корня репозитория; `set -euo pipefail`; требует `VPS_HOST`, `VPS_USER` (понятная ошибка, если не заданы); `REMOTE_DIR=${REMOTE_DIR:-/opt/avtozakaz}`; `ssh` → `mkdir -p "$REMOTE_DIR"`; `rsync -az --delete --exclude .venv --exclude .git --exclude __pycache__ --exclude .pytest_cache --exclude deploy/.env ./ "$VPS_USER@$VPS_HOST:$REMOTE_DIR/"` (excluded-файлы `--delete` не удаляет — серверный `.env` цел); если на сервере нет `deploy/.env` — вывести подсказку из `docs/deploy.md` и остановиться; иначе `ssh ... "cd $REMOTE_DIR/deploy && docker compose up -d --build"` и `docker compose ps`. Сделать исполняемым (`chmod +x`). |
| `.gitignore` | добавить `deploy/.env` |

`README.md` и `docs/deploy.md` не трогать — их ведёт Claude.

## Проверка (Codex)

- Если на Mac есть Docker: `docker build -t avtozakaz .` и
  `docker run --rm avtozakaz pytest -q` — все тесты зелёные на Python 3.12.
  Плюс `docker compose -f deploy/docker-compose.yml config` с
  `deploy/.env`, скопированным из `.env.example` (потом удалить) — без ошибок.
- Если Docker на Mac нет — так и написать в отчёте; эту проверку делает
  человек на VPS (шаг в `docs/deploy.md`).
- `bash -n deploy/deploy.sh` — синтаксис скрипта корректен.
- Обновить `.planning/STATE.md` (строка «5. Деплой»: файлы готовы, сервер —
  за человеком).

## Проверка после деплоя (человек / Claude)

1. `curl -sI https://<домен>` → `401` (без пароля не пускает).
2. `curl -sI -u <логин>:<пароль> https://<домен>` → `200`, сертификат Let's Encrypt.
3. Браузер: первый расчёт ~30 с, повторный с теми же параметрами — сразу;
   фильтры и выгрузка xlsx работают.
4. Повторный `deploy.sh` обновляет приложение и не затирает серверный `.env`.
