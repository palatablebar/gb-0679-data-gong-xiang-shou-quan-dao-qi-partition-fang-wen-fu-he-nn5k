import csv,io
from app.pipeline import execute,load_sample
from app import store as run_store
from app.incremental import store as iv
from app.incremental.evidence import build_interval_evidence

BIZ="2026-11-16"

def _run(sample):
    return execute(load_sample(sample))["run_id"]

def _setup_two_batches():
    r1=_run("dirty.csv");r2=_run("clean.csv")
    iv.intake(BIZ,r1);iv.intake(BIZ,r2)
    return r1,r2

def test_intake_idempotent_same_batch_not_duplicated():
    "同一区间重跑同批次不新增结论、不重复占位"
    r1,_=_setup_two_batches()
    before=iv.get_interval(BIZ)
    iv.intake(BIZ,r1)
    after=iv.get_interval(BIZ)
    assert after["current_version"]==before["current_version"]==1
    assert after["versions"][-1]["run_ids"]==before["versions"][-1]["run_ids"]
    assert len(after["versions"][-1]["run_ids"])==len(set(after["versions"][-1]["run_ids"]))

def test_close_creates_single_conclusion():
    "收口后每个增量区间只有一个受理结论，复查与导出锚定同一批次"
    r1,r2=_setup_two_batches()
    closed=iv.close(BIZ)
    assert closed["status"]==iv.CLOSED
    anchor=closed["conclusion"]["merged_run_id"]
    assert anchor and closed["conclusion"]["version"]==1
    # 重复收口不新增结论
    again=iv.close(BIZ)
    assert again["conclusion"]==closed["conclusion"]
    # 授权复查沿用同一结论锚点
    reviewed=iv.review(BIZ,1,"已复核")
    assert reviewed["status"]==iv.REVIEWED
    assert reviewed["conclusion"]["merged_run_id"]==anchor
    assert reviewed["conclusion"]["review_decision"]=="已复核"
    # 证据导出与复查同一版本
    evidence=build_interval_evidence(BIZ)
    head=next(csv.reader(io.StringIO(evidence.encode().decode("utf-8-sig"))))
    meta=list(csv.reader(io.StringIO(evidence.encode().decode("utf-8-sig"))))[1]
    assert head[0]=="interval_id" and meta[2]=="1" and meta[3]=="已复核"
    assert anchor in evidence

def test_late_record_after_close_makes_new_version_keeps_old():
    "先收口已完成部分，晚到记录走新版本回看；旧版结论与原始依据保留"
    r1,r2=_setup_two_batches()
    iv.close(BIZ);iv.review(BIZ,1,"已复核")
    old=iv.get_version(BIZ,1)
    late=_run("legacy.csv")
    reopened=iv.intake(BIZ,late)
    assert reopened["status"]==iv.REOPENED and reopened["current_version"]==2
    # 旧版快照原样保留，仍是已复核结论
    preserved=iv.get_version(BIZ,1)
    assert preserved["status"]==iv.REVIEWED
    assert preserved["merged_run_id"]==old["merged_run_id"]
    assert preserved["run_ids"]==old["run_ids"]
    assert preserved["superseded_at"]
    # 新版本包含全部批次且不重复
    v2=iv.get_version(BIZ,2)
    assert v2["run_ids"]==[r1,r2,late] and len(set(v2["run_ids"]))==3
    closed2=iv.close(BIZ)
    assert closed2["conclusion"]["version"]==2
    assert closed2["conclusion"]["merged_run_id"]!=old["merged_run_id"]
    # 旧版证据仍可独立导出
    old_evidence=build_interval_evidence(BIZ,1)
    assert old["merged_run_id"] in old_evidence

def test_late_intake_while_open_merges_into_current_version():
    "开放受理期不同批次并入当前版本，同批次重放不重复占位、不新增结论"
    r1=_run("dirty.csv");iv.intake(BIZ,r1)
    r2=_run("clean.csv");iv.intake(BIZ,r2)
    v=iv.get_interval(BIZ)
    assert v["current_version"]==1 and v["versions"][-1]["run_ids"]==[r1,r2]
    iv.intake(BIZ,r1)
    assert iv.get_interval(BIZ)["versions"][-1]["run_ids"]==[r1,r2]

def test_stale_review_409_and_failed_switch_keeps_old():
    "回看范围切换失败（陈旧版本复查）时旧版结论与原始依据保留"
    _setup_two_batches();iv.close(BIZ);iv.review(BIZ,1,"已复核")
    late=_run("legacy.csv");iv.intake(BIZ,late);iv.close(BIZ)
    before=iv.get_version(BIZ,1)
    try:
        iv.review(BIZ,1,"退回复核")
        assert False
    except Exception as e:
        assert e.status==409 and e.code=="STALE_VERSION"
    # 旧版结论与依据未被改写
    after=iv.get_version(BIZ,1)
    assert after["status"]==before["status"]=="已复核"
    assert after["merged_run_id"]==before["merged_run_id"]
    assert after["run_ids"]==before["run_ids"]
    current=iv.get_interval(BIZ)
    assert current["current_version"]==2

def test_review_requires_closed_interval():
    r1=_run("dirty.csv");iv.intake(BIZ,r1)
    try:
        iv.review(BIZ,1,"已复核");assert False
    except Exception as e:
        assert e.code=="NOT_CLOSED"

def test_bad_biz_date_and_missing_interval():
    import pytest
    from app.errors import DomainError
    with pytest.raises(DomainError):iv.get_interval("2026-13-99")
    with pytest.raises(DomainError):iv.close("2026-11-15")

def test_merged_evidence_covers_all_sources():
    "合并结论保留全部来源行，晚到记录不漏审"
    r1,r2=_setup_two_batches()
    iv.close(BIZ)
    merged_id=iv.get_interval(BIZ)["conclusion"]["merged_run_id"]
    merged=run_store.get(merged_id)
    # 合并后采纳行不少于任一单批次，且行数对平
    m6=merged["stages"][5]["metrics"]
    assert m6["balanced"] is True
    assert m6["accepted_inputs"]>=max(
        run_store.get(r1)["stages"][5]["metrics"]["accepted_inputs"],
        run_store.get(r2)["stages"][5]["metrics"]["accepted_inputs"])

def test_interval_http_flow(client):
    "HTTP 层：受理->收口->复查->晚到补录->409->双版本证据导出"
    r1=_run("dirty.csv");r2=_run("legacy.csv")
    base=f"/api/intervals/{BIZ}"
    assert client.post(base+"/intake",json={"run_id":r1}).status_code==200
    assert client.post(base+"/intake",json={"run_id":r2}).status_code==200
    assert client.post(base+"/close",json={}).get_json()["status"]==iv.CLOSED
    assert client.post(base+"/review",json={"version":1,"decision":"已复核"}).status_code==200
    late=_run("clean.csv")
    reopened=client.post(base+"/intake",json={"run_id":late}).get_json()
    assert reopened["current_version"]==2
    stale=client.post(base+"/review",json={"version":1,"decision":"退回复核"})
    assert stale.status_code==409
    client.post(base+"/close",json={})
    assert client.post(base+"/review",json={"version":2,"decision":"已复核"}).status_code==200
    ev_current=client.get(base+"/evidence")
    ev_old=client.get(base+"/evidence?version=1")
    assert ev_current.status_code==ev_old.status_code==200
    assert client.get("/api/intervals").status_code==200
    assert client.get("/intervals").status_code==200
    assert client.post("/api/intervals/bad-date/close",json={}).status_code==422
