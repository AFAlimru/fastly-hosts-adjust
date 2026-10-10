#!/usr/bin/env python3
"""fastly-hosts: find the most stable nearby Fastly route for GitHub downloads and X (Twitter) images.
fastly-hosts：自動找出附近最順的 Fastly 路線，加速 GitHub 下載與 X 圖片。

Run without arguments for the menu. / 直接執行會出現選單。

Commands / 指令：
  test            find the best route, change nothing        找出最順的路線，只測試
  apply [--yes]   test, then write the best route to hosts    測試後套用（需要管理員 / root）
  region [CODE]   scan nearby regions and pick one            掃描後選擇地區，例如 region ICN
  switch [CODE]   switch using the last scan                  用上次的掃描紀錄切換，例如 switch ICN
  list            latency of all nodes                        所有節點延遲
  update          check GitHub for a new version              檢查更新
  restore         remove this tool's hosts entries            還原
  purge           delete all data, back to the original route 刪除所有資料
  status          show the current status                     顯示目前狀況
  --lang=en|zh    display language                            顯示語言

Python standard library only; Windows and Linux. / 只使用 Python 標準函式庫，支援 Windows 與 Linux。
"""
import hashlib
import http.client
import io
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import ssl
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

VERSION = "0.7.0"
IS_WINDOWS = platform.system() == "Windows"
HOSTS_PATH = (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "etc", "hosts")
              if IS_WINDOWS else "/etc/hosts")
# hosts 檔裡只寫 ASCII，避免 Windows 解析 hosts 時遇到非英文字元出問題
MARK_BEGIN = "# >>> fastly-hosts >>> (managed by fastly_hosts.py, do not edit this block)"
MARK_END = "# <<< fastly-hosts <<<"
USER_AGENT = f"fastly-hosts/{VERSION}"
REPO = "AFAlimru/fastly-hosts-adjust"          # 檢查更新用

# GitHub 用 Fastly IP 尾碼 .133、X 圖片用 .159（同一個 /24 走同一條路線）
GITHUB = {
    "name": ("GitHub 下載", "GitHub downloads"),
    "key": "github",
    "hosts": ["release-assets.githubusercontent.com", "raw.githubusercontent.com"],
    "suffix": 133,
    "probe_host": "raw.githubusercontent.com",
    "probe_path": "/github/gitignore/main/README.md",
}
X_IMAGES = {
    "name": ("X 圖片", "X images"),
    "key": "x-images",
    "hosts": ["pbs.twimg.com"],
    "suffix": 159,
    "probe_host": "pbs.twimg.com",
    "probe_path": "/profile_images/1683325380441128960/yRsRRjGO_400x400.jpg",
}
GROUPS = [GITHUB, X_IMAGES]

# Fastly 節點代碼 → 城市（中文, 英文）
POP_NAMES = {
    "ICN": ("首爾", "Seoul"), "NRT": ("東京", "Tokyo"), "HND": ("東京", "Tokyo"), "TYO": ("東京", "Tokyo"),
    "ITM": ("大阪", "Osaka"), "KIX": ("大阪", "Osaka"), "HKG": ("香港", "Hong Kong"),
    "TPE": ("台北", "Taipei"), "SIN": ("新加坡", "Singapore"), "QPG": ("新加坡", "Singapore"),
    "MNL": ("馬尼拉", "Manila"), "KUL": ("吉隆坡", "Kuala Lumpur"), "BKK": ("曼谷", "Bangkok"),
    "CGK": ("雅加達", "Jakarta"), "SYD": ("雪梨", "Sydney"), "MEL": ("墨爾本", "Melbourne"),
    "BNE": ("布里斯本", "Brisbane"), "PER": ("伯斯", "Perth"), "ADL": ("阿德雷德", "Adelaide"),
    "AKL": ("奧克蘭", "Auckland"), "WLG": ("威靈頓", "Wellington"), "CHC": ("基督城", "Christchurch"),
    "BOM": ("孟買", "Mumbai"), "DEL": ("德里", "Delhi"), "MAA": ("清奈", "Chennai"),
    "HYD": ("海得拉巴", "Hyderabad"), "CCU": ("加爾各答", "Kolkata"), "DXB": ("杜拜", "Dubai"),
    "RUH": ("利雅德", "Riyadh"), "LAX": ("洛杉磯", "Los Angeles"), "BUR": ("洛杉磯", "Los Angeles"),
    "SJC": ("聖荷西", "San Jose"), "WVI": ("華森維爾", "Watsonville"), "PAO": ("帕羅奧圖", "Palo Alto"),
    "SEA": ("西雅圖", "Seattle"), "BFI": ("西雅圖", "Seattle"), "PDX": ("波特蘭", "Portland"),
    "YVR": ("溫哥華", "Vancouver"), "DFW": ("達拉斯", "Dallas"), "IAH": ("休士頓", "Houston"),
    "ORD": ("芝加哥", "Chicago"), "CHI": ("芝加哥", "Chicago"), "IAD": ("華盛頓", "Washington"),
    "NYC": ("紐約", "New York"), "EWR": ("紐約", "New York"), "LGA": ("紐約", "New York"),
    "JFK": ("紐約", "New York"), "BOS": ("波士頓", "Boston"), "ATL": ("亞特蘭大", "Atlanta"),
    "MIA": ("邁阿密", "Miami"), "YYZ": ("多倫多", "Toronto"), "YUL": ("蒙特婁", "Montreal"),
    "LHR": ("倫敦", "London"), "LON": ("倫敦", "London"), "LCY": ("倫敦", "London"),
    "AMS": ("阿姆斯特丹", "Amsterdam"), "FRA": ("法蘭克福", "Frankfurt"), "PAR": ("巴黎", "Paris"),
    "MAD": ("馬德里", "Madrid"), "MXP": ("米蘭", "Milan"), "LIN": ("米蘭", "Milan"),
    "FCO": ("羅馬", "Rome"), "VIE": ("維也納", "Vienna"), "CPH": ("哥本哈根", "Copenhagen"),
    "OSL": ("奧斯陸", "Oslo"), "HEL": ("赫爾辛基", "Helsinki"), "DUB": ("都柏林", "Dublin"),
    "BER": ("柏林", "Berlin"), "MUC": ("慕尼黑", "Munich"), "BRU": ("布魯塞爾", "Brussels"),
    "GRU": ("聖保羅", "São Paulo"), "GIG": ("里約", "Rio de Janeiro"),
    "EZE": ("布宜諾斯艾利斯", "Buenos Aires"), "SCL": ("聖地牙哥", "Santiago"),
    "BOG": ("波哥大", "Bogotá"), "LIM": ("利馬", "Lima"), "JNB": ("約翰尼斯堡", "Johannesburg"),
    "CPT": ("開普敦", "Cape Town"),
}

FASTLY_IP_LIST_URL = "https://api.fastly.com/public-ip-list"
# 抓不到官方清單時使用（2026-10 的官方清單）
FALLBACK_RANGES = [
    "23.235.32.0/20", "43.249.72.0/22", "103.244.50.0/24", "103.245.222.0/23", "103.245.224.0/24",
    "104.156.80.0/20", "140.248.64.0/18", "140.248.128.0/17", "146.75.0.0/17", "151.101.0.0/16",
    "157.52.64.0/18", "167.82.0.0/17", "167.82.128.0/20", "167.82.160.0/20", "167.82.224.0/20",
    "172.111.64.0/18", "185.31.16.0/22", "199.27.72.0/21", "199.232.0.0/16",
]
SCAN_WORKERS = 48           # 完整掃描時同時連線數
SCAN_TIMEOUT = 3
# 只看附近：先對所有 IP 段做只量延遲的輕量連線，比最近的節點慢超過這麼多的直接略過，
# 不做完整檢查。完整掃描全世界約 80 秒，只看附近約 15 秒。
NEAR_MARGIN_MS = 60
PRECHECK_WORKERS = 64
PRECHECK_TIMEOUT = 1.0
PRECHECK_SLACK_MS = 40      # 輕量連線時同時連線多、延遲偏高，第一階段多留一點餘裕
SPEED_TOP_N = 10            # 挑延遲最低的幾個 IP 來測速
REGION_MAX_IPS = 8          # 指定地區時最多測幾條線路（同地區不同線路的穩定度差很多，測少了容易漏掉好的）
# 實測（HiNet 晚上）：塞住的路線是「連線一開始就卡在 1 Mbps 以下」，
# 同一個 IP 有時快有時卡，所以多輪交錯測、看順暢的比例，不看單次速度。
SPEED_ROUNDS = 3
SPEED_SAMPLE_SECONDS = 3
SPEED_SAMPLE_BYTES = 8 << 20  # 每次最多 8 MB，快的路線不到一秒就結束，控制總流量
FAST_RATIO = 0.3            # 速度達到本次測到最快值的 30% 才算「順暢」
FAST_FLOOR_MBPS = 3.0       # 而且至少 3 Mbps：實測卡住時是 0.3～2.3 Mbps；
                            # 只測單一地區、全部都卡住時，光看相對比例會把卡住誤判成順暢
