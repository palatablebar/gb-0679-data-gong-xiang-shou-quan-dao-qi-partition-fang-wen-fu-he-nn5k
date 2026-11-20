from flask import render_template,request
from app.config import TITLE,SHORT,MODULES
from app.incremental import store

def register_interval_pages(app):
    @app.get("/intervals")
    def intervals_page():
        selected=request.args.get("date")
        intervals=store.list_intervals()
        current=None
        if selected:
            current=store.get_interval(selected)
        elif intervals:
            current=intervals[0]
        return render_template("intervals.html",title=TITLE,short=SHORT,modules=MODULES,
                               intervals=intervals,current=current)
