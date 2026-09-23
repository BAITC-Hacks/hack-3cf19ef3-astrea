# Фаза 5 — Деплой на VPS

Решение человека 2026-09-23: Streamlit Community Cloud не подходит (репозиторий
организации требует admin и одобрения владельца организации; репозиторий
приватный → приложение приватное, одно на аккаунт, жюри по приглашениям;
Python 3.9 недоступен; сон через 12 ч). Разворачиваем на VPS человека
(Linux + Docker, свой домен), интерфейс остаётся на Streamlit.

По AGENTS.md конфиги деплоя и файлы окружения меняются только с согласия
человека — согласие получено (утверждён план деплоя).

**Порядок:** фаза делается **последней** (решение человека 2026-09-23) —
после фаз 7 и 4. Не начинать без отдельной команды.

## Что уже есть после фазы 7

`Dockerfile`, `.dockerignore`, `.streamlit/config.toml`, `docker-compose.yml`
(`app` + `db`, порты только на `127.0.0.1`), `.env.example`. Локально
`docker compose up --build` уже поднимает весь проект. Фаза 5 **только
добавляет** HTTPS с паролем и доставку кода на сервер — образ и основной
compose-файл те же.

## Схема на сервере

```
браузер ──https──► caddy (80/443, Let's Encrypt, basic_auth)
                     └──► app:8501 (Streamlit) ──► db:5432 (PostgreSQL, том pg_data)
```

На сервере в `/opt/avtozakaz/.env` задано
`COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` — поэтому любые
команды `docker compose …` в этой папке сразу работают с Caddy, без флагов `-f`.

## Файлы

| Файл | Содержание |
|---|---|
| `docker-compose.prod.yml` | только сервис `caddy`: `image: caddy:2`, `ports: ["80:80", "443:443"]`, `volumes: ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro`, `caddy_data:/data`, `caddy_config:/config`; `environment: DOMAIN, BASIC_AUTH_USER, BASIC_AUTH_HASH` из `.env` (через `${…:?}` — без них не стартует); `depends_on: [app]`, `restart: unless-stopped`. Тома `caddy_data`, `caddy_config`. Сервисы `app` и `db` здесь **не переопределять**. |
| `deploy/Caddyfile` | `{$DOMAIN} {` / `basic_auth {` / `{$BASIC_AUTH_USER} {$BASIC_AUTH_HASH}` / `}` / `reverse_proxy app:8501` / `}` |
| `deploy/deploy.sh` | запускается на Mac из корня; `set -euo pipefail`; требует `VPS_HOST`, `VPS_USER` (понятная ошибка, если не заданы); `REMOTE_DIR=${REMOTE_DIR:-/opt/avtozakaz}`; `ssh` → `mkdir -p "$REMOTE_DIR"`; `rsync -az --delete --exclude .venv --exclude .git --exclude __pycache__ --exclude .pytest_cache --exclude .env ./ "$VPS_USER@$VPS_HOST:$REMOTE_DIR/"` (excluded-файлы `--delete` не трогает — серверный `.env` цел); если на сервере нет `$REMOTE_DIR/.env` — вывести подсказку «см. docs/deploy.md, шаг 4» и остановиться; иначе `ssh … "cd $REMOTE_DIR && docker compose up -d --build && docker compose ps"`. Исполняемый. |
| `.env.example` | блок для сервера уже есть с фазы 7 — проверить, что там `COMPOSE_FILE`, `DOMAIN`, `BASIC_AUTH_USER`, `BASIC_AUTH_HASH=''` с комментарием: хэш из `docker run --rm caddy:2 caddy hash-password --plaintext '<пароль>'`, **в одинарных кавычках** (в bcrypt-хэше есть `$`) |

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

1. `curl -sI https://<домен>` → `401` (без пароля не пускает).
2. `curl -sI -u <логин>:<пароль> https://<домен>` → `200`, сертификат Let's Encrypt.
3. Снаружи порты 8501 и 5432 закрыты: `nc -zv <IP> 8501` и `nc -zv <IP> 5432` — отказ.
4. Браузер: результат открывается, фильтры, выгрузка, утверждение тестового
   заказа и «История заказов» работают.
5. Повторный `deploy.sh` обновляет приложение, не затирает `.env` и не
   стирает утверждённые заказы (том `pg_data`).
