# Дизайн: Веха 2 — синхронизация промптов + точечные UI-фиксы

Дата: 2026-07-20
Статус: черновик на ревью

## Контекст и цель

Продолжение плана фикса прод-багов CX Copilot
([[2026-07-20-cx-copilot-prod-bugfix-plan-design]]). Веха 0 (контекст чата +
usage-трекинг) завершена и смержена в `main`. Эта веха закрывает 🟠-баги #3,
#4, #5, #6, #14, #16, #17, #18 из исходного брифа, плюс усиливает #15 (частично
закрытый Вехой 0).

Ключевая находка: `backend/src/services/openai/prompts.ts` использует урезанные
заглушки системных промптов (`GENERATE_SYSTEM`/`EDIT_SYSTEM`/`REPAIR_SYSTEM`) —
комментарий в коде прямо называет их "Trimmed to key security + format rules".
Полные версии лежат в `Генерация схемы/system_prompts_mermaid_chat_v2/*.prompt.txt`
и содержат существенно больше правил: обязательные ✅/❌ внутри текста узла,
стиль subgraph, полную структуру компоновки сложных схем, и алгоритм действия
`HIGHLIGHT_MAIN_PATH` (включая явный запрет `linkStyle` — прод-скрин показывает,
что сейчас путь подсвечивается именно через раскраску рёбер, что и объясняет
нестабильность при повторной генерации).

Дополнительная находка: исходное ТЗ модуля, `codex_mermaid_chat_task.txt`,
явно указывает путь размещения — `backend/src/prompts/generateMermaid.prompt.txt`
и т.д. Значит текущая урезанная реализация — не осознанное архитектурное
решение, а недоделанный перенос.

## Зафиксированные решения

- **Расположение промптов:** `.prompt.txt` файлы переезжают в
  `backend/src/prompts/` (путь из `codex_mermaid_chat_task.txt`), читаются с
  диска синхронно при старте процесса (`readFileSync`, как `config/index.ts`
  читает `.env`). Деплоятся вместе с раннером как обычный код репозитория —
  без volume-монтирования и hot-reload (решено в рамках предыдущей брейнсторм-сессии).
- **Новые правила стилей**, которых не было ни в урезанной, ни в полной версии
  промпта, добавляются в `.prompt.txt` файлы:
  - `classDef decision fill:#ECECFF,stroke:#9370DB,stroke-width:1px` —
    стандартный стиль точки принятия решения.
  - `classDef decisionNegative fill:#FFCDD2,stroke:#C62828,stroke-width:2px` —
    для отрицательных сценариев.
  - Точечное правило в секции FREEFORM (`editMermaid.prompt.txt`): при запросе
    вида "покрасить узлы X в цвет блока Y" красить именно узлы X в цвет
    источника Y, а не наоборот (сейчас направление путается).
- **Frontend-баги (#14, #16, #17)** — каждый через отдельную investigation
  внутри своей задачи implementation-плана, а не предрешается здесь архитектурно:
  - #16: `.modal-backdrop` (`position:fixed; inset:0; z-index:30`,
    `frontend/src/styles.css:2045`) не перекрывает header на проде (скрины
    подтверждают). Вероятная причина — containing-block ловушка (анцестор с
    `transform`/`filter`/`contain` создаёт новый containing block для
    `position:fixed`), но точная причина устанавливается в задаче.
  - #17: `.message.user` (`max-width: calc(100% - 40px)`,
    `frontend/src/styles.css:1336`) не хагает контент по ширине — нужен
    `width: fit-content` (или эквивалент) с сохранением `max-width` и переноса
    длинных сообщений.
  - #14: `.chat-file-strip` (`frontend/src/styles.css:1690`) уже имеет
    `overflow-x: auto` — баг воспроизводится в каком-то конкретном состоянии UI,
    которое надо найти и воспроизвести перед фиксом.
- **Стили → токены:** цвета (`#ECECFF`, `#9370DB`, `#FFCDD2`, `#C62828`,
  `rgba(21,33,73,0.6)`, `#f9f9f9`/`#ddd`) выносятся в общие константы — на
  mermaid-стороне как часть промпт-файлов/маленького TS-модуля со стилями, на
  frontend-стороне как CSS custom properties в `styles.css` (там уже есть
  `--icon-blue-filter` и подобные — используем тот же паттерн).
- **Docker/CI:** проверить, что `backend/src/prompts/` попадает в образ backend
  (Dockerfile, `.dockerignore`) — иначе синхронизация промптов сломает прод.

## Архитектура

### A. Промпт-модуль

- Новые файлы: `backend/src/prompts/generateMermaid.prompt.txt`,
  `editMermaid.prompt.txt`, `repairMermaid.prompt.txt` — полное содержимое
  текущих `.prompt.txt` файлов + новые правила (decision/decisionNegative
  classDef, FREEFORM color-direction).
- `backend/src/services/openai/prompts.ts`: `GENERATE_SYSTEM`, `EDIT_SYSTEM`,
  `REPAIR_SYSTEM` больше не строковые константы в коде — читаются один раз при
  импорте модуля через `readFileSync(join(..., "generateMermaid.prompt.txt"), "utf8")`
  и т.д. `sanitize()`, `buildGeneratePrompt`, `buildChatPrompt`, `buildRepairPrompt`
  не меняются структурно — они уже собирают промпт вокруг этих констант.
- `mermaidValidation.rules.txt` в этот перенос НЕ входит — он не является
  системным промптом модели, а описывает backend-side validation pipeline,
  которого сейчас нет (см. ниже).

### B. Frontend

- Три независимых точечных CSS/JS-фикса в `frontend/src/styles.css` (и, если
  понадобится, `frontend/src/main.ts` для #16, если проблема не только в CSS,
  а в структуре DOM — например, модалка рендерится не как прямой потомок
  корневого контейнера).

## Тестирование

- Backend: новый тест на промпт-модуль — снапшот/regex-проверка, что
  `buildGeneratePrompt`/`buildChatPrompt`/`buildRepairPrompt` больше не
  содержат старых урезанных фраз ("Trimmed to key") и содержат маркеры полного
  промпта (например, "ГЛАВНЫЙ ПРИНЦИП", `classDef decision`). Существующие
  тесты `prompts.test.ts` не должны сломаться (они проверяют структуру
  результата, не точный текст системного промпта).
- Backend: тест на наличие `classDef decision`/`decisionNegative` в
  сгенерированном промпте.
- Frontend: regression на каждый баг (#14, #16, #17) — ручная/визуальная
  проверка (как в Вехе 0, автотестов для frontend в репозитории нет).

## Технический долг, зафиксированный, но не устраняемый в этой вехе

`mermaidValidation.rules.txt` описывает полноценный validation pipeline:
session-lock на один активный AI-запрос (frontend + backend requestId),
проверка уникальности ID узлов/subgraph, проверка наложений по SVG bounding
box после рендера (`LAYOUT_OVERLAP`/`LAYOUT_TOO_WIDE`/`LAYOUT_DENSE`),
эвристики читаемости, атомарное обновление UI. Текущий `validateMermaid()`
(`backend/src/services/mermaid/index.ts`) делает только проверку заголовка
`flowchart` и запрещённых тегов — на порядок меньше описанного. Это не входит
ни в один пункт исходного багтрекера, поэтому остаётся зафиксированным долгом,
а не задачей этой вехи.
