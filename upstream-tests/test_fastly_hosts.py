"""Tests for AFAlimru/fastly-hosts-adjust (upstream/fastly_hosts.py, MIT).

Scope: 纯函数 + 配置逻辑 + 失败路径。不碰网络（不扫真实 IP）、不写 /etc/hosts、
不读用户真实配置（见 conftest.isolated_config）。
"""
import json

import pytest

import fastly_hosts as fh


# ---------------------------------------------------------------- 语言 L()

def test_L_zh_returns_chinese_and_fixes_checkmark():
    fh.LANG = "zh"
    assert fh.L("連線成功✔", "connected OK") == "連線成功√"


def test_L_en_returns_english_and_fixes_punctuation():
    fh.LANG = "en"
    assert fh.L("連線成功", "loading… done✔") == "loading... doneOK"


def test_L_en_plain_passthrough():
    fh.LANG = "en"
    assert fh.L("中文", "plain") == "plain"


def test_sname_uses_current_language():
    fh.LANG = "zh"
    assert fh.sname(fh.GITHUB) == "GitHub 下載"
    fh.LANG = "en"
    assert fh.sname(fh.GITHUB) == "GitHub downloads"


# ---------------------------------------------------------------- detect_lang()

def _clear_locale(monkeypatch):
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)


def test_detect_lang_zh_from_lc_all(monkeypatch):
    _clear_locale(monkeypatch)
    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
    assert fh.detect_lang() == "zh"


def test_detect_lang_zh_case_insensitive(monkeypatch):
    _clear_locale(monkeypatch)
    monkeypatch.setenv("LANG", "ZH_TW.UTF-8")
    assert fh.detect_lang() == "zh"


def test_detect_lang_falls_back_through_lc_messages(monkeypatch):
    _clear_locale(monkeypatch)
    monkeypatch.setenv("LC_ALL", "")
    monkeypatch.setenv("LC_MESSAGES", "zh_HK.UTF-8")
    assert fh.detect_lang() == "zh"


def test_detect_lang_en_default(monkeypatch):
    _clear_locale(monkeypatch)
    assert fh.detect_lang() == "en"


def test_detect_lang_en_locale(monkeypatch):
    _clear_locale(monkeypatch)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert fh.detect_lang() == "en"


# ---------------------------------------------------------------- place() / city()

def test_place_known_pop_zh():
    fh.LANG = "zh"
    assert fh.place("ICN") == "首爾（ICN）"


def test_place_known_pop_en():
    fh.LANG = "en"
    assert fh.place("ICN") == "Seoul (ICN)"


def test_place_unknown_code_returns_code_itself():
    fh.LANG = "zh"
    assert fh.place("ZZZ") == "ZZZ"


def test_place_empty_or_question_mark():
    fh.LANG = "zh"
    assert fh.place("") == "節點不明"
    assert fh.place("?") == "節點不明"
    fh.LANG = "en"
    assert fh.place("") == "unknown node"


def test_city_known_and_unknown():
    fh.LANG = "zh"
    assert fh.city("NRT") == "東京"
    assert fh.city("ZZZ") == ""


# ---------------------------------------------------------------- width() / pad()

def test_width_ascii():
    assert fh.width("abc") == 3


def test_width_cjk_counts_double():
    assert fh.width("中文") == 4


def test_width_mixed():
    assert fh.width("a中b") == 4


def test_pad_ascii():
    assert fh.pad("ab", 5) == "ab   "


def test_pad_cjk_alignment():
    assert fh.pad("中", 4) == "中  "


def test_pad_never_removes_and_keeps_one_space_minimum():
    assert fh.pad("abcdef", 5) == "abcdef "


# ---------------------------------------------------------------- pop_of()

def test_pop_of_github_header():
    assert fh.pop_of("cache-nrt-rjtf7700089-NRT") == "NRT"


def test_pop_of_x_header_takes_last_matching_cache():
    assert fh.pop_of("t4_p, cache-nrt-rjaa8190044-NRT, cache-sin-wsat1880090-SIN, cache-tw-ZZZ1") == "SIN"


def test_pop_of_no_match_returns_question():
    assert fh.pop_of("cache-tw-ZZZ1") == "?"
    assert fh.pop_of("t4_p") == "?"


def test_pop_of_empty_or_none_returns_question():
    assert fh.pop_of("") == "?"
    assert fh.pop_of(None) == "?"


# ---------------------------------------------------------------- same_24()

def test_same_24_swaps_last_octet():
    assert fh.same_24("146.75.48.133", 159) == "146.75.48.159"


def test_same_24_accepts_string_suffix():
    assert fh.same_24("146.75.48.159", "133") == "146.75.48.133"


# ---------------------------------------------------------------- version_tuple()

def test_version_tuple_basic():
    assert fh.version_tuple("0.8.1") == (0, 8, 1)


