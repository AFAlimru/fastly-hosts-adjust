# fastly-hosts

[English](README.en.md) | 繁體中文

自動找出附近最順的 Fastly 路線，加速 **GitHub 下載**與 **X（Twitter）圖片**。支援 Windows 與 Linux，中英文介面，用數字選單操作，不用打指令。

## 為什麼需要它

GitHub 的 release 下載檔、raw 檔案，還有 X 的圖片，都是透過 CDN 公司 Fastly 在世界各地的機房傳給你。網路業者會自動幫你選一個機房，但選到的路線不一定順。

例如中華電信（HiNet）的實測結果：

| 路線 | 晚上尖峰時段的下載狀況 |
|---|---|
| 系統預設：新加坡（SIN） | 幾乎每次都卡在 1 Mbps 以下 |
| 本工具找到的路線：首爾（ICN） | 每次都跑滿線路 |

這個工具會：

1. 找出你附近能用的 Fastly 機房，比最近的機房慢 60 ms 以上的直接略過（約 15 秒）
2. 實際下載測試好幾輪，看哪條路線最穩（約 1～2 分鐘）
3. 把最穩的路線寫進電腦的 hosts 檔，以後電腦就直接走那條路

好路線會隨網路業者的調整而改變，所以每次都會重新測試，不會把 IP 寫死在程式裡。

## 下載與使用

### Windows

1. 到 [Releases](../../releases) 下載 `fastly-hosts-x.x.x-windows-x64.zip`，解壓縮
2. 雙擊 `fastly-hosts.exe`
   - 第一次執行如果被 SmartScreen 擋下，點「其他資訊」→「仍要執行」（程式沒有數位簽章）
3. 照選單輸入數字：

```
【目前狀況】
  GitHub 下載：  目前走 新加坡（SIN），延遲約 63 ms
  X 圖片：       目前走 新加坡（SIN），延遲約 64 ms
  本工具設定：   未套用（使用系統原本的路線）

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
  0. 離開
```

需要修改設定的選項（套用、選擇地區、指定節點、還原、刪除）會跳出系統管理員權限的確認視窗，按「是」即可。

### Linux

需要 Python 3.8 以上（Ubuntu 等發行版通常已內建）。

```sh
git clone https://github.com/AFAlimru/fastly-hosts.git
cd fastly-hosts
sh linux/install.sh
```

之後桌面和應用程式選單會出現 **fastly-hosts** 圖示，雙擊就會開啟同樣的選單。選「套用」或「還原」時，會在同一個視窗詢問你的登入密碼（sudo）。

也可以直接執行：`python3 fastly_hosts.py`

### 語言

系統語言是中文就顯示中文，其他語言顯示英文。選單按 `L` 可以切換，程式會記住你的選擇。也可以用參數 `--lang=zh` 或 `--lang=en` 指定。

### 自己指定要走哪個地區

不想讓程式自動挑選時，有兩種方式：

- **3. 手動選擇地區**：重新掃描附近的節點，列出可用的地區和延遲，再輸入要去哪裡
- **6. 指定節點**：不用等掃描，直接輸入代碼切換。使用上次掃描的紀錄，並先確認那些線路現在還連得到同一個地區

「3. 手動選擇地區」會列出：

```
【附近可用的地區】（依延遲排序）
  ICN  首爾      延遲約 47 ms
  HKG  香港      延遲約 52 ms
  NRT  東京      延遲約 57 ms
  ...
```

輸入代碼（`ICN`）或城市名稱（`首爾` 或 `Seoul`）就會改走那裡。同一個地區通常有好幾條線路，程式會先實測（最多 8 條），再挑最穩的那條。如果 X 在那個地區沒有機房（例如香港），X 圖片會維持系統原本的路線。

較遠的地區會被略過；如果你就是想走那裡（例如 `LAX`），直接輸入代碼，程式會問你要不要完整掃描全世界的節點（約 1.5 分鐘）。

想看所有地區（約 100 個）的延遲，用「8. 所有節點延遲」：每頁 10 個，`n` 下一頁、`p` 上一頁、`q` 返回。執行前會問你要重新掃描，還是直接看上次的結果。

### 更新與刪除

