"""Импорт и экспорт: JSON-backup (полное восстановление) и CSV.

Загружаемый файл передаётся телом запроса (для CSV — base64 внутри JSON
вместе с настройками сопоставления), тело читается потоково с жёстким
лимитом размера. Файл — только данные: из него ничего не исполняется.

Preview-эндпоинты никогда не пишут в БД. Restore/commit заново проверяют
файл целиком (клиенту не доверяем) и пишут одной транзакцией.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.backup import csv_export
from app.backup.csv_import import (
    MAX_CSV_BYTES,
    CsvImportFileError,
    CsvImportRequest,
    build_plan,
    commit_plan,
    decode_upload,
    plan_to_dict,
)
from app.backup.exporter import build_backup
from app.backup.format import MAX_BACKUP_BYTES
from app.backup.restore import RestoreFailedError, restore_backup
from app.backup.validator import BackupInvalidError, summarize, validate_backup
from app.db.session import get_db
from app.notifications.service import create_system_notification

router = APIRouter(tags=["import-export"])
logger = logging.getLogger("app.import_export")

_MB = 1024 * 1024


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail=f"Файл слишком большой: максимум {limit // _MB} МБ.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=f"Файл слишком большой: максимум {limit // _MB} МБ.")
        chunks.append(chunk)
    return b"".join(chunks)


def _attachment(body: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _today() -> str:
    return datetime.now().date().isoformat()


# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------


@router.get("/export/backup")
def export_backup(db: Session = Depends(get_db)) -> Response:
    body = json.dumps(build_backup(db), ensure_ascii=False, indent=2).encode("utf-8")
    return _attachment(body, f"finance-ai-backup-{_today()}.json", "application/json; charset=utf-8")


_CSV_EXPORTS = {
    "transactions": csv_export.transactions_csv,
    "transfers": csv_export.transfers_csv,
    "accounts": csv_export.accounts_csv,
    "debts": csv_export.debts_csv,
    "goals": csv_export.goals_csv,
}


@router.get("/export/{kind}.csv")
def export_csv(kind: str, db: Session = Depends(get_db)) -> Response:
    builder = _CSV_EXPORTS.get(kind)
    if builder is None:
        raise HTTPException(status_code=404, detail="Неизвестный вид экспорта")
    return _attachment(builder(db), f"finance-ai-{kind}-{_today()}.csv", "text/csv; charset=utf-8")


# ---------------------------------------------------------------------------
# Восстановление из JSON-backup
# ---------------------------------------------------------------------------


@router.post("/import/backup/preview")
async def preview_backup(request: Request) -> dict:
    """Только проверка и сводка. Не читает и не меняет БД."""
    raw = await _read_body(request, MAX_BACKUP_BYTES)
    try:
        doc = validate_backup(raw)
    except BackupInvalidError as e:
        return {"valid": False, "errors": e.errors, "errors_total": e.total}
    return {
        "valid": True,
        "errors": [],
        "errors_total": 0,
        "version": doc.version,
        "exported_at": doc.exported_at.isoformat().replace("+00:00", "Z"),
        "base_currency": doc.base_currency,
        "counts": summarize(doc),
    }


@router.post("/import/backup/restore")
async def restore(request: Request, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    if not confirm:
        raise HTTPException(status_code=400, detail="Восстановление требует явного подтверждения.")
    raw = await _read_body(request, MAX_BACKUP_BYTES)
    try:
        doc = validate_backup(raw)
    except BackupInvalidError as e:
        raise HTTPException(
            status_code=400,
            detail="Резервная копия не прошла проверку, данные не изменены: " + "; ".join(e.errors[:5]),
        ) from None
    try:
        counts = restore_backup(db, doc)
    except RestoreFailedError:
        raise HTTPException(
            status_code=500,
            detail="Восстановление не выполнено, текущие данные не изменены.",
        ) from None
    try:
        now = datetime.now(timezone.utc)
        create_system_notification(
            db,
            f"restore:{now.isoformat()}",
            "Данные восстановлены из резервной копии",
            f"Восстановлено состояние из резервной копии от {doc.exported_at.strftime('%d.%m.%Y')} "
            f"(формат версии {doc.version}).",
            data={"backup_version": doc.version, "exported_at": doc.exported_at.isoformat()},
        )
    except Exception:
        # Восстановление уже зафиксировано; уведомление — не повод его ронять.
        logger.exception("Не удалось записать системное уведомление о восстановлении")
    return {"restored": True, "counts": counts}


# ---------------------------------------------------------------------------
# Импорт операций из CSV
# ---------------------------------------------------------------------------


async def _csv_request(request: Request) -> tuple[CsvImportRequest, bytes]:
    body = await _read_body(request, (MAX_CSV_BYTES * 4) // 3 + 64 * 1024)
    try:
        payload = CsvImportRequest.model_validate_json(body)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Некорректный запрос импорта.") from None
    try:
        raw = decode_upload(payload.file_base64)
    except CsvImportFileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return payload, raw


@router.post("/import/transactions/preview")
async def preview_transactions(request: Request, db: Session = Depends(get_db)) -> dict:
    """Разбор, проверка и поиск дублей. В БД ничего не пишется."""
    payload, raw = await _csv_request(request)
    try:
        plan = build_plan(db, raw, payload.options)
    except CsvImportFileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return plan_to_dict(plan)


@router.post("/import/transactions/commit")
async def commit_transactions(request: Request, db: Session = Depends(get_db)) -> dict:
    payload, raw = await _csv_request(request)
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Импорт требует явного подтверждения.")
    try:
        plan = build_plan(db, raw, payload.options)
    except CsvImportFileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if not plan.can_import:
        problems = plan.mapping_errors or [f"строка {e['row']}: {e['message']}" for e in plan.errors[:5]]
        if not problems:
            problems = ["нет новых операций для импорта"]
        raise HTTPException(status_code=400, detail="Импорт не выполнен, данные не изменены: " + "; ".join(problems))
    try:
        return commit_plan(db, plan)
    except Exception:
        raise HTTPException(status_code=500, detail="Импорт не выполнен, данные не изменены.") from None
