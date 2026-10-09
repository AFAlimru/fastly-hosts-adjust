#!/usr/bin/env python3
"""fastly-hosts：自動找出最順的 Fastly 路線，加速 GitHub 下載與 X（Twitter）圖片

直接執行會出現選單，用數字選擇即可（Windows 雙擊 exe、Linux 雙擊捷徑）。

也可以加參數執行：
  test      找出最順的路線，只測試、不改任何設定
  apply     測試後把最順的路線寫入 hosts（需要管理員 / root）
  region [代碼]  手動選擇地區，例如：region ICN、region 首爾
  restore   移除本工具寫入的設定
  status    顯示目前狀況
  --yes     套用時不再詢問確認

只使用 Python 標準函式庫，支援 Windows 與 Linux。
"""
import http.client
import ipaddress
import json
import os
import platform
import shutil
import socket
import ssl
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

VERSION = "0.5.0"
IS_WINDOWS = platform.system() == "Windows"
HOSTS_PATH = (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "etc", "hosts")
              if IS_WINDOWS else "/etc/hosts")
# hosts 檔裡只寫 ASCII，避免 Windows 解析 hosts 時遇到非英文字元出問題
MARK_BEGIN = "# >>> fastly-hosts >>> (managed by fastly_hosts.py, do not edit this block)"
MARK_END = "# <<< fastly-hosts <<<"
USER_AGENT = f"fastly-hosts/{VERSION}"

# GitHub 用 Fastly IP 尾碼 .133、X 圖片用 .159（同一個 /24 走同一條路線）
GITHUB = {
    "name": "GitHub 下載",
    "key": "github",
    "hosts": ["release-assets.githubusercontent.com", "raw.githubusercontent.com"],
    "suffix": 133,
    "probe_host": "raw.githubusercontent.com",
    "probe_path": "/github/gitignore/main/README.md",
}
X_IMAGES = {
    "name": "X 圖片",
    "key": "x-images",
    "hosts": ["pbs.twimg.com"],
    "suffix": 159,
    "probe_host": "pbs.twimg.com",
    "probe_path": "/profile_images/1683325380441128960/yRsRRjGO_400x400.jpg",
}
GROUPS = [GITHUB, X_IMAGES]

# Fastly 節點代碼 → 城市
POP_NAMES = {
    "ICN": "首爾", "NRT": "東京", "HND": "東京", "TYO": "東京", "ITM": "大阪", "KIX": "大阪",
    "HKG": "香港", "TPE": "台北", "SIN": "新加坡", "QPG": "新加坡", "MNL": "馬尼拉",
    "KUL": "吉隆坡", "BKK": "曼谷", "CGK": "雅加達", "SYD": "雪梨", "MEL": "墨爾本",
    "BNE": "布里斯本", "PER": "伯斯", "ADL": "阿德雷德", "AKL": "奧克蘭", "WLG": "威靈頓",
    "CHC": "基督城", "BOM": "孟買", "DEL": "德里", "MAA": "清奈", "HYD": "海得拉巴",
    "CCU": "加爾各答", "DXB": "杜拜", "RUH": "利雅德", "LAX": "洛杉磯", "BUR": "洛杉磯",
    "SJC": "聖荷西", "WVI": "華森維爾", "PAO": "帕羅奧圖", "SEA": "西雅圖", "BFI": "西雅圖", "PDX": "波特蘭",
    "YVR": "溫哥華", "DFW": "達拉斯", "IAH": "休士頓", "ORD": "芝加哥", "CHI": "芝加哥",
    "IAD": "華盛頓", "NYC": "紐約", "EWR": "紐約", "LGA": "紐約", "JFK": "紐約",
    "BOS": "波士頓", "ATL": "亞特蘭大", "MIA": "邁阿密", "YYZ": "多倫多", "YUL": "蒙特婁",
    "LHR": "倫敦", "LON": "倫敦", "LCY": "倫敦", "AMS": "阿姆斯特丹", "FRA": "法蘭克福",
    "PAR": "巴黎", "MAD": "馬德里", "MXP": "米蘭", "LIN": "米蘭", "FCO": "羅馬",
    "VIE": "維也納", "CPH": "哥本哈根", "OSL": "奧斯陸", "HEL": "赫爾辛基", "DUB": "都柏林",
    "BER": "柏林", "MUC": "慕尼黑", "BRU": "布魯塞爾", "GRU": "聖保羅", "GIG": "里約",
    "EZE": "布宜諾斯艾利斯", "SCL": "聖地牙哥", "BOG": "波哥大", "LIM": "利馬",
    "JNB": "約翰尼斯堡", "CPT": "開普敦",
}

