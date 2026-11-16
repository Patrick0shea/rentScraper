import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False, help="run tests that hit real websites")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits real websites (opt-in with --live or RENTSCRAPER_LIVE_TESTS=1)")


def pytest_collection_modifyitems(config, items):
    import os

    if config.getoption("--live") or os.environ.get("RENTSCRAPER_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="live test: use --live or RENTSCRAPER_LIVE_TESTS=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def cfg(tmp_path):
    with open(ROOT / "config.json", encoding="utf-8") as fh:
        c = json.load(fh)
    c = copy.deepcopy(c)
    c["output"]["directory"] = str(tmp_path / "out")
    c["output"]["history_file"] = str(tmp_path / "history.json")
    c["http"]["min_delay_seconds"] = 0
    c["http"]["jitter_seconds"] = 0
    c["http"]["backoff_seconds"] = 0
    return c