SPEED_REPOS = ["ollama/ollama", "cli/cli"]  # 從這些專案的最新 release 挑最大的檔案測速
TIMEOUT = 10
LINE = "─" * 60


# ---------------------------------------------------------------- 語言

LANG = "zh"


def L(zh, en):
    """依目前語言回傳中文或英文。英文用 ...，「…」在部分英文主控台的字碼頁會變成亂碼。"""
    return zh if LANG == "zh" else en.replace("…", "...")


def detect_lang():
    """系統語言是中文就用中文，其他用英文。"""
    if IS_WINDOWS:
        try:
            import ctypes
            return "zh" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x04 else "en"
        except Exception:
            return "zh"
    env = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    return "zh" if env.lower().startswith("zh") else "en"


def gname(group):
    return L(*group["name"])


def place(pop):
    """'ICN' → '首爾（ICN）' / 'Seoul (ICN)'；不認得的代碼只顯示代碼。"""
    if pop in POP_NAMES:
        zh, en = POP_NAMES[pop]
        return L(f"{zh}（{pop}）", f"{en} ({pop})")
    return pop or "?"


def city(pop):
    return L(*POP_NAMES[pop]) if pop in POP_NAMES else ""


def width(text):
    """終端機顯示寬度：中文等全形字佔兩格。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def pad(text, cols):
    return text + " " * max(cols - width(text), 1)


def progress(label, done, total):
    pct = int(done * 100 / total) if total else 100
    print(f"\r  {label} {pct:3d}%", end="" if done < total else "\n", flush=True)


# ---------------------------------------------------------------- 資料檔（掃描紀錄、設定）

def data_dir():
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "fastly-hosts")


def cache_path():
    return os.path.join(data_dir(), "scan-cache.json")


def config_path():
    return os.path.join(data_dir(), "config.json")


def _can_write_user_data():
    # Linux 用 sudo 執行時不寫：避免在 /root 或使用者資料夾留下 root 擁有的檔案
    return IS_WINDOWS or os.geteuid() != 0


def _write_json(path, data):
    if not _can_write_user_data():
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_scan(found, scanned, near_only):
    _write_json(cache_path(), {"time": f"{datetime.now():%Y-%m-%d %H:%M}", "scanned": scanned,
                               "near_only": near_only, "found": found})


def load_scan():
    data = _read_json(cache_path())
    return data if data and data.get("found") else None


def load_lang_setting():
    data = _read_json(config_path()) or {}
    return data.get("lang") if data.get("lang") in ("zh", "en") else None


def save_lang_setting(lang):
    data = _read_json(config_path()) or {}
    data["lang"] = lang
    _write_json(config_path(), data)


# ---------------------------------------------------------------- 網路量測

def resolve_system(host):
    """系統目前解析出的 IPv4（會受 hosts 影響）。"""
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)})
    except socket.gaierror:
        return []


def https_get(host, path, ip, method="GET", max_bytes=0, max_seconds=0.0, timeout=None):
    """直接連到指定 IP、但用正確網域做 TLS（SNI）和 Host，回傳量測結果。"""
    timeout = timeout or TIMEOUT
    result = {"ip": ip, "ok": False}
    t0 = time.perf_counter()
    raw = socket.create_connection((ip, 443), timeout=timeout)
    result["connect_ms"] = (time.perf_counter() - t0) * 1000
    ctx = ssl.create_default_context()
    sock = ctx.wrap_socket(raw, server_hostname=host)
    conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ctx)
    conn.sock = sock
    try:
        conn.request(method, path, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        resp = conn.getresponse()
        result["status"] = resp.status
        result["served_by"] = resp.getheader("x-served-by", "")
        got, t_start = 0, time.perf_counter()
        if method == "GET":
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                elapsed = time.perf_counter() - t_start
                if (max_bytes and got >= max_bytes) or (max_seconds and elapsed >= max_seconds):
                    break
        elapsed = max(time.perf_counter() - t_start, 1e-6)
        result["bytes"] = got
        result["mbps"] = got * 8 / elapsed / 1e6
        result["ok"] = 200 <= resp.status < 400
    finally:
        conn.close()
    return result


def tcp_latency(ip, tries=3, timeout=None):
    vals = []
    for _ in range(tries):
        t0 = time.perf_counter()
        try:
            socket.create_connection((ip, 443), timeout=timeout or TIMEOUT).close()
            vals.append((time.perf_counter() - t0) * 1000)
        except OSError:
            pass
    return statistics.median(vals) if vals else None


def pop_of(served_by):
    """從 x-served-by 取出最靠近使用者的 Fastly 節點代碼。
    GitHub：'cache-nrt-rjtf7700089-NRT' → 'NRT'
    X：'t4_p, cache-nrt-rjaa8190044-NRT, cache-sin-wsat1880090-SIN, cache-tw-ZZZ1' → 'SIN'
    （最後一個符合 cache-xxx-...-XXX 格式的就是對外的邊緣節點）"""
    for part in reversed((served_by or "").split(",")):
        bits = part.strip().split("-")
        if len(bits) >= 3 and bits[0] == "cache" and len(bits[-1]) == 3 and bits[-1].isalpha():
            return bits[-1].upper()
    return "?"


def probe(group, ip, tries=1, timeout=None):
    """用該組網域對 IP 發 HEAD：確認憑證與內容正確，回傳節點與延遲；失敗回傳 None。"""
    try:
        lat = tcp_latency(ip, tries=tries, timeout=timeout)
        r = https_get(group["probe_host"], group["probe_path"], ip, method="HEAD", timeout=timeout)
        if lat is None or not r["ok"]:
            return None
        return {"ip": ip, "pop": pop_of(r.get("served_by")), "latency_ms": lat}
    except (OSError, ssl.SSLError, http.client.HTTPException):
        return None


def _follow_to_githubusercontent(url):
    """github.com 的下載連結會 302 轉到 githubusercontent.com 的簽章網址。"""
    for _ in range(5):
        host, path = url.split("/", 3)[2], "/" + url.split("/", 3)[3]
        conn = http.client.HTTPSConnection(host, timeout=TIMEOUT)
        conn.request("GET", path, headers={"User-Agent": USER_AGENT})
        resp = conn.getresponse()
        loc = resp.getheader("location")
        conn.close()
        if resp.status not in (301, 302, 303, 307, 308) or not loc:
            break
        url = loc
        if "githubusercontent.com" in url.split("/", 3)[2]:
            return url
    raise RuntimeError("no release-assets download URL")


def github_release_url():
    """取得一個大型 GitHub release 檔案的下載網址（測速時只下載開頭幾 MB）。
    簽章網址幾分鐘後會過期，所以每一輪測速前重新取得。"""
    last_error = None
    for repo in SPEED_REPOS:
        try:
            conn = http.client.HTTPSConnection("api.github.com", timeout=TIMEOUT)
            conn.request("GET", f"/repos/{repo}/releases/latest", headers={"User-Agent": USER_AGENT})
            data = json.loads(conn.getresponse().read())
            conn.close()
            asset = max(data["assets"], key=lambda a: a["size"])
            return _follow_to_githubusercontent(asset["browser_download_url"]), asset["name"]
        except Exception as e:
            last_error = e
    raise RuntimeError(L(f"拿不到測速檔案：{last_error}", f"cannot get a speed-test file: {last_error}"))


def fastly_ranges():
    try:
        conn = http.client.HTTPSConnection("api.fastly.com", timeout=TIMEOUT)
        conn.request("GET", "/public-ip-list", headers={"User-Agent": USER_AGENT})
        return json.loads(conn.getresponse().read())["addresses"]
    except Exception:
        return FALLBACK_RANGES


def same_24(ip, suffix):
    """同一個 /24 換成另一個尾碼，例如 146.75.48.133 → 146.75.48.159。"""
    return ".".join(ip.split(".")[:3] + [str(suffix)])


def _all_probe_ips(ranges):
    ips = []
    for cidr in ranges:
        net = ipaddress.ip_network(cidr, strict=False)
        subs = net.subnets(new_prefix=24) if net.prefixlen < 24 else [net]
        ips += [same_24(str(s.network_address), GITHUB["suffix"]) for s in subs]
    return ips


def scan(label, near_only=True):
    """每個 /24 挑一個 IP 檢查。回傳 {"found": [IP 資訊（依延遲排序）], "scanned": 總數, "skipped": 略過的遠方數量}。
    near_only=True：先只量延遲，比最近的慢 NEAR_MARGIN_MS 以上的略過，只對附近的做完整檢查。"""
    ips = _all_probe_ips(fastly_ranges())
    if near_only:
        # 第一階段：只量延遲（0～80%）
        lat = {}
        with ThreadPoolExecutor(max_workers=PRECHECK_WORKERS) as pool:
            futures = {pool.submit(tcp_latency, ip, 1, PRECHECK_TIMEOUT): ip for ip in ips}
            for done, fut in enumerate(as_completed(futures), 1):
                if fut.result():
                    lat[futures[fut]] = fut.result()
                if done % 32 == 0:
                    progress(label, done * 80 // len(ips), 100)
        if not lat:
            progress(label, 100, 100)
            return {"found": [], "scanned": len(ips), "skipped": 0}
        cutoff = min(lat.values()) + NEAR_MARGIN_MS + PRECHECK_SLACK_MS
        targets = [ip for ip, ms in lat.items() if ms <= cutoff]
        # 第二階段：附近的才做完整檢查（80～100%），延遲量 3 次比較準
        found = []
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(probe, GITHUB, ip, 3, SCAN_TIMEOUT) for ip in targets]
            for done, fut in enumerate(as_completed(futures), 1):
                if fut.result():
                    found.append(fut.result())
                progress(label, 80 + done * 20 // len(futures), 100)
        if found:
            nearest = min(r["latency_ms"] for r in found)
            found = [r for r in found if r["latency_ms"] <= nearest + NEAR_MARGIN_MS]
        found.sort(key=lambda r: r["latency_ms"])
        return {"found": found, "scanned": len(ips), "skipped": len(lat) - len(found)}

    # 完整掃描：全部做完整檢查，再把每個 IP 的延遲各量 3 次（同時量的數量少，比較準）
    found = []
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        futures = [pool.submit(probe, GITHUB, ip, 1, SCAN_TIMEOUT) for ip in ips]
        for done, fut in enumerate(as_completed(futures), 1):
            if fut.result():
                found.append(fut.result())
            if done % 24 == 0 or done == len(futures):
                progress(label, done * 80 // len(futures), 100)
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(tcp_latency, r["ip"], 3, SCAN_TIMEOUT): r for r in found}
        for done, fut in enumerate(as_completed(futures), 1):
            if fut.result():
                futures[fut]["latency_ms"] = fut.result()
            progress(label, 80 + done * 20 // max(len(futures), 1), 100)
    if not found:
        progress(label, 100, 100)
    found.sort(key=lambda r: r["latency_ms"])
    return {"found": found, "scanned": len(ips), "skipped": 0}


def scan_cached(label, near_only=True):
    result = scan(label, near_only)
    save_scan(result["found"], result["scanned"], near_only)
    return result


def regions_from(found):
    """掃描結果依地區分組：{節點代碼: [IP 資訊（依延遲排序）]}。"""
    regions = {}
    for r in found:
        if r.get("pop") and r["pop"] != "?":
            regions.setdefault(r["pop"], []).append(r)
    for ips in regions.values():
        ips.sort(key=lambda r: r["latency_ms"])
    return regions


def speed_test(candidates, label, rounds=SPEED_ROUNDS):
    """多輪交錯測速。回傳 {ip: [Mbps, ...]}。"""
    speeds = {c["ip"]: [] for c in candidates}
    total, done = len(candidates) * rounds, 0
    for _ in range(rounds):
        url, _ = github_release_url()
        host, path = url.split("/", 3)[2], "/" + url.split("/", 3)[3]
        for c in candidates:
            try:
                r = https_get(host, path, c["ip"], max_bytes=SPEED_SAMPLE_BYTES, max_seconds=SPEED_SAMPLE_SECONDS)
                speeds[c["ip"]].append(r["mbps"] if r["ok"] else 0.0)
            except (OSError, ssl.SSLError, http.client.HTTPException):
                speeds[c["ip"]].append(0.0)
            done += 1
            progress(label, done, total)
    return speeds


def rank(candidates, speeds):
    """依「順暢次數」→「速度中位數」→「延遲」排序。"""
    peak = max((v for vs in speeds.values() for v in vs), default=0)
    threshold = max(peak * FAST_RATIO, FAST_FLOOR_MBPS)
    for c in candidates:
        vs = speeds.get(c["ip"], [])
        c["fast"] = sum(1 for v in vs if v >= threshold)
        c["median"] = statistics.median(vs) if vs else 0
        c["speeds"] = vs
    return sorted(candidates, key=lambda c: (-c["fast"], -c["median"], c["latency_ms"]))


def analyze():
    """掃描附近節點 + 測速 + 判斷。回傳 GitHub 與 X 圖片各自的建議。"""
    has_block = bool(current_block(read_hosts()))
    base_word = L("目前設定", "Current setting") if has_block else L("目前路線", "Current route")
    sc = scan_cached(L("步驟 1/2：尋找附近的節點…", "Step 1/2: finding nearby nodes…"))
    top = sc["found"]
    if not top:
        fail = {"best": None, "apply": False,
                "reason": L("找不到可用的節點（網路不通或被擋）", "No usable node found (network down or blocked)")}
        return {"github": dict(fail, group=GITHUB), "x": dict(fail, group=X_IMAGES), "ranked": [], **sc}

    # 測速對象：延遲最低的幾個 + GitHub 目前用的 IP + X 圖片目前用的 IP 所在的路線
    base_gh = resolve_system(GITHUB["probe_host"])
    base_x = resolve_system(X_IMAGES["probe_host"])
    cands = {c["ip"]: c for c in top[:SPEED_TOP_N]}
    for ip in base_gh + [same_24(ip, GITHUB["suffix"]) for ip in base_x]:
        if ip not in cands:
            info = probe(GITHUB, ip)
            if info:
                cands[ip] = info
    cands = list(cands.values())
    ranked = rank(cands, speed_test(cands, L("步驟 2/2：實際測試下載速度…", "Step 2/2: testing download speed…")))
    for c in ranked:
        c["is_base_gh"] = c["ip"] in base_gh
        c["is_base_x_route"] = c["ip"] in {same_24(ip, GITHUB["suffix"]) for ip in base_x}

    def smooth(n, total=SPEED_ROUNDS):
        return L(f"{total} 次測試有 {n} 次順暢", f"smooth in {n} of {total} tests")

    # GitHub
    best = ranked[0]
    base_rows = [c for c in ranked if c["is_base_gh"]]
    base_fast = max((c["fast"] for c in base_rows), default=0)
    base_pop = base_rows[0]["pop"] if base_rows else "?"
    before = L(f"{base_word} {place(base_pop)}：", f"{base_word} {place(base_pop)}: ") + smooth(base_fast)
    after = (L(f"建議路線 {place(best['pop'])}：", f"Suggested {place(best['pop'])}: ") + smooth(best["fast"]) +
             L(f"，延遲約 {best['latency_ms']:.0f} ms", f", latency ~{best['latency_ms']:.0f} ms"))
    if best["is_base_gh"]:
        gh = {"apply": False, "reason": L(f"{base_word}已經是最順的路線，不需要改",
                                          f"{base_word} is already the smoothest, no change needed")}
    elif best["fast"] > base_fast:
        gh = {"apply": True, "reason": f"{before}\n{after}"}
    else:
        gh = {"apply": False, "reason": before + L("，跟其他路線一樣順，不需要改",
                                                   ", as smooth as the others, no change needed")}
    gh.update(group=GITHUB, best=best)

    # X 圖片：圖片太小測不出速度，用同一個 /24 在 GitHub 測速的結果代表該路線的穩定度。
    # 但 X 不是每個節點都有部署（實測連香港的 IP，X 會轉給新加坡出貨），
    # 所以只採用「X 實際出貨節點 = 該路線 GitHub 節點」的路線，確定真的走那條路。
    by_ip = {c["ip"]: c for c in ranked}
    base_x_fast, base_x_verified, base_x_pop = 0, False, "?"
    for ip in base_x:
        route = by_ip.get(same_24(ip, GITHUB["suffix"]))
        info = probe(X_IMAGES, ip)
        if info:
            base_x_pop = info["pop"]
        if route and info and info["pop"] == route["pop"]:
            base_x_fast = max(base_x_fast, route["fast"])
            base_x_verified = True
    x_best = None
    for c in ranked:
        if c["fast"] <= base_x_fast:
            break
        info = probe(X_IMAGES, same_24(c["ip"], X_IMAGES["suffix"]))
        if info and info["pop"] == c["pop"]:
            info["fast"] = c["fast"]
            x_best = info
            break
    if x_best:
        head = L(f"{base_word} {place(base_x_pop)}：", f"{base_word} {place(base_x_pop)}: ")
        before = head + (smooth(base_x_fast) if base_x_verified else L("無法確認順不順", "cannot be verified"))
        after = (L(f"建議路線 {place(x_best['pop'])}：", f"Suggested {place(x_best['pop'])}: ") + smooth(x_best["fast"]) +
                 L(f"，延遲約 {x_best['latency_ms']:.0f} ms", f", latency ~{x_best['latency_ms']:.0f} ms"))
        x = {"apply": True, "best": x_best, "reason": f"{before}\n{after}"}
    else:
        x = {"apply": False, "best": None,
             "reason": L("沒有比目前更順、又能提供 X 圖片的路線，不需要改",
                         "No smoother route that also serves X images, no change needed")}
    x.update(group=X_IMAGES)
    return {"github": gh, "x": x, "ranked": ranked, **sc}


# ---------------------------------------------------------------- 顯示

def print_summary(result):
    print(L(f"\n【結果】（掃描 {result['scanned']} 個位置，附近可用 {len(result['found'])} 個，"
            f"略過較遠的 {result['skipped']} 個）",
            f"\n[Result] (scanned {result['scanned']} locations, {len(result['found'])} usable nearby, "
            f"{result['skipped']} distant ones skipped)"))
    for key in ("github", "x"):
        r = result[key]
        if r["apply"]:
            print(L(f"\n  ✔ {gname(r['group'])}：建議改走 {place(r['best']['pop'])}",
                    f"\n  ✔ {gname(r['group'])}: switch to {place(r['best']['pop'])}"))
        else:
            print(L(f"\n  ・{gname(r['group'])}：維持現狀", f"\n  - {gname(r['group'])}: keep as is"))
        for line in r["reason"].split("\n"):
            print(f"      {line}")
    print(L("\n  「順暢」＝速度達到這次測到最快速度的 30% 以上（且至少 3 Mbps）；卡住的路線通常只剩 1 Mbps 左右。",
            "\n  \"Smooth\" = at least 30% of the fastest speed in this test (and at least 3 Mbps);"
            "\n  a congested route usually crawls at about 1 Mbps."))


def print_details(result):
    print(L(f"\n【詳細數據】GitHub 下載測速（每條路線測 {SPEED_ROUNDS} 次，單位 Mbps）",
            f"\n[Details] GitHub download speed ({SPEED_ROUNDS} tests per route, Mbps)"))
    print(f"  {'IP':<16}{pad(L('地點', 'Location'), 20)}{L('延遲', 'Latency'):>7}  "
          f"{pad(L('順暢', 'Smooth'), 7)}{L('各次速度', 'Speeds')}")
    for c in result["ranked"]:
        tag = (L("← 目前 GitHub", "← current GitHub") if c["is_base_gh"] else
               (L("← 目前 X 圖片", "← current X images") if c["is_base_x_route"] else ""))
        vs = " / ".join(f"{v:5.1f}" for v in c["speeds"])
        smooth = f"{c['fast']}/{SPEED_ROUNDS}"
        print(f"  {c['ip']:<16}{pad(place(c['pop']), 20)}{c['latency_ms']:5.0f}ms  {pad(smooth, 7)}{vs}  {tag}")


def current_status():
    """目前每組網域實際走的節點與延遲，以及 hosts 套用狀態。"""
    block = current_block(read_hosts())
    applied = next((l.split("applied", 1)[1].strip() for l in block if l.startswith("# applied")), None)
    rows = []
    for g in GROUPS:
        ips = resolve_system(g["probe_host"])
        info = probe(g, ips[0], tries=3) if ips else None
        rows.append({"group": g, "ip": ips[0] if ips else None, "info": info})
    return {"block": block, "applied": applied, "rows": rows}


def print_status(st):
    print(L("【目前狀況】", "[Current status]"))
    for r in st["rows"]:
        label = pad(gname(r["group"]) + L("：", ":"), 20)
        if r["info"]:
            print(L(f"  {label}目前走 {place(r['info']['pop'])}，延遲約 {r['info']['latency_ms']:.0f} ms",
                    f"  {label}via {place(r['info']['pop'])}, latency ~{r['info']['latency_ms']:.0f} ms"))
        elif r["ip"]:
            print(L(f"  {label}連不上（{r['ip']}）", f"  {label}unreachable ({r['ip']})"))
        else:
            print(L(f"  {label}查不到網址（DNS 失敗）", f"  {label}DNS lookup failed"))
    label = pad(L("本工具設定：", "This tool:"), 20)
    if st["block"]:
        print(L(f"  {label}已套用（{st['applied'] or '時間不明'}）",
                f"  {label}applied ({st['applied'] or 'time unknown'})"))
    else:
        print(L(f"  {label}未套用（使用系統原本的路線）", f"  {label}not applied (system default route)"))


# ---------------------------------------------------------------- hosts 檔

def is_admin():
    if IS_WINDOWS:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def read_hosts():
    # latin-1：任何位元組都能原樣讀進來再原樣寫回，不會改壞原檔裡的其他文字
    with open(HOSTS_PATH, "r", encoding="latin-1") as f:
        return f.read()


def strip_block(text):
    out, inside = [], False
    for line in text.splitlines():
        if line.strip() == MARK_BEGIN:
            inside = True
            continue
        if line.strip() == MARK_END:
            inside = False
            continue
        if not inside:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n"


def current_block(text):
    lines, inside = [], False
    for line in text.splitlines():
        if line.strip() == MARK_BEGIN:
            inside = True
            continue
        if line.strip() == MARK_END:
            break
        if inside:
            lines.append(line)
    return lines


def write_hosts(text):
    backup = HOSTS_PATH + ".fastly-hosts.bak"
    if not os.path.exists(backup):       # 只在第一次備份，保留最原始的版本
        shutil.copy2(HOSTS_PATH, backup)
    newline = "\r\n" if IS_WINDOWS else "\n"
    with open(HOSTS_PATH, "w", encoding="latin-1", newline=newline) as f:
        f.write(text)
    return backup


def flush_dns():
    cmds = [["ipconfig", "/flushdns"]] if IS_WINDOWS else [["resolvectl", "flush-caches"]]
    for cmd in cmds:
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass


def write_routes(routes):
    """routes：[(群組, IP, 節點代碼), ...]。整段取代本工具的設定，回傳備份檔路徑。"""
    lines = [MARK_BEGIN, f"# applied {datetime.now():%Y-%m-%d %H:%M}"]
    for group, ip, pop in routes:
        lines.append(f"# {group['key']}: Fastly {pop}")
        lines += [f"{ip}\t{h}" for h in group["hosts"]]
    lines.append(MARK_END)
    backup = write_hosts(strip_block(read_hosts()) + "\n" + "\n".join(lines) + "\n")
    flush_dns()
    return backup


# ---------------------------------------------------------------- 權限

def _script_args(action, pause, extra_args=()):
    """重新執行自己時的程式與參數（exe 或 .py 都適用）。語言要明確傳下去：
    Linux 的 sudo 會換成 root 的家目錄，讀不到使用者的語言設定。"""
    extra = [action] + list(extra_args) + [f"--lang={LANG}"] + (["--pause"] if pause else [])
    if getattr(sys, "frozen", False):
        return sys.executable, extra
    return sys.executable, [os.path.abspath(__file__)] + extra


def run_elevated(action, extra_args=()):
    """以管理員 / root 身分執行同一個動作，等它結束。回傳是否有成功啟動。"""
    if not IS_WINDOWS:
        exe, args = _script_args(action, pause=False, extra_args=extra_args)
        print(L("需要 root 權限，請輸入你的 Linux 登入密碼（輸入時畫面不會顯示）：",
                "Root permission needed. Enter your Linux login password (it will not be shown):"))
        return subprocess.call(["sudo", exe] + args) == 0
    # Windows：跳出 UAC，開新視窗執行，等它關閉
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    exe, args = _script_args(action, pause=True, extra_args=extra_args)
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40                     # SEE_MASK_NOCLOSEPROCESS：拿到 process handle 才能等它
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = subprocess.list2cmdline(args)
    info.nShow = 1
    print(L("需要系統管理員權限，請在跳出的視窗按「是」。",
            "Administrator permission needed. Click \"Yes\" in the pop-up window."))
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        print(L("沒有取得權限（可能按了「否」）。", "Permission was not granted (\"No\" was clicked?)."))
        return False
    print(L("已在新視窗執行，完成後請在新視窗按 Enter 關閉…",
            "Running in a new window. When it finishes, press Enter there to close it…"))
    if info.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return True


# ---------------------------------------------------------------- 動作

def ask_yes(question, default=True):
    ans = input(f"{question} {'(Y/n)' if default else '(y/N)'}{L('：', ': ')}").strip().lower()
    return default if not ans else ans in ("y", "yes")


def cancelled(changed=False):
    print(L("已取消，沒有修改任何設定。", "Cancelled, nothing changed.") if not changed else L("已取消。", "Cancelled."))
    return 0


def action_test(interactive=True):
    print(L("\n開始測試，大約需要 2 分鐘，會用掉約 300 MB 流量（只測試，不改任何設定）。\n",
            "\nTesting, about 2 minutes and ~300 MB of data (test only, nothing is changed).\n"))
    result = analyze()
    print_summary(result)
    if interactive and result["ranked"] and ask_yes(L("\n要看詳細數據嗎？", "\nShow details?"), default=False):
        print_details(result)
    elif not interactive and result["ranked"]:
        print_details(result)
    return result


def action_apply(yes=False):
    if not is_admin():
        return 0 if run_elevated("apply", ["--yes"] if yes else []) else 1
    # 先拿掉舊設定再測，避免量到自己上次寫入的結果
    original = read_hosts()
    if current_block(original):
        write_hosts(strip_block(original))
        flush_dns()
    result = action_test(interactive=not yes)
    routes = [(result[k]["group"], result[k]["best"]["ip"], result[k]["best"]["pop"])
              for k in ("github", "x") if result[k]["apply"]]
    if not routes:
        print(L("\n目前的路線已經很順，不需要修改，設定維持原狀。",
                "\nThe current route is already smooth; nothing to change."))
        return 0
    if not yes and not ask_yes(L("\n要套用上面建議的路線嗎？", "\nApply the suggested route(s)?")):
        return cancelled()
    backup = write_routes(routes)
    print(L("\n✔ 已套用！之後 GitHub 下載 / X 圖片會走新的路線。",
            "\n✔ Applied! GitHub downloads / X images will now use the new route."))
    print(L(f"  （設定寫在 {HOSTS_PATH}，原始檔案備份在 {backup}）",
            f"  (Written to {HOSTS_PATH}; original backed up to {backup})"))
    print(L("  想恢復原狀，隨時選「還原」即可。", "  Choose \"Restore\" any time to undo."))
    return 0


def find_region(text, regions):
    """輸入地區代碼（ICN）或城市名稱（首爾 / Seoul），回傳可用的節點代碼；找不到回傳 None。"""
    t = text.strip()
    if t.upper() in regions:
        return t.upper()
    same_city = [pop for pop in regions if t.lower() in (n.lower() for n in POP_NAMES.get(pop, ()))]
    return min(same_city, key=lambda pop: regions[pop][0]["latency_ms"]) if same_city else None


def choose_and_apply(pop, ips, verify=False):
    """在指定地區的線路裡實測挑最穩的，確認後套用（GitHub + 可用的話 X 圖片）。
    verify=True：IP 來自舊的掃描紀錄，先確認它們現在還連到同一個地區。"""
    if verify:
        checked = [probe(GITHUB, c["ip"], tries=3) for c in ips[:REGION_MAX_IPS + 2]]
        cands = [c for c in checked if c and c["pop"] == pop][:REGION_MAX_IPS]
        if not cands:
            print(L(f"上次記錄的 {place(pop)} 線路現在連不到，或已經改連別的地區。",
                    f"The recorded routes to {place(pop)} are unreachable now or go elsewhere."))
            print(L("請用「3. 手動選擇地區」重新掃描。", "Use \"3. Choose region\" to scan again."))
            return 1
    else:
        cands = ips[:REGION_MAX_IPS]

    # 同一個地區不同 IP 的穩定度差很多（實測東京有的 IP 每次都順、有的常卡），所以再挑一次
    secs = max(10, len(cands) * 6)
    print(L(f"\n測試 {place(pop)} 的 {len(cands)} 條線路（約 {secs} 秒）…",
            f"\nTesting {len(cands)} route(s) to {place(pop)} (about {secs} s)…"))
    ranked = rank(cands, speed_test(cands, L("測試線路…", "Testing routes…"), rounds=2))
    for c in ranked:
        vs = " / ".join(f"{v:5.1f}" for v in c["speeds"])
        print(L(f"  {c['ip']:<16}延遲 {c['latency_ms']:4.0f} ms  順暢 {c['fast']}/2  [{vs}] Mbps",
                f"  {c['ip']:<16}latency {c['latency_ms']:4.0f} ms  smooth {c['fast']}/2  [{vs}] Mbps"))
    best = ranked[0]
    if best["fast"] == 0 and not ask_yes(
            L(f"\n{place(pop)} 目前每條線路都卡住，仍要改走這裡嗎？",
              f"\nEvery route to {place(pop)} is congested right now. Switch anyway?"), default=False):
        return cancelled()

    # X 圖片：只採用 X 實際由這個地區出貨的線路
    x = None
    for c in ranked:
        info = probe(X_IMAGES, same_24(c["ip"], X_IMAGES["suffix"]))
        if info and info["pop"] == pop:
            x = info
            break
    print(L(f"\n  {pad('GitHub 下載：', 14)}改走 {place(pop)}，使用 {best['ip']}",
            f"\n  {pad('GitHub downloads:', 19)}switch to {place(pop)} via {best['ip']}"))
    if x:
        print(L(f"  {pad('X 圖片：', 14)}改走 {place(pop)}，使用 {x['ip']}",
                f"  {pad('X images:', 19)}switch to {place(pop)} via {x['ip']}"))
    else:
        print(L(f"  {pad('X 圖片：', 14)}X 在 {place(pop)} 沒有機房，維持系統原本的路線",
                f"  {pad('X images:', 19)}X has no node in {place(pop)}; keeping the default route"))
    if not ask_yes(L("\n確定要套用嗎？", "\nApply?")):
        return cancelled()
    args = [f"github={best['ip']}:{pop}"] + ([f"x={x['ip']}:{pop}"] if x else [])
    return action_set(args)


def ask_code(code):
    if code is None:
        code = input(L("\n請輸入地區代碼或城市名稱（例如 ICN 或 首爾），直接按 Enter 取消：",
                       "\nEnter a region code or city (e.g. ICN or Seoul), or press Enter to cancel: ")).strip()
    return code


def full_scan_for(code):
    """附近的掃描裡找不到時：問要不要完整掃描全世界的節點，回傳新的地區表或 None。"""
    if not ask_yes(L(f"附近的節點裡沒有「{code}」，可能距離較遠被略過了。要完整掃描全世界的節點嗎？（約 1.5 分鐘）",
                     f"\"{code}\" is not among nearby nodes (distant ones are skipped). "
                     f"Scan all nodes worldwide? (about 1.5 min)")):
        return None
    return regions_from(scan_cached(L("掃描所有節點…", "Scanning all nodes…"), near_only=False)["found"])


def action_region(code=None):
    """手動選擇地區：掃描附近、列出可用的地區，輸入代碼後在該地區挑最穩的線路。"""
    print(L("\n正在尋找附近可用的地區…", "\nFinding nearby regions…"))
    regions = regions_from(scan_cached(L("尋找附近的地區…", "Finding nearby regions…"))["found"])
    if not regions:
        print(L("找不到可用的地區（網路不通或被擋）。", "No usable region found (network down or blocked)."))
        return 1
    nearest = sorted(regions, key=lambda pop: regions[pop][0]["latency_ms"])
    print(L("\n【附近可用的地區】（依延遲排序）", "\n[Nearby regions] (by latency)"))
    for pop in nearest:
        print(L(f"  {pop}  {pad(city(pop), 10)}延遲約 {regions[pop][0]['latency_ms']:.0f} ms",
                f"  {pop}  {pad(city(pop), 14)}latency ~{regions[pop][0]['latency_ms']:.0f} ms"))
    print(L("  （較遠的地區已略過；也可以直接輸入它們的代碼，會再完整掃描）",
            "  (Distant regions are skipped; you can still enter their code to scan everything.)"))

    code = ask_code(code)
    if not code:
        return cancelled(changed=True)
    pop = find_region(code, regions)
    if not pop:
        regions = full_scan_for(code)
        pop = find_region(code, regions) if regions else None
    if not pop:
        print(L(f"找不到「{code}」這個地區，或你的網路目前連不到那裡。",
                f"Region \"{code}\" not found, or it is unreachable from your network."))
        return 1
    return choose_and_apply(pop, regions[pop])


def action_switch(code=None):
    """指定節點：用上次的掃描紀錄，直接輸入代碼切換（不用等掃描）。"""
    cache = load_scan()
    if cache:
        print(L(f"\n使用上次的掃描紀錄（{cache['time']}）。", f"\nUsing the last scan ({cache['time']})."))
        regions = regions_from(cache["found"])
    else:
        print(L("\n還沒有掃描紀錄，先掃描附近的節點…", "\nNo scan yet; scanning nearby nodes first…"))
        regions = regions_from(scan_cached(L("尋找附近的地區…", "Finding nearby regions…"))["found"])
    code = ask_code(code)
    if not code:
        return cancelled(changed=True)
    pop = find_region(code, regions)
    from_cache = bool(cache)
    if not pop:
        regions = full_scan_for(code)
        pop, from_cache = (find_region(code, regions) if regions else None), False
    if not pop:
        print(L(f"找不到「{code}」這個節點，或你的網路目前連不到那裡。",
                f"Node \"{code}\" not found, or it is unreachable from your network."))
        return 1
    return choose_and_apply(pop, regions[pop], verify=from_cache)


def action_list():
    """查看所有節點的延遲，每頁 10 個。"""
    cache = load_scan()
    if cache and not cache.get("near_only"):
        rescan = ask_yes(L(f"\n上次掃描時間：{cache['time']}。要重新掃描所有節點嗎？（選 n 直接顯示上次的結果）",
                           f"\nLast scan: {cache['time']}. Scan all nodes again? (n = show the last result)"),
                         default=False)
    elif cache:
        print(L(f"\n上次（{cache['time']}）只掃描了附近的節點，要看全部需要完整掃描（約 1.5 分鐘）。",
                f"\nThe last scan ({cache['time']}) covered nearby nodes only; "
                f"listing all needs a full scan (about 1.5 min)."))
        if not ask_yes(L("要開始完整掃描嗎？（選 n 只顯示附近的節點）", "Start a full scan? (n = show nearby nodes only)")):
            rescan = False
        else:
            rescan = True
    else:
        print(L("\n還沒有掃描紀錄，需要先掃描所有節點（約 1.5 分鐘）。",
                "\nNo scan yet; all nodes need to be scanned first (about 1.5 min)."))
        if not ask_yes(L("要開始掃描嗎？", "Start scanning?")):
            return cancelled(changed=True)
        rescan = True
    if rescan:
        sc = scan_cached(L("掃描所有節點…", "Scanning all nodes…"), near_only=False)
        regions, when = regions_from(sc["found"]), f"{datetime.now():%Y-%m-%d %H:%M}"
    else:
        regions, when = regions_from(cache["found"]), cache["time"]
    if not regions:
        print(L("找不到可用的節點（網路不通或被擋）。", "No usable node found (network down or blocked)."))
        return 1

    rows = sorted(regions.items(), key=lambda kv: kv[1][0]["latency_ms"])
    per, page = 10, 0
    pages = (len(rows) + per - 1) // per
    while True:
        print(L(f"\n【所有節點延遲】共 {len(rows)} 個｜第 {page + 1}/{pages} 頁｜掃描時間 {when}",
                f"\n[Node latency] {len(rows)} nodes | page {page + 1}/{pages} | scanned {when}"))
        print(f"  {pad(L('排名', '#'), 6)}{pad(L('代碼', 'Code'), 6)}{pad(L('城市', 'City'), 18)}"
              f"{L('延遲', 'Latency'):>7}   {L('線路數', 'Routes')}")
        for i, (pop, ips) in enumerate(rows[page * per:(page + 1) * per], page * per + 1):
            print(f"  {i:<6}{pop:<6}{pad(city(pop), 18)}{ips[0]['latency_ms']:5.0f} ms   {len(ips)}")
        cmd = input(L("\nn 下一頁、p 上一頁、q 返回（直接按 Enter = 下一頁）：",
                      "\nn = next, p = previous, q = back (Enter = next): ")).strip().lower()
        if cmd in ("", "n"):
            if page + 1 < pages:
                page += 1
            else:
                print(L("已經是最後一頁。", "This is the last page."))
        elif cmd == "p":
            if page > 0:
                page -= 1
            else:
                print(L("已經是第一頁。", "This is the first page."))
        elif cmd == "q":
            return 0
        else:
            print(L("請輸入 n、p 或 q。", "Please enter n, p or q."))


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def action_update():
    """從 GitHub Releases 檢查並下載新版本。"""
    print(L(f"\n正在檢查 GitHub（{REPO}）上的最新版本…", f"\nChecking GitHub ({REPO}) for the latest version…"))
    try:
        rel = json.loads(http_get(f"https://api.github.com/repos/{REPO}/releases/latest"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(L("GitHub 上還沒有發佈任何版本。", "No release has been published on GitHub yet."))
            return 1
        raise
    latest = rel.get("tag_name", "").lstrip("vV")
    if not latest or version_tuple(latest) <= version_tuple(VERSION):
        print(L(f"已經是最新版（{VERSION}）。", f"You already have the latest version ({VERSION})."))
        return 0
    print(L(f"\n有新版本：{latest}（目前是 {VERSION}）", f"\nNew version: {latest} (you have {VERSION})"))
    notes = [l for l in (rel.get("body") or "").splitlines() if l.strip()][:8]
    for line in notes:
        print(f"  {line}")
    if not ask_yes(L("\n要更新嗎？", "\nUpdate now?")):
        return cancelled(changed=True)
    try:
        return update_exe(rel, latest) if getattr(sys, "frozen", False) else update_script(rel, latest)
    except PermissionError:
        print(L("沒有權限覆蓋程式檔。請把程式放在自己的資料夾（例如「下載」或「桌面」）再更新。",
                "No permission to replace the program file. Move it to your own folder "
                "(e.g. Downloads or Desktop) and try again."))
        return 1


def update_script(rel, latest):
    text = http_get(f"https://raw.githubusercontent.com/{REPO}/{rel['tag_name']}/fastly_hosts.py").decode("utf-8")
    compile(text, "fastly_hosts.py", "exec")     # 確認下載的是完整、能執行的程式
    if f'VERSION = "{latest}"' not in text:
        print(L("下載的檔案版本不符，已取消更新。", "The downloaded file has the wrong version; update cancelled."))
        return 1
    path = os.path.abspath(__file__)
    with open(path + ".new", "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(path + ".new", path)
    print(L(f"\n✔ 已更新到 {latest}，請關閉程式後重新開啟。", f"\n✔ Updated to {latest}. Please close and reopen the program."))
    return 0


def update_exe(rel, latest):
    asset = next((a for a in rel.get("assets", []) if a["name"].endswith("windows-x64.zip")), None)
    if not asset:
        print(L("這個版本沒有提供 Windows 版檔案。", "This release has no Windows file."))
        return 1
    print(L(f"下載 {asset['name']}（{asset['size'] / 1e6:.1f} MB）…",
            f"Downloading {asset['name']} ({asset['size'] / 1e6:.1f} MB)…"))
    with zipfile.ZipFile(io.BytesIO(http_get(asset["browser_download_url"], timeout=120))) as z:
        exe = z.read("fastly-hosts.exe")
    # 發佈說明裡有 SHA256 就核對，避免下載不完整或被竄改
    expected = re.search(r"\b[0-9a-fA-F]{64}\b", rel.get("body") or "")
    actual = hashlib.sha256(exe).hexdigest()
    if expected and expected.group(0).lower() != actual:
        print(L("校驗碼不符（可能下載不完整或檔案被竄改），已取消更新。",
                "Checksum mismatch (incomplete or tampered download); update cancelled."))
        return 1
    if not expected:
        print(L("（這個版本的說明沒有提供 SHA256 校驗碼，略過核對）",
                "(This release does not list a SHA256 checksum; skipping verification)"))
    cur = sys.executable
    with open(cur + ".new", "wb") as f:
        f.write(exe)
    if os.path.exists(cur + ".old"):
        os.remove(cur + ".old")
    os.replace(cur, cur + ".old")                # 執行中的 exe 不能覆蓋，但可以改名
    os.replace(cur + ".new", cur)
    print(L(f"\n✔ 已更新到 {latest}，請關閉程式後重新開啟。", f"\n✔ Updated to {latest}. Please close and reopen the program."))
    return 0


def purge_system():
    """移除 hosts 裡本工具的設定與備份檔（需要管理員 / root）。"""
    text = read_hosts()
    if current_block(text):
        write_hosts(strip_block(text))           # 先改 hosts（若沒有備份會先建立），再刪備份
        flush_dns()
    backup = HOSTS_PATH + ".fastly-hosts.bak"
    if os.path.exists(backup):
        os.remove(backup)
    print(L("✔ 已切回原本的節點，並刪除 hosts 備份檔。", "✔ Back to the original route; hosts backup deleted."))
    return 0


def action_purge():
    """刪除本工具的所有資料，切回原本的節點。"""
    has_block = bool(current_block(read_hosts()))
    backup = HOSTS_PATH + ".fastly-hosts.bak"
    user_files = [p for p in (cache_path(), config_path()) if os.path.exists(p)]
    items = []
    if has_block:
        items.append(L(f"hosts 裡本工具的設定（{HOSTS_PATH}）", f"This tool's entries in hosts ({HOSTS_PATH})"))
    if os.path.exists(backup):
        items.append(L(f"hosts 備份檔（{backup}）", f"hosts backup ({backup})"))
    if os.path.exists(cache_path()):
        items.append(L(f"掃描紀錄（{cache_path()}）", f"Scan record ({cache_path()})"))
    if os.path.exists(config_path()):
        items.append(L(f"語言設定（{config_path()}）", f"Language setting ({config_path()})"))
    if not items:
        print(L("\n沒有任何本工具的資料，不需要刪除。", "\nThere is no data from this tool to delete."))
        return 0
    print(L("\n將會刪除：", "\nThe following will be deleted:"))
    for item in items:
        print(L(f"  ・{item}", f"  - {item}"))
    print(L("（程式本身不會刪除，需要的話請自行刪除）", "(The program itself is not deleted.)"))
    if not ask_yes(L("\n確定要刪除嗎？", "\nDelete?"), default=False):
        return cancelled(changed=True)
    for p in user_files:
        os.remove(p)
    if user_files:
        try:
            os.rmdir(data_dir())
        except OSError:
            pass
        print(L("✔ 已刪除掃描紀錄與設定。", "✔ Scan record and settings deleted."))
    if has_block or os.path.exists(backup):
        if is_admin():
            return purge_system()
        return 0 if run_elevated("purge-system") else 1
    return 0


def action_set(args):
    """直接寫入指定的線路：set github=IP:代碼 [x=IP:代碼]（選地區提權後使用）。"""
    groups = {"github": GITHUB, "x": X_IMAGES}
    routes = []
    for arg in args:
        try:
            key, rest = arg.split("=", 1)
            ip, pop = rest.rsplit(":", 1)
            ipaddress.IPv4Address(ip)
            if key not in groups or not (len(pop) == 3 and pop.isalpha()):
                raise ValueError
        except ValueError:
            print(L(f"參數格式錯誤：{arg}（應為 github=IP:代碼 或 x=IP:代碼）",
                    f"Invalid argument: {arg} (expected github=IP:CODE or x=IP:CODE)"))
            return 2
        routes.append((groups[key], ip, pop.upper()))
    if not routes:
        print(L("沒有指定要寫入的線路。", "No route specified."))
        return 2
    if not is_admin():
        return 0 if run_elevated("set", args) else 1
    backup = write_routes(routes)
    print(L("\n✔ 已套用！", "\n✔ Applied!"))
    for group, ip, pop in routes:
        print(L(f"  {pad(gname(group) + '：', 14)}改走 {place(pop)}（{ip}）",
                f"  {pad(gname(group) + ':', 19)}now via {place(pop)} ({ip})"))
    print(L(f"  （設定寫在 {HOSTS_PATH}，原始檔案備份在 {backup}）",
            f"  (Written to {HOSTS_PATH}; original backed up to {backup})"))
    return 0


def action_restore():
    if not is_admin():
        return 0 if run_elevated("restore") else 1
    text = read_hosts()
    if not current_block(text):
        print(L("\n目前沒有本工具的設定，不需要還原。", "\nNothing from this tool to restore."))
        return 0
    write_hosts(strip_block(text))
    flush_dns()
    print(L("\n✔ 已還原，回到系統原本的路線。", "\n✔ Restored to the system's original route."))
    return 0


def action_status():
    print(L("正在檢查目前狀況…", "Checking current status…"))
    print_status(current_status())
    return 0


def action_language():
    global LANG
    LANG = "en" if LANG == "zh" else "zh"
    save_lang_setting(LANG)
    print(L("✔ 已切換為中文。", "✔ Switched to English."))
    return 0


def help_text():
    return L(f"""