FASTLY_IP_LIST_URL = "https://api.fastly.com/public-ip-list"
# 抓不到官方清單時使用（2026-10 的官方清單）
FALLBACK_RANGES = [
    "23.235.32.0/20", "43.249.72.0/22", "103.244.50.0/24", "103.245.222.0/23", "103.245.224.0/24",
    "104.156.80.0/20", "140.248.64.0/18", "140.248.128.0/17", "146.75.0.0/17", "151.101.0.0/16",
    "157.52.64.0/18", "167.82.0.0/17", "167.82.128.0/20", "167.82.160.0/20", "167.82.224.0/20",
    "172.111.64.0/18", "185.31.16.0/22", "199.27.72.0/21", "199.232.0.0/16",
]
SCAN_WORKERS = 48           # 掃描時同時連線數
SCAN_TIMEOUT = 3
SPEED_TOP_N = 10            # 掃描後挑延遲最低的幾個 IP 來測速
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
LINE = "─" * 56


def place(pop):
    """'ICN' → '首爾（ICN）'；不認得的代碼只顯示代碼。"""
    return f"{POP_NAMES[pop]}（{pop}）" if pop in POP_NAMES else (pop or "?")


def width(text):
    """終端機顯示寬度：中文等全形字佔兩格。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def pad(text, cols):
    return text + " " * max(cols - width(text), 1)


def progress(label, done, total):
    pct = int(done * 100 / total) if total else 100
    print(f"\r  {label} {pct:3d}%", end="" if done < total else "\n", flush=True)


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
    raise RuntimeError("拿不到 release-assets 下載網址")


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
    raise RuntimeError(f"拿不到測速檔案：{last_error}")


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


def scan(ranges, label="步驟 1/2：尋找附近的節點…"):
    """每個 /24 挑一個 IP，用 GitHub 網域做 HEAD，回傳所有能用的 IP（依延遲排序）。"""
    ips = []
    for cidr in ranges:
        net = ipaddress.ip_network(cidr, strict=False)
        subs = net.subnets(new_prefix=24) if net.prefixlen < 24 else [net]
        ips += [same_24(str(s.network_address), GITHUB["suffix"]) for s in subs]
    found = []
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        futures = [pool.submit(probe, GITHUB, ip, timeout=SCAN_TIMEOUT) for ip in ips]
        for done, fut in enumerate(as_completed(futures), 1):
            if fut.result():
                found.append(fut.result())
            if done % 24 == 0 or done == len(futures):
                progress(label, done, len(futures))
    # 掃描時同時連線多，延遲不準；前 30 名再各量 3 次排序
    found.sort(key=lambda r: r["latency_ms"])
    top = found[:30]
    for r in top:
        r["latency_ms"] = tcp_latency(r["ip"], tries=3, timeout=SCAN_TIMEOUT) or 9e9
    top.sort(key=lambda r: r["latency_ms"])
    return top + found[30:], len(ips), len(found)


def speed_test(candidates, rounds=SPEED_ROUNDS, label="步驟 2/2：實際測試下載速度…"):
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
    """掃描 + 測速 + 判斷。回傳 GitHub 與 X 圖片各自的建議。"""
    has_block = bool(current_block(read_hosts()))
    base_word = "目前設定" if has_block else "目前路線"
    top, scanned, usable = scan(fastly_ranges())
    if not top:
        fail = {"best": None, "apply": False, "reason": "找不到可用的節點（網路不通或被擋）"}
        return {"github": dict(fail, group=GITHUB), "x": dict(fail, group=X_IMAGES), "ranked": [],
                "scanned": scanned, "usable": 0}

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
    ranked = rank(cands, speed_test(cands))
    for c in ranked:
        c["is_base_gh"] = c["ip"] in base_gh
        c["is_base_x_route"] = c["ip"] in {same_24(ip, GITHUB["suffix"]) for ip in base_x}

    # GitHub
    best = ranked[0]
    base_rows = [c for c in ranked if c["is_base_gh"]]
    base_fast = max((c["fast"] for c in base_rows), default=0)
    base_pop = base_rows[0]["pop"] if base_rows else "?"
    before = f"{base_word} {place(base_pop)}：{SPEED_ROUNDS} 次測試有 {base_fast} 次順暢"
    after = (f"建議路線 {place(best['pop'])}：{SPEED_ROUNDS} 次測試有 {best['fast']} 次順暢，"
             f"延遲約 {best['latency_ms']:.0f} ms")
    if best["is_base_gh"]:
        gh = {"apply": False, "reason": f"{base_word}已經是最順的路線，不需要改"}
    elif best["fast"] > base_fast:
        gh = {"apply": True, "reason": f"{before}\n{after}"}
    else:
        gh = {"apply": False, "reason": f"{before}，跟其他路線一樣順，不需要改"}
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
        before = (f"{base_word} {place(base_x_pop)}：{SPEED_ROUNDS} 次測試有 {base_x_fast} 次順暢"
                  if base_x_verified else f"{base_word} {place(base_x_pop)}：無法確認順不順")
        after = (f"建議路線 {place(x_best['pop'])}：{SPEED_ROUNDS} 次測試有 {x_best['fast']} 次順暢，"
                 f"延遲約 {x_best['latency_ms']:.0f} ms")
        x = {"apply": True, "best": x_best, "reason": f"{before}\n{after}"}
    else:
        x = {"apply": False, "best": None, "reason": "沒有比目前更順、又能提供 X 圖片的路線，不需要改"}
    x.update(group=X_IMAGES)
    return {"github": gh, "x": x, "ranked": ranked, "scanned": scanned, "usable": usable}


# ---------------------------------------------------------------- 顯示

def print_summary(result):
    print(f"\n【結果】（掃描 {result['scanned']} 個位置，找到 {result['usable']} 個可用節點）")
    for key in ("github", "x"):
        r = result[key]
        name = r["group"]["name"]
        if r["apply"]:
            print(f"\n  ✔ {name}：建議改走 {place(r['best']['pop'])}")
        else:
            print(f"\n  ・{name}：維持現狀")
        for line in r["reason"].split("\n"):
            print(f"      {line}")
    print("\n  「順暢」＝速度達到這次測到最快速度的 30% 以上（且至少 3 Mbps）；卡住的路線通常只剩 1 Mbps 左右。")


def print_details(result):
    print(f"\n【詳細數據】GitHub 下載測速（每條路線測 {SPEED_ROUNDS} 次，單位 Mbps）")
    print(f"  {'IP':<16}{pad('地點', 14)}{' ' * 3}延遲  {pad('順暢', 6)}各次速度")
    for c in result["ranked"]:
        tag = "← 目前 GitHub" if c["is_base_gh"] else ("← 目前 X 圖片" if c["is_base_x_route"] else "")
        vs = " / ".join(f"{v:5.1f}" for v in c["speeds"])
        print(f"  {c['ip']:<16}{pad(place(c['pop']), 14)}{c['latency_ms']:5.0f}ms  {c['fast']}/{SPEED_ROUNDS}   {vs}  {tag}")


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
    print("【目前狀況】")
    for r in st["rows"]:
        label = pad(f"{r['group']['name']}：", 14)
        if r["info"]:
            print(f"  {label}目前走 {place(r['info']['pop'])}，延遲約 {r['info']['latency_ms']:.0f} ms")
        elif r["ip"]:
            print(f"  {label}連不上（{r['ip']}）")
        else:
            print(f"  {label}查不到網址（DNS 失敗）")
    label = pad("本工具設定：", 14)
    if st["block"]:
        print(f"  {label}已套用（{st['applied'] or '時間不明'}）")
    else:
        print(f"  {label}未套用（使用系統原本的路線）")


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


# ---------------------------------------------------------------- 權限

def _script_args(action, pause, extra_args=()):
    """重新執行自己時的程式與參數（exe 或 .py 都適用）。"""
    extra = [action] + list(extra_args) + (["--pause"] if pause else [])
    if getattr(sys, "frozen", False):
        return sys.executable, extra
    return sys.executable, [os.path.abspath(__file__)] + extra


def run_elevated(action, extra_args=()):
    """以管理員 / root 身分執行同一個動作，等它結束。回傳是否有成功啟動。"""
    if not IS_WINDOWS:
        exe, args = _script_args(action, pause=False, extra_args=extra_args)
        print("需要 root 權限，請輸入你的 Linux 登入密碼（輸入時畫面不會顯示）：")
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
    print("需要系統管理員權限，請在跳出的視窗按「是」。")
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        print("沒有取得權限（可能按了「否」）。")
        return False
    print("已在新視窗執行，完成後請在新視窗按 Enter 關閉…")
    if info.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return True


# ---------------------------------------------------------------- 動作

def ask_yes(question, default=True):
    ans = input(f"{question} {'(Y/n)' if default else '(y/N)'}：").strip().lower()
    return default if not ans else ans in ("y", "yes")


def action_test(interactive=True):
    print("\n開始測試，大約需要 3 分鐘，會用掉約 300 MB 流量（只測試，不改任何設定）。\n")
    result = analyze()
    print_summary(result)
    if interactive and result["ranked"] and ask_yes("\n要看詳細數據嗎？", default=False):
        print_details(result)
    elif not interactive:
        print_details(result)
    return result


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


def action_apply(yes=False):
    if not is_admin():
        return 0 if run_elevated("apply") else 1
    # 先拿掉舊設定再測，避免量到自己上次寫入的結果
    original = read_hosts()
    if current_block(original):
        write_hosts(strip_block(original))
        flush_dns()
    result = action_test(interactive=not yes)
    routes = [(result[k]["group"], result[k]["best"]["ip"], result[k]["best"]["pop"])
              for k in ("github", "x") if result[k]["apply"]]
    if not routes:
        print("\n目前的路線已經很順，不需要修改，設定維持原狀。")
        return 0
    if not yes and not ask_yes("\n要套用上面建議的路線嗎？"):
        print("已取消，沒有修改任何設定。")
        return 0
    backup = write_routes(routes)
    print("\n✔ 已套用！之後 GitHub 下載 / X 圖片會走新的路線。")
    print(f"  （設定寫在 {HOSTS_PATH}，原始檔案備份在 {backup}）")
    print("  想恢復原狀，隨時選「還原」即可。")
    return 0


def find_region(text, regions):
    """輸入地區代碼（ICN）或城市名稱（首爾），回傳可用的節點代碼；找不到回傳 None。"""
    t = text.strip()
    if t.upper() in regions:
        return t.upper()
    same_city = [pop for pop in regions if POP_NAMES.get(pop) == t]
    return min(same_city, key=lambda pop: regions[pop][0]["latency_ms"]) if same_city else None


def action_region(code=None):
    """手動選擇地區：列出附近可用的地區，輸入代碼後在該地區挑最穩的線路。"""
    print("\n正在尋找可用的地區（約 1 分鐘）…")
    found, _, _ = scan(fastly_ranges(), label="尋找可用的地區…")
    regions = {}
    for r in found:
        regions.setdefault(r["pop"], []).append(r)
    regions.pop("?", None)
    for ips in regions.values():
        ips.sort(key=lambda r: r["latency_ms"])
    if not regions:
        print("找不到可用的地區（網路不通或被擋）。")
        return 1
    nearest = sorted(regions, key=lambda pop: regions[pop][0]["latency_ms"])
    print("\n【附近可用的地區】（依延遲排序）")
    for pop in nearest[:15]:
        print(f"  {pop}  {pad(POP_NAMES.get(pop, ''), 10)}延遲約 {regions[pop][0]['latency_ms']:.0f} ms")
    print(f"  …共 {len(regions)} 個地區，不在列表上的代碼也可以輸入")

    if code is None:
        code = input("\n請輸入地區代碼或城市名稱（例如 ICN 或 首爾），直接按 Enter 取消：").strip()
        if not code:
            print("已取消。")
            return 0
    pop = find_region(code, regions)
    if not pop:
        print(f"找不到「{code}」這個地區，或你的網路目前連不到那裡。")
        return 1

    # 同一個地區不同 IP 的穩定度差很多（實測東京有的 IP 每次都順、有的常卡），所以再挑一次
    cands = regions[pop][:4]
    print(f"\n測試 {place(pop)} 的 {len(cands)} 條線路（約 30 秒）…")
    ranked = rank(cands, speed_test(cands, rounds=2, label="測試線路…"))
    for c in ranked:
        vs = " / ".join(f"{v:5.1f}" for v in c["speeds"])
        print(f"  {c['ip']:<16}延遲 {c['latency_ms']:4.0f} ms  順暢 {c['fast']}/2  [{vs}] Mbps")
    best = ranked[0]
    if best["fast"] == 0 and not ask_yes(f"\n{place(pop)} 目前每條線路都卡住，仍要改走這裡嗎？", default=False):
        print("已取消，沒有修改任何設定。")
        return 0

    # X 圖片：只採用 X 實際由這個地區出貨的線路
    x = None
    for c in ranked:
        info = probe(X_IMAGES, same_24(c["ip"], X_IMAGES["suffix"]))
        if info and info["pop"] == pop:
            x = info
            break
    print(f"\n  {pad('GitHub 下載：', 14)}改走 {place(pop)}，使用 {best['ip']}")
    if x:
        print(f"  {pad('X 圖片：', 14)}改走 {place(pop)}，使用 {x['ip']}")
    else:
        print(f"  {pad('X 圖片：', 14)}X 在 {place(pop)} 沒有機房，維持系統原本的路線")
    if not ask_yes("\n確定要套用嗎？"):
        print("已取消，沒有修改任何設定。")
        return 0
    args = [f"github={best['ip']}:{pop}"] + ([f"x={x['ip']}:{pop}"] if x else [])
    return action_set(args)


def action_set(args):
    """直接寫入指定的線路：set github=IP:代碼 [x=IP:代碼]（手動選地區提權後使用）。"""
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
            print(f"參數格式錯誤：{arg}（應為 github=IP:代碼 或 x=IP:代碼）")
            return 2
        routes.append((groups[key], ip, pop.upper()))
    if not routes:
        print("沒有指定要寫入的線路。")
        return 2
    if not is_admin():
        return 0 if run_elevated("set", args) else 1
    backup = write_routes(routes)
    print("\n✔ 已套用！")
    for group, ip, pop in routes:
        print(f"  {pad(group['name'] + '：', 14)}改走 {place(pop)}（{ip}）")
    print(f"  （設定寫在 {HOSTS_PATH}，原始檔案備份在 {backup}）")
    return 0


def action_restore():
    if not is_admin():
        return 0 if run_elevated("restore") else 1
    text = read_hosts()
    if not current_block(text):
        print("\n目前沒有本工具的設定，不需要還原。")
        return 0
    write_hosts(strip_block(text))
    flush_dns()
    print("\n✔ 已還原，回到系統原本的路線。")
    return 0


def action_status():
    print("正在檢查目前狀況…")
    print_status(current_status())
    return 0


HELP_TEXT = f"""
【這個工具在做什麼】
  GitHub 的下載檔、X（Twitter）的圖片，都是透過一家叫 Fastly 的公司在世界各地的
  機房傳給你。你的網路業者會自動幫你選一個機房，但選到的不一定順：
  例如中華電信晚上連新加坡機房，常常卡到只剩 1 Mbps。

  這個工具會：
    1. 找出你附近所有能用的機房（約 1 分鐘）
    2. 實際下載測試好幾次，看哪條路線最穩（約 2 分鐘）
    3. 把最穩的路線寫進電腦的 hosts 檔，讓電腦以後直接走那條路

  也可以用「手動選擇地區」，輸入代碼（例如 ICN）或城市名稱（例如 首爾）指定要走哪裡。

  好路線會隨網路業者調整而改變，覺得又變慢時重新「套用」一次就好。
  換到其他網路（例如筆電帶出門）覺得變慢，先「還原」。

