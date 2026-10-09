# fastly-hosts

自動找出最順的 Fastly 路線，加速 **GitHub 下載**與 **X（Twitter）圖片**。支援 Windows 與 Linux，用數字選單操作，不用打指令。

## 為什麼需要它

GitHub 的 release 下載檔、raw 檔案，還有 X 的圖片，都是透過 CDN 公司 Fastly 在世界各地的機房傳給你。網路業者會自動幫你選一個機房，但選到的路線不一定順。

例如中華電信（HiNet）的實測結果：

| 路線 | 晚上尖峰時段的下載狀況 |
|---|---|
| 系統預設：新加坡（SIN） | 幾乎每次都卡在 1 Mbps 以下 |
| 本工具找到的路線：首爾（ICN） | 每次都跑滿線路 |

這個工具會：

1. 找出你附近所有能用的 Fastly 機房（約 1 分鐘）
2. 實際下載測試好幾輪，看哪條路線最穩（約 2 分鐘）
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
  1. 測試      找出目前最順的路線，只測試、不改設定（約 3 分鐘）
  2. 套用      測試後，把最順的路線設定到電腦上（需要管理員權限）
  3. 還原      移除本工具的設定，回到原本的狀態
  4. 重新整理  重新檢查目前狀況
  5. 說明      這個工具在做什麼
  0. 離開
```

選「套用」時會跳出系統管理員權限的確認視窗，按「是」即可。

### Linux

需要 Python 3.8 以上（Ubuntu 等發行版通常已內建）。

```sh
git clone https://github.com/AFAlimru/fastly-hosts.git
cd fastly-hosts
sh linux/install.sh
```

之後桌面和應用程式選單會出現 **fastly-hosts** 圖示，雙擊就會開啟同樣的選單。選「套用」或「還原」時，會在同一個視窗詢問你的登入密碼（sudo）。

也可以直接執行：`python3 fastly_hosts.py`

## 常見問題

**會改到我電腦的什麼？**
只會在 hosts 檔（Windows：`C:\Windows\System32\drivers\etc\hosts`，Linux：`/etc/hosts`）加上一小段有標記的設定，影響的網域只有：

- `release-assets.githubusercontent.com`
- `raw.githubusercontent.com`
- `pbs.twimg.com`

「還原」會把這段完整移除，原本的內容不會動。第一次修改前，會自動把原檔備份成 `hosts.fastly-hosts.bak`。

**測試會用掉多少流量？**
每次約 300 MB（測速時只下載檔案開頭幾 MB，不會存檔）。

**什麼時候要重新套用？**
覺得 GitHub 下載又變慢的時候。換到其他網路（例如筆電帶出門）覺得變慢，先「還原」。

**為什麼要管理員權限？**
hosts 檔是系統檔案，只有管理員 / root 能修改。「測試」不需要權限。

**防毒軟體跳出警告？**
有些防毒軟體會把「修改 hosts」視為可疑行為。程式碼全部公開在這個 repo，可以自行檢查。

**只支援中華電信嗎？**
任何網路都可以用，程式會針對你目前的網路實測。不過目前只在中華電信上實際驗證過效果。

## 自己打包 Windows exe

- 在 Windows 上：安裝 Python 後，執行 `build\build-windows.bat`
- 在 Linux 上（透過 Wine）：`sudo apt install wine` 後執行 `sh build/build-windows-wine.sh`

## 原理

GitHub 和 X 的檔案都放在 Fastly 上，而 Fastly 有一部分 IP 段會固定連到特定機房。程式會：

1. 從 [Fastly 官方 IP 清單](https://api.fastly.com/public-ip-list)取得所有 IP 段，每段挑一個 IP，用 GitHub 的網域連線，確認能正常提供內容，並記錄機房與延遲
2. 對延遲最低的 10 條路線和系統預設的路線交錯測速 3 輪。塞住的路線通常一開始就卡在 1 Mbps 左右，所以看的是「順暢的次數」，不是單次最高速度
3. X 圖片太小，測不出速度，所以沿用同一條路線的 GitHub 測速結果。不過 X 並不是每個機房都有部署，所以只採用「X 實際出貨的機房跟該路線一致」的路線

只使用 Python 標準函式庫，沒有任何第三方套件。

## 授權

[MIT License](LICENSE)