【這個工具在做什麼】
  GitHub 的下載檔、X（Twitter）的圖片，都是透過一家叫 Fastly 的公司在世界各地的
  機房傳給你。你的網路業者會自動幫你選一個機房，但選到的不一定順：
  例如中華電信晚上連新加坡機房，常常卡到只剩 1 Mbps。

  這個工具會：
    1. 找出你附近能用的機房（比最近的機房慢 {NEAR_MARGIN_MS} ms 以上的會略過，約 15 秒）
    2. 實際下載測試好幾次，看哪條路線最穩（約 1～2 分鐘）
    3. 把最穩的路線寫進電腦的 hosts 檔，讓電腦以後直接走那條路

  也可以自己指定要走哪裡：
    「3. 手動選擇地區」重新掃描後列出附近的地區再選
    「6. 指定節點」用上次的掃描紀錄，直接輸入代碼（例如 ICN）或城市名稱切換

  好路線會隨網路業者調整而改變，覺得又變慢時重新「套用」一次就好。
  換到其他網路（例如筆電帶出門）覺得變慢，先「還原」。

【會改到什麼】
  只會在 hosts 檔加上一小段標記好的設定，「還原」會把那段完整移除，
  原本的內容不會動。第一次修改前會自動備份原檔。
  hosts 檔位置：{HOSTS_PATH}
  掃描紀錄與設定：{data_dir()}
