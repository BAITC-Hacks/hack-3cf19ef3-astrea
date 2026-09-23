# Фаза 7 — Корректировка и утверждение заказа, PostgreSQL

Решение человека 2026-09-23: хранить утверждённые заказы в **PostgreSQL**
и дать менеджеру корректировать количество. Закрывает ключевой сценарий
RULE.md п.3: «проверяет, **корректирует при необходимости → утверждает
заказ**», и показывает требование п.9: заказ фиксируется только после
подтверждения человеком и **никуда не отправляется**.

**Порядок:** после закрытия `REVIEW.md` (К2…Н1), до README (фаза 4) и
деплоя (фаза 5).

**Зависимость:** `psycopg[binary]==3.2.3` одобрена человеком (выбор
PostgreSQL), поддерживает Python 3.9 и 3.12. ORM не добавлять — чистый SQL.
Создание новой схемы БД одобрено человеком (AGENTS.md).

## Что в базе, а что нет

- **В базе:** только решения менеджера — утверждённые заказы, строки с
  рекомендованным и утверждённым количеством, комментарии, кто и когда.
- **Не в базе:** данные 1С. Источник правды — xlsx в `data/raw/`, расчёт
  как сейчас. Копию продаж и остатков в Postgres не заводим.

## Схема (`db/migrations/001_orders.sql`)

```sql
CREATE TABLE IF NOT EXISTS purchase_orders (
    id              BIGSERIAL PRIMARY KEY,
    supplier        TEXT        NOT NULL CHECK (supplier IN ('IEK', 'SE')),
    approved_by     TEXT        NOT NULL,
    approved_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_as_of      DATE        NOT NULL,
    forecast_method TEXT        NOT NULL,
    params          JSONB       NOT NULL,      -- сроки поставки, покрытие, прирост
    line_count      INTEGER     NOT NULL,
    total_qty       INTEGER     NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_order_lines (
    order_id         BIGINT  NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    sku_code         TEXT    NOT NULL,
    article          TEXT,
    name             TEXT,
    unit             TEXT,
    category         TEXT,
    moq              INTEGER NOT NULL,
    recommended_qty  INTEGER NOT NULL,
    approved_qty     INTEGER NOT NULL CHECK (approved_qty >= 0),
    urgency          TEXT,
    stock_unknown    BOOLEAN NOT NULL,
    explanation      TEXT    NOT NULL,
    comment          TEXT,
    PRIMARY KEY (order_id, sku_code)
);
```

Применение — `app/db.py: ensure_schema()` при старте (идемпотентно,
`CREATE … IF NOT EXISTS`). Отдельного инструмента миграций не нужно.

## Модули

- **`app/db.py`** — подключение по `DATABASE_URL` из окружения;
  `ensure_schema()`, `save_order(...) -> int` (одна транзакция: заказ +
  строки), `list_orders()`, `get_order_lines(order_id)`.
- **`app/orders.py`** — логика без базы, чтобы её можно было тестировать
  без Postgres:
  - `apply_corrections(recommendations, edits)` → `approved_qty`, `comment`;
  - проверка: `approved_qty` целое, ≥ 0; если не кратно MOQ — **предупреждение**,
    не запрет (менеджер решает);
  - если `approved_qty` ≠ `recommended_qty` и нет комментария — предупреждение
    «укажите причину корректировки»;
  - строки `stock_unknown` утверждаются только после явной отметки
    «остаток сверен с 1С» (чекбокс в строке); без неё — в заказ не идут.
- **Интерфейс (`app/ui/streamlit_app.py`)**:
  - таблица рекомендаций по поставщику — `st.data_editor`: редактируются
    только «Утверждённое количество» (по умолчанию = рекомендованному),
    «Комментарий» и, для `stock_unknown`, «Остаток сверен»; остальные колонки
    только для чтения. Изменённые строки выделены;
  - над таблицей: итог «рекомендовано N шт. → к утверждению M шт.,
    изменено K строк»;
  - поле «Кто утверждает» (обязательно) и кнопка **«Утвердить заказ <поставщик>»**
    → `save_order` → сообщение «Заказ №… сохранён. Поставщику ничего не
    отправлено»; после этого — кнопка скачать xlsx этого заказа;
  - xlsx: на листах поставщика — **утверждённое** количество; в «Обосновании»
    — обе цифры и комментарий;
  - новая вкладка **«История заказов»**: список из `list_orders()`, при
    выборе — строки заказа и повторная выгрузка xlsx;
  - **если `DATABASE_URL` не задан или база недоступна** — приложение
    работает как сейчас (расчёт, корректировка, выгрузка), а кнопка
    утверждения и история отключены с понятным сообщением. Падать нельзя:
    жюри может запускать без Postgres.
