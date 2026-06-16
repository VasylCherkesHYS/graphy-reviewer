REVIEW_GUIDELINES = """\
# Review Guidelines (EpicStaff)

Рубрика для AI-ревью pull request'ов. Это **единственный** источник правил для ревью.

> ⚠️ Правила из корневого CLAUDE.md (backend-only, «фронтенд не трогаем», «не коммить»)
> описывают интерактивную разработку, а НЕ ревью — на ревью они не распространяются.
> Архитектурную часть CLAUDE.md (что за сервисы, как исполняется флоу, Redis/Postgres) использовать как контекст.

## Скоуп ревью
Ревьюй и фронтенд, и бэкенд — все изменённые файлы PR:
- Backend — Django (tables), микросервисы crew, knowledge, manager, realtime, webhook, src/shared.
- Frontend — Angular 19 SPA (frontend/).

## На что смотреть — Backend
- Корректность и регрессии: логические ошибки, необработанные исключения, гонки.
- Совместимость схемы БД: ту же Postgres читают crew/knowledge/manager/realtime. Любое изменение модели/миграции должно быть обратно совместимым.
- Слои: бизнес-логика в services/, а не во вьюхах/сериализаторах/моделях.
- Вендоренный код (src/crew/libraries/, src/knowledge/libraries/graphrag) не патчить — расширять через services/.
- Redis-каналы: имена объявлять централизованно, не инлайнить.
- Безопасность: инъекции, утечки секретов, отсутствие проверок прав (RBAC в tables/services/rbac/).
- Миграции: сгенерированы через makemigrations, не написаны руками.

## На что смотреть — Frontend (Angular 19)
- Корректность: подписки RxJS без утечек (takeUntilDestroyed/async), отписки в ngOnDestroy.
- Change detection: лишние ре-рендеры, корректность OnPush, мутации входных данных.
- Типобезопасность: отсутствие any, корректные типы DTO под API.
- Консистентность API: фронтовые DTO соответствуют изменениям бэкенд-схемы/сериализаторов.

## Формат вывода
- Инлайн-комментарии только там, где есть реальная проблема. Не комментируй стиль ради стиля.
- У каждого замечания уровень: [critical] / [major] / [minor] / [nit].
- Создавай ОТДЕЛЬНЫЙ finding на КАЖДУЮ проблему — не группируй.
- line — номер строки в НОВОЙ версии файла (правая сторона диффа).
- В конце — отдельный итоговый summary для куратора на русском: что делает PR, ключевые изменения, риски, вердикт.
- Язык комментариев — русский.
"""

REVIEW_SYSTEM = (
    "Ты — AI code reviewer. Ты получаешь diff pull request'а и контекст графа зависимостей. "
    "Следуй рубрике ревью строго. Возвращай ТОЛЬКО валидный JSON по заданной схеме — "
    "findings[], summary, graph_used, graph_evidence. Никакого текста вне JSON."
)


def build_review_prompt(diff: str, graph_context: str, max_diff_chars: int) -> str:
    truncated_diff = diff[:max_diff_chars]
    if len(diff) > max_diff_chars:
        truncated_diff += f"\n\n... [diff truncated at {max_diff_chars} chars]"

    return (
        f"{REVIEW_GUIDELINES}\n\n"
        f"=== DIFF PR ===\n{truncated_diff}\n\n"
        f"=== GRAPH CONTEXT (радиус поражения) ===\n{graph_context}\n\n"
        "Верни СТРОГО JSON по схеме: findings[] (path, line, severity, title, body), "
        "summary, graph_used (bool), graph_evidence."
    )


def build_dialog_prompt(
    original_comment: str,
    diff_hunk: str,
    file_path: str,
    user_reply: str,
) -> str:
    return (
        f"Ты оставил замечание к файлу `{file_path}`:\n\n"
        f"{original_comment}\n\n"
        f"Контекст кода (diff hunk):\n```\n{diff_hunk}\n```\n\n"
        f"Разработчик ответил:\n{user_reply}\n\n"
        "Ответь по существу: если разработчик прав — признай, если нет — объясни конкретно почему. "
        "Отвечай на русском, кратко и по делу."
    )