def test_version_tuple_comparable():
    assert fh.version_tuple("0.8.1") < fh.version_tuple("0.9.0")
    assert fh.version_tuple("0.10.0") > fh.version_tuple("0.9.9")


def test_version_tuple_partial():
    assert fh.version_tuple("v1.2") == (1, 2)


# ---------------------------------------------------------------- fastly_ip()

def test_fastly_ip_inside_range():
    assert fh.fastly_ip("151.101.1.1", ["151.101.0.0/16"]) is True


def test_fastly_ip_outside_range():
    assert fh.fastly_ip("8.8.8.8", ["151.101.0.0/16"]) is False


def test_fastly_ip_uses_fallback_list_shape():
    assert fh.fastly_ip("23.235.32.5", fh.FALLBACK_RANGES) is True


def test_fastly_ip_invalid_address_raises():
    with pytest.raises(ValueError):
        fh.fastly_ip("not-an-ip", ["151.101.0.0/16"])


# ---------------------------------------------------------------- strip_block() / current_block()

SAMPLE_HOSTS = (
    "127.0.0.1 localhost\n"
    "::1 localhost\n"
    f"{fh.MARK_BEGIN}\n"
    "151.101.1.133\traw.githubusercontent.com\n"
    f"{fh.MARK_END}\n"
    "\n"
)


def test_strip_block_removes_managed_block_and_trailing_blanks():
    out = fh.strip_block(SAMPLE_HOSTS)
    assert out == "127.0.0.1 localhost\n::1 localhost\n"
    assert fh.MARK_BEGIN not in out
    assert "raw.githubusercontent.com" not in out


def test_strip_block_without_marks_keeps_content():
    out = fh.strip_block("127.0.0.1 localhost\n\n\n")
    assert out == "127.0.0.1 localhost\n"


def test_current_block_extracts_inner_lines():
    assert fh.current_block(SAMPLE_HOSTS) == ["151.101.1.133\traw.githubusercontent.com"]


def test_current_block_without_marks_returns_empty():
    assert fh.current_block("127.0.0.1 localhost\n") == []


# ---------------------------------------------------------------- rank()

def _cand(ip, latency):
    return {"ip": ip, "latency_ms": latency}


def test_rank_orders_by_smooth_count_first():
    cands = [_cand("1.1.1.133", 10), _cand("2.2.2.133", 5), _cand("3.3.3.133", 3)]
    speeds = {"1.1.1.133": [10.0, 10.0, 10.0],
              "2.2.2.133": [10.0, 10.0, 1.0],
              "3.3.3.133": []}
    ranked = fh.rank(cands, speeds)
    # peak=10 → threshold=max(10*0.3, 3.0)=3.0；fast: 3 / 2 / 0
    assert [c["ip"] for c in ranked] == ["1.1.1.133", "2.2.2.133", "3.3.3.133"]
    assert ranked[0]["fast"] == 3 and ranked[0]["median"] == 10.0
    assert ranked[2]["fast"] == 0 and ranked[2]["speeds"] == []


def test_rank_tie_breaks_on_median_speed():
    cands = [_cand("1.1.1.133", 9), _cand("2.2.2.133", 9)]
    speeds = {"1.1.1.133": [10.0, 1.0], "2.2.2.133": [8.0, 2.0]}
    ranked = fh.rank(cands, speeds)
    # 阈值 3.0：两者 fast 都是 1；median 5.5 > 5.0 → 1.1.1.133 排前
    assert ranked[0]["ip"] == "1.1.1.133"
    assert ranked[1]["ip"] == "2.2.2.133"


def test_rank_without_speed_data_falls_back_to_latency():
    cands = [_cand("1.1.1.133", 30), _cand("2.2.2.133", 10)]
    ranked = fh.rank(cands, {})
    assert [c["ip"] for c in ranked] == ["2.2.2.133", "1.1.1.133"]


def test_rank_floor_threshold_blocks_all_slow_routes():
    # 全部卡住时 FAST_FLOOR_MBPS=3.0 兜底：fast 全为 0，按 median 再按延迟排
    cands = [_cand("1.1.1.133", 10), _cand("2.2.2.133", 20)]
    speeds = {"1.1.1.133": [1.0, 1.2], "2.2.2.133": [2.0, 2.1]}
    ranked = fh.rank(cands, speeds)
    assert all(c["fast"] == 0 for c in ranked)
    assert ranked[0]["ip"] == "2.2.2.133"  # median 2.05 > 1.1


# ---------------------------------------------------------------- regions_from()

def test_regions_from_groups_and_sorts_by_latency():
    found = {"github": [
        {"ip": "a", "pop": "NRT", "latency_ms": 20},
        {"ip": "b", "pop": "NRT", "latency_ms": 10},
        {"ip": "c", "pop": "?", "latency_ms": 1},
        {"ip": "d", "latency_ms": 2},          # 无 pop 字段直接跳过
    ]}
    regions = fh.regions_from(found)
    assert list(regions.keys()) == ["NRT"]
    assert [r["ip"] for r in regions["NRT"]] == ["b", "a"]


