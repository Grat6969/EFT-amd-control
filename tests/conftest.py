import pytest

from tarkov_display import staticapi


@pytest.fixture(autouse=True)
def fresh_static_files():
    # Downloaded tarkov.dev files are shared process-wide; don't let one
    # test's fake files leak into another.
    staticapi.clear_cache()
    yield
    staticapi.clear_cache()


@pytest.fixture()
def webapp(tmp_path, monkeypatch):
    """The real app (window server included) with made-up tarkov.dev data."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from tests import demo

    demo.install(monkeypatch)
    from tarkov_display.webapp import WebApp

    app = WebApp(open_on_start=False, port=0)
    app.app.prices.refresh()
    app.server.start()
    yield app
    app.server.stop()
