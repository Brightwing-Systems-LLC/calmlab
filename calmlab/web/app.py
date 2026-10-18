"""The local web view: your data, served on 127.0.0.1 and nowhere else.

Two guards because any web page you visit can make your browser send a request to
127.0.0.1: the Host header must name this server, which stops DNS-rebinding pages from
reading anything, and a form must carry this process's token, which stops another site
from posting a check-in.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
import webbrowser
from datetime import date
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request

from .. import __version__, checkin, findings, metrics, paths, scene, store
from ..cli import WHAT_IS_RECORDED
from ..install import DEFAULT_SETTINGS, installed
from . import charts


def _load():
    with store.connect() as conn:
        evs = store.events(conn)
        cks = store.checkins(conn)
        pending = checkin.pending(conn, time.time())
        demo = bool(store.get_meta(conn, "demo"))
        consent = store.get_meta(conn, "consent")
    return evs, cks, pending, demo, consent


def _offset(evs: list[dict]) -> int:
    return evs[-1]["utc_offset_min"] if evs else store.local_offset_min()


def create_app(port: int = 7474) -> Flask:
    app = Flask(__name__)
    app.config["TOKEN"] = secrets.token_urlsafe(24)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @app.before_request
    def guard():
        if not app.testing and request.host not in allowed_hosts:
            abort(403)
        if request.method == "POST" and request.form.get("token") != app.config["TOKEN"]:
            abort(403)

    @app.context_processor
    def common():
        return {"token": app.config["TOKEN"], "version": __version__, "data_folder": str(paths.home())}

    @app.get("/healthz")
    def healthz():
        return "calmlab", 200, {"Content-Type": "text/plain"}

    @app.get("/")
    def you():
        evs, cks, pending, demo, consent = _load()
        all_days = findings.days(evs, cks)
        today = date.today()
        recording_since = min(all_days) if all_days else None
        return render_template(
            "you.html", tab="you", demo=demo, pending=pending, labels=checkin.DRAIN_LABELS,
            has_data=bool(evs), hooked=installed(DEFAULT_SETTINGS) or demo, consent=consent,
            days_recorded=len([d for d in all_days.values() if d.get("turns")]),
            since=recording_since, finding=findings.finding(all_days),
            week=findings.week(all_days, today), chart=charts.daily_bars(all_days, today),
            recent=[(d, row) for d, row in sorted(all_days.items(), reverse=True) if row.get("turns")][:14],
            duration=findings.duration, delta=findings.delta,
        )

    @app.get("/day/<iso>")
    def day(iso: str):
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            abort(404)
        evs, cks, pending, demo, _ = _load()
        all_days = findings.days(evs, cks)
        row = all_days.get(d)
        if not row or not row.get("turns"):
            abort(404)
        active = sorted(k for k, v in all_days.items() if v.get("turns"))
        i = active.index(d)
        tl = metrics.timeline(evs, d)
        return render_template(
            "day.html", tab="you", demo=demo, d=d, row=row, duration=findings.duration,
            chart=charts.timeline(tl, _offset(tl["events"])),
            checkins=[c for c in cks if c["local_date"] == iso], labels=checkin.DRAIN_LABELS,
            prev=active[i - 1] if i else None, next=active[i + 1] if i + 1 < len(active) else None,
        )

    @app.get("/experiment")
    def experiment():
        evs, cks, _, demo, _ = _load()
        all_days = findings.days(evs, cks)
        return render_template(
            "experiment.html", tab="experiment", demo=demo, scene=scene.running(),
            days_recorded=len([d for d in all_days.values() if d.get("turns")]), baseline_target=14,
        )

    @app.get("/others")
    def others():
        _, _, _, demo, _ = _load()
        return render_template("others.html", tab="others", demo=demo)

    @app.get("/about")
    def about():
        _, _, _, demo, _ = _load()
        return render_template("about.html", tab=None, demo=demo, recorded=WHAT_IS_RECORDED)

    @app.post("/checkin")
    def answer():
        try:
            drain = int(request.form.get("drain", ""))
        except ValueError:
            abort(400)
        if not 1 <= drain <= 5:
            abort(400)
        with store.connect() as conn:
            checkin.answer(conn, drain, time.time())
        return redirect("/?answered=1", code=303)

    return app


def serve(port: int, open_browser: bool = True, home: Path | None = None) -> None:
    from werkzeug.serving import make_server

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    if home is not None:
        os.environ["CALMLAB_HOME"] = str(home)
    server = make_server("127.0.0.1", port, create_app(port), threaded=True)
    if open_browser:
        threading.Timer(0.4, webbrowser.open, (f"http://127.0.0.1:{port}/",)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Recording carries on without it.")