def test_regions_from_accepts_plain_list():
    routes = [{"ip": "a", "pop": "ICN", "latency_ms": 5}]
    assert fh.regions_from(routes)["ICN"][0]["ip"] == "a"


# ---------------------------------------------------------------- find_region()

REGIONS = {"ICN": [{"latency_ms": 10}], "NRT": [{"latency_ms": 5}], "HND": [{"latency_ms": 8}]}


def test_find_region_by_code_case_insensitive():
    assert fh.find_region("icn", REGIONS) == "ICN"
    assert fh.find_region(" ICN ", REGIONS) == "ICN"


def test_find_region_by_english_city_picks_fastest():
    # Tokyo 对应 NRT/HND/TYO：选延迟最低的 NRT
    assert fh.find_region("Tokyo", REGIONS) == "NRT"


def test_find_region_by_chinese_city():
    assert fh.find_region("首爾", REGIONS) == "ICN"


def test_find_region_unknown_returns_none():
    assert fh.find_region("火星", REGIONS) is None
    assert fh.find_region("XXX", REGIONS) is None


# ---------------------------------------------------------------- smooth_text()

def test_smooth_text_zh():
    fh.LANG = "zh"
    assert fh.smooth_text(2) == "3 次測試有 2 次順暢"


def test_smooth_text_en():
    fh.LANG = "en"
    assert fh.smooth_text(2) == "smooth in 2 of 3 tests"


# ---------------------------------------------------------------- scan_keys()

def test_scan_keys_x_images_folds_into_github():
    assert fh.scan_keys([fh.GITHUB, fh.X_IMAGES, fh.TWITCH]) == ["github", "twitch"]


def test_scan_keys_only_github():
    assert fh.scan_keys([fh.GITHUB]) == ["github"]


# ---------------------------------------------------------------- custom_service()

def test_custom_service_without_test_url():
    svc = fh.custom_service({"domain": "example.com", "suffix": 133})
    assert svc["key"] == "custom:example.com"
    assert svc["hosts"] == [("example.com", 133)]
    assert svc["probe"] == ("example.com", "/", 133)
    assert svc["speed"] is None
    assert svc["custom"] is True


def test_custom_service_with_test_url_enables_speed_test():
    svc = fh.custom_service({"domain": "example.com", "suffix": 167,
                             "test_url": "https://example.com/big.bin"})
    assert svc["speed"] == "url"
    assert svc["test_url"] == "https://example.com/big.bin"


# ---------------------------------------------------------------- svc_by_key() / enabled() / all_services()

def test_svc_by_key_builtin(isolated_config):
    assert fh.svc_by_key("github") is fh.GITHUB
    assert fh.svc_by_key("twitch")["key"] == "twitch"
    assert fh.svc_by_key("no-such-service") is None


def test_enabled_defaults_to_true(isolated_config):
    assert fh.enabled(fh.GITHUB) is True
    assert fh.enabled(fh.TWITCH) is True


def test_enabled_respects_config_and_enabled_services_filters(isolated_config):
    isolated_config.write_text(json.dumps({"services": {"twitch": False}}), encoding="utf-8")
    assert fh.enabled(fh.TWITCH) is False
    keys = [s["key"] for s in fh.enabled_services()]
    assert "twitch" not in keys
    assert "github" in keys and "x" in keys


def test_all_services_includes_custom_from_config(isolated_config):
    isolated_config.write_text(
        json.dumps({"custom": [{"domain": "cdn.example", "suffix": 167}]}), encoding="utf-8")
    services = fh.all_services()
    custom = [s for s in services if s["key"] == "custom:cdn.example"]
    assert len(custom) == 1
    assert custom[0]["hosts"] == [("cdn.example", 167)]
    assert fh.svc_by_key("custom:cdn.example")["key"] == "custom:cdn.example"


# ---------------------------------------------------------------- 失败路径（无网络）

def test_add_custom_domain_rejects_invalid_hostname(isolated_config):
    assert fh.add_custom_domain("not a domain!!", ask=False) is False


def test_add_custom_domain_rejects_already_listed_domain(isolated_config):
    assert fh.add_custom_domain("raw.githubusercontent.com", ask=False) is False


def test_tcp_latency_refused_port_returns_none():
    # 127.0.0.1:443 本机无监听 → 连接被拒 → 返回 None（失败路径）
    assert fh.tcp_latency("127.0.0.1", tries=1, timeout=1) is None


def test_cancelled_returns_zero():
    assert fh.cancelled() == 0
    assert fh.cancelled(changed=True) == 0
