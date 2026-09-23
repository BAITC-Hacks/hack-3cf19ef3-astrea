# Фаза 5 — Деплой на VPS

Решение человека 2026-09-23: Streamlit Community Cloud не подходит (репозиторий
организации требует admin и одобрения владельца организации; репозиторий
приватный → приложение приватное, одно на аккаунт, жюри по приглашениям;
Python 3.9 недоступен; сон через 12 ч). Разворачиваем на VPS человека
(Linux + Docker, свой домен), интерфейс остаётся на Streamlit.

По AGENTS.md конфиги деплоя и файлы окружения меняются только с согласия
человека — согласие получено (утверждён план деплоя).

**Порядок:** после фазы 8 (решение человека 2026-09-23).

**Обновление 2026-09-23:** сервер уже развёрнут человеком вручную
(`/opt/astrea`, Caddy с `basic_auth`). После фазы 8A в приложении есть
свой вход, поэтому **`basic_auth` из Caddy убирается** — Caddy отвечает
только за HTTPS. Задача фазы: положить в репозиторий файлы, совпадающие
с сервером (без `basic_auth`), и скрипт обновления.

## Что уже есть после фазы 7

`Dockerfile`, `.dockerignore`, `.streamlit/config.toml`, `docker-compose.yml`
(`app` + `db`, порты только на `127.0.0.1`), `.env.example`. Локально
`docker compose up --build` уже поднимает весь проект. Фаза 5 **только
добавляет** HTTPS и доставку кода на сервер — образ и основной
compose-файл те же.

## Схема на сервере

```
браузер ──https──► caddy (80/443, Let's Encrypt)
                     └──► app:8501 (Streamlit) ──► db:5432 (PostgreSQL, том pg_data)
```

На сервере в `/opt/astrea/.env` задано
`COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` — поэтому любые
команды `docker compose …` в этой папке сразу работают с Caddy, без флагов `-f`.

## Файлы

| Файл | Содержание |
|---|---|
| `docker-compose.prod.yml` | только сервис `caddy`: `image: caddy:2`, `ports: ["80:80", "443:443"]`, `volumes: ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro`, `caddy_data:/data`, `caddy_config:/config`; `environment: DOMAIN` из `.env` (через `${DOMAIN:?}` — без него не стартует); `depends_on: [app]`, `restart: unless-stopped`. Тома `caddy_data`, `caddy_config`. Сервисы `app` и `db` здесь **не переопределять**. |
| `deploy/Caddyfile` | `{$DOMAIN} {` / `encode gzip` / `reverse_proxy app:8501` / `}` — **без `basic_auth`** (вход — в приложении, фаза 8A) |
| `deploy/deploy.sh` | запускается на Mac из корня; `set -euo pipefail`; требует `VPS_HOST`, `VPS_USER` (понятная ошибка, если не заданы); `REMOTE_DIR=${REMOTE_DIR:-/opt/astrea}`; `ssh` → `mkdir -p "$REMOTE_DIR"`; `rsync -az --delete --exclude .venv --exclude .git --exclude __pycache__ --exclude .pytest_cache --exclude .env ./ "$VPS_USER@$VPS_HOST:$REMOTE_DIR/"` (excluded-файлы `--delete` не трогает — серверный `.env` цел); если на сервере нет `$REMOTE_DIR/.env` — вывести подсказку «см. docs/deploy.md, шаг 4» и остановиться; иначе `ssh … "cd $REMOTE_DIR && docker compose up -d --build && docker compose ps"`. Исполняемый. |
| `.env.example` | серверный блок: `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`, `DOMAIN=`; `INVITE_CODE=` (уже с 8A); строки `BASIC_AUTH_*` **удалить** |

`README.md` и `docs/deploy.md` не трогать — их ведёт Claude.

## Проверка (Codex)

- `docker compose -f docker-compose.yml -f docker-compose.prod.yml config`
  с тестовым `.env` (скопирован из `.env.example`, серверный блок
  раскомментирован, потом удалить) — без ошибок; у `app` и `db` порты только
  на `127.0.0.1`, наружу — только 80/443 у `caddy`.
- `bash -n deploy/deploy.sh`.
- Если Docker на Mac запущен: `docker compose up --build` локально (без prod)
  по-прежнему работает.
- Обновить `.planning/STATE.md` (строка «5. Деплой»: файлы готовы, сервер —
  за человеком).

## Проверка после деплоя (человек / Claude)

1. `curl -sI https://<домен>` → `200`, сертификат Let's Encrypt; в браузере — только экран входа приложения, данных без входа нет.
2. Регистрация с кодом из `INVITE_CODE` работает, без кода — отказ.
3. Снаружи порты 8501 и 5432 закрыты: `nc -zv <IP> 8501` и `nc -zv <IP> 5432` — отказ.
4. Браузер: результат открывается, фильтры, выгрузка, утверждение тестового
   заказа и «История заказов» работают.
5. Повторный `deploy.sh` обновляет приложение, не затирает `.env` и не
   стирает утверждённые заказы (том `pg_data`).
