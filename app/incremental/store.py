import json,sqlite3
from datetime import date
from app import store as run_store
from app.config import RULE_VERSION
from app.errors import DomainError

OPEN="受理中";CLOSED="已收口";REVIEWED="已复核";REOPENED="晚到补录中"

def connect():
    run_store.connect()
    db=sqlite3.connect(run_store.DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS intervals(
        interval_id TEXT PRIMARY KEY,
        biz_date TEXT NOT NULL,
        current_version INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT '受理中',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS interval_versions(
        interval_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        status TEXT NOT NULL,
        run_ids TEXT NOT NULL,
        merged_run_id TEXT,
        intake_sha256 TEXT,
        review_decision TEXT,
        reviewed_at TEXT,
        superseded_at TEXT,
        payload TEXT NOT NULL,
        PRIMARY KEY(interval_id,version))""")
    return db

def _now():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).isoformat()

def check_biz_date(biz_date):
    try: date.fromisoformat(biz_date)
    except (ValueError,TypeError): raise DomainError("BAD_INTERVAL","增量区间需为YYYY-MM-DD业务日")
    return biz_date

def _row(db,biz_date):
    return db.execute("SELECT interval_id,current_version,status,created_at,updated_at FROM intervals WHERE biz_date=?",(biz_date,)).fetchone()

def get_interval(biz_date):
    check_biz_date(biz_date)
    with connect() as db:
        row=_row(db,biz_date)
        if not row: raise DomainError("NOT_FOUND","增量区间不存在",404)
        interval_id,current_version,status,created_at,updated_at=row
        versions=[_load_version(db,interval_id,v) for v in range(1,current_version+1)]
    current=versions[-1]
    return {"interval_id":interval_id,"biz_date":biz_date,"status":status,
            "current_version":current_version,"rule_version":RULE_VERSION,
            "created_at":created_at,"updated_at":updated_at,
            "conclusion":_conclusion(current),"versions":versions}

def list_intervals():
    with connect() as db:
        rows=db.execute("SELECT biz_date FROM intervals ORDER BY biz_date DESC").fetchall()
    return [get_interval(b) for (b,) in rows]

def _load_version(db,interval_id,version):
    row=db.execute("""SELECT status,run_ids,merged_run_id,intake_sha256,review_decision,
        reviewed_at,superseded_at,payload FROM interval_versions
        WHERE interval_id=? AND version=?""",(interval_id,version)).fetchone()
    if not row: raise DomainError("NOT_FOUND","区间版本不存在",404)
    payload=json.loads(row[7])
    payload.update(version=version,status=row[0],run_ids=json.loads(row[1]),
                   merged_run_id=row[2],intake_sha256=row[3],review_decision=row[4],
                   reviewed_at=row[5],superseded_at=row[6])
    return payload

def _conclusion(version_payload):
    # 唯一受理结论：收口/复核结论与证据导出共用同一版本快照
    return {"version":version_payload["version"],"status":version_payload["status"],
            "merged_run_id":version_payload["merged_run_id"],
            "review_decision":version_payload.get("review_decision"),
            "intake_sha256":version_payload["intake_sha256"]}

def get_version(biz_date,version):
    check_biz_date(biz_date)
    with connect() as db:
        row=_row(db,biz_date)
        if not row: raise DomainError("NOT_FOUND","增量区间不存在",404)
        interval_id=row[0]
        return _load_version(db,interval_id,version)

def intake(biz_date,run_id):
    """受理一个增量批次。同区间同批次幂等；收口后受理即晚到补录，产生新版本。"""
    check_biz_date(biz_date)
    run_store.get(run_id)
    now=_now()
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO intervals(interval_id,biz_date,current_version,status,created_at,updated_at) VALUES(?,?,0,?,?,?)",
                   ("iv-"+biz_date,biz_date,OPEN,now,now))
        row=_row(db,biz_date)
        interval_id,current_version,status,_,_=row
        if current_version:
            current=_load_version(db,interval_id,current_version)
            # 已核对内容不得因补发重复占位：同批次重放直接复用，不新增结论
            if run_id in current["run_ids"]:
                return get_interval(biz_date)
            if status in (OPEN,REOPENED):
                # 受理窗口仍开放：新批次并入当前版本，不产生新结论
                run_ids=current["run_ids"]+[run_id]
                db.execute("UPDATE interval_versions SET run_ids=?,payload=? WHERE interval_id=? AND version=?",
                           (json.dumps(run_ids,ensure_ascii=False),
                            json.dumps({"run_ids":run_ids},ensure_ascii=False),
                            interval_id,current_version))
                db.execute("UPDATE intervals SET updated_at=? WHERE biz_date=?",(now,biz_date))
                return get_interval(biz_date)
            # 收口/复核后才送来的晚到记录：封存旧版结论，开启新版本回看
            db.execute("UPDATE interval_versions SET superseded_at=? WHERE interval_id=? AND version=? AND superseded_at IS NULL",
                       (now,interval_id,current_version))
            new_version=current_version+1
            db.execute("UPDATE intervals SET current_version=?,status=?,updated_at=? WHERE biz_date=?",
                       (new_version,REOPENED,now,biz_date))
            run_ids=current["run_ids"]+[run_id]
            _insert_version(db,interval_id,new_version,REOPENED,run_ids,now)
        else:
            new_version=1
            db.execute("UPDATE intervals SET current_version=1,updated_at=? WHERE biz_date=?",(now,biz_date))
            _insert_version(db,interval_id,1,OPEN,[run_id],now)
    return get_interval(biz_date)

def _insert_version(db,interval_id,version,status,run_ids,now):
    db.execute("""INSERT INTO interval_versions(interval_id,version,status,run_ids,payload)
        VALUES(?,?,?,?,?)""",(interval_id,version,status,json.dumps(run_ids,ensure_ascii=False),
        json.dumps({"run_ids":run_ids},ensure_ascii=False)))

def close(biz_date):
    """收口当前版本：合并全部已受理批次为唯一受理结论。重跑同内容不新增结论。"""
    check_biz_date(biz_date)
    with connect() as db:
        row=_row(db,biz_date)
        if not row: raise DomainError("NOT_FOUND","增量区间不存在",404)
        interval_id,current_version,status,_,_=row
        if status in (CLOSED,REVIEWED): return get_interval(biz_date)
        current=_load_version(db,interval_id,current_version)
        merged=_merge(current["run_ids"])
        now=_now()
        db.execute("UPDATE interval_versions SET status=?,merged_run_id=?,intake_sha256=?,payload=? WHERE interval_id=? AND version=?",
                   (CLOSED,merged["merged_run_id"],merged["intake_sha256"],
                    json.dumps(merged,ensure_ascii=False),interval_id,current_version))
        db.execute("UPDATE intervals SET status=?,updated_at=? WHERE biz_date=?",(CLOSED,now,biz_date))
    return get_interval(biz_date)

def _merge(run_ids):
    runs=[run_store.get(rid) for rid in run_ids]
    raw=b"".join(r["raw_text"].encode() for r in runs)
    import hashlib
    from app.pipeline import execute
    merged_run=execute(raw)
    return {"run_ids":run_ids,"merged_run_id":merged_run["run_id"],
            "intake_sha256":hashlib.sha256(raw).hexdigest(),
            "metrics":merged_run["stages"][5]["metrics"],
            "differences":merged_run["stages"][6]["metrics"]["differences"]}

def review(biz_date,version,decision):
    """授权复查：仅作用于收口版本，乐观锁保证旧版提交不覆盖新结论。"""
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    check_biz_date(biz_date);now=_now()
    with connect() as db:
        row=_row(db,biz_date)
        if not row: raise DomainError("NOT_FOUND","增量区间不存在",404)
        interval_id,current_version,status,_,_=row
        if version!=current_version:
            raise DomainError("STALE_VERSION","区间已有新版本，请基于最新版本复查",409)
        if status==REVIEWED and decision=="已复核":
            return get_interval(biz_date)
        if status not in (CLOSED,REVIEWED):
            raise DomainError("NOT_CLOSED","区间尚未收口，不能授权复查")
        new_status=REVIEWED if decision=="已复核" else CLOSED
        cursor=db.execute("""UPDATE interval_versions SET status=?,review_decision=?,reviewed_at=?
            WHERE interval_id=? AND version=? AND status IN (?,?)""",
            (new_status,decision,now,interval_id,version,CLOSED,REVIEWED))
        if cursor.rowcount!=1: raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
        db.execute("UPDATE intervals SET status=?,updated_at=? WHERE biz_date=?",(new_status,now,biz_date))
    return get_interval(biz_date)
