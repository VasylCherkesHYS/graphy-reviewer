# AI Code Review — GitHub App

GitHub App, который ревьюит pull request'ы (OpenAI или Anthropic на выбор), ведёт
обсуждение в тредах своих комментариев и по команде **сам применяет предложенные
правки**, коммитит их и пушит в ветку PR.

## Возможности

- **Ревью PR** — инлайн-комментарии по изменённым строкам + итоговый summary.
  Использует граф зависимостей (`code-review-graph`) как контекст «радиуса поражения».
- **Триггеры ревью:**
  - бот назначен ревьюером PR (`review_requested`) — `AUTO_REVIEW_ON_REQUEST=true`;
  - команда `/review` в комментарии к PR;
  - опционально автоматически при открытии/обновлении PR — `AUTO_REVIEW_ON_OPEN=true`.
- **Диалог** — ответьте в треде комментария бота, и он ответит по существу.
- **Применение правок (новое):**
  - `/apply` — ответом **в треде конкретного замечания**: бот генерирует правку,
    применяет её, коммитит и пушит в ветку PR (отдельным коммитом);
  - `/apply-all` — комментарием к PR: применяет все свои замечания, каждое
    отдельным коммитом;
  - либо не применять — разработчик правит сам.

## Команды

| Команда      | Где писать                                   | Что делает                                  |
|--------------|----------------------------------------------|---------------------------------------------|
| `/review`    | комментарий к PR                             | (пере)запустить ревью                       |
| `/apply`     | ответ в треде моего инлайн-замечания         | применить эту правку, закоммитить, запушить |
| `/apply-all` | комментарий к PR                             | применить все замечания (по коммиту каждое) |
| `/help`      | комментарий к PR                             | показать список команд                      |

## Конфигурация

Скопируйте `.env.example` → `.env` и заполните. Ключевые переменные:

- `LLM_PROVIDER` — `openai` (по умолчанию) или `anthropic`.
- `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_COMPLEX_MODEL`.
- `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`.
- `AUTO_REVIEW_ON_REQUEST`, `AUTO_REVIEW_ON_OPEN`.
- `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL` — личность коммитов с правками.

## Локальный запуск (быстрый старт для теста)

Нужны: Python 3.12+, Node.js (для туннеля), заполненный `.env`.

**1. Установить зависимости** (один раз):

```powershell
# полный вариант (с code-review-graph для контекста графа)
pip install -e .

# или минимальный рантайм, если code-review-graph не ставится:
pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27" `
            "openai>=1.50" "anthropic>=0.40" "pyjwt[crypto]>=2.9" "pydantic-settings>=2.5"
```

**2. Поднять сервер** (терминал №1, оставить открытым):

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Проверка: `curl http://localhost:8000/healthz` → `{"status":"ok"}`.

**3. Поднять публичный туннель** (терминал №2, оставить открытым):

```powershell
npx --yes localtunnel --port 8000 --subdomain graphy-reviewer-bot
```

Выведет: `your url is: https://graphy-reviewer-bot.loca.lt`.
Если этот subdomain занят — localtunnel выдаст случайный, тогда **обнови Webhook URL в GitHub**.

**4. Прописать вебхук** в GitHub App → General → Webhook (один раз, если URL не менялся):

- **Payload URL:** `https://graphy-reviewer-bot.loca.lt/webhook`
- **Content type:** `application/json`
- **Secret:** значение из `.env` → `GITHUB_WEBHOOK_SECRET`

**5. Запустить ревью:** в PR назначить бота ревьюером или написать `/review`.

> Сервер и туннель должны быть запущены, пока пользуешься ботом. Для постоянной
> работы без локального ПК — задеплой на Railway (`railway.toml` уже в проекте),
> переменные из `.env` задаются в панели Railway.

**Если бот не отвечает** — проверь GitHub App → Advanced → **Recent Deliveries**:
там видно, ушло ли событие и какой код ответа (401 = не совпал Secret,
таймаут = сервер/туннель недоступен).

## Настройка GitHub App

См. раздел в инструкции (права, события, как добавить бота ревьюером).
Кратко — права: **Contents: Read & Write**, **Pull requests: Read & Write**,
**Metadata: Read**; события: **Pull request**, **Issue comment**,
**Pull request review comment**.
