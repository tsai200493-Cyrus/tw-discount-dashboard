# 打折窗口溫度計 🌡️

一個**自動更新**的台股個人儀表板：把「個股估值便宜度 × 基本面動能 × 大盤恐慌度」合成一個「窗口溫度」，
告訴你現在是**便宜＋恐慌（適合備子彈獵折扣）**還是**貴＋貪婪（該收手）**。

> ⚠️ 這是**溫度計、不是買賣訊號**。沒有模型能可靠擇時，它只給情境傾向。**非投資建議，決策與風險自負。**

資料來源：FinMind（純讀取）。網站是靜態的，資料由 GitHub Action 排程重跑、自動更新。

---

## 我要加/刪追蹤的股票怎麼做？（最常用）

改 **`watchlist.txt`** 就好，一行一檔：

```
2454  # 聯發科
```

- **電腦**：改完 `git push`。
- **手機**：直接在 GitHub 網頁打開 `watchlist.txt` → 鉛筆編輯 → Commit。

一 commit 就會**自動觸發** Action 重算，網站幾分鐘後更新，重新整理就看到。

---

## 第一次設定（一次就好）

1. **建一個 repo**（建議 **public**，免費 Pages 用；裡面沒有機密，token 走 Secret 不進程式碼）。
2. 把這整個資料夾 push 上去（`git init` → add → commit → `git remote add` → push）。
3. **加 FinMind Token**（避免排程被限流）：
   - 免費註冊 <https://finmindtrade.com/> 拿 token。
   - repo → **Settings → Secrets and variables → Actions → New repository secret**
   - Name 填 `FINMIND_TOKEN`，Value 貼你的 token。
4. **開啟 GitHub Pages**：
   - repo → **Settings → Pages** → Source 選 **Deploy from a branch** → Branch `main`、資料夾 **`/docs`** → Save。
   - 幾分鐘後網址是 `https://你的帳號.github.io/repo名稱/`，手機打開就能看。
5. （可選）到 **Actions** 頁面按一次 **Run workflow**，馬上產一份最新資料。

---

## 本機預覽

`docs/index.html` 用 `fetch` 讀同資料夾的 `data.json`，**不能直接雙擊開**（瀏覽器擋 file://）。要本機看：

```bash
cd docs
python -m http.server 8000
# 瀏覽器開 http://localhost:8000
```

手動重算資料：`python scripts/build_data.py`（本機沒設 token 也能跑，只是有流量上限）。

---

## 檔案結構

```
watchlist.txt                 ← 你唯一要改的檔（加/刪股票）
scripts/build_data.py         ← 抓 FinMind + 算分數 → 產生 docs/data.json
docs/index.html               ← 儀表板（讀 data.json）
docs/data.json                ← 產出資料（Action 自動更新，不用手改）
.github/workflows/update.yml  ← 排程：每交易日收盤後 + 你改 watchlist 時 + 手動
```

---

## ⚠️ 同步提醒（重要）

`scripts/build_data.py` 是本機 skill `tw-value-investing`（`fetch_*` / `discount_window.py`）的**獨立複本**，
因為 Action 在雲端跑、碰不到你電腦 `~/.claude` 的 skill。

- **前提**：兩邊算法要一致，網站分數才等於你本機工具的分數。
- **已知代價**：skill 改了算法，這支**不會自動跟上**，要**手動把改動同步過來**。
- **排錯線索**：若哪天網站分數跟本機 skill 對不上，先懷疑這裡是舊版、需要同步。
