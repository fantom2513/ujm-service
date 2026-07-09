# Copilot для Mermaid-схем

Frontend + backend на TypeScript. Генерация и правка UX-архитектуры (Mermaid-схем) через self-hosted LLM (Gemma, vLLM/OpenAI-совместимый API), с извлечением текста из PDF/DOCX/TXT и реальным рендерингом Mermaid.js в браузере. Jira/Confluence-ссылки и транскрибация записей встреч — контролируемые заглушки (места для подключения подготовлены, не входили в текущий скоуп).

## Требования

- Node.js 24 или новее (используется нативный TypeScript type-stripping — без бандлера/tsc).
- `pnpm` (через `corepack enable && corepack prepare pnpm@latest --activate`).
- Доступный vLLM-эндпоинт с моделью (OpenAI-совместимый `/v1/chat/completions`).

## Настройка

1. Скопируйте `.env.example` в `.env`.
2. Укажите реальные `LLM_URL` (обычно `http://<host>:<port>/v1`), `LLM_MODEL`, при необходимости `LLM_API_KEY`.
3. При необходимости измените `APP_PORT`, `APP_HOST` и `PRODUCT_HOME_URL`.
4. Не добавляйте реальные ключи и токены в репозиторий (`.env` в `.gitignore`).

## Запуск (без Docker)

```bash
pnpm install
node scripts/build.mjs
node backend/src/server/index.ts
```

Либо короткие команды из `package.json`: `pnpm run build && pnpm run dev` (или `npm`, если pnpm недоступен).

После запуска сайт открывается по адресу `http://127.0.0.1:4173` (или другой `APP_PORT` из `.env`). В этом режиме backend сам раздаёт собранный frontend (`frontend/dist`) — годится для локальной разработки.

## Запуск в Docker

Два независимых образа:

- `Dockerfile` (корень) — backend, слушает только `/api/*`, никогда не отдаёт статику фронта.
- `frontend/Dockerfile` — nginx, отдаёт собранный `frontend/dist` и проксирует `/ux-architecture/api/` на backend. **Build-контекст — корень репозитория**, а не `frontend/` (сборочный скрипт использует ассеты из корня).

```bash
docker compose -f docker-compose.test.yaml build   # или docker-compose.prod.yaml
docker compose -f docker-compose.test.yaml up -d
```

Оба контейнера рассчитаны на общую внешнюю docker-сеть `cx_net` (создаётся снаружи, `external: true`) и **не публикуют портов наружу** — доступ только через reverse-proxy (см. `frontend/nginx.conf`), который отдаёт сервис под путём `/ux-architecture/`.

## CI/CD

`.gitlab-ci.yml` — build/deploy для веток `test`/`master`, раннеры `ux02-copilot_docker`/`ux01-copilot_docker`. `.env` в раннере создаётся из CI/CD-переменных `ENV_TEST`/`ENV_PROD` (masked+protected) — реальный `.env` в репозиторий не попадает.

## Что реализовано

- Генерация UX-архитектуры из текстового файла (TXT/PDF/DOCX), записи встречи (заглушка) или ссылки (заглушка) — через реальный вызов LLM.
- Извлечение текста из PDF (`pdf-parse`) и DOCX (`mammoth`).
- AI-редактирование схемы через чат: быстрые действия (разбить на блоки, упростить, выделить основной путь), свободный текст, отмена последнего изменения (`RESTORE_PREVIOUS`, включая распознавание фраз "верни предыдущую версию" и т.п.).
- Валидация и одна попытка автоматического ремонта невалидного Mermaid-кода от LLM.
- Retry с экспоненциальным backoff + fallback по `response_format` (`json_schema` → `json_object` → `none`) при проблемах на стороне LLM.
- Рендеринг схемы в браузере через Mermaid.js (CDN), экспорт SVG/PNG (PDF — как SVG, см. комментарий в `frontend/src/utils/export.ts`).
- Масштабирование, перемещение, автоцентрирование схемы; временное состояние через `sessionStorage`.
- Backend API: генерация, чат, health-check, публичный конфиг.

## Что пока является заглушкой

- Jira/Confluence: backend проверяет ссылку и возвращает контролируемую заглушку вместо реального обращения к API.
- Транскрибация записей встреч (mp3/mp4 и т.п.): не реализована.
- Извлечение XLS/XLSX: место для подключения подготовлено, реального парсинга нет.

## API

- `GET /api/health` — проверка запуска backend.
- `GET /api/config` — публичные настройки frontend.
- `POST /api/generate` — построение схемы из файла, записи или ссылки (реальный вызов LLM).
- `POST /api/chat` — сообщение в AI-чат: правка схемы через LLM, включая отмену последнего изменения.

## Важные ограничения

- Аутентификации на `/api/*` нет — предполагается, что она обеспечивается внешним gateway/reverse-proxy.
- CORS не настроен — рассчитан на same-origin деплой через reverse-proxy (см. раздел про Docker).
- Постоянная база данных, история схем, регистрация и личный кабинет не реализованы — состояние живёт в `sessionStorage` браузера.
