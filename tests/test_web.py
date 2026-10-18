from __future__ import annotations

import re
import time
from datetime import date

import pytest

from calmlab import checkin, store, synth
from calmlab.web.app import create_app


@pytest.fixture
def client():
    app = create_app(7474)
    app.testing = True
    return app.test_client()


@pytest.fixture
def demo(consented):
    with store.connect() as conn:
        synth.load(conn)


def test_empty_state_says_how_to_start(client, calmlab_home):
    page = client.get("/").get_data(as_text=True)
    assert "isn't recording yet" in page and "./setup" in page


def test_after_setup_the_empty_page_says_go_and_work(client, calmlab_home, tmp_path):
    from calmlab import cli

    cli.main(["setup", "--yes", "--settings", str(tmp_path / "settings.json")])
    assert "set up. Go and work." in client.get("/").get_data(as_text=True)


def test_pages_render_on_the_demo_data(client, demo):
    home = client.get("/")
    assert home.status_code == 200
    page = home.get_data(as_text=True)
    assert "Parallel starts per day" in page and "<svg" in page
    assert "CalmLab · by Brightwing Systems" in page
    day = re.search(r'href="/day/([0-9-]+)"', page).group(1)
    assert "The day, agent by agent" in client.get(f"/day/{day}").get_data(as_text=True)
    for path in ("/patterns", "/experiment", "/others", "/about", "/healthz"):
        assert client.get(path).status_code == 200


def test_patterns_renders_every_range_and_measure(client, demo):
    for rng in ("14", "56", "all", "bogus"):
        for x in ("parallel_starts", "mean_concurrency", "day_length_h", "longest_stretch_min", "median_wait_s", "bogus"):
            page = client.get(f"/patterns?range={rng}&x={x}")
            assert page.status_code == 200
    page = client.get("/patterns").get_data(as_text=True)
    for heading in ("When you work", "How long agents wait for you", "How many agents at once",
                    "Drain against your days", "Over time"):
        assert heading in page
    assert page.count("<svg") >= 11


def test_patterns_empty_state(client, calmlab_home):
    assert "Nothing to see yet." in client.get("/patterns").get_data(as_text=True)


def test_the_first_day_of_real_work_renders(client, consented):
    now = time.time()
    with store.connect() as conn:
        for kind, at in (("session_start", now - 600), ("prompt_submit", now - 590), ("turn_start", now - 590),
                         ("turn_end", now - 300), ("prompt_submit", now - 100), ("turn_start", now - 100)):
            store.add_event(conn, store.Event(kind=kind, ts=at, utc_offset_min=0, session="a" * 16))
    for path in ("/", "/patterns", "/experiment", "/about"):
        assert client.get(path).status_code == 200, path


def test_unknown_or_empty_days_are_404(client, demo):
    assert client.get("/day/not-a-date").status_code == 404
    assert client.get(f"/day/{date(2001, 1, 1).isoformat()}").status_code == 404


def test_a_waiting_checkin_can_be_answered_from_the_page(client, consented):
    with store.connect() as conn:
        checkin.mark_asked(conn, "end_of_day", time.time())
        store.add_event(conn, store.Event(kind="session_start", ts=time.time(), utc_offset_min=0, session="a" * 16))
    page = client.get("/").get_data(as_text=True)
    assert "How drained are you right now?" in page
    token = re.search(r'name="token" value="([^"]+)"', page).group(1)
    assert client.post("/checkin", data={"drain": "3"}).status_code == 403, "no token, no write"
    assert client.post("/checkin", data={"drain": "9", "token": token}).status_code == 400
    assert client.post("/checkin", data={"drain": "3", "token": token}).status_code == 303
    with store.connect() as conn:
        (row,) = store.checkins(conn)
    assert (row["drain"], row["trigger"]) == (3, "end_of_day")


def test_requests_for_another_host_are_refused(consented):
    app = create_app(7474)
    client = app.test_client()
    assert client.get("/", headers={"Host": "127.0.0.1:7474"}).status_code == 200
    assert client.get("/", headers={"Host": "evil.example:7474"}).status_code == 403


def test_the_page_loads_nothing_from_the_internet(client, demo):
    page = client.get("/").get_data(as_text=True)
    css = client.get("/static/calmlab.css").get_data(as_text=True)
    assert not re.search(r'(src|href)="https?://', page)
    assert "http" not in css
