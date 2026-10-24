"""Безопасный `alembic check`: никогда не открывает backend/data/finance.db.

Alembic берёт URL базы из app.config (backend/alembic/env.py), а переменная
окружения DATABASE_PATH приоритетнее backend/.env. Скрипт запускает Alembic в
дочернем процессе с DATABASE_PATH, указывающим во временный каталог, и
проверяет это до запуска.

Режимы:
  fresh (по умолчанию)  пустая временная БД → `alembic upgrade head` →
                        `alembic check`. Проверяет, что миграции дают ту же
                        схему, что и модели. Основная БД не читается вообще.
  copy                  побайтная копия основной БД (и её -wal, если он есть)
                        во временный каталог → `alembic current` и
                        `alembic check` на копии, без upgrade. Показывает,
                        в каком состоянии схема рабочей базы. Основная БД
                        только читается как файл, SQLite её не открывает.

Защита:
  * до запуска Alembic дочерний процесс печатает settings.db_file — путь
    обязан лежать во временном каталоге и не совпадать с основной БД;
  * SHA-256 основной БД и наличие её -wal/-shm сравниваются до и после;
  * режим copy отказывается работать, если backend слушает порт 8000:
    копия работающей базы может оказаться несогласованной;
  * удаляется только временный каталог, созданный этим запуском
    (--keep оставляет его для разбора).

Код выхода: 0 — схема совпадает; 1 — alembic check нашёл расхождения или
упал; 2 — не подтвердилась изоляция или изменилась основная БД.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
MAIN_DB = BACKEND / "data" / "finance.db"
SIDECARS = ("-wal", "-shm")
VENV_PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"


def sha256(path: Path) -> str | None:
    """Хэш файла, прочитанного побайтно (SQLite файл не открывает)."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main_db_state() -> dict[str, object]:
    return {
        "sha256": sha256(MAIN_DB),
        **{s: MAIN_DB.with_name(MAIN_DB.name + s).exists() for s in SIDECARS},
    }


def backend_listening(port: int = 8000) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run(python: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [python, *args], cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="alembic check без доступа к основной БД")
    parser.add_argument("--mode", choices=["fresh", "copy"], default="fresh")
    parser.add_argument("--keep", action="store_true", help="не удалять временный каталог")
    opts = parser.parse_args()

    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    before = main_db_state()

    if opts.mode == "copy":
        if not MAIN_DB.exists():
            print(f"Основной БД нет: {MAIN_DB}")
            return 2
        if backend_listening():
            print("Backend слушает порт 8000: остановите его, иначе копия может быть несогласованной.")
            return 2

    workdir = Path(tempfile.mkdtemp(prefix="finance-ai-alembic-check-"))
    target = workdir / "finance-check.db"
    print(f"Временный каталог: {workdir}")
    try:
        if opts.mode == "copy":
            # Только чтение байтов; -shm не нужен — SQLite построит его заново.
            shutil.copyfile(MAIN_DB, target)
            wal = MAIN_DB.with_name(MAIN_DB.name + "-wal")
            if wal.exists():
                shutil.copyfile(wal, target.with_name(target.name + "-wal"))
            if sha256(target) != before["sha256"]:
                print("Копия не совпала с основной БД по SHA-256.")
                return 2

        env = {**os.environ, "DATABASE_PATH": str(target), "PYTHONIOENCODING": "utf-8"}

        # Изоляция подтверждается ДО запуска Alembic: тот же процесс-интерпретатор,
        # тот же app.config, что прочитает env.py.
        probe = run(python, ["-B", "-c", "from app.config import settings; print(settings.db_file)"], env)
        resolved = Path(probe.stdout.strip().splitlines()[-1]).resolve() if probe.returncode == 0 and probe.stdout.strip() else None
        if resolved is None or resolved == MAIN_DB.resolve() or workdir.resolve() not in resolved.parents:
            print(f"Изоляция не подтверждена (db_file = {resolved}). Alembic не запускался.")
            print(probe.stderr)
            return 2
        print(f"Alembic будет работать с: {resolved}")

        steps = [["-m", "alembic", "upgrade", "head"]] if opts.mode == "fresh" else [["-m", "alembic", "current"]]
        steps.append(["-m", "alembic", "check"])
        code = 0
        for step in steps:
            result = run(python, step, env)
            print(f"\n$ alembic {' '.join(step[2:])}  → код {result.returncode}")
            output = (result.stdout + result.stderr).strip()
            if output:
                print(output)
            if result.returncode != 0:
                code = 1
                break
    finally:
        if opts.keep:
            print(f"\nВременный каталог сохранён: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    after = main_db_state()
    print(f"\nОсновная БД: SHA-256 {after['sha256']}, -wal: {after['-wal']}, -shm: {after['-shm']}")
    if after != before:
        print("ВНИМАНИЕ: состояние основной БД изменилось во время проверки.")
        return 2
    print("Основная БД не изменилась.")
    print("Схема совпадает с моделями." if code == 0 else "alembic check сообщил о расхождении или ошибке.")
    return code


if __name__ == "__main__":
    sys.exit(main())
