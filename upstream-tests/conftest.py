"""conftest for upstream-tests: import fastly_hosts from ../upstream without touching it."""
import os
import sys

import pytest

UPSTREAM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "upstream")
sys.path.insert(0, UPSTREAM)

import fastly_hosts as fh  # noqa: E402  (path setup above is intentional)


@pytest.fixture(autouse=True)
def _restore_lang():
    """fastly_hosts.LANG 是模块全局变量：每个用例后恢复。"""
    old = fh.LANG
    yield
    fh.LANG = old


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    """把配置读写隔离到临时目录，避免读写用户真实 ~/.cache/fastly-hosts。"""
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(fh, "config_path", lambda: str(cfg))
    return cfg
