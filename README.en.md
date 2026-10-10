# fastly-hosts

English | [繁體中文](README.md)

Automatically finds the most stable nearby Fastly route to speed up **GitHub downloads** and **X (Twitter) images**. Works on Windows and Linux, in English and Chinese, through a simple numbered menu.

## Why

GitHub release downloads, raw files and X images are delivered by the CDN Fastly from data centers around the world. Your ISP picks one for you automatically, but that route is not always smooth.

Measured on Chunghwa Telecom (HiNet, Taiwan):

| Route | Downloads during evening peak hours |
|---|---|
| System default: Singapore (SIN) | almost always stuck below 1 Mbps |
| Route found by this tool: Seoul (ICN) | full line speed every time |

This tool:

1. Finds usable Fastly nodes near you; anything 60 ms slower than the nearest one is skipped (about 15 s)
2. Downloads test data in several rounds to see which route is the most stable (1-2 min)
3. Writes the most stable route into your hosts file so your computer uses it from then on

Good routes change as ISPs adjust their routing, so every run tests again; no IP is hard-coded.

## Download and use

### Windows

1. Download `fastly-hosts-x.x.x-windows-x64.zip` from [Releases](../../releases) and unzip it
2. Double-click `fastly-hosts.exe`
   - If SmartScreen blocks it the first time, click "More info" → "Run anyway" (the program is not code-signed)
3. Choose from the menu by number:

```
[Current status]
  GitHub downloads:   via Singapore (SIN), latency ~63 ms
  X images:           via Singapore (SIN), latency ~64 ms
  This tool:          not applied (system default route)

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
  0. Exit
```

Options that change settings (apply, choose region, switch node, restore, delete) show an administrator prompt; click "Yes".

### Linux

Requires Python 3.8 or later (preinstalled on Ubuntu and most distributions).

```sh
git clone https://github.com/AFAlimru/fastly-hosts-adjust.git
cd fastly-hosts-adjust
sh linux/install.sh
```

A **fastly-hosts** icon appears on the desktop and in the application menu; double-click it to open the same menu. When you apply or restore, it asks for your login password (sudo) in the same window.

You can also run it directly: `python3 fastly_hosts.py`

### Language

The menu is shown in Chinese if your system language is Chinese, otherwise in English. Press `L` in the menu to switch; your choice is remembered. You can also pass `--lang=en` or `--lang=zh`.

### Choosing a region yourself

If you don't want the automatic pick:

- **3. Choose region**: scans nearby nodes, lists the usable regions with latency, then asks where to go
- **6. Switch node**: no waiting for a scan; enter a code and switch right away. It uses the last scan and first checks that those routes still reach the same region

"3. Choose region" lists:

```
[Nearby regions] (by latency)
  ICN  Seoul         latency ~47 ms
  HKG  Hong Kong     latency ~52 ms
  NRT  Tokyo         latency ~57 ms
  ...
```

Enter a code (`ICN`) or a city name (`Seoul`) to switch there. A region usually has several routes; the tool tests up to 8 and picks the most stable one. If X has no node in that region (e.g. Hong Kong), X images keep the system default route.

Distant regions are skipped. If you really want one (e.g. `LAX`), enter its code and the tool will offer a full worldwide scan (about 1.5 min).

To see the latency of every region (about 100), use "8. Node latency": 10 per page, `n` next, `p` previous, `q` back. It first asks whether to scan again or show the last result.

### Update and delete

- **7. Update**: checks this project's GitHub Releases. If there is a new version it asks before updating; reopen the program afterwards. The Windows version verifies the SHA256 checksum listed in the release notes and cancels on mismatch
- **9. Delete**: deletes all data from this tool (hosts entries, hosts backup, scan record, language setting) and goes back to the original route. It lists everything first and asks you to confirm. The program itself is not deleted

### Command line (advanced)

```
fastly_hosts.py test           test only
fastly_hosts.py apply [--yes]  auto apply (--yes: don't ask)
fastly_hosts.py region ICN     scan, then choose a region
fastly_hosts.py switch ICN     switch using the last scan
fastly_hosts.py list           latency of all nodes
fastly_hosts.py update         check for updates
fastly_hosts.py restore        restore
fastly_hosts.py purge          delete all data
fastly_hosts.py status         current status
--lang=en / --lang=zh          display language
```

On Windows, use `fastly-hosts.exe` with the same arguments.

## FAQ

**What does it change on my computer?**
Only a small, marked block in the hosts file (Windows: `C:\Windows\System32\drivers\etc\hosts`, Linux: `/etc/hosts`), affecting only:

- `release-assets.githubusercontent.com`
- `raw.githubusercontent.com`
- `pbs.twimg.com`

"Restore" removes that block completely and leaves everything else untouched. Before the first change, the original file is backed up as `hosts.fastly-hosts.bak`.

The last scan result and the language setting are stored in `%LOCALAPPDATA%\fastly-hosts\` (Windows) or `~/.cache/fastly-hosts/` (Linux). "9. Delete" removes all of it.

**How much data does a test use?**
About 300 MB per run (only the first few MB of a file are downloaded per sample; nothing is saved).

**When should I apply again?**
When GitHub downloads feel slow again. If you move to another network (e.g. a laptop on the go) and it feels slow, restore first.

**Why does it need administrator rights?**
The hosts file is a system file that only administrators / root can change. "Test" needs no special rights.

**My antivirus complains?**
Some antivirus software treats changing the hosts file as suspicious. All the code is in this repository for you to review.

**Does it only work on Chunghwa Telecom?**
It works on any network; tests are based on the nodes nearest to you. So far, the improvement has only been verified on Chunghwa Telecom.

## Build the Windows exe yourself

- On Windows: install Python, then run `build\build-windows.bat`
- On Linux (via Wine): `sudo apt install wine`, then run `sh build/build-windows-wine.sh`

## Releasing a new version (maintainers)

1. Bump `VERSION` in `fastly_hosts.py` and the version in `build/version_info.txt`
2. Run `sh build/build-windows-wine.sh`; it produces `dist/fastly-hosts-x.x.x-windows-x64.zip` and prints the exe's SHA256
3. Create a GitHub Release tagged `v` + version (e.g. `v0.7.0`), upload the zip, **and paste the SHA256 into the release notes** (the update feature uses it to verify the download)

## How it works

GitHub and X files are served by Fastly, and some Fastly IP ranges always lead to a specific data center. The tool:

1. Fetches all IP ranges from [Fastly's official IP list](https://api.fastly.com/public-ip-list) (about 1,200 /24 blocks), picks one IP per block and first measures only latency. Anything 60 ms slower than the nearest node is skipped; the nearby ones are fully checked with GitHub's domain to confirm they serve the content, recording data center and latency
2. Runs 3 interleaved speed-test rounds on the 10 lowest-latency routes plus the system default. A congested route usually crawls at about 1 Mbps from the start, so what counts is how often a route is smooth, not its single best speed ("smooth" = at least 30% of the fastest speed in that test, and at least 3 Mbps)
3. X images are too small to measure speed, so the GitHub result for the same route is used. X is not deployed in every data center, so only routes where X is actually served from that same data center are used

Python standard library only, no third-party packages.

## License

[MIT License](LICENSE)