- **7. 更新**：到本專案的 GitHub Releases 檢查新版本，有新版會問你要不要更新，下載後重新開啟程式即可。Windows 版會核對發佈說明裡的 SHA256 校驗碼，不符就取消更新
- **9. 刪除**：刪除本工具的所有資料（hosts 裡的設定、hosts 備份檔、掃描紀錄、語言設定），切回原本的節點。執行前會列出清單讓你確認。程式本身不會被刪除

### 指令模式（進階）

```
fastly_hosts.py test           只測試
fastly_hosts.py apply [--yes]  自動套用（--yes：不詢問確認）
fastly_hosts.py region ICN     掃描後選擇地區
fastly_hosts.py switch ICN     用上次的掃描紀錄直接切換
fastly_hosts.py list           所有節點延遲
fastly_hosts.py update         檢查更新
fastly_hosts.py restore        還原
fastly_hosts.py purge          刪除所有資料
fastly_hosts.py status         顯示目前狀況
--lang=zh / --lang=en          指定語言
```

Windows 用 `fastly-hosts.exe` 加上同樣的參數。

## 常見問題

**會改到我電腦的什麼？**
只會在 hosts 檔（Windows：`C:\Windows\System32\drivers\etc\hosts`，Linux：`/etc/hosts`）加上一小段有標記的設定，影響的網域只有：

- `release-assets.githubusercontent.com`
- `raw.githubusercontent.com`
- `pbs.twimg.com`

「還原」會把這段完整移除，原本的內容不會動。第一次修改前，會自動把原檔備份成 `hosts.fastly-hosts.bak`。

另外會把上次的掃描結果和語言設定存在 `%LOCALAPPDATA%\fastly-hosts\`（Windows）或 `~/.cache/fastly-hosts/`（Linux）。「9. 刪除」會把這些全部清掉。

**測試會用掉多少流量？**
每次約 300 MB（測速時只下載檔案開頭幾 MB，不會存檔）。

**什麼時候要重新套用？**
覺得 GitHub 下載又變慢的時候。換到其他網路（例如筆電帶出門）覺得變慢，先「還原」。

**為什麼要管理員權限？**
hosts 檔是系統檔案，只有管理員 / root 能修改。「測試」不需要權限。

**防毒軟體跳出警告？**
有些防毒軟體會把「修改 hosts」視為可疑行為。程式碼全部公開在這個 repo，可以自行檢查。

**只支援中華電信嗎？**
任何網路都可以用，程式會以你所在位置最近的節點為基準來測試。不過目前只在中華電信上實際驗證過效果。

## 自己打包 Windows exe

- 在 Windows 上：安裝 Python 後，執行 `build\build-windows.bat`
- 在 Linux 上（透過 Wine）：`sudo apt install wine` 後執行 `sh build/build-windows-wine.sh`

## 發佈新版本（維護者）

1. 修改 `fastly_hosts.py` 的 `VERSION` 和 `build/version_info.txt` 的版本號
2. 執行 `sh build/build-windows-wine.sh`，產出 `dist/fastly-hosts-x.x.x-windows-x64.zip`，並印出 exe 的 SHA256
3. 在 GitHub 建立 Release，標籤用 `v` 加版本號（例如 `v0.7.0`），上傳 zip，**並把 SHA256 貼在發佈說明裡**（程式的「更新」功能會用它核對下載的檔案）

## 原理

GitHub 和 X 的檔案都放在 Fastly 上，而 Fastly 有一部分 IP 段會固定連到特定機房。程式會：

1. 從 [Fastly 官方 IP 清單](https://api.fastly.com/public-ip-list)取得所有 IP 段（約 1200 段），每段挑一個 IP，先只量延遲。比最近的節點慢 60 ms 以上的直接略過，剩下附近的才用 GitHub 的網域完整連線，確認能正常提供內容，並記錄機房與延遲
2. 對延遲最低的 10 條路線和系統預設的路線交錯測速 3 輪。塞住的路線通常一開始就卡在 1 Mbps 左右，所以看的是「順暢的次數」，不是單次最高速度（「順暢」＝達到該次最快速度的 30% 以上，且至少 3 Mbps）
3. X 圖片太小，測不出速度，所以沿用同一條路線的 GitHub 測速結果。不過 X 並不是每個機房都有部署，所以只採用「X 實際出貨的機房跟該路線一致」的路線

只使用 Python 標準函式庫，沒有任何第三方套件。

## 授權

[MIT License](LICENSE)
