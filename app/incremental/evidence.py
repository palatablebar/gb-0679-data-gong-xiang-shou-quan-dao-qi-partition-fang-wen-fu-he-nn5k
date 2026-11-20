import csv,io,json
from app.archive import build_archive
from app import store as run_store
from app.incremental import store as iv_store

def build_interval_evidence(biz_date,version=None):
    """证据导出与授权复查使用同一版本结论；旧版快照永久保留可单独导出。"""
    interval=iv_store.get_interval(biz_date)
    version=version or interval["current_version"]
    snapshot=iv_store.get_version(biz_date,version)
    if not snapshot.get("merged_run_id"):
        from app.errors import DomainError
        raise DomainError("NOT_CLOSED","该版本尚未收口，无受理结论可导出")
    run=run_store.get(snapshot["merged_run_id"])
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["interval_id","biz_date","version","status","review_decision",
                     "intake_sha256","superseded_at","run_ids"])
    writer.writerow([interval["interval_id"],biz_date,version,snapshot["status"],
                     snapshot.get("review_decision") or "",snapshot["intake_sha256"],
                     snapshot.get("superseded_at") or "",
                     json.dumps(snapshot["run_ids"],ensure_ascii=False)])
    writer.writerow([])
    body=build_archive(run)
    if body.startswith("﻿"): body=body[1:]
    return "﻿"+stream.getvalue()+body
