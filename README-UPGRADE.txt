# v3 Forex Factory upgrade

覆蓋以下檔案：

- `scripts/generate_calendar.py`
- `.github/workflows/update-calendar.yml`
- `requirements.txt`

不要刪除 `docs/`。新版會讀取既有 ICS，保留尚未過期的中長期事件，
並每天以 Forex Factory current-week / next-week XML 更新近期事件。

重要改動：

- 不再連線 BLS，因此不受 BLS 對 GitHub Actions 的 403 封鎖影響。
- Forex Factory 提供近期 Impact、Forecast、Previous、Actual。
- BEA、Census、Federal Reserve 仍作為官方中長期排程來源。
- 驗證不再錯誤要求每週都必須出現 CPI、PPI、NFP。
