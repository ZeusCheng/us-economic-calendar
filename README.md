# 美國重要經濟數據行事曆（Apple Calendar 訂閱用）

這個專案會用 GitHub Actions 每天自動抓官方資料，產生 `docs/us-economic-calendar.ics`。
你可以把 GitHub Pages 的 `.ics` 網址加入 Apple 行事曆訂閱，之後資料更新時 Apple 裝置會跟著更新。

## 會抓哪些資料

預設包含交易常看的美國高影響數據：

- BLS：CPI、PPI、Employment Situation / NFP、JOLTS、Productivity and Costs
- BEA：GDP、Personal Income and Outlays / PCE、International Trade
- Census：Retail Sales、Durable Goods、Housing Starts、New Home Sales、Construction Spending、Advance Economic Indicators
- Federal Reserve：FOMC 利率決議 / Statement

每個事件都有 60 分鐘與 30 分鐘前提醒。

## 安裝方式

### 1. 建立 GitHub repo

建立一個新的 GitHub repository，例如：

`us-economic-calendar`

建議設為 Public，GitHub Pages 最省事。

### 2. 上傳這些檔案

把本專案所有檔案放進 repo 根目錄，commit 到 `main`。

### 3. 先手動跑一次 GitHub Actions

到 GitHub repo：

`Actions` → `Update US Economic Calendar ICS` → `Run workflow`

跑完後應該會產生或更新：

`docs/us-economic-calendar.ics`

### 4. 開 GitHub Pages

到 GitHub repo：

`Settings` → `Pages` → `Build and deployment` → `Deploy from a branch`

選：

- Branch：`main`
- Folder：`/docs`

儲存後等待 GitHub Pages 發布。

### 5. Apple 行事曆訂閱網址

假設你的 GitHub 帳號是：

`YOUR_GITHUB_USERNAME`

repo 名稱是：

`us-economic-calendar`

你的 ICS 網址會是：

```text
https://YOUR_GITHUB_USERNAME.github.io/us-economic-calendar/us-economic-calendar.ics
```

Apple Calendar 通常可用：

```text
webcal://YOUR_GITHUB_USERNAME.github.io/us-economic-calendar/us-economic-calendar.ics
```

## iPhone / iPad 加入方式

`設定` → `行事曆` → `帳號` → `加入帳號` → `其他` → `加入已訂閱的行事曆`

貼上 `webcal://...` 網址。

## Mac 加入方式

`行事曆 App` → `檔案` → `新增行事曆訂閱`

貼上 `webcal://...` 網址。

建議 Location 選 iCloud，這樣會同步到同 Apple ID 的裝置。

## 自訂項目

想新增或刪除某些數據，到 `scripts/generate_calendar.py` 修改：

- `BLS_KEEP`
- `BEA_KEEP`
- `CENSUS_KEEP`

例如不想看 JOLTS，就把 `Job Openings and Labor Turnover Survey` 刪掉。

## 注意事項

- 這是「訂閱型唯讀行事曆」，不是手動匯入。不要用 Import，不然只會複製一次，不會更新。
- FOMC 官方頁面主要公布會議日期；本專案把決議時間設為常見的美東 14:00。遇到特殊年份或 Fed 改時間時，請以官方公告為準。
- 官方資料頁面若改版，爬蟲可能需要更新。
