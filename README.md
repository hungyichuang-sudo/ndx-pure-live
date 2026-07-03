# ndx-pure-live — 純 radj-150 Top-3 即時儀表板

凍結歷史(Sharadar PIT 2013-01→2026-06, 三重驗證) + 即時延伸(yfinance, 決策即時記錄=PIT)。
每交易日 22:20 UTC 自動:更新當前 Top-3/本月至今 → 月底翻月後自動記錄換倉決策、
把完成月份接上曲線、重算 CAGR/日頻MDD/月度bar/交易表/MC。

## 部署(5 步)
1. 建 Public repo(例 ndx-pure-live),把本資料夾全部內容 push 上去
2. Settings → Pages → Source = GitHub Actions
3. Settings → Actions → General → Workflow permissions = Read and write ←最常漏
4. Actions → update-dashboard → Run workflow(手動跑第一次)
5. 開 https://<帳號>.github.io/ndx-pure-live/

## 慣例(與 VPS 回測一致)
月底收盤形成 Top-3(無cap)→次月持有;20bps 往返×換手率,月底吸收;
2×=月底重設、IBKR 融資 6.5%/yr 假設(僅借款計息)。MC: block=3 / 36月 / 20k / seed 42 / 障壁 −45%。

## 已知界線(誠實列)
- 2026-06/07 是資料接縫:之前 Sharadar(含下市股),之後 yfinance。兩源還原價微差可能存在。
- 凍結段曲線為週取樣顯示;日頻 MDD 統計(−44.3%/−68.7%)來自 VPS 日頻回測,延伸段為真日頻追蹤。
- MC 與 VPS 原版同法但 RNG 實作差 ±1pp 級(首日對照:腰斬 15.7% vs 14.6%)。
- yfinance 偶發限流:workflow 內建重試,失敗則保留舊頁,隔日自動補跑(決策 append-only 不會漏月)。

## 成分股自動更新(每次執行)
三層保險: Wikipedia Nasdaq-100 成分表(主源, 免金鑰) → FMP API(備援, 選配:
repo Settings→Secrets→Actions 加 FMP_API_KEY) → 都失敗則沿用上次快取(頁面會標示)。
護欄: 抓到的檔數必須在 95~110 之間才接受。成分變動自動記日期入 live.json(保 PIT)。
叢集判定: 產業子分類含 "semiconductor" 自動標記(新進半導體自動抓到);
記憶體/儲存(WDC/STX/SNDK)維持手動 HARD_SEMI 名單 —— 因為 ICB/GICS 把 AAPL
和硬碟廠放同一子分類, 用 storage 關鍵字會把蘋果誤標成叢集。若未來有純儲存新股
入指數, 手動加進 compute.py 的 HARD_SEMI(罕見; 變動記錄會提醒你)。
已知界線: Wikipedia 對指數換股的更新通常快但可能滯後數小時~數天;
罕見的多日補跑情境下, 補記的舊決策會用補跑當日的成分清單(誤差極小, 誠實揭露)。

## 系統狀態面板(頁面頂部)
- 資料更新燈:由「你的瀏覽器」即時計算 —— 就算後端整個掛掉、live.json 停在舊資料,
  頁面自己會變黃/紅,不會安靜地給你看過期數字。規則:>32h 黃(跨週末寬限)、再+24h 紅。
- 成分來源燈:ok=當次真的抓到(wikipedia/fmp);紅=抓取失敗沿用快取(顯示最後成功日+錯誤類型)。
- 成分變動:append-only 記錄含日期(PIT);無變動顯示基線日。
- 資料完整性:缺價股票列名;含 Sharadar→yfinance 接縫提示。

## 即時 K 線與近10年視窗
- K 線=嵌入 TradingView(第三方免費源):盤中即時或最多延遲 ~15 分鐘,依其供應而定;
  符號每天自動跟隨本月持倉;元件載入失敗時顯示直連備援連結。這是靜態頁做到「即時」
  唯一務實的方式 —— 自建即時報價服務超出 GitHub Pages 能力範圍。
- 資金曲線「近10年」:視窗每日自動前滾,起點資金重設為 1(顯示的是「近10年把 1 變成幾倍」);
  「全期」則維持 2013 起點的絕對倍數。v1 部署版有個已修正的 bug:近10年按鈕實際只畫近1年。
- 圖表互動:滑鼠/手指移到圖上即顯示該日數值(不需精準壓線)+虛線十字定位,三張圖皆適用。

## radj-150 公式
頁面「八項總結」內含完整公式與白話拆解(分子/分母/A-B 對照/實作坑/誠實註記)。
凍結曲線末點標籤已於顯示層校正為 2026-06-30(VPS 週取樣標籤偏移 3 個交易日,值正確、統計不受影響)。

## 其他慣例
- GOOGL/GOOG 同發行人去重(取 radj 高者)。歷史月份已凍結, 成分更新不影響過去。