""", f"""
[What this tool does]
  GitHub downloads and X (Twitter) images are delivered by a CDN called Fastly from
  data centers around the world. Your ISP picks one for you automatically, but the
  route is not always smooth: e.g. at night, Chunghwa Telecom users going through the
  Singapore node often crawl at about 1 Mbps.

  This tool:
    1. Finds usable nodes near you (anything {NEAR_MARGIN_MS} ms slower than the nearest
       one is skipped; about 15 s)
    2. Downloads test data several times to see which route is the most stable (1-2 min)
    3. Writes the most stable route into your hosts file so your computer uses it

  You can also choose where to go yourself:
    "3. Choose region"  scan, list nearby regions, then pick one
    "6. Switch node"    use the last scan and switch by code (e.g. ICN) or city name

  Good routes change as ISPs adjust their routing; if things get slow again, just
  "Apply" once more. If you move to another network (e.g. a laptop on the go) and it
  feels slow, "Restore" first.

[What gets changed]
  Only a small, marked block in the hosts file. "Restore" removes that block
  completely and leaves everything else untouched. The original file is backed up
  before the first change.
  hosts file: {HOSTS_PATH}
  Scan record and settings: {data_dir()}
""")


def menu_text():
    return L("""
【請選擇】
  1. 測試          找出目前最順的路線，只測試、不改設定（約 2 分鐘）
  2. 自動套用      測試後，把最順的路線設定到電腦上（需要管理員權限）
  3. 手動選擇地區  掃描後列出附近的地區，再選擇要走哪裡
  4. 還原          移除本工具的設定，回到原本的狀態
  5. 重新整理      重新檢查目前狀況
  6. 指定節點      直接輸入代碼（例如 ICN）切換，使用上次的掃描紀錄
  7. 更新          從 GitHub 檢查並下載新版本
  8. 所有節點延遲  列出所有節點的延遲，每頁 10 個
  9. 刪除          刪除本工具的所有資料，切回原本的節點
  L. Language      切換為英文 / Switch to English
  h. 說明          這個工具在做什麼
  0. 離開""", """
