"""Explicit source-only retention: keep the complete report for long-term progress."""
from uuid import UUID
import shutil

from fastapi import APIRouter, Depends

from .db import database
from .replay_jobs import owned, replay_directory
from .web import account_required, csrf, reject


def remove_source(job_id, owner_id):
    with database() as connection:
        row = owned(connection, owner_id, job_id, lock=True)
        if row["state"] != "ready" or not row["result_payload"]:
            reject(409, "REPLAY_REPORT_REQUIRED", "Сначала дождитесь готового разбора.")
        if row["storage_deleted_at"] is not None:
            return {"source_deleted": True, "report_retained": True}
        # Holding the job lock excludes an ordinary state transition while
        # deleting. If deletion fails, the disk reservation is not released;
        # another request can retry without losing the stored report.
        directory = replay_directory(job_id)
        try:
            if directory.exists():
                shutil.rmtree(directory)
        except OSError:
            reject(503, "REPLAY_SOURCE_DELETE_PENDING", "Разбор сохранён. Повторите освобождение места.")
        connection.execute("DELETE FROM replay_parts WHERE job_id=%s", (job_id,))
        connection.execute("""UPDATE replay_jobs SET storage_deleted_at=now()
            WHERE id=%s AND state='ready'""", (job_id,))
    return {"source_deleted": True, "report_retained": True}


def attach_replay_archive(app):
    router = APIRouter(prefix="/api/replays")

    @router.delete("/{job_id}/source", dependencies=[Depends(csrf)])
    def archive(job_id: UUID, account=Depends(account_required)):
        return remove_source(job_id, account["owner_id"])

    app.include_router(router)
