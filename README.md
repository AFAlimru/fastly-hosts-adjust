# fastly-hosts

[English](README.en.md) | 繁體中文

自動找出附近最順的 Fastly 路線，加速 **GitHub 下載**、**X（Twitter）圖片**與 **Twitch 網頁和圖片**。支援 Windows 與 Linux，中英文介面，用數字選單操作，不用打指令。

## 為什麼需要它

GitHub 的 release 下載檔、raw 檔案、X 的圖片，還有 Twitch 的網頁、圖片和表情符號，都是透過 CDN 公司 Fastly 在世界各地的機房傳給你。網路業者會自動幫你選一個機房，但選到的路線不一定順。

例如中華電信（HiNet）的實測結果：

| 路線 | 晚上尖峰時段的下載狀況 |
|---|---|
| 系統預設：新加坡（SIN） | GitHub、Twitch 幾乎每次都卡在 1 Mbps 以下 |
| 本工具找到的路線：首爾（ICN） | 每次都跑滿線路 |

這個工具會：

1. 找出你附近能用的 Fastly 機房，比最近的機房慢 60 ms 以上的直接略過（約 15 秒）
2. 實際下載測試好幾輪，看哪條路線最穩（每個服務約 1.5 分鐘）
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
  1. 測試          找出目前最順的路線，只測試、不改設定（約 4 分鐘）
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
  0. 離開
```

需要修改設定的選項（套用、選擇地區、指定節點、還原、刪除）會跳出系統管理員權限的確認視窗，按「是」即可。

### Linux

需要 Python 3.8 以上（Ubuntu 等發行版通常已內建）。

```sh
git clone https://github.com/AFAlimru/fastly-hosts-adjust.git
cd fastly-hosts-adjust
sh linux/install.sh
```

之後桌面和應用程式選單會出現 **fastly-hosts** 圖示，雙擊就會開啟同樣的選單。選「套用」或「還原」時，會在同一個視窗詢問你的登入密碼（sudo）。

也可以直接執行：`python3 fastly_hosts.py`

### 要加速哪些服務

選單按 `S` 可以選擇要加速的服務，預設全部開啟。不用 Twitch 的話可以關掉，測試時間會從約 4 分鐘縮短到約 2 分鐘。

| 服務 | 網域 |
|---|---|
| GitHub 下載 | `release-assets.githubusercontent.com`、`raw.githubusercontent.com` |
| X 圖片 | `pbs.twimg.com` |
| Twitch 網頁與圖片 | `www.twitch.tv`、`gql.twitch.tv`、`static-cdn.jtvnw.net`、`assets.twitch.tv`、`k.twitchcdn.net` |

**Twitch 的限制**：只有網頁、圖片、表情符號和網站資料在 Fastly 上，能改善的是「網頁一直轉圈」、「圖片跑很久」、「切頻道很慢」這類問題。**直播影片本身和聊天室**在 Twitch 自己的機房與 AWS 上，這個工具改不到。

### 自訂網域

其他放在 Fastly 上的網站也可以自己加入，選單按 `D` → `a`，輸入網域即可，例如 X 的影片 `video.twimg.com`、Python 套件庫 `files.pythonhosted.org`。

- 程式會先檢查這個網域是不是在 Fastly 上，不是的話會拒絕並說明原因（這個工具只能處理 Fastly）
- 會自動判斷它用的 IP 尾碼（例如 `video.twimg.com` 是 `.158`），並在附近的節點裡找出能提供它的路線
- **測速檔（選填）**：可以填一個同網域、至少幾百 KB 的檔案網址。有測速檔才能分辨哪條路線會卡住；沒有的話只能依延遲挑選，結果會標示「沒有測速」
- 加入後跟內建服務一樣，會出現在測試、套用、選擇地區、狀態裡，也能在 `S` 開關；「9. 刪除」會一併清除

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

輸入代碼（`ICN`）或城市名稱（`首爾` 或 `Seoul`）就會改走那裡。每個服務都會在那個地區各自實測（最多 8 條線路），再挑最穩的那條。如果某個服務在那個地區沒有機房（例如 X 在香港沒有），那個服務會維持系統原本的路線。

較遠的地區會被略過；如果你就是想走那裡（例如 `LAX`），直接輸入代碼，程式會問你要不要完整掃描全世界的節點（約 1.5 分鐘）。

想看所有地區（約 100 個）的延遲，用「8. 所有節點延遲」：每頁 10 個，`n` 下一頁、`p` 上一頁、`q` 返回。執行前會問你要重新掃描，還是直接看上次的結果。

### 更新與刪除

- **7. 更新**：到本專案的 GitHub Releases 檢查新版本，有新版會問你要不要更新，下載後重新開啟程式即可。Windows 版會核對發佈說明裡的 SHA256 校驗碼，不符就取消更新
- **9. 刪除**：刪除本工具的所有資料（hosts 裡的設定、hosts 備份檔、掃描紀錄、語言與服務設定），切回原本的節點。執行前會列出清單讓你確認。程式本身不會被刪除

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
fastly_hosts.py add 網域 [測速檔網址]  加入自訂網域
fastly_hosts.py remove 網域    移除自訂網域
--lang=zh / --lang=en          指定語言
```

Windows 用 `fastly-hosts.exe` 加上同樣的參數。

## 常見問題

**會改到我電腦的什麼？**
只會在 hosts 檔（Windows：`C:\Windows\System32\drivers\etc\hosts`，Linux：`/etc/hosts`）加上一小段有標記的設定，影響的只有上面「要加速哪些服務」表格列出、而且有開啟的網域，以及你自己加入的自訂網域。

「還原」會把這段完整移除，原本的內容不會動。第一次修改前，會自動把原檔備份成 `hosts.fastly-hosts.bak`。

另外會把上次的掃描結果、語言與服務設定存在 `%LOCALAPPDATA%\fastly-hosts\`（Windows）或 `~/.cache/fastly-hosts/`（Linux）。「9. 刪除」會把這些全部清掉。

**測試會用掉多少流量？**
三個服務都開時每次約 360 MB（GitHub 約 300 MB、Twitch 約 60 MB；測速時只下載檔案開頭幾 MB，不會存檔）。

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

GitHub、X、Twitch 的檔案都放在 Fastly 上，而 Fastly 有一部分 IP 段會固定連到特定機房。每個客戶有自己的一批 IP 段和固定的 IP 尾碼（GitHub `.133`、X `.159`、Twitch `.214`），所以每個服務要分開掃描。程式會：

1. 從 [Fastly 官方 IP 清單](https://api.fastly.com/public-ip-list)取得所有 IP 段（約 1200 段），每段挑一個 IP，先只量延遲。比最近的節點慢 60 ms 以上的直接略過，剩下附近的才用各服務自己的網域完整連線，確認能正常提供內容，並記錄機房與延遲
2. 對每個服務延遲最低的 10 條路線和系統預設的路線交錯測速 3 輪（GitHub 用 release 檔、Twitch 用網頁程式檔）。塞住的路線通常一開始就卡在 1 Mbps 左右，所以看的是「順暢的次數」，不是單次最高速度（「順暢」＝達到該次最快速度的 30% 以上，且至少 3 Mbps）
3. X 圖片太小，測不出速度，所以沿用同一條路線的 GitHub 測速結果。不過 X 並不是每個機房都有部署，所以只採用「X 實際出貨的機房跟該路線一致」的路線

只使用 Python 標準函式庫，沒有任何第三方套件。

## 授權

[MIT License](LICENSE)
