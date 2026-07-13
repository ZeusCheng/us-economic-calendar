v3.3：Fair Economy 全球 ICS → 美國 USD 過濾版

覆蓋：
- scripts/generate_calendar.py
- .github/workflows/update-calendar.yml
- requirements.txt

新增主要來源：
- https://nfs.faireconomy.media/ff_calendar_thisweek.ics
- https://nfs.faireconomy.media/ff_calendar_nextweek.ics

處理方式：
1. 下載全球 ICS。
2. 從 SUMMARY / DESCRIPTION / CATEGORIES / LOCATION 等欄位辨識 USD、
   United States 或 U.S.。
3. 只保留美國事件。
4. 再依白名單只保留 CPI、PPI、PCE、NFP、GDP、FOMC、零售銷售、
   ISM、JOLTS、ADP、初領失業金、耐久財與重要房市／信心數據。
5. 低重要性事件排除。
6. XML 仍用來補 Forecast / Previous / Actual。
7. FRED、Fed、BEA、Census 與舊 ICS 保留機制繼續當備援。

更新頻率：
- 每 6 小時，台灣時間約 02:35、08:35、14:35、20:35。

驗證 Log：
- Fair Economy ICS feeds fetched
- Fair Economy ICS matched USD events
- CPI / PPI / NFP 等事件數量

注意：
- 請勿把全球版 ICS 直接訂閱到 Apple 行事曆。
- 正式訂閱仍使用你 GitHub Pages 的 us-economic-calendar.ics。
