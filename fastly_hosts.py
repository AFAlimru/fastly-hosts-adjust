#!/usr/bin/env python3
"""fastly-hosts: find the most stable nearby Fastly route for GitHub downloads, X (Twitter) images and Twitch.
fastly-hosts：自動找出附近最順的 Fastly 路線，加速 GitHub 下載、X 圖片與 Twitch。

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
  add DOMAIN [URL]  add a Fastly domain (optional test file)  加入自訂網域（可附測速檔網址）
  remove DOMAIN   remove a custom domain                      移除自訂網域
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

VERSION = "0.8.2"
IS_WINDOWS = platform.system() == "Windows"
HOSTS_PATH = (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "etc", "hosts")
              if IS_WINDOWS else "/etc/hosts")
# hosts 檔裡只寫 ASCII，避免 Windows 解析 hosts 時遇到非英文字元出問題
MARK_BEGIN = "# >>> fastly-hosts >>> (managed by fastly_hosts.py, do not edit this block)"
MARK_END = "# <<< fastly-hosts <<<"
USER_AGENT = f"fastly-hosts/{VERSION}"
REPO = "AFAlimru/fastly-hosts-adjust"          # 檢查更新用

# ---------------------------------------------------------------- 服務
# Fastly 上每個客戶用固定的 IP 尾碼（GitHub .133、X 圖片 .159、Twitch .214），同一個 /24 走同一條路線。
# hosts：要寫進 hosts 的 (網域, 尾碼)；probe：確認路線能用的 (網域, 路徑, 尾碼)；
# pop_probe：probe 的回應沒有節點資訊時，改用同一個 /24 的這個網域判斷節點；
# speed：測速方式；via：沒有自己的路線，沿用另一個服務的路線（X 圖片太小測不出速度，沿用 GitHub 的測速結果）
GITHUB = {
    "key": "github",
    "name": ("GitHub 下載", "GitHub downloads"),
    "hosts": [("release-assets.githubusercontent.com", 133), ("raw.githubusercontent.com", 133)],
    "probe": ("raw.githubusercontent.com", "/github/gitignore/main/README.md", 133),
    "pop_probe": None,
    "speed": "github",
}
X_IMAGES = {
    "key": "x",
    "name": ("X 圖片", "X images"),
    "hosts": [("pbs.twimg.com", 159)],
    "probe": ("pbs.twimg.com", "/profile_images/1683325380441128960/yRsRRjGO_400x400.jpg", 159),
    "pop_probe": None,
    "via": "github",
}
# Twitch 只有網頁、圖片、表情符號、網站資料在 Fastly 上；直播影片和聊天室在 Twitch 自己的機房與 AWS，改不到。
# Twitch 在 Fastly 上用的是另一批 IP 段（GitHub 的路線不提供 Twitch），所以要另外掃描。
TWITCH = {
    "key": "twitch",
    "name": ("Twitch 網頁與圖片", "Twitch pages & images"),
    "hosts": [("www.twitch.tv", 214), ("gql.twitch.tv", 214), ("static-cdn.jtvnw.net", 214),
              ("assets.twitch.tv", 214), ("k.twitchcdn.net", 167)],
    "probe": ("static-cdn.jtvnw.net", "/jtv_user_pictures/xarth/404_user_70x70.png", 214),
    "pop_probe": ("k.twitchcdn.net", "/", 167),   # static-cdn 的回應沒有 x-served-by
    "speed": "twitch",
}
BUILTIN = [GITHUB, X_IMAGES, TWITCH]
CUSTOM_PREFIX = "custom:"

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
SPEED_SAMPLE_SECONDS = 2   # 卡住的線路一開始就只有 1 Mbps 左右，2 秒足以判斷
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
    """依目前語言回傳中文或英文。「✔」不在 Big5 和英文字碼頁裡，部分主控台會顯示成問號：
    中文改用 Big5 有的「√」，英文改用 ASCII（... 和 OK；「…」在英文字碼頁也會變亂碼）。"""
    return zh.replace("✔", "√") if LANG == "zh" else en.replace("…", "...").replace("✔", "OK")


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


def sname(svc):
    return L(*svc["name"])


def place(pop):
    """'ICN' → '首爾（ICN）' / 'Seoul (ICN)'；不認得的代碼只顯示代碼。"""
    if pop in POP_NAMES:
        zh, en = POP_NAMES[pop]
        return L(f"{zh}（{pop}）", f"{en} ({pop})")
    if not pop or pop == "?":
        return L("節點不明", "unknown node")
    return pop


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

def _home():
    # Linux 用 sudo 執行時讀「原本使用者」的資料夾，才讀得到使用者的語言與服務設定
    if not IS_WINDOWS and os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        try:
            import pwd
            return pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir
        except (ImportError, KeyError):
            pass
    return os.path.expanduser("~")


def data_dir():
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or _home()
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(_home(), ".cache")
    return os.path.join(base, "fastly-hosts")


def cache_path():
    return os.path.join(data_dir(), "scan-cache.json")


def config_path():
    return os.path.join(data_dir(), "config.json")


def _can_write_user_data():
    # Linux 用 sudo 執行時不寫：避免在使用者資料夾留下 root 擁有的檔案
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
    """found：{服務代碼: [路線資訊]}。"""
    _write_json(cache_path(), {"time": f"{datetime.now():%Y-%m-%d %H:%M}", "scanned": scanned,
                               "near_only": near_only, "found": found})


def load_scan():
    data = _read_json(cache_path())
    if not data or not data.get("found"):
        return None
    if isinstance(data["found"], list):          # 0.7.0 以前的格式：只有 GitHub
        data["found"] = {"github": data["found"]}
    return data


def load_config():
    return _read_json(config_path()) or {}


def save_config(**changes):
    data = load_config()
    data.update(changes)
    _write_json(config_path(), data)


def load_lang_setting():
    lang = load_config().get("lang")
    return lang if lang in ("zh", "en") else None


def custom_service(c):
    """使用者自訂的網域。不知道網站有哪些路徑，所以檢查時對「/」發 HEAD，有回應（< 500）就算能用；
    沒有提供測速檔就只依延遲挑選。"""
    d = c["domain"]
    return {"key": CUSTOM_PREFIX + d, "name": (d, d), "hosts": [(d, c["suffix"])], "probe": (d, "/", c["suffix"]),
            "pop_probe": None, "any_status": True, "speed": "url" if c.get("test_url") else None,
            "test_url": c.get("test_url"), "custom": True}


def all_services():
    return BUILTIN + [custom_service(c) for c in load_config().get("custom", [])]


def svc_by_key(key):
    return next((s for s in all_services() if s["key"] == key), None)


def tested():
    """有自己的路線、會掃描和測速的服務（X 圖片沿用 GitHub 的路線，不在內）。"""
    return [s for s in all_services() if not s.get("via")]


def enabled(svc):
    return load_config().get("services", {}).get(svc["key"], True)


def enabled_services():
    return [s for s in all_services() if enabled(s)]


def scan_keys(services):
    """要掃描哪些服務的路線：X 圖片沿用 GitHub 的路線。"""
    keys = {s["key"] for s in services if not s.get("via")} | {s["via"] for s in services if s.get("via")}
    return [s["key"] for s in tested() if s["key"] in keys]


# ---------------------------------------------------------------- 網路量測

def resolve_system(host):
    """系統目前解析出的 IPv4（會受 hosts 影響）。"""
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)})
    except socket.gaierror:
        return []


def https_get(host, path, ip, method="GET", max_bytes=0, max_seconds=0.0, timeout=None, keep_body=False):
    """直接連到指定 IP、但用正確網域做 TLS（SNI）和 Host，回傳量測結果（keep_body=True 時附上內容）。"""
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
        got, t_start, body = 0, time.perf_counter(), bytearray()
        if method == "GET":
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if keep_body:
                    body += chunk
                elapsed = time.perf_counter() - t_start
                if (max_bytes and got >= max_bytes) or (max_seconds and elapsed >= max_seconds):
                    break
        elapsed = max(time.perf_counter() - t_start, 1e-6)
        result["bytes"] = got
        result["mbps"] = got * 8 / elapsed / 1e6
        result["ok"] = 200 <= resp.status < 400
        if keep_body:
            result["body"] = bytes(body)
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


def same_24(ip, suffix):
    """同一個 /24 換成另一個尾碼，例如 146.75.48.133 → 146.75.48.159。"""
    return ".".join(ip.split(".")[:3] + [str(suffix)])


def probe(svc, ip, tries=1, timeout=None):
    """用該服務的網域對 IP 發 HEAD：確認憑證與內容正確，回傳節點與延遲；失敗回傳 None。
    ip 可以是同一個 /24 的任何尾碼，會自動換成該服務的尾碼。"""
    host, path, sfx = svc["probe"]
    ip = same_24(ip, sfx)
    try:
        lat = tcp_latency(ip, tries=tries, timeout=timeout)
        r = https_get(host, path, ip, method="HEAD", timeout=timeout)
        usable = r["ok"] or (svc.get("any_status") and r.get("status", 999) < 500)
        if lat is None or not usable:
            return None
        pop = pop_of(r.get("served_by"))
        if svc.get("pop_probe"):
            phost, ppath, psfx = svc["pop_probe"]
            try:
                pop = pop_of(https_get(phost, ppath, same_24(ip, psfx), method="HEAD", timeout=timeout)
                             .get("served_by"))
            except (OSError, ssl.SSLError, http.client.HTTPException):
                pop = "?"
        return {"ip": ip, "pop": pop, "latency_ms": lat}
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
            return _follow_to_githubusercontent(asset["browser_download_url"])
        except Exception as e:
            last_error = e
    raise RuntimeError(L(f"拿不到 GitHub 測速檔案：{last_error}", f"cannot get a GitHub speed-test file: {last_error}"))


_twitch_url = None


def _twitch_homepage(candidates):
    """抓 Twitch 首頁。系統預設路線常常正是卡住的那條（實測連首頁都逾時），
    所以先透過延遲最低的幾條候選路線抓，都失敗才走系統預設。"""
    for c in sorted(candidates, key=lambda c: c["latency_ms"])[:5]:
        try:
            r = https_get("www.twitch.tv", "/", same_24(c["ip"], 214), max_seconds=8, timeout=5, keep_body=True)
            if r["ok"] and r["body"]:
                return r["body"].decode("utf-8", "replace")
        except (OSError, ssl.SSLError, http.client.HTTPException):
            pass
    req = urllib.request.Request("https://www.twitch.tv/", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def twitch_asset_url(candidates=()):
    """Twitch 首頁引用的網頁程式檔（assets.twitch.tv）。最大的約 1.8 MB，足夠分辨順暢和卡住：
    順暢的路線不到半秒下載完，卡住的路線 2 秒內只能下載一點點。檔名帶雜湊會隨改版變動，每次執行重新找。"""
    global _twitch_url
    if _twitch_url:
        return _twitch_url
    html = _twitch_homepage(candidates)
    urls = sorted(set(re.findall(r'https://assets\.twitch\.tv/assets/[^"\'\s>]+\.js', html)))
    if not urls:
        raise RuntimeError(L("Twitch 首頁找不到測速檔案", "no speed-test file found on the Twitch homepage"))
    # 目前最大的是 nomodulePolyfills 和 core；都找不到就用第一個
    for name in ("nomodulePolyfills", "core-"):
        pick = next((u for u in urls if name in u), None)
        if pick:
            _twitch_url = pick
            return pick
    _twitch_url = urls[0]
    return _twitch_url


def speed_url(svc, candidates=()):
    kind = svc.get("speed")
    if kind == "github":
        return github_release_url()
    if kind == "twitch":
        return twitch_asset_url(candidates)
    if kind == "url":
        return svc["test_url"]
    raise RuntimeError(L("沒有設定測速檔", "no speed-test file set"))


def fastly_ranges():
    try:
        conn = http.client.HTTPSConnection("api.fastly.com", timeout=TIMEOUT)
        conn.request("GET", "/public-ip-list", headers={"User-Agent": USER_AGENT})
        return json.loads(conn.getresponse().read())["addresses"]
    except Exception:
        return FALLBACK_RANGES


def _all_blocks(ranges):
    """所有 /24 的代表 IP（尾碼 .1，只用來量延遲；各服務檢查時會換成自己的尾碼）。"""
    ips = []
    for cidr in ranges:
        net = ipaddress.ip_network(cidr, strict=False)
        subs = net.subnets(new_prefix=24) if net.prefixlen < 24 else [net]
        ips += [same_24(str(s.network_address), 1) for s in subs]
    return ips


def scan(label, keys, near_only=True):
    """掃描各服務能用的路線。回傳 {"found": {服務代碼: [路線（依延遲排序）]}, "scanned": /24 總數,
    "skipped": 略過的遠方 /24 數量}。
    near_only=True：先只量延遲（所有服務共用），比最近的慢 NEAR_MARGIN_MS 以上的略過，只對附近的做完整檢查。"""
    blocks = _all_blocks(fastly_ranges())
    keys = list(keys)
    found = {k: [] for k in keys}
    skipped = 0
    if near_only:
        # 第一階段：只量延遲（0～70%）
        lat = {}
        with ThreadPoolExecutor(max_workers=PRECHECK_WORKERS) as pool:
            futures = {pool.submit(tcp_latency, same_24(b, 133), 1, PRECHECK_TIMEOUT): b for b in blocks}
            for done, fut in enumerate(as_completed(futures), 1):
                if fut.result():
                    lat[futures[fut]] = fut.result()
                if done % 32 == 0:
                    progress(label, done * 70 // len(blocks), 100)
        if not lat:
            progress(label, 100, 100)
            return {"found": found, "scanned": len(blocks), "skipped": 0}
        cutoff = min(lat.values()) + NEAR_MARGIN_MS + PRECHECK_SLACK_MS
        targets = [b for b, ms in lat.items() if ms <= cutoff]
        skipped = len(blocks) - len(targets)
        tries, workers, start, share = 3, 16, 70, 30
    else:
        targets, tries, workers, start, share = blocks, 1, SCAN_WORKERS, 0, 80
    # 第二階段：各服務用自己的網域檢查
    jobs = [(k, b) for k in keys for b in targets]
    svcs = {k: svc_by_key(k) for k in keys}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe, svcs[k], b, tries, SCAN_TIMEOUT): k for k, b in jobs}
        for done, fut in enumerate(as_completed(futures), 1):
            if fut.result():
                found[futures[fut]].append(fut.result())
            if done % 8 == 0 or done == len(jobs):
                progress(label, start + done * share // max(len(jobs), 1), 100)
    if not near_only:
        # 完整掃描時同時連線多、延遲不準：每條路線再各量 3 次（80～100%）
        routes = [r for k in keys for r in found[k]]
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = {pool.submit(tcp_latency, r["ip"], 3, SCAN_TIMEOUT): r for r in routes}
            for done, fut in enumerate(as_completed(futures), 1):
                if fut.result():
                    futures[fut]["latency_ms"] = fut.result()
                progress(label, 80 + done * 20 // max(len(routes), 1), 100)
        if not routes:
            progress(label, 100, 100)
    for k in keys:
        rs = found[k]
        if near_only and rs:
            nearest = min(r["latency_ms"] for r in rs)
            rs[:] = [r for r in rs if r["latency_ms"] <= nearest + NEAR_MARGIN_MS]
        rs.sort(key=lambda r: r["latency_ms"])
    return {"found": found, "scanned": len(blocks), "skipped": skipped}


def scan_cached(label, keys, near_only=True):
    result = scan(label, keys, near_only)
    save_scan(result["found"], result["scanned"], near_only)
    return result


def regions_from(found):
    """路線依地區分組：{節點代碼: [路線（依延遲排序）]}。found 可以是清單或 {服務: 清單}。"""
    routes = found if isinstance(found, list) else [r for rs in found.values() for r in rs]
    regions = {}
    for r in routes:
        if r.get("pop") and r["pop"] != "?":
            regions.setdefault(r["pop"], []).append(r)
    for rs in regions.values():
        rs.sort(key=lambda r: r["latency_ms"])
    return regions


def speed_test(svc, candidates, label, rounds=SPEED_ROUNDS):
    """多輪交錯測速。回傳 {ip: [Mbps, ...]}。"""
    speeds = {c["ip"]: [] for c in candidates}
    total, done = len(candidates) * rounds, 0
    for _ in range(rounds):
        url = speed_url(svc, candidates)
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
    """依「順暢次數」→「速度中位數」→「延遲」排序。沒有測速資料時只看延遲。"""
    peak = max((v for vs in speeds.values() for v in vs), default=0)
    threshold = max(peak * FAST_RATIO, FAST_FLOOR_MBPS)
    for c in candidates:
        vs = speeds.get(c["ip"], [])
        c["fast"] = sum(1 for v in vs if v >= threshold)
        c["median"] = statistics.median(vs) if vs else 0
        c["speeds"] = vs
    return sorted(candidates, key=lambda c: (-c["fast"], -c["median"], c["latency_ms"]))


def smooth_text(n, total=SPEED_ROUNDS):
    return L(f"{total} 次測試有 {n} 次順暢", f"smooth in {n} of {total} tests")


def evaluate(svc, found, base_word, extra_base=(), step=""):
    """一個有自己路線的服務：延遲最低的幾條 + 目前用的路線一起測速，判斷要不要換。"""
    base_ips = [same_24(ip, svc["probe"][2]) for ip in resolve_system(svc["probe"][0])]
    cands = {c["ip"]: c for c in found[:SPEED_TOP_N]}
    for ip in base_ips + [same_24(ip, svc["probe"][2]) for ip in extra_base]:
        if ip not in cands:
            info = probe(svc, ip)
            if info:
                cands[ip] = info
    cands = list(cands.values())
    if not cands:
        return {"svc": svc, "apply": False, "best": None, "ranked": [], "measured": False,
                "reason": L("找不到可用的路線", "No usable route found")}
    measured = True
    try:
        speeds = speed_test(svc, cands, step + L(f"測速：{sname(svc)}…", f"speed test: {sname(svc)}…"))
    except Exception as e:      # 抓不到測速檔：只依延遲挑選
        print(L(f"  （{sname(svc)}：{e}，改成只依延遲挑選）", f"  ({sname(svc)}: {e}; choosing by latency only)"))
        speeds, measured = {}, False
    ranked = rank(cands, speeds)
    for c in ranked:
        c["is_base"] = c["ip"] in base_ips
    best = ranked[0]
    base_rows = [c for c in ranked if c["is_base"]]
    base_fast = max((c["fast"] for c in base_rows), default=0)
    base_pop = base_rows[0]["pop"] if base_rows else "?"
    if measured:
        before = L(f"{base_word} {place(base_pop)}：", f"{base_word} {place(base_pop)}: ") + smooth_text(base_fast)
        after = (L(f"建議路線 {place(best['pop'])}：", f"Suggested {place(best['pop'])}: ") + smooth_text(best["fast"]) +
                 L(f"，延遲約 {best['latency_ms']:.0f} ms", f", latency ~{best['latency_ms']:.0f} ms"))
        if best["pop"] == base_pop and not best["is_base"]:
            after += L(f"（同地區的另一條線路 {best['ip']}）", f" (another route in the same region: {best['ip']})")
        if best["is_base"]:
            res = {"apply": False, "reason": L(f"{base_word}已經是最順的路線，不需要改",
                                               f"{base_word} is already the smoothest, no change needed")}
        elif best["fast"] > base_fast:
            res = {"apply": True, "reason": f"{before}\n{after}"}
        else:
            res = {"apply": False, "reason": before + L("，跟其他路線一樣順，不需要改",
                                                        ", as smooth as the others, no change needed")}
    elif not base_rows:
        res = {"apply": True, "reason": L(
            f"沒有測速；{base_word}連不上，依延遲建議 {place(best['pop'])}（約 {best['latency_ms']:.0f} ms）",
            f"No speed test; {base_word} is unreachable, suggest {place(best['pop'])} by latency "
            f"(~{best['latency_ms']:.0f} ms)")}
    else:
        base_lat = min(c["latency_ms"] for c in base_rows)
        if best["is_base"] or best["latency_ms"] >= base_lat - 10:
            res = {"apply": False, "reason": L("沒有測速，延遲也沒有明顯較低的路線，不需要改",
                                               "No speed test, and no route with clearly lower latency; no change")}
        else:
            res = {"apply": True, "reason": L(
                f"沒有測速，依延遲建議 {place(best['pop'])}（約 {best['latency_ms']:.0f} ms，{base_word}約 {base_lat:.0f} ms）",
                f"No speed test; by latency, suggest {place(best['pop'])} (~{best['latency_ms']:.0f} ms vs "
                f"{base_word} ~{base_lat:.0f} ms)")}
    res.update(svc=svc, best=best, ranked=ranked, measured=measured)
    return res


def evaluate_x(gh_ranked, base_word):
    """X 圖片：圖片太小測不出速度，用同一個 /24 在 GitHub 測速的結果代表該路線的穩定度。
    但 X 不是每個節點都有部署（實測連香港的 IP，X 會轉給新加坡出貨），
    所以只採用「X 實際出貨節點 = 該路線 GitHub 節點」的路線，確定真的走那條路。"""
    by_ip = {c["ip"]: c for c in gh_ranked}
    base_fast, verified, base_pop = 0, False, "?"
    for ip in resolve_system(X_IMAGES["probe"][0]):
        route = by_ip.get(same_24(ip, GITHUB["probe"][2]))
        info = probe(X_IMAGES, ip)
        if info:
            base_pop = info["pop"]
        if route and info and info["pop"] == route["pop"]:
            base_fast = max(base_fast, route["fast"])
            verified = True
    best = None
    for c in gh_ranked:
        if c["fast"] <= base_fast:
            break
        info = probe(X_IMAGES, c["ip"])
        if info and info["pop"] == c["pop"]:
            info["fast"] = c["fast"]
            best = info
            break
    if best:
        head = L(f"{base_word} {place(base_pop)}：", f"{base_word} {place(base_pop)}: ")
        before = head + (smooth_text(base_fast) if verified else L("無法確認順不順", "cannot be verified"))
        after = (L(f"建議路線 {place(best['pop'])}：", f"Suggested {place(best['pop'])}: ") + smooth_text(best["fast"]) +
                 L(f"，延遲約 {best['latency_ms']:.0f} ms", f", latency ~{best['latency_ms']:.0f} ms"))
        return {"svc": X_IMAGES, "apply": True, "best": best, "ranked": [], "reason": f"{before}\n{after}"}
    return {"svc": X_IMAGES, "apply": False, "best": None, "ranked": [],
            "reason": L("沒有比目前更順、又能提供 X 圖片的路線，不需要改",
                        "No smoother route that also serves X images, no change needed")}


def analyze():
    """掃描附近節點 + 測速 + 判斷。回傳每個啟用的服務各自的建議。"""
    block = current_block(read_hosts())

    def base_word(svc):
        # 只有本工具真的設定過的服務才叫「目前設定」（舊版的 X 圖片標記是 x-images）
        keys = {svc["key"], "x-images"} if svc is X_IMAGES else {svc["key"]}
        mine = any(l.startswith(f"# {k}:") for l in block for k in keys)
        return L("目前設定", "Current setting") if mine else L("目前路線", "Current route")

    services = enabled_services()
    keys = scan_keys(services)
    # 步驟：1 找節點，之後每個有自己路線的服務各一步（例如 GitHub、Twitch → 共 3 步）
    steps = 1 + len(keys)
    sc = scan_cached(L(f"步驟 1/{steps}：尋找附近的節點…", f"Step 1/{steps}: finding nearby nodes…"), keys)
    out = {"results": [], **sc}
    evaluated = {}
    step = 1
    for svc in tested():
        if svc["key"] in keys:
            step += 1
            extra = ([same_24(ip, 133) for ip in resolve_system(X_IMAGES["probe"][0])]
                     if svc is GITHUB and X_IMAGES in services else [])
            evaluated[svc["key"]] = evaluate(svc, sc["found"][svc["key"]], base_word(svc), extra,
                                             L(f"步驟 {step}/{steps}：", f"Step {step}/{steps}: "))
    for svc in services:
        if svc is X_IMAGES:
            out["results"].append(evaluate_x(evaluated["github"]["ranked"], base_word(X_IMAGES)))
        else:
            out["results"].append(evaluated[svc["key"]])
    return out


# ---------------------------------------------------------------- 顯示

def print_summary(result):
    usable = "、".join(f"{sname(svc_by_key(k))} {len(v)}" for k, v in result["found"].items() if svc_by_key(k))
    usable_en = ", ".join(f"{sname(svc_by_key(k))} {len(v)}" for k, v in result["found"].items() if svc_by_key(k))
    print(L(f"\n【結果】（掃描 {result['scanned']} 個位置，略過較遠的 {result['skipped']} 個；附近可用路線：{usable}）",
            f"\n[Result] (scanned {result['scanned']} locations, skipped {result['skipped']} distant ones; "
            f"usable nearby routes: {usable_en})"))
    for r in result["results"]:
        if r["apply"]:
            print(L(f"\n  ✔ {sname(r['svc'])}：建議改走 {place(r['best']['pop'])}",
                    f"\n  ✔ {sname(r['svc'])}: switch to {place(r['best']['pop'])}"))
        else:
            print(L(f"\n  ・{sname(r['svc'])}：維持現狀", f"\n  - {sname(r['svc'])}: keep as is"))
        for line in r["reason"].split("\n"):
            print(f"      {line}")
    print(L("\n  「順暢」＝速度達到這次測到最快速度的 30% 以上（且至少 3 Mbps）；卡住的路線通常只剩 1 Mbps 左右。",
            "\n  \"Smooth\" = at least 30% of the fastest speed in this test (and at least 3 Mbps);"
            "\n  a congested route usually crawls at about 1 Mbps."))


def print_details(result):
    for r in result["results"]:
        if not r["ranked"]:
            continue
        print(L(f"\n【詳細數據】{sname(r['svc'])} 測速（每條路線測 {SPEED_ROUNDS} 次，單位 Mbps）",
                f"\n[Details] {sname(r['svc'])} speed ({SPEED_ROUNDS} tests per route, Mbps)"))
        lat = L("延遲", "Latency")
        print(f"  {'IP':<16}{pad(L('地點', 'Location'), 20)}{' ' * (7 - width(lat))}{lat}  "
              f"{pad(L('順暢', 'Smooth'), 7)}{L('各次速度', 'Speeds')}")
        for c in r["ranked"]:
            tag = L("← 目前", "← current") if c.get("is_base") else ""
            vs = " / ".join(f"{v:5.1f}" for v in c["speeds"]) or L("（未測速）", "(not tested)")
            smooth = f"{c['fast']}/{SPEED_ROUNDS}" if c["speeds"] else "-"
            print(f"  {c['ip']:<16}{pad(place(c['pop']), 20)}{c['latency_ms']:5.0f}ms  {pad(smooth, 7)}{vs}  {tag}")


def current_status():
    """目前每個啟用的服務實際走的節點與延遲，以及 hosts 套用狀態。"""
    block = current_block(read_hosts())
    applied = next((l.split("applied", 1)[1].strip() for l in block if l.startswith("# applied")), None)
    rows = []
    for svc in enabled_services():
        ips = resolve_system(svc["probe"][0])
        info = probe(svc, ips[0], tries=3) if ips else None
        rows.append({"svc": svc, "ip": ips[0] if ips else None, "info": info})
    return {"block": block, "applied": applied, "rows": rows}


def print_status(st):
    print(L("【目前狀況】", "[Current status]"))
    cols = max([22] + [width(sname(r["svc"])) + 4 for r in st["rows"]])
    for r in st["rows"]:
        label = pad(sname(r["svc"]) + L("：", ":"), cols)
        if r["info"]:
            print(L(f"  {label}目前走 {place(r['info']['pop'])}，延遲約 {r['info']['latency_ms']:.0f} ms",
                    f"  {label}via {place(r['info']['pop'])}, latency ~{r['info']['latency_ms']:.0f} ms"))
        elif r["ip"]:
            print(L(f"  {label}連不上（{r['ip']}）", f"  {label}unreachable ({r['ip']})"))
        else:
            print(L(f"  {label}查不到網址（DNS 失敗）", f"  {label}DNS lookup failed"))
    label = pad(L("本工具設定：", "This tool:"), cols)
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
    """routes：[(服務, 路線 IP, 節點代碼), ...]。整段取代本工具的設定，回傳備份檔路徑。
    路線 IP 可以是該 /24 的任何尾碼，每個網域會換成自己的尾碼。"""
    lines = [MARK_BEGIN, f"# applied {datetime.now():%Y-%m-%d %H:%M}"]
    for svc, ip, pop in routes:
        lines.append(f"# {svc['key']}: Fastly {pop}")
        lines += [f"{same_24(ip, sfx)}\t{host}" for host, sfx in svc["hosts"]]
    lines.append(MARK_END)
    backup = write_hosts(strip_block(read_hosts()) + "\n" + "\n".join(lines) + "\n")
    flush_dns()
    return backup


# ---------------------------------------------------------------- 權限

def _script_args(action, pause, extra_args=()):
    """重新執行自己時的程式與參數（exe 或 .py 都適用）。語言明確傳下去，管理員視窗才會用同一種語言。"""
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


def estimate():
    """預估（分鐘, MB）：掃描約半分鐘；每個服務測速約 1.5 分鐘；流量 GitHub 約 300 MB、Twitch 約 60 MB。"""
    keys = scan_keys(enabled_services())
    timed = [k for k in keys if (svc_by_key(k) or {}).get("speed")]
    mb = (300 if "github" in keys else 0) + (60 if "twitch" in keys else 0) + 30 * len(
        [k for k in timed if k.startswith(CUSTOM_PREFIX)])
    return max(1, round(0.5 + 1.5 * len(timed) + 0.2 * (len(keys) - len(timed)))), mb


def action_test(interactive=True):
    mins, mb = estimate()
    print(L(f"\n開始測試，大約需要 {mins} 分鐘，會用掉約 {mb} MB 流量（只測試，不改任何設定）。\n",
            f"\nTesting, about {mins} minutes and ~{mb} MB of data (test only, nothing is changed).\n"))
    result = analyze()
    print_summary(result)
    has_details = any(r["ranked"] for r in result["results"])
    if interactive and has_details and ask_yes(L("\n要看詳細數據嗎？", "\nShow details?"), default=False):
        print_details(result)
    elif not interactive and has_details:
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
    routes = [(r["svc"], r["best"]["ip"], r["best"]["pop"]) for r in result["results"] if r["apply"]]
    if not routes:
        print(L("\n目前的路線已經很順，不需要修改，設定維持原狀。",
                "\nThe current route is already smooth; nothing to change."))
        return 0
    if not yes and not ask_yes(L("\n要套用上面建議的路線嗎？", "\nApply the suggested route(s)?")):
        return cancelled()
    backup = write_routes(routes)
    print(L("\n✔ 已套用！之後會走新的路線。", "\n✔ Applied! The new route(s) are now in use."))
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


def choose_and_apply(pop, found, verify=False):
    """在指定地區，對每個啟用的服務實測挑最穩的線路，確認後套用。
    found：{服務代碼: [路線]}；verify=True：路線來自舊的掃描紀錄，先確認它們現在還連到同一個地區。"""
    services = enabled_services()
    picks, lines = {}, []
    for svc in tested():
        if svc["key"] not in scan_keys(services):
            continue
        routes = [r for r in found.get(svc["key"], []) if r["pop"] == pop]
        if verify:
            checked = [probe(svc, r["ip"], tries=3) for r in routes[:REGION_MAX_IPS + 2]]
            routes = [r for r in checked if r and r["pop"] == pop]
        cands = routes[:REGION_MAX_IPS]
        if not cands:
            continue
        secs = max(10, len(cands) * 6)
        print(L(f"\n測試 {sname(svc)} 到 {place(pop)} 的 {len(cands)} 條線路（約 {secs} 秒）…",
                f"\nTesting {len(cands)} {sname(svc)} route(s) to {place(pop)} (about {secs} s)…"))
        try:
            speeds = speed_test(svc, cands, L("測試線路…", "Testing routes…"), rounds=2)
        except Exception as e:
            print(L(f"  （{e}，改成只依延遲挑選）", f"  ({e}; choosing by latency only)"))
            speeds = {}
        ranked = rank(cands, speeds)
        for c in ranked:
            vs = " / ".join(f"{v:5.1f}" for v in c["speeds"]) or L("未測速", "not tested")
            print(L(f"  {c['ip']:<16}延遲 {c['latency_ms']:4.0f} ms  順暢 {c['fast']}/2  [{vs}] Mbps",
                    f"  {c['ip']:<16}latency {c['latency_ms']:4.0f} ms  smooth {c['fast']}/2  [{vs}] Mbps"))
        picks[svc["key"]] = ranked
    if not picks:
        print(L(f"{place(pop)} 目前沒有可用的線路。", f"No usable route to {place(pop)} right now."))
        return 1
    stuck = [k for k, ranked in picks.items() if ranked[0]["speeds"] and ranked[0]["fast"] == 0]
    if stuck and not ask_yes(
            L(f"\n{place(pop)} 目前有服務的每條線路都卡住，仍要改走這裡嗎？",
              f"\nEvery route to {place(pop)} is congested for some service right now. Switch anyway?"),
            default=False):
        return cancelled()

    args = []
    print()
    for svc in services:
        label = pad(sname(svc) + L("：", ":"), 22)
        if svc is X_IMAGES:
            # X 圖片：只採用 X 實際由這個地區出貨的線路
            x = next((i for i in (probe(X_IMAGES, c["ip"]) for c in picks.get("github", []))
                      if i and i["pop"] == pop), None)
            if x:
                args.append(f"x={x['ip']}:{pop}")
                lines.append(L(f"  {label}改走 {place(pop)}，使用 {x['ip']}", f"  {label}switch to {place(pop)} via {x['ip']}"))
            else:
                lines.append(L(f"  {label}X 在 {place(pop)} 沒有機房，維持系統原本的路線",
                               f"  {label}X has no node in {place(pop)}; keeping the default route"))
        elif svc["key"] in picks:
            best = picks[svc["key"]][0]
            args.append(f"{svc['key']}={best['ip']}:{pop}")
            lines.append(L(f"  {label}改走 {place(pop)}，使用 {best['ip']}", f"  {label}switch to {place(pop)} via {best['ip']}"))
        else:
            lines.append(L(f"  {label}在 {place(pop)} 沒有線路，維持系統原本的路線",
                           f"  {label}no route in {place(pop)}; keeping the default route"))
    print("\n".join(lines))
    if not args:
        print(L("沒有可以套用的線路。", "Nothing to apply."))
        return 1
    if not ask_yes(L("\n確定要套用嗎？", "\nApply?")):
        return cancelled()
    return action_set(args)


def ask_code(code):
    if code is None:
        code = input(L("\n請輸入地區代碼或城市名稱（例如 ICN 或 首爾），直接按 Enter 取消：",
                       "\nEnter a region code or city (e.g. ICN or Seoul), or press Enter to cancel: ")).strip()
    return code


def full_scan_for(code):
    """附近的掃描裡找不到時：問要不要完整掃描全世界的節點，回傳新的 found 或 None。"""
    if not ask_yes(L(f"附近的節點裡沒有「{code}」，可能距離較遠被略過了。要完整掃描全世界的節點嗎？（約 1.5～3 分鐘）",
                     f"\"{code}\" is not among nearby nodes (distant ones are skipped). "
                     f"Scan all nodes worldwide? (about 1.5-3 min)")):
        return None
    return scan_cached(L("掃描所有節點…", "Scanning all nodes…"), scan_keys(enabled_services()), near_only=False)["found"]


def action_region(code=None):
    """手動選擇地區：掃描附近、列出可用的地區，輸入代碼後在該地區挑最穩的線路。"""
    print(L("\n正在尋找附近可用的地區…", "\nFinding nearby regions…"))
    found = scan_cached(L("尋找附近的地區…", "Finding nearby regions…"), scan_keys(enabled_services()))["found"]
    regions = regions_from(found)
    if not regions:
        print(L("找不到可用的地區（網路不通或被擋）。", "No usable region found (network down or blocked)."))
        return 1
    print(L("\n【附近可用的地區】（依延遲排序）", "\n[Nearby regions] (by latency)"))
    for pop in sorted(regions, key=lambda p: regions[p][0]["latency_ms"]):
        print(L(f"  {pop}  {pad(city(pop), 10)}延遲約 {regions[pop][0]['latency_ms']:.0f} ms",
                f"  {pop}  {pad(city(pop), 14)}latency ~{regions[pop][0]['latency_ms']:.0f} ms"))
    print(L("  （較遠的地區已略過；也可以直接輸入它們的代碼，會再完整掃描）",
            "  (Distant regions are skipped; you can still enter their code to scan everything.)"))
    code = ask_code(code)
    if not code:
        return cancelled(changed=True)
    pop = find_region(code, regions)
    if not pop:
        found = full_scan_for(code)
        pop = find_region(code, regions_from(found)) if found else None
    if not pop:
        print(L(f"找不到「{code}」這個地區，或你的網路目前連不到那裡。",
                f"Region \"{code}\" not found, or it is unreachable from your network."))
        return 1
    return choose_and_apply(pop, found)


def action_switch(code=None):
    """指定節點：用上次的掃描紀錄，直接輸入代碼切換（不用等掃描）。"""
    keys = scan_keys(enabled_services())
    cache = load_scan()
    if cache and all(k in cache["found"] for k in keys):
        print(L(f"\n使用上次的掃描紀錄（{cache['time']}）。", f"\nUsing the last scan ({cache['time']})."))
        found, from_cache = cache["found"], True
    else:
        print(L("\n沒有可用的掃描紀錄，先掃描附近的節點…", "\nNo usable scan record; scanning nearby nodes first…"))
        found, from_cache = scan_cached(L("尋找附近的地區…", "Finding nearby regions…"), keys)["found"], False
    code = ask_code(code)
    if not code:
        return cancelled(changed=True)
    pop = find_region(code, regions_from(found))
    if not pop:
        found = full_scan_for(code)
        pop, from_cache = (find_region(code, regions_from(found)) if found else None), False
    if not pop:
        print(L(f"找不到「{code}」這個節點，或你的網路目前連不到那裡。",
                f"Node \"{code}\" not found, or it is unreachable from your network."))
        return 1
    return choose_and_apply(pop, found, verify=from_cache)


def action_list():
    """查看所有節點的延遲，每頁 10 個。"""
    keys = scan_keys(enabled_services())
    cache = load_scan()
    full_cache = cache and not cache.get("near_only") and all(k in cache["found"] for k in keys)
    if full_cache:
        rescan = ask_yes(L(f"\n上次掃描時間：{cache['time']}。要重新掃描所有節點嗎？（選 n 直接顯示上次的結果）",
                           f"\nLast scan: {cache['time']}. Scan all nodes again? (n = show the last result)"),
                         default=False)
    elif cache:
        print(L(f"\n上次（{cache['time']}）只掃描了附近的節點，要看全部需要完整掃描（約 1.5～3 分鐘）。",
                f"\nThe last scan ({cache['time']}) covered nearby nodes only; "
                f"listing all needs a full scan (about 1.5-3 min)."))
        rescan = ask_yes(L("要開始完整掃描嗎？（選 n 只顯示附近的節點）", "Start a full scan? (n = show nearby nodes only)"))
    else:
        print(L("\n還沒有掃描紀錄，需要先掃描所有節點（約 1.5～3 分鐘）。",
                "\nNo scan yet; all nodes need to be scanned first (about 1.5-3 min)."))
        if not ask_yes(L("要開始掃描嗎？", "Start scanning?")):
            return cancelled(changed=True)
        rescan = True
    if rescan:
        found = scan_cached(L("掃描所有節點…", "Scanning all nodes…"), keys, near_only=False)["found"]
        when = f"{datetime.now():%Y-%m-%d %H:%M}"
    else:
        found, when = cache["found"], cache["time"]
    regions = regions_from(found)
    if not regions:
        print(L("找不到可用的節點（網路不通或被擋）。", "No usable node found (network down or blocked)."))
        return 1

    def count(pop, key):
        return sum(1 for r in found.get(key, []) if r["pop"] == pop)

    cols = [k for k in keys if k in found and svc_by_key(k)]

    def col_label(k):
        svc = svc_by_key(k)
        label = svc["name"][1].split()[0] if not svc.get("custom") else svc["name"][1]
        return label if len(label) <= 10 else label[:9] + "~"
    rows = sorted(regions.items(), key=lambda kv: kv[1][0]["latency_ms"])
    per, page = 10, 0
    pages = (len(rows) + per - 1) // per
    while True:
        print(L(f"\n【所有節點延遲】共 {len(rows)} 個｜第 {page + 1}/{pages} 頁｜掃描時間 {when}",
                f"\n[Node latency] {len(rows)} nodes | page {page + 1}/{pages} | scanned {when}"))
        print(f"  {pad(L('排名', '#'), 6)}{pad(L('代碼', 'Code'), 6)}{pad(L('城市', 'City'), 18)}"
              f"{L('延遲', 'Latency'):>7}   " + "  ".join(pad(col_label(k), 10) for k in cols))
        for i, (pop, rs) in enumerate(rows[page * per:(page + 1) * per], page * per + 1):
            print(f"  {i:<6}{pop:<6}{pad(city(pop), 18)}{rs[0]['latency_ms']:5.0f} ms   " +
                  "  ".join(pad(str(count(pop, k) or "-"), 10) for k in cols))
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


HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def fastly_ip(ip, ranges):
    addr = ipaddress.ip_address(ip)
    return any(addr in ipaddress.ip_network(r, strict=False) for r in ranges)


def add_custom_domain(domain, test_url=None, ask=True):
    """新增自訂網域：確認它在 Fastly 上、找出它用的 IP 尾碼，可選填測速檔。成功回傳 True。"""
    domain = domain.strip().lower().rstrip(".")
    if domain.startswith(("http://", "https://")):
        domain = domain.split("/", 3)[2]
    if not HOSTNAME_RE.match(domain):
        print(L(f"「{domain}」不是有效的網域名稱。", f"\"{domain}\" is not a valid domain name."))
        return False
    existing = {h for s in all_services() for h, _ in s["hosts"]}
    if domain in existing:
        print(L(f"「{domain}」已經在清單裡了。", f"\"{domain}\" is already on the list."))
        return False
    ips = resolve_system(domain)
    if not ips:
        print(L(f"查不到「{domain}」的 IP（網域不存在或 DNS 失敗）。", f"Cannot resolve \"{domain}\"."))
        return False
    ranges = fastly_ranges()
    fips = [ip for ip in ips if fastly_ip(ip, ranges)]
    if not fips:
        print(L(f"「{domain}」目前的 IP（{', '.join(ips[:3])}）不在 Fastly 上，這個工具只能加速 Fastly 的網域。",
                f"\"{domain}\" ({', '.join(ips[:3])}) is not served by Fastly; this tool only works with Fastly."))
        return False
    suffixes = [int(ip.rsplit(".", 1)[1]) for ip in fips]
    suffix = max(set(suffixes), key=suffixes.count)
    svc = custom_service({"domain": domain, "suffix": suffix})
    info = probe(svc, fips[0], tries=2)
    if not info:
        print(L(f"「{domain}」在 Fastly 上，但連線檢查失敗（憑證錯誤或沒有回應），無法加入。",
                f"\"{domain}\" is on Fastly, but the connection check failed (certificate error or no reply)."))
        return False
    print(L(f"✔ 「{domain}」在 Fastly 上：IP 尾碼 .{suffix}，目前走 {place(info['pop'])}，延遲約 {info['latency_ms']:.0f} ms",
            f"✔ \"{domain}\" is on Fastly: last octet .{suffix}, via {place(info['pop'])}, "
            f"latency ~{info['latency_ms']:.0f} ms"))

    if test_url is None and ask:
        print(L("\n測速用的檔案網址（選填）：同一個網域上、至少幾百 KB 的檔案，例如影片或大圖片。",
                "\nSpeed-test file URL (optional): a file of at least a few hundred KB on the same domain."))
        print(L("  不填的話，只能依延遲挑選路線，無法分辨哪條路線會卡住。",
                "  Without one, routes are chosen by latency only; congestion cannot be detected."))
        test_url = input(L("網址（直接按 Enter 略過）：", "URL (Enter to skip): ")).strip() or None
    if test_url:
        if not test_url.lower().startswith(f"https://{domain}/"):
            print(L(f"測速網址要以 https://{domain}/ 開頭，已略過測速檔。",
                    f"The URL must start with https://{domain}/; skipping the speed-test file."))
            test_url = None
        else:
            path = "/" + test_url.split("/", 3)[3]
            try:
                r = https_get(domain, path, info["ip"], max_bytes=SPEED_SAMPLE_BYTES, max_seconds=5)
                if not r["ok"]:
                    raise RuntimeError(f"HTTP {r['status']}")
                if r["bytes"] < 256 * 1024:
                    print(L(f"（這個檔案只有 {r['bytes'] / 1024:.0f} KB，太小可能測不出差異）",
                            f"(This file is only {r['bytes'] / 1024:.0f} KB; it may be too small to tell routes apart)"))
            except Exception as e:
                print(L(f"測速檔下載失敗（{e}），已略過測速檔。", f"Speed-test file failed ({e}); skipping it."))
                test_url = None
    customs = load_config().get("custom", [])
    customs.append({"domain": domain, "suffix": suffix, "test_url": test_url})
    save_config(custom=customs)
    print(L(f"✔ 已加入「{domain}」" + ("，有測速檔。" if test_url else "，沒有測速檔（只依延遲挑選）。"),
            f"✔ Added \"{domain}\"" + (" with a speed-test file." if test_url else " without a speed-test file "
                                                                                     "(latency only).")))
    print(L("  之後的測試、套用、選擇地區都會包含它，也可以在「S. 服務設定」開關。",
            "  It is now included in test, apply and region selection; toggle it under \"S. Services\"."))
    return True


def remove_custom_domain(domain):
    customs = load_config().get("custom", [])
    left = [c for c in customs if c["domain"] != domain]
    if len(left) == len(customs):
        print(L(f"清單裡沒有「{domain}」。", f"\"{domain}\" is not on the list."))
        return False
    services = load_config().get("services", {})
    services.pop(CUSTOM_PREFIX + domain, None)
    save_config(custom=left, services=services)
    print(L(f"✔ 已移除「{domain}」。如果已經套用過，hosts 裡它的設定會在下次「套用」或「還原」時移除。",
            f"✔ Removed \"{domain}\". If it was applied, its hosts entry goes away at the next apply or restore."))
    return True


def action_custom():
    """自訂網域：列出、新增、移除。"""
    while True:
        customs = load_config().get("custom", [])
        print(L("\n【自訂網域】", "\n[Custom domains]"))
        if not customs:
            print(L("  （還沒有自訂網域）", "  (none yet)"))
        for i, c in enumerate(customs, 1):
            tag = L("有測速檔", "speed test") if c.get("test_url") else L("只看延遲", "latency only")
            print(f"  {i}. {c['domain']}  (.{c['suffix']}, {tag})")
        print(L("\n  a. 新增　r. 移除　直接按 Enter 返回", "\n  a. Add   r. Remove   Enter to go back"))
        choice = input(L("請選擇：", "Choose: ")).strip().lower()
        if not choice:
            return 0
        if choice == "a":
            domain = input(L("要加入的網域（例如 video.twimg.com）：", "Domain to add (e.g. video.twimg.com): ")).strip()
            if domain:
                add_custom_domain(domain)
        elif choice == "r":
            if not customs:
                continue
            n = input(L("要移除第幾個：", "Number to remove: ")).strip()
            if n.isdigit() and 1 <= int(n) <= len(customs):
                remove_custom_domain(customs[int(n) - 1]["domain"])
            else:
                print(L("請輸入列表中的編號。", "Please enter a number from the list."))
        else:
            print(L("請輸入 a、r，或直接按 Enter。", "Please enter a, r, or just Enter."))


def action_services():
    """選擇要加速哪些服務。"""
    while True:
        states = load_config().get("services", {})
        print(L("\n【要加速的服務】", "\n[Services to speed up]"))
        services = all_services()
        for i, svc in enumerate(services, 1):
            on = states.get(svc["key"], True)
            print(f"  {i}. [{'x' if on else ' '}] {sname(svc)}")
        print(L("  （Twitch 只能加速網頁、圖片和表情符號；直播影片本身不在 Fastly 上，改不到）",
                "  (Twitch: pages, images and emotes only; the live video itself is not on Fastly)"))
        choice = input(L("\n輸入編號切換開關，直接按 Enter 返回：", "\nEnter a number to toggle, or Enter to go back: ")).strip()
        if not choice:
            return 0
        if not choice.isdigit() or not 1 <= int(choice) <= len(services):
            print(L("請輸入列表中的編號。", "Please enter a number from the list."))
            continue
        key = services[int(choice) - 1]["key"]
        states[key] = not states.get(key, True)
        if not any(states.get(s["key"], True) for s in services):
            print(L("至少要保留一個服務。", "At least one service must stay on."))
            continue
        save_config(services=states)


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
        items.append(L(f"語言與服務設定（{config_path()}）", f"Language and service settings ({config_path()})"))
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
    """直接寫入指定的線路：set 服務=IP:代碼 ...（選地區提權後使用）。服務：github、x、twitch。"""
    routes = []
    for arg in args:
        try:
            key, rest = arg.split("=", 1)
            ip, pop = rest.rsplit(":", 1)
            ipaddress.IPv4Address(ip)
            if not svc_by_key(key) or not (len(pop) == 3 and pop.isalpha()):
                raise ValueError
        except ValueError:
            keys = "、".join(s["key"] for s in all_services())
            print(L(f"參數格式錯誤：{arg}（應為 服務=IP:代碼，服務是 {keys}）",
                    f"Invalid argument: {arg} (expected SERVICE=IP:CODE; SERVICE is one of {keys.replace('、', ', ')})"))
            return 2
        routes.append((svc_by_key(key), ip, pop.upper()))
    if not routes:
        print(L("沒有指定要寫入的線路。", "No route specified."))
        return 2
    if not is_admin():
        return 0 if run_elevated("set", args) else 1
    backup = write_routes(routes)
    print(L("\n✔ 已套用！", "\n✔ Applied!"))
    for svc, ip, pop in routes:
        label = pad(sname(svc) + L("：", ":"), 22)
        print(L(f"  {label}改走 {place(pop)}（{ip}）", f"  {label}now via {place(pop)} ({ip})"))
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
    save_config(lang=LANG)
    print(L("✔ 已切換為中文。", "✔ Switched to English."))
    return 0


def help_text():
    return L(f"""
