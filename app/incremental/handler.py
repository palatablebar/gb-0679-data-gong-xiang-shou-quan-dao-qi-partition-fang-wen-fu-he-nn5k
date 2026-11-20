from flask import Blueprint,jsonify,request
from app.errors import DomainError
from app.incremental import store,evidence

bp=Blueprint("incremental",__name__)

@bp.get("/api/intervals")
def list_intervals():
    return jsonify({"intervals":store.list_intervals()})

@bp.get("/api/intervals/<biz_date>")
def interval_detail(biz_date):
    return jsonify(store.get_interval(biz_date))

@bp.get("/api/intervals/<biz_date>/versions/<int:version>")
def version_detail(biz_date,version):
    return jsonify(store.get_version(biz_date,version))

@bp.post("/api/intervals/<biz_date>/intake")
def intake(biz_date):
    p=request.get_json(silent=True) or {}
    if not isinstance(p.get("run_id"),str) or not p["run_id"]:
        raise DomainError("BAD_RUN","请提供已采信批次run_id")
    return jsonify(store.intake(biz_date,p["run_id"]))

@bp.post("/api/intervals/<biz_date>/close")
def close(biz_date):
    return jsonify(store.close(biz_date))

@bp.post("/api/intervals/<biz_date>/review")
def review(biz_date):
    p=request.get_json(silent=True) or {}
    if not isinstance(p.get("version"),int): raise DomainError("BAD_VERSION","请提供版本号")
    return jsonify(store.review(biz_date,p["version"],p.get("decision")))

@bp.get("/api/intervals/<biz_date>/evidence")
def export(biz_date):
    version=request.args.get("version",type=int)
    body=evidence.build_interval_evidence(biz_date,version)
    from flask import current_app
    return current_app.response_class(body,mimetype="text/csv",
        headers={"Content-Disposition":f'attachment; filename="evidence-{biz_date}-v{version or "current"}.csv"'})