【會改到什麼】
  只會在 hosts 檔加上一小段標記好的設定，「還原」會把那段完整移除，
  原本的內容不會動。第一次修改前會自動備份原檔。
  hosts 檔位置：{HOSTS_PATH}
"""


def menu():
    st = None
    while True:
        print("\n" + LINE)
        print(f"  fastly-hosts {VERSION}｜加速 GitHub 下載與 X 圖片")
        print(LINE)
        if st is None:
            print("正在檢查目前狀況…")
            try:
                st = current_status()
            except Exception as e:
                st = {"error": e}
        if "error" in st:
            print(f"（檢查狀況失敗：{st['error']}）")
        else:
            print_status(st)
        print(f"""
【請選擇】
  1. 測試          找出目前最順的路線，只測試、不改設定（約 3 分鐘）
  2. 自動套用      測試後，把最順的路線設定到電腦上（需要管理員權限）
  3. 手動選擇地區  輸入代碼（例如 ICN）或城市名稱，指定要走哪裡
  4. 還原          移除本工具的設定，回到原本的狀態
  5. 重新整理      重新檢查目前狀況
  6. 說明          這個工具在做什麼
  0. 離開""")
        choice = input("\n請輸入數字：").strip()
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
                print(HELP_TEXT)
            elif choice == "0":
                return 0
            else:
                print("請輸入 0～6 的數字。")
                continue
        except PermissionError as e:
            print(f"\n寫入失敗，沒有權限：{e}")
        except Exception as e:  # 網路錯誤等：顯示原因後回到選單，不要整個關掉
            print(f"\n發生錯誤：{type(e).__name__}: {e}")
        input("\n按 Enter 回到選單…")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    pause = "--pause" in argv
    yes = "--yes" in argv
    cmds = {"test": lambda: (action_test(interactive=False), 0)[1], "apply": lambda: action_apply(yes),
            "region": lambda: action_region(args[1] if len(args) > 1 else None),
            "set": lambda: action_set(args[1:]), "restore": action_restore, "status": action_status}
    if args and args[0] not in cmds:
        print(__doc__)
        return 2
    try:
        return cmds[args[0]]() if args else menu()
    except PermissionError as e:
        print(f"\n寫入失敗，沒有權限：{e}")
        if IS_WINDOWS:
            print("如果已經是系統管理員，可能是 hosts 被設成唯讀，或被防毒軟體保護。")
        return 1
    finally:
        if pause:
            input("\n按 Enter 關閉這個視窗…")


if __name__ == "__main__":
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
