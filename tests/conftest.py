import pytest

from tarkov_display import staticapi


@pytest.fixture(autouse=True)
def fresh_static_files():
    # Downloaded tarkov.dev files are shared process-wide; don't let one
    # test's fake files leak into another.
    staticapi.clear_cache()
    yield
    staticapi.clear_cache()
