"""pytest 共用設定：從倉庫根目錄匯入 fastly_hosts。"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fastly_hosts as fh  # noqa: E402  （上面先設定好路徑才能匯入）


@pytest.fixture(autouse=True)
def _restore_lang():
    """fastly_hosts.LANG 是模組層級的全域變數：每個測試結束後還原。"""
    old = fh.LANG
    yield
    fh.LANG = old


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    """把設定檔的讀寫隔離到暫存資料夾，不碰使用者真正的 ~/.cache/fastly-hosts。"""
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(fh, "config_path", lambda: str(cfg))
    return cfg