- **Контейнеризация — см. раздел ниже.** Весь проект (приложение + база)
  запускается одной командой `docker compose up`.

## Контейнеризация (решение человека 2026-09-23)

Один образ и один compose-файл для всего: локальный запуск, проверка
жюри, основа для деплоя. Фаза 5 только добавляет Caddy поверх
(`docker-compose.prod.yml`).

| Файл | Содержание |
|---|---|
| `Dockerfile` | `FROM python:3.12-slim`; `ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1`; `WORKDIR /app`; `COPY requirements.txt` → `pip install --no-cache-dir -r requirements.txt`; затем **отдельный `COPY` на каждый каталог**: `app`, `data`, `db`, `scripts`, `tests`, `.streamlit`, `pytest.ini` (несколько каталогов в одном `COPY` склеиваются в кучу); непривилегированный пользователь (`useradd -m app`, `USER app`); `EXPOSE 8501`; `HEALTHCHECK` через `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"` (в slim нет curl); `CMD ["streamlit", "run", "app/ui/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]` |
| `.dockerignore` | `.venv`, `.git`, `__pycache__`, `*.pyc`, `.pytest_cache`, `.env`, `deploy/`, `docs/`, `.planning/` |
| `.streamlit/config.toml` | `[server] headless = true`; `[browser] gatherUsageStats = false`; `[client] toolbarMode = "viewer"` (закрывает С5 из `REVIEW.md`) |
| `docker-compose.yml` | **`db`**: `postgres:16-alpine`; `POSTGRES_DB=autozakaz`, `POSTGRES_USER=autozakaz`, `POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?задайте в .env}`; том `pg_data:/var/lib/postgresql/data`; `ports: ["127.0.0.1:5432:5432"]` (для `pytest` с хоста; снаружи недоступен); healthcheck `pg_isready -U autozakaz`; `restart: unless-stopped`. **`app`**: `build: .`; `environment: DATABASE_URL=postgresql://autozakaz:${POSTGRES_PASSWORD}@db:5432/autozakaz`; `depends_on: db: condition: service_healthy`; `ports: ["127.0.0.1:8501:8501"]` (на VPS наружу не торчит — туда ходит Caddy); `restart: unless-stopped`. Том `pg_data`. |
| `.env.example` | `POSTGRES_PASSWORD=change-me` с комментарием «для локального запуска можно оставить, на сервере — `openssl rand -hex 24`»; ниже закомментированный блок для сервера: `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`, `DOMAIN=`, `BASIC_AUTH_USER=`, `BASIC_AUTH_HASH=''` |
| `.gitignore` | `.env` |

**Запуск для человека и жюри:**
```bash
cp .env.example .env
docker compose up --build        # → http://localhost:8501
docker compose run --rm app pytest -q   # тесты на Python 3.12, включая интеграционные с базой
```

`ensure_schema()` выполняется при старте приложения — база готова без ручных шагов.

## Тесты

- `tests/test_orders.py` — без базы: корректировка, предупреждения MOQ и
  комментария, `stock_unknown` без отметки не попадает в заказ, итоги.
- `tests/test_db.py` — интеграционные, **пропускаются**
  (`pytest.mark.skipif`), если `DATABASE_URL` не задан: `ensure_schema`
  дважды без ошибок; `save_order` → `list_orders`/`get_order_lines`
  возвращают то же; при ошибке в строках транзакция откатывается целиком.
- Интерфейс: `streamlit.testing` — без базы кнопка утверждения отключена и
  приложение не падает.

## Критерии приёмки

- `pytest` зелёный без Postgres (интеграционные — skipped) и с Postgres
  (`docker compose up -d db`, `DATABASE_URL` задан) — все прошли.
- `cp .env.example .env && docker compose up --build` поднимает приложение и
  базу, `http://localhost:8501` открывается; `docker compose run --rm app
  pytest -q` зелёный внутри контейнера (Python 3.12).
- Вручную с Postgres: скорректировать 2 строки, утвердить заказ IEK, увидеть
  его в «Истории», скачать xlsx — в нём утверждённые количества.
- Без Postgres приложение открывается и считает, утверждение отключено с
  сообщением.
- Никакого кода отправки заказа поставщику.
- `requirements.txt` содержит `psycopg[binary]==3.2.3`;
  `.planning/STATE.md` обновлён.