[Menu]
  1. Test            Find the smoothest route; test only, nothing changes (~2 min)
  2. Auto apply      Test, then set the smoothest route (needs administrator)
  3. Choose region   Scan, list nearby regions, then pick where to go
  4. Restore         Remove this tool's settings and go back to the original
  5. Refresh         Check the current status again
  6. Switch node     Switch by code (e.g. ICN) using the last scan
  7. Update          Check GitHub for a new version
  8. Node latency    List the latency of all nodes, 10 per page
  9. Delete          Delete all data from this tool and go back to the original
  L. Language        Switch to Chinese (中文)
  h. Help            What this tool does
  0. Exit""")


def menu():
    st = None
    while True:
        print("\n" + LINE)
        print(L(f"  fastly-hosts {VERSION}｜加速 GitHub 下載與 X 圖片",
                f"  fastly-hosts {VERSION} | Faster GitHub downloads and X images"))
        print(LINE)
        if st is None:
            print(L("正在檢查目前狀況…", "Checking current status…"))
            try:
                st = current_status()
            except Exception as e:
                st = {"error": e}
        if "error" in st:
            print(L(f"（檢查狀況失敗：{st['error']}）", f"(Status check failed: {st['error']})"))
        else:
            print_status(st)
        print(menu_text())
        choice = input(L("\n請輸入數字（h = 說明）：", "\nEnter a number (h = help): ")).strip().lower()
        try:
            if choice == "1":
                action_test()
            elif choice == "2":
                action_apply()
                st = None
            elif choice == "3":
                action_region()
                st = None
            elif choice == "4":
                action_restore()
                st = None
            elif choice == "5":
                st = None
                continue
            elif choice == "6":
                action_switch()
                st = None
            elif choice == "7":
                action_update()
            elif choice == "8":
                action_list()
            elif choice == "9":
                action_purge()
                st = None
            elif choice == "l":
                action_language()
                continue
            elif choice == "h":
                print(help_text())
            elif choice == "0":
                return 0
            else:
                print(L("請輸入 0～9 的數字，或 L、h。", "Please enter 0-9, L or h."))
                continue
        except PermissionError as e:
            print(L(f"\n寫入失敗，沒有權限：{e}", f"\nWrite failed, permission denied: {e}"))
        except Exception as e:  # 網路錯誤等：顯示原因後回到選單，不要整個關掉
            print(L(f"\n發生錯誤：{type(e).__name__}: {e}", f"\nError: {type(e).__name__}: {e}"))
        input(L("\n按 Enter 回到選單…", "\nPress Enter to return to the menu…"))


def main(argv):
    global LANG
    flags = [a for a in argv[1:] if a.startswith("--")]
    args = [a for a in argv[1:] if not a.startswith("--")]
    lang_flag = next((f.split("=", 1)[1] for f in flags if f.startswith("--lang=")), None)
    LANG = lang_flag if lang_flag in ("zh", "en") else (load_lang_setting() or detect_lang())
    pause = "--pause" in flags
    yes = "--yes" in flags
    cmds = {"test": lambda: (action_test(interactive=False), 0)[1], "apply": lambda: action_apply(yes),
            "region": lambda: action_region(args[1] if len(args) > 1 else None),
            "switch": lambda: action_switch(args[1] if len(args) > 1 else None),
            "list": action_list, "update": action_update, "purge": action_purge,
            "purge-system": lambda: purge_system() if is_admin() else
            (print(L("需要管理員 / root 權限。", "Administrator / root permission needed.")), 1)[1],
            "set": lambda: action_set(args[1:]), "restore": action_restore, "status": action_status}
    if args and args[0] not in cmds:
        print(__doc__)
        return 2
    try:
        return cmds[args[0]]() if args else menu()
    except PermissionError as e:
        print(L(f"\n寫入失敗，沒有權限：{e}", f"\nWrite failed, permission denied: {e}"))
        if IS_WINDOWS:
            print(L("如果已經是系統管理員，可能是 hosts 被設成唯讀，或被防毒軟體保護。",
                    "If you are already an administrator, hosts may be read-only or protected by antivirus."))
        return 1
    finally:
        if pause:
            input(L("\n按 Enter 關閉這個視窗…", "\nPress Enter to close this window…"))


def cleanup_old_exe():
    if getattr(sys, "frozen", False) and os.path.exists(sys.executable + ".old"):
        try:
            os.remove(sys.executable + ".old")
        except OSError:
            pass


if __name__ == "__main__":
    cleanup_old_exe()
    # 輸出被導向到檔案、或遇到不支援中文的編碼時，用 ? 代替，不要讓程式當掉
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        sys.exit(main(sys.argv))
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(130)