【這個工具在做什麼】
  GitHub 的下載檔、X（Twitter）的圖片、Twitch 的網頁和圖片，都是透過一家叫 Fastly
  的公司在世界各地的機房傳給你。你的網路業者會自動幫你選一個機房，但選到的不一定順：
  例如中華電信晚上連新加坡機房，常常卡到只剩 1 Mbps。

  這個工具會：
    1. 找出你附近能用的機房（比最近的機房慢 {NEAR_MARGIN_MS} ms 以上的會略過，約 15 秒）
    2. 實際下載測試好幾次，看哪條路線最穩（每個服務約 1 分鐘）
    3. 把最穩的路線寫進電腦的 hosts 檔，讓電腦以後直接走那條路

  要加速哪些服務，可以在「S. 服務設定」選擇；其他放在 Fastly 上的網域，可以在「D. 自訂網域」自己加入。
  Twitch 只能加速網頁、圖片和表情符號；直播影片和聊天室不在 Fastly 上，改不到。

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
  GitHub downloads, X (Twitter) images and Twitch pages/images are delivered by a CDN
  called Fastly from data centers around the world. Your ISP picks one for you
  automatically, but the route is not always smooth: e.g. at night, Chunghwa Telecom
  users going through the Singapore node often crawl at about 1 Mbps.

  This tool:
    1. Finds usable nodes near you (anything {NEAR_MARGIN_MS} ms slower than the nearest
       one is skipped; about 15 s)
    2. Downloads test data several times to see which route is the most stable
       (about 1 min per service)
    3. Writes the most stable route into your hosts file so your computer uses it

  Choose which services to speed up under "S. Services"; add other Fastly-served
  domains under "D. Custom domains".
  Twitch: only pages, images and emotes can be sped up; the live video and chat are
  not on Fastly.

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
    mins = estimate()[0]
    return L(f"""
【請選擇】
  1. 測試          找出目前最順的路線，只測試、不改設定（約 {mins} 分鐘）
  2. 自動套用      測試後，把最順的路線設定到電腦上（需要管理員權限）
  3. 手動選擇地區  掃描後列出附近的地區，再選擇要走哪裡
  4. 還原          移除本工具的設定，回到原本的狀態
  5. 重新整理      重新檢查目前狀況
  6. 指定節點      直接輸入代碼（例如 ICN）切換，使用上次的掃描紀錄
  7. 更新          從 GitHub 檢查並下載新版本
  8. 所有節點延遲  列出所有節點的延遲，每頁 10 個
  9. 刪除          刪除本工具的所有資料，切回原本的節點
  S. 服務設定      選擇要加速哪些服務（GitHub、X 圖片、Twitch、自訂網域）
  D. 自訂網域      自己加入其他放在 Fastly 上的網域
  L. Language      切換為英文 / Switch to English
  h. 說明          這個工具在做什麼
  0. 離開""", f"""
[Menu]
  1. Test            Find the smoothest route; test only, nothing changes (~{mins} min)
  2. Auto apply      Test, then set the smoothest route (needs administrator)
  3. Choose region   Scan, list nearby regions, then pick where to go
  4. Restore         Remove this tool's settings and go back to the original
  5. Refresh         Check the current status again
  6. Switch node     Switch by code (e.g. ICN) using the last scan
  7. Update          Check GitHub for a new version
  8. Node latency    List the latency of all nodes, 10 per page
  9. Delete          Delete all data from this tool and go back to the original
  S. Services        Choose what to speed up (GitHub, X images, Twitch, custom)
  D. Custom domains  Add other domains that are served by Fastly
  L. Language        Switch to Chinese (中文)
  h. Help            What this tool does
  0. Exit""")


def menu():
    st = None
    while True:
        print("\n" + LINE)
        print(L(f"  fastly-hosts {VERSION}｜加速 GitHub、X 圖片與 Twitch",
                f"  fastly-hosts {VERSION} | Faster GitHub, X images and Twitch"))
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
        choice = input(L("\n請輸入數字或字母（h = 說明）：", "\nEnter a number or letter (h = help): ")).strip().lower()
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
            elif choice == "s":
                action_services()
                st = None
                continue
            elif choice == "d":
                action_custom()
                st = None
                continue
            elif choice == "l":
                action_language()
                continue
            elif choice == "h":
                print(help_text())
            elif choice == "0":
                return 0
            else:
                print(L("請輸入 0～9 的數字，或 S、D、L、h。", "Please enter 0-9, S, D, L or h."))
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
            "add": lambda: (0 if len(args) > 1 and add_custom_domain(args[1], args[2] if len(args) > 2 else None,
                                                                      ask=False) else 1),
            "remove": lambda: (0 if len(args) > 1 and remove_custom_domain(args[1].lower()) else 1),
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
