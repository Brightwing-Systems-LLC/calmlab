import pytest


@pytest.fixture(autouse=True)
def calmlab_home(tmp_path, monkeypatch):
    """Every test gets its own empty data folder. Never the real ~/.calmlab."""
    home = tmp_path / "calmlab"
    monkeypatch.setenv("CALMLAB_HOME", str(home))
    return home


@pytest.fixture
def utc(monkeypatch):
    """Pin the local clock to UTC, so hour-of-day rules are testable anywhere."""
    from calmlab import store

    monkeypatch.setattr(store, "local_offset_min", lambda ts=None: 0)


@pytest.fixture
def consented(calmlab_home):
    from calmlab import store

    with store.connect() as conn:
        store.set_meta(conn, "consent", {"version": "test", "agreed_at": 0})
    return calmlab_home
