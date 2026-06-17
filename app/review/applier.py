import logging
import os
import re
import subprocess

from app.config import settings
from app.review.schema import Edit

logger = logging.getLogger(__name__)

_SUGGESTION_RE = re.compile(r"```suggestion\r?\n(.*?)```", re.DOTALL)


class ApplyError(Exception):
    """Raised when a suggested fix cannot be applied to the working tree."""


def extract_suggestion(body: str) -> str | None:
    """Return the contents of a ```suggestion block, or None if absent."""
    m = _SUGGESTION_RE.search(body or "")
    if not m:
        return None
    text = m.group(1)
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    return text


def _safe_path(repo_dir: str, file_path: str) -> str:
    full = os.path.normpath(os.path.join(repo_dir, file_path))
    if not full.startswith(os.path.normpath(repo_dir)):
        raise ApplyError(f"Путь вне репозитория: {file_path}")
    if not os.path.isfile(full):
        raise ApplyError(f"Файл не найден: {file_path}")
    return full


def file_exists(repo_dir: str, file_path: str) -> bool:
    full = os.path.normpath(os.path.join(repo_dir, file_path))
    return full.startswith(os.path.normpath(repo_dir)) and os.path.isfile(full)


def read_text(repo_dir: str, file_path: str) -> str:
    with open(_safe_path(repo_dir, file_path), "r", encoding="utf-8") as f:
        return f.read()


def apply_suggestion(
    repo_dir: str, file_path: str, start_line: int, end_line: int, new_text: str
) -> None:
    """Replace lines [start_line..end_line] (1-based, inclusive) with new_text."""
    full = _safe_path(repo_dir, file_path)
    with open(full, "r", encoding="utf-8", newline="") as f:
        raw = f.read()

    nl = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(nl)

    if start_line < 1 or end_line > len(lines) or start_line > end_line:
        raise ApplyError(
            f"Строки {start_line}..{end_line} вне диапазона файла {file_path} ({len(lines)} строк)"
        )

    replacement = new_text.replace("\r\n", "\n").split("\n")
    new_lines = lines[: start_line - 1] + replacement + lines[end_line:]
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(nl.join(new_lines))


def apply_edits(repo_dir: str, file_path: str, edits: list[Edit]) -> None:
    """Apply exact-string edits to one file in the working tree.

    Each edit's `old` must occur exactly once. Raises ApplyError otherwise.
    """
    if not edits:
        raise ApplyError("Пустой список правок")
    full = _safe_path(repo_dir, file_path)

    with open(full, "r", encoding="utf-8") as f:
        text = f.read()

    for e in edits:
        count = text.count(e.old)
        if count == 0:
            raise ApplyError(
                f"Не найден фрагмент для замены в {file_path} (возможно, файл изменился)"
            )
        if count > 1:
            raise ApplyError(
                f"Фрагмент встречается {count} раз в {file_path} — замена неоднозначна"
            )
        text = text.replace(e.old, e.new, 1)

    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def _run(args: list[str], cwd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def commit(repo_dir: str, file_path: str, message: str) -> str | None:
    """Stage `file_path` and commit. Returns short SHA, or None if nothing changed."""
    _run(["git", "add", "--", file_path], repo_dir)

    status = _run(["git", "status", "--porcelain"], repo_dir)
    if not status.stdout.strip():
        return None

    res = _run(
        [
            "git",
            "-c", f"user.name={settings.git_author_name}",
            "-c", f"user.email={settings.git_author_email}",
            "commit", "-m", message,
        ],
        repo_dir,
    )
    if res.returncode != 0:
        raise ApplyError(f"git commit failed: {res.stderr.strip()}")

    sha = _run(["git", "rev-parse", "--short", "HEAD"], repo_dir)
    return sha.stdout.strip()


def push(repo_dir: str, branch: str) -> None:
    res = _run(["git", "push", "origin", f"HEAD:{branch}"], repo_dir, timeout=120)
    if res.returncode != 0:
        raise ApplyError(
            f"git push не удался (ветка {branch}). "
            f"Для PR из форка включите 'Allow edits by maintainers'. {res.stderr.strip()}"
        )
