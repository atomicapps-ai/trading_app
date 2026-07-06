/* chart_tools.js — shared chart panel + indicator helper.
 *
 * Used by:
 *   /universe/{name}/edit   — ticker chips → source picker → floating panel
 *   /pending                 — inline dual chart with toggle chips
 *
 * Design note: every overlay & sub-pane series the chart renders comes
 * from /api/indicators/{symbol}, which is itself a thin wrapper over
 * services/indicator_service.py. That keeps the agents and the chart
 * UI looking at the **same numbers** — the chart can never disagree
 * with what compliance/risk/portfolio agents are computing internally.
 *
 * Public API:
 *   ChartTools.INDICATORS              — catalog of supported indicators
 *   ChartTools.FILTER_INDICATOR_MAP    — Finviz filter → indicator IDs
 *   ChartTools.filtersToIndicators(f)  — derive default-on indicator set
 *                                        from a screener's filters dict
 *   ChartTools.renderChart(el, opts)   — render a chart inside `el`
 *                                        and return a control instance
 *   ChartTools.openSourcePopover(chip, ctxOpts)
 *                                       — show 4-source popover near chip,
 *                                        spawn a floating panel on pick
 *   ChartTools.bindTickerChips(root, ctxOpts)
 *                                       — delegate-bind .ticker-chip clicks
 *   ChartTools.createFloatingPanel(opts)
 *                                       — open a draggable/resizable panel
 *   ChartTools.closePanel(panel)        — destroy a panel + its chart
 *
 * Requires: lightweight-charts (loaded via <script> on the host page).
 */
(function () {
  'use strict';
  if (window.ChartTools) return;  // idempotent

  // ── Indicator catalog ───────────────────────────────────────────────
  // Each indicator has a stable `id` (sent to /api/indicators), a
  // human label (chip text), a kind ('overlay' = on price chart;
  // 'subpane' = stacked below), and a brand color.
  const INDICATORS = [
    { id: 'sma20',  label: 'SMA20',   kind: 'overlay', color: '#f59e0b' },
    { id: 'sma50',  label: 'SMA50',   kind: 'overlay', color: '#a855f7' },
    { id: 'sma200', label: 'SMA200',  kind: 'overlay', color: '#ef4444' },
    { id: 'ema20',  label: 'EMA20',   kind: 'overlay', color: '#22d3ee' },
    { id: 'bb',     label: 'BB',      kind: 'overlay', color: '#94a3b8' },
    { id: 'vwap',   label: 'VWAP',    kind: 'overlay', color: '#4a9eff' },
    { id: 'hl20',   label: 'H/L 20',  kind: 'overlay', color: '#34d399' },
    { id: 'hl50',   label: 'H/L 50',  kind: 'overlay', color: '#10b981' },
    { id: 'hl52w',  label: 'H/L 52w', kind: 'overlay', color: '#059669' },
    { id: 'rsi',    label: 'RSI',     kind: 'subpane', color: '#a78bfa' },
    { id: 'macd',   label: 'MACD',    kind: 'subpane', color: '#fb923c' },
    { id: 'atr',    label: 'ATR',     kind: 'subpane', color: '#f87171' },
    { id: 'volume', label: 'Vol',     kind: 'subpane', color: '#64748b' },
  ];
  const IND_BY_ID = INDICATORS.reduce((m, i) => { m[i.id] = i; return m; }, {});

  // Mapping of Finviz filter IDs → indicator IDs to auto-activate.
  // When a chart opens for a ticker that came from a screener whose
  // filters include `ta_sma50`, we light up the SMA50 overlay so the
  // chart visually represents what the screener tested for.
  const FILTER_INDICATOR_MAP = {
    ta_sma20:           ['sma20'],
    ta_sma50:           ['sma50'],
    ta_sma200:          ['sma200'],
    ta_highlow20d:      ['hl20'],
    ta_highlow50d:      ['hl50'],
    ta_highlow52w:      ['hl52w'],
    ta_rsi:             ['rsi'],
    ta_averagetruerange:['atr'],
  };

  function filtersToIndicators(filters) {
    const set = new Set();
    if (!filters || typeof filters !== 'object') return [];
    Object.keys(filters).forEach(k => {
      const list = FILTER_INDICATOR_MAP[k];
      if (list) list.forEach(i => set.add(i));
    });
    return [...set];
  }

  // ── One-time CSS injection ──────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById('chart-tools-styles')) return;
    const css = `
.ct-chart-root{display:flex;flex-direction:column;width:100%;height:100%;
  background:var(--bg-base);color:var(--text-primary);overflow:hidden;}
.ct-chart-head{display:flex;align-items:center;flex-wrap:wrap;gap:8px;
  padding:6px 8px;background:var(--bg-stat);border-bottom:1px solid var(--border);
  flex:0 0 auto;min-height:32px;}
.ct-tfs{display:flex;gap:2px;flex:0 0 auto;}
.ct-tf{padding:3px 9px;border:1px solid var(--border);border-radius:4px;
  background:var(--surface-2);color:var(--text-secondary);
  font-size:11px;font-weight:500;cursor:pointer;font-family:var(--font-mono);}
.ct-tf:hover{background:var(--surface-3);color:var(--text-primary);}
.ct-tf.active{background:var(--accent-blue);border-color:var(--accent-blue);color:#fff;}
.ct-chips{display:flex;gap:3px;flex-wrap:wrap;flex:1 1 auto;justify-content:flex-end;}
.ct-chip{padding:3px 8px;border:1px solid var(--border);border-radius:10px;
  background:var(--surface-2);color:var(--text-tertiary);
  font-size:10px;font-weight:600;cursor:pointer;letter-spacing:.02em;
  transition:all .12s;}
.ct-chip:hover{color:var(--text-primary);border-color:var(--text-tertiary);}
.ct-chip.active{background:var(--chip-color,var(--accent-blue));
  border-color:var(--chip-color,var(--accent-blue));color:#fff;}
.ct-chart-body{flex:1 1 auto;display:flex;flex-direction:column;min-height:0;
  position:relative;}
.ct-pane{position:relative;min-height:30px;flex:0 0 auto;}
.ct-pane-price{flex:1 1 auto;}
/* Vertical event bars (Found / EP / exit) + top label chip. */
.ct-vlines{position:absolute;inset:0;overflow:hidden;pointer-events:none;z-index:4;}
.ct-vline{position:absolute;top:0;bottom:0;width:2px;margin-left:-1px;opacity:0.5;}
.ct-vmark{position:absolute;top:3px;transform:translateX(-50%);z-index:5;
  font-size:9px;font-weight:700;line-height:1;color:#0b0d13;
  padding:2px 6px;border-radius:4px;white-space:nowrap;
  box-shadow:0 1px 3px rgba(0,0,0,0.4);}
/* Shaded valid window (Valid → first-invalidation). */
.ct-vshade{position:absolute;top:0;bottom:0;z-index:3;pointer-events:none;
  background:rgba(34,197,94,0.10);border-left:0;border-right:0;}
.chart-legend{display:flex;flex-wrap:wrap;gap:14px;align-items:center;
  padding:6px 2px;font-size:11px;color:var(--text-secondary,#8b90a0);}
.chart-legend .leg-item{display:inline-flex;align-items:center;gap:5px;cursor:default;}
.chart-legend .leg-dot{width:9px;height:9px;border-radius:50%;display:inline-block;}
.ct-pane-sub{border-top:1px solid var(--border);}
.ct-sub-label{position:absolute;top:4px;left:8px;z-index:5;
  font-size:10px;font-weight:600;color:var(--text-tertiary);
  letter-spacing:.05em;text-transform:uppercase;pointer-events:none;}
.ct-sub-chart{width:100%;height:100%;}
.ct-error{padding:20px;color:var(--accent-red);font-size:12px;}
.ct-loading{padding:20px;color:var(--text-tertiary);font-size:12px;}

/* ── Source picker popover ──────────────────────────────────────── */
.ct-src-popover{position:fixed;z-index:920;background:var(--surface-1);
  border:1px solid var(--border);border-radius:8px;
  box-shadow:0 8px 22px rgba(0,0,0,.55);padding:6px;min-width:280px;
  display:flex;flex-direction:column;gap:4px;}
.ct-src-row{display:flex;align-items:center;gap:6px;padding:4px 6px;}
.ct-src-row .ct-src-name{font-size:11px;color:var(--text-secondary);
  flex:0 0 80px;font-weight:500;}
.ct-src-row .ct-src-tfs{display:flex;gap:3px;flex:1 1 auto;justify-content:flex-end;}
.ct-src-row .ct-src-btn{padding:3px 9px;border:1px solid var(--border);
  border-radius:4px;background:var(--surface-2);color:var(--text-primary);
  font-size:11px;cursor:pointer;font-family:var(--font-mono);font-weight:500;}
.ct-src-row .ct-src-btn:hover{background:var(--accent-blue);
  border-color:var(--accent-blue);color:#fff;}
.ct-src-row .ct-src-link{padding:3px 10px;border-radius:4px;
  background:var(--accent-blue);color:#fff;font-size:11px;
  text-decoration:none;font-weight:500;}
.ct-src-row .ct-src-link:hover{background:var(--accent-blue);opacity:.85;}
.ct-src-symbol{padding:6px 10px 4px;font-size:11px;color:var(--text-tertiary);
  font-family:var(--font-mono);border-bottom:1px solid var(--border);
  margin-bottom:4px;}

/* ── Floating panel wrapping the chart ──────────────────────────── */
.chart-panel.ct-floating{position:fixed;z-index:850;background:var(--surface-1);
  border:1px solid var(--border);border-radius:8px;
  box-shadow:0 8px 28px rgba(0,0,0,.5);
  display:flex;flex-direction:column;overflow:hidden;
  min-width:360px;min-height:280px;}
.chart-panel .cp-head{display:flex;align-items:center;justify-content:space-between;
  padding:6px 10px;background:var(--surface-3);
  border-bottom:1px solid var(--border);cursor:move;user-select:none;
  font-size:12px;flex:0 0 auto;}
.chart-panel .cp-title{font-weight:600;color:var(--text-primary);}
.chart-panel .cp-tf{color:var(--text-tertiary);font-size:11px;margin-left:6px;
  font-family:var(--font-mono);}
.chart-panel .cp-source{color:var(--accent-blue);font-size:10px;margin-left:8px;
  text-transform:uppercase;letter-spacing:.05em;font-weight:600;}
.chart-panel .cp-actions{display:flex;gap:4px;}
.chart-panel .cp-btn{background:none;border:none;color:var(--text-tertiary);
  cursor:pointer;font-size:14px;padding:2px 6px;border-radius:3px;}
.chart-panel .cp-btn:hover{background:var(--surface-2);color:var(--text-primary);}
.chart-panel .cp-btn.close:hover{color:var(--accent-red);}
.chart-panel .cp-body{flex:1 1 auto;position:relative;background:var(--bg-base);
  min-height:0;overflow:hidden;}
.chart-panel .cp-resize{position:absolute;right:0;bottom:0;width:14px;height:14px;
  cursor:nwse-resize;z-index:10;
  background:linear-gradient(135deg,transparent 50%,var(--text-tertiary) 50%);
  opacity:.4;border-bottom-right-radius:8px;}
.chart-panel .cp-resize:hover{opacity:.9;}
.chart-panel.pinned{border-color:var(--accent-blue);}
.chart-panel.pinned .cp-btn.pin{color:var(--accent-blue);}

.ct-finviz-wrap{padding:10px;background:#fff;height:100%;overflow:auto;
  display:flex;flex-direction:column;align-items:center;}
.ct-finviz-wrap img{max-width:100%;border-radius:4px;}
.ct-finviz-foot{margin-top:8px;font-size:11px;color:var(--text-tertiary);
  text-align:center;background:var(--surface-1);width:100%;padding:6px;}
.ct-finviz-foot a{color:var(--accent-blue);text-decoration:none;}
.ct-finviz-foot a:hover{text-decoration:underline;}
`;
    const tag = document.createElement('style');
    tag.id = 'chart-tools-styles';
    tag.textContent = css;
    document.head.appendChild(tag);
  }

  // ── Chart instance ──────────────────────────────────────────────────
  // Single class drives the inline chart pane. Holds:
  //   • The price chart (always present, candles).
  //   • Zero-or-more sub-pane charts, one per active sub-pane indicator,
  //     time-axis-synced to the price chart bidirectionally.
  //   • The full bars array, exposed as `inst.bars` for callers that
  //     want to do their own dblclick/lazy-load on top.
  //
  // Public methods (kept stable for /pending consumption):
  //   inst.priceChart, inst.priceSeries
  //   inst.bars
  //   inst.setData(bars), inst.prependBars(older)
  //   inst.setInterval(iv), inst.toggleIndicator(id)
  //   inst.refreshIndicators(), inst.destroy()
  //   inst.addPriceLine({price, color, lineStyle, title}) → priceLine
  class ChartInstance {
    constructor(container, opts) {
      this.container = container;
      this.opts = opts || {};
      this.symbol = String(this.opts.symbol || '').toUpperCase();
      this.interval = this.opts.interval || '1d';
      // Indicators: union of explicit defaults from caller + any saved
      // from localStorage. Filter-aware activation lives in the caller.
      const defaults = new Set(this.opts.indicators || []);
      this.activeIndicators = defaults;
      this.persistKey = this.opts.persistKey || null;
      this._loadPrefs(defaults);
      this.bars = [];
      this.subPanes = {};       // id → {chart, wrap, chartEl, seriesList}
      this.overlaySeries = {};  // id → ISeries[] (for removal on toggle off)
      // Caller-added IPriceLine handles (entry/stop/TP). Lightweight
      // Charts price lines persist across setData(), so we only need
      // to re-create them when the user changes timeframe (which
      // currently only re-runs setData on the same series — they
      // survive). Tracked here mainly so destroy() can remove them.
      this._extraPriceLines = [];
      // Trade markers (discovery + EP/TP/SL hits). null = none.
      this.tradeMarkers = this.opts.tradeMarkers || null;
      this._vlineWrap = null;   // overlay holding the vertical event bars
      this._vlines = [];
      this._vshade = null;      // shaded valid-window rectangle (window mode)
      injectStyles();
      this._buildShell();
      this.loadData();
    }

    _loadPrefs(defaults) {
      if (!this.persistKey) return;
      try {
        const raw = localStorage.getItem('chart.indicators.' + this.persistKey);
        if (!raw) return;
        const stored = JSON.parse(raw);
        if (Array.isArray(stored)) {
          // Saved prefs supersede defaults — user-driven state wins.
          this.activeIndicators = new Set(stored);
        }
      } catch (_) { /* ignore corrupt prefs */ }
    }

    _savePrefs() {
      if (!this.persistKey) return;
      try {
        localStorage.setItem(
          'chart.indicators.' + this.persistKey,
          JSON.stringify([...this.activeIndicators])
        );
      } catch (_) { /* ignore quota */ }
    }

    _buildShell() {
      this.container.classList.add('ct-chart-root');
      this.container.innerHTML = '';

      // Header bar
      const head = document.createElement('div');
      head.className = 'ct-chart-head';
      this.container.appendChild(head);

      if (this.opts.showTimeframes !== false) {
        const tfWrap = document.createElement('div');
        tfWrap.className = 'ct-tfs';
        ['1h', '2h', '4h', '1d'].forEach(iv => {
          const b = document.createElement('button');
          b.className = 'ct-tf' + (iv === this.interval ? ' active' : '');
          b.textContent = iv.toUpperCase();
          b.dataset.iv = iv;
          b.addEventListener('click', () => this.setInterval(iv));
          tfWrap.appendChild(b);
        });
        head.appendChild(tfWrap);
      }

      if (this.opts.showChips !== false) {
        const chipWrap = document.createElement('div');
        chipWrap.className = 'ct-chips';
        INDICATORS.forEach(ind => {
          const c = document.createElement('button');
          c.className = 'ct-chip' + (this.activeIndicators.has(ind.id) ? ' active' : '');
          c.style.setProperty('--chip-color', ind.color);
          c.dataset.id = ind.id;
          c.dataset.kind = ind.kind;
          c.title = `${ind.label} — toggle ${ind.kind === 'subpane' ? 'sub-pane' : 'overlay'}`;
          c.textContent = ind.label;
          c.addEventListener('click', () => this.toggleIndicator(ind.id));
          chipWrap.appendChild(c);
        });
        head.appendChild(chipWrap);
      }

      // Body container
      const body = document.createElement('div');
      body.className = 'ct-chart-body';
      this.container.appendChild(body);
      this.body = body;

      // Main price pane
      const priceWrap = document.createElement('div');
      priceWrap.className = 'ct-pane ct-pane-price';
      body.appendChild(priceWrap);
      this.priceWrap = priceWrap;

      const chart = LightweightCharts.createChart(priceWrap, this._chartOpts(true));
      const _CC = (window.CHART_COLORS || {});
      const series = chart.addCandlestickSeries({
        upColor: '#1db87a', downColor: '#e05252',
        borderUpColor: '#1db87a', borderDownColor: '#e05252',
        wickUpColor: '#1db87a', wickDownColor: '#e05252',
        // Current-price line — bright pink by default (Settings → Chart colors)
        // so it never blends into the green take-profit lines.
        priceLineVisible: true,
        lastValueVisible: true,
        priceLineColor: _CC.current_price || '#ff2e97',
        priceLineStyle: 0,   // solid
        priceLineWidth: 1,
      });
      this.priceChart = chart;
      this.priceSeries = series;

      // Overlay layer for vertical event bars (Found / EP / exit). Kept in sync
      // with the time scale so bars track their candle as you pan/zoom.
      const vlw = document.createElement('div');
      vlw.className = 'ct-vlines';
      priceWrap.appendChild(vlw);
      this._vlineWrap = vlw;
      chart.timeScale().subscribeVisibleLogicalRangeChange(() => this._positionVlines());

      // Build any sub-panes for sub-pane indicators that started active
      INDICATORS.filter(i => i.kind === 'subpane' && this.activeIndicators.has(i.id))
        .forEach(i => this._buildSubPane(i.id));

      // Body resize observer
      this._ro = new ResizeObserver(() => this._resize());
      this._ro.observe(body);
      // Run an initial resize after the body has flexed into its final box.
      requestAnimationFrame(() => this._resize());
    }

    _chartOpts(isPrice) {
      const intraday = this.interval !== '1d';
      return {
        layout:           { background: { color: '#0f1117' }, textColor: '#8b8fa8' },
        grid:             { vertLines: { color: '#1a1d27' }, horzLines: { color: '#1a1d27' } },
        timeScale:        { borderColor: '#2a2d37', timeVisible: intraday,
                            secondsVisible: false, visible: !!isPrice },
        rightPriceScale:  { borderColor: '#2a2d37', minimumWidth: 60 },
        crosshair:        { mode: LightweightCharts.CrosshairMode.Normal },
        autoSize:         false,
        handleScale:      true,
        handleScroll:     true,
      };
    }

    _resize() {
      if (!this.body) return;
      const totalH = this.body.clientHeight;
      const w = this.body.clientWidth;
      if (totalH <= 0 || w <= 0) return;
      const subIds = Object.keys(this.subPanes);
      const subCount = subIds.length;
      // Sub-panes share 35% of the body, divided evenly. With no
      // sub-panes the price chart fills 100%.
      const subTotal = subCount > 0 ? Math.max(80 * subCount, totalH * 0.35) : 0;
      const mainH = Math.max(120, totalH - subTotal);
      const subH = subCount > 0 ? Math.max(60, (totalH - mainH) / subCount) : 0;
      this.priceWrap.style.height = mainH + 'px';
      this.priceChart.applyOptions({ width: w, height: mainH });
      subIds.forEach(id => {
        const sp = this.subPanes[id];
        sp.wrap.style.height = subH + 'px';
        sp.chart.applyOptions({ width: w, height: subH });
      });
      this._positionVlines();
    }

    async loadData() {
      const limit = this.opts.limit || (this.interval === '1d' ? 365 : 300);
      try {
        const r = await fetch(
          `/api/bars/${this.symbol}?interval=${this.interval}&limit=${limit}`
        );
        if (!r.ok) {
          this._showError(`Bars failed: HTTP ${r.status}`);
          return;
        }
        const data = await r.json();
        const bars = (data.bars || []).map(b => ({
          time: b.time, open: b.open, high: b.high,
          low: b.low, close: b.close, volume: b.volume,
        }));
        if (!bars.length) {
          this._showError(`No bars for ${this.symbol}.`);
          return;
        }
        this.bars = bars;
        this.priceSeries.setData(bars.map(b => ({
          time: b.time, open: b.open, high: b.high,
          low: b.low, close: b.close,
        })));
        // Note: price lines on a series persist across setData() — no
        // need to re-create them after every reload.
        this.priceChart.timeScale().fitContent();
        this._applyTradeMarkers();
        await this.refreshIndicators();
      } catch (err) {
        this._showError('Load failed: ' + err);
      }
    }

    // Refresh ALL indicator series (overlays + sub-panes). Called after
    // (a) initial load, (b) any toggle, (c) any interval change.
    async refreshIndicators() {
      // Tear down existing overlays first so we never leak series.
      Object.values(this.overlaySeries).forEach(arr => {
        arr.forEach(s => { try { this.priceChart.removeSeries(s); } catch (_) {} });
      });
      this.overlaySeries = {};
      Object.entries(this.subPanes).forEach(([id, sp]) => {
        if (sp.seriesList) {
          sp.seriesList.forEach(s => { try { sp.chart.removeSeries(s); } catch (_) {} });
          sp.seriesList = [];
        }
      });

      const ids = [...this.activeIndicators];
      if (!ids.length) return;

      const limit = this.opts.limit || (this.interval === '1d' ? 365 : 300);
      try {
        const r = await fetch(
          `/api/indicators/${this.symbol}?interval=${this.interval}` +
          `&indicators=${ids.join(',')}&limit=${limit}`
        );
        if (!r.ok) return;
        const data = await r.json();
        this._renderOverlays(data.indicators || {});
        Object.keys(this.subPanes).forEach(id => {
          this._renderSubPaneData(id, data.indicators || {});
        });
      } catch (err) {
        console.warn('indicators fetch failed', err);
      }
    }

    _renderOverlays(data) {
      const addLine = (id, dataKey, color, opts) => {
        opts = opts || {};
        if (!this.activeIndicators.has(id) || !data[dataKey]) return;
        const s = this.priceChart.addLineSeries({
          color,
          lineWidth: opts.lineWidth || 1.5,
          lineStyle: opts.lineStyle || 0,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        s.setData(data[dataKey]);
        if (!this.overlaySeries[id]) this.overlaySeries[id] = [];
        this.overlaySeries[id].push(s);
      };

      addLine('sma20',  'sma20',  IND_BY_ID.sma20.color);
      addLine('sma50',  'sma50',  IND_BY_ID.sma50.color);
      addLine('sma200', 'sma200', IND_BY_ID.sma200.color);
      addLine('ema20',  'ema20',  IND_BY_ID.ema20.color);
      addLine('vwap',   'vwap',   IND_BY_ID.vwap.color, { lineStyle: 2 });

      // Bollinger Bands: middle as solid, outer bands as dashed.
      if (this.activeIndicators.has('bb')) {
        addLine('bb', 'bb_upper',  IND_BY_ID.bb.color, { lineStyle: 2, lineWidth: 1 });
        addLine('bb', 'bb_middle', IND_BY_ID.bb.color, { lineStyle: 0, lineWidth: 1 });
        addLine('bb', 'bb_lower',  IND_BY_ID.bb.color, { lineStyle: 2, lineWidth: 1 });
      }
      // High/Low bands: dotted.
      ['hl20', 'hl50', 'hl52w'].forEach(id => {
        addLine(id, id + '_high', IND_BY_ID[id].color, { lineStyle: 1, lineWidth: 1 });
        addLine(id, id + '_low',  IND_BY_ID[id].color, { lineStyle: 1, lineWidth: 1 });
      });
    }

    _buildSubPane(id) {
      if (this.subPanes[id]) return;
      const wrap = document.createElement('div');
      wrap.className = 'ct-pane ct-pane-sub';
      wrap.dataset.id = id;
      const lbl = document.createElement('div');
      lbl.className = 'ct-sub-label';
      lbl.textContent = IND_BY_ID[id].label;
      wrap.appendChild(lbl);
      const chartEl = document.createElement('div');
      chartEl.className = 'ct-sub-chart';
      wrap.appendChild(chartEl);
      this.body.appendChild(wrap);

      const subChart = LightweightCharts.createChart(chartEl, this._chartOpts(false));
      this.subPanes[id] = { chart: subChart, wrap, chartEl, seriesList: [] };

      this._wireSubPaneSync(id);
    }

    _renderSubPaneData(id, indicators) {
      const sp = this.subPanes[id];
      if (!sp) return;
      const color = IND_BY_ID[id].color;
      const list = sp.seriesList;

      if (id === 'rsi' && indicators.rsi) {
        const s = sp.chart.addLineSeries({
          color, lineWidth: 1.5,
          priceLineVisible: false, lastValueVisible: true,
          crosshairMarkerVisible: false,
        });
        s.setData(indicators.rsi);
        // 30/70 reference lines — overbought/oversold thresholds.
        s.createPriceLine({ price: 70, color: '#e05252', lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: '70' });
        s.createPriceLine({ price: 30, color: '#1db87a', lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: '30' });
        list.push(s);
      } else if (id === 'atr' && indicators.atr) {
        const s = sp.chart.addLineSeries({
          color, lineWidth: 1.5,
          priceLineVisible: false, lastValueVisible: true,
          crosshairMarkerVisible: false,
        });
        s.setData(indicators.atr);
        list.push(s);
      } else if (id === 'macd') {
        if (indicators.macd_hist) {
          const h = sp.chart.addHistogramSeries({
            priceLineVisible: false, lastValueVisible: false,
          });
          h.setData(indicators.macd_hist);
          list.push(h);
        }
        if (indicators.macd_line) {
          const l = sp.chart.addLineSeries({
            color: '#4a9eff', lineWidth: 1.25,
            priceLineVisible: false, lastValueVisible: true,
            crosshairMarkerVisible: false,
          });
          l.setData(indicators.macd_line);
          list.push(l);
        }
        if (indicators.macd_signal) {
          const s = sp.chart.addLineSeries({
            color: '#fb923c', lineWidth: 1.25,
            priceLineVisible: false, lastValueVisible: true,
            crosshairMarkerVisible: false,
          });
          s.setData(indicators.macd_signal);
          list.push(s);
        }
      } else if (id === 'volume' && indicators.volume) {
        const h = sp.chart.addHistogramSeries({
          priceLineVisible: false, lastValueVisible: false,
        });
        h.setData(indicators.volume);
        list.push(h);
      }
    }

    // Bidirectional time-scale sync between price chart and a sub-pane.
    // Locked by a flag to break the would-be infinite ping-pong loop.
    _wireSubPaneSync(id) {
      const sp = this.subPanes[id];
      if (!sp) return;
      const lock = { v: false };
      const a = this.priceChart.timeScale();
      const b = sp.chart.timeScale();
      a.subscribeVisibleLogicalRangeChange(r => {
        if (lock.v || !r) return;
        lock.v = true;
        try { b.setVisibleLogicalRange(r); } catch (_) {}
        lock.v = false;
      });
      b.subscribeVisibleLogicalRangeChange(r => {
        if (lock.v || !r) return;
        lock.v = true;
        try { a.setVisibleLogicalRange(r); } catch (_) {}
        lock.v = false;
      });
      // Crosshair sync: hover on price → ghost crosshair on sub.
      this.priceChart.subscribeCrosshairMove(p => {
        if (!p || !p.time) {
          try { sp.chart.clearCrosshairPosition(); } catch (_) {}
          return;
        }
        if (sp.seriesList && sp.seriesList[0]) {
          const ref = p.seriesData && p.seriesData.get(this.priceSeries);
          const closeVal = ref && typeof ref.close === 'number' ? ref.close : 0;
          try { sp.chart.setCrosshairPosition(closeVal, p.time, sp.seriesList[0]); }
          catch (_) {}
        }
      });
    }

    toggleIndicator(id) {
      const ind = IND_BY_ID[id];
      if (!ind) return;
      const chip = this.container.querySelector(`.ct-chip[data-id="${id}"]`);
      if (this.activeIndicators.has(id)) {
        this.activeIndicators.delete(id);
        if (chip) chip.classList.remove('active');
        // Sub-pane: tear it down completely.
        if (ind.kind === 'subpane' && this.subPanes[id]) {
          try { this.subPanes[id].chart.remove(); } catch (_) {}
          this.subPanes[id].wrap.remove();
          delete this.subPanes[id];
        }
      } else {
        this.activeIndicators.add(id);
        if (chip) chip.classList.add('active');
        if (ind.kind === 'subpane') this._buildSubPane(id);
      }
      this._savePrefs();
      this._resize();
      this.refreshIndicators();
    }

    setInterval(iv) {
      if (iv === this.interval) return;
      this.interval = iv;
      this.container.querySelectorAll('.ct-tf').forEach(b => {
        b.classList.toggle('active', b.dataset.iv === iv);
      });
      const intraday = iv !== '1d';
      this.priceChart.applyOptions({ timeScale: { timeVisible: intraday } });
      Object.values(this.subPanes).forEach(sp => {
        sp.chart.applyOptions({ timeScale: { timeVisible: intraday } });
      });
      this.loadData();
    }

    // Caller-driven helpers used by /pending for plan levels and
    // page-managed lazy-load.
    addPriceLine(opts) {
      const pl = this.priceSeries.createPriceLine(opts);
      this._extraPriceLines.push(pl);
      return pl;
    }

    setData(bars) {
      this.bars = bars.slice();
      this.priceSeries.setData(bars.map(b => ({
        time: b.time, open: b.open, high: b.high, low: b.low, close: b.close,
      })));
      this._applyTradeMarkers();
    }

    prependBars(older) {
      if (!older || !older.length) return;
      this.bars = older.concat(this.bars);
      this.priceSeries.setData(this.bars.map(b => ({
        time: b.time, open: b.open, high: b.high, low: b.low, close: b.close,
      })));
      this._applyTradeMarkers();
    }

    // ── Trade markers: discovery point + EP/TP/SL level hits ────────────
    // cfg: {entry, stop, tp1, tp2, direction:'long'|'short', discoveryTime:epochSec}
    // Discovery = where the strategy found the setup (look forward from here).
    // Hits are computed client-side from the loaded bars, so no server change
    // is needed; they recompute on every (re)load and lazy-load.
    // cfg.events: [{ time:<epochSec>, kind, color, label, tip }]. Each is drawn
    // as a VERTICAL bar at that candle with the label chip at the TOP edge
    // (clear of the price action). Times are real: Found = the trigger candle;
    // EP / exit only exist once the trade is actually entered / closed.
    setTradeMarkers(cfg) { this.tradeMarkers = cfg || null; this._applyTradeMarkers(); }

    // Index of the bar that CONTAINS time t (last bar whose start time <= t).
    // Daily bars are stamped at 00:00, so a mid-day ts belongs to that day's
    // bar — not the next. Returns 0 if t predates all bars, -1 if none.
    _containingBarIndex(t) {
      const bars = this.bars;
      if (!bars || !bars.length || !t) return -1;
      let idx = 0;
      for (let i = 0; i < bars.length; i++) {
        if (bars[i].time <= t) idx = i; else break;
      }
      return idx;
    }

    // Add one vertical bar + top label chip at time t (snapped to the
    // candle that contains t). Pushes into this._vlines for positioning.
    _addVline(t, color, label, tip) {
      const idx = this._containingBarIndex(t);
      const bt = idx >= 0 ? this.bars[idx].time : t;
      const line = document.createElement('div');
      line.className = 'ct-vline';
      line.style.background = color;
      const mark = document.createElement('div');
      mark.className = 'ct-vmark';
      mark.style.background = color;
      mark.textContent = label || '';
      if (tip) { line.title = tip; mark.title = tip; }
      this._vlineWrap.appendChild(line);
      this._vlineWrap.appendChild(mark);
      this._vlines.push({ t: bt, line, mark });
    }

    // Compute the valid window for a fresh/pending trade from the loaded bars.
    // Rule (operator-chosen): the setup is VALID from the discovery candle
    // and stops being valid at the FIRST invalidation, whichever comes first:
    //   • stop hit (after fill)              → 'stop'
    //   • first take-profit touched (after fill; setup no longer fresh) → 'tp1'
    //   • price ran away before the entry filled (missed / chased) → 'chased'
    //   • time-stop deadline reached          → 'expired'
    // cfg: {direction, discoveryTime:epochSec, entry, stop, tp1, timeStopDays}
    _computeValidWindow() {
      const cfg = this.tradeMarkers;
      if (!cfg || cfg.discoveryTime == null || cfg.entry == null) return null;
      const bars = this.bars;
      if (!bars || !bars.length) return null;

      const isLong = (cfg.direction || 'long') !== 'short';
      const E = cfg.entry;
      const S = (cfg.stop != null) ? cfg.stop : null;
      const T = (cfg.tp1 != null) ? cfg.tp1 : null;
      const risk = (S != null) ? Math.abs(E - S) : null;
      const buf = Math.max(risk != null ? risk * 0.25 : 0, Math.abs(E) * 0.001);
      const days = cfg.timeStopDays || 5;

      const discIdx = this._containingBarIndex(cfg.discoveryTime);
      if (discIdx < 0) return null;
      const validTime = bars[discIdx].time;
      const deadline = validTime + days * 86400;

      let filled = false;
      let end = null;   // { time, reason }
      for (let i = discIdx + 1; i < bars.length; i++) {
        const b = bars[i];
        if (!filled) {
          const hitEntry = isLong ? (b.low <= E) : (b.high >= E);
          if (hitEntry) filled = true;
        }
        if (filled) {
          if (S != null) {
            const hitStop = isLong ? (b.low <= S) : (b.high >= S);
            if (hitStop) { end = { time: b.time, reason: 'stop' }; break; }
          }
          if (T != null) {
            const hitTp = isLong ? (b.high >= T) : (b.low <= T);
            if (hitTp) { end = { time: b.time, reason: 'tp1' }; break; }
          }
        } else {
          // Never filled and price gapped/ran away from the entry → chased.
          const chased = isLong ? (b.low >= E + buf) : (b.high <= E - buf);
          if (chased) { end = { time: b.time, reason: 'chased' }; break; }
        }
        if (b.time >= deadline) { end = { time: b.time, reason: 'expired' }; break; }
      }
      return { validTime, filled, end };
    }

    _applyTradeMarkers() {
      if (!this._vlineWrap) return;
      this._vlineWrap.innerHTML = '';
      this._vlines = [];
      this._vshade = null;
      const cfg = this.tradeMarkers;
      if (!cfg) { this._positionVlines(); return; }
      const CC = window.CHART_COLORS || {};

      // Mode A — explicit real events (detail page: actual fill / exit stamps).
      if (cfg.events && cfg.events.length) {
        cfg.events.forEach(e => {
          if (e.time == null) return;
          this._addVline(e.time, e.color || CC.discovery || '#f59e0b',
                         e.label || '', e.tip);
        });
        this._positionVlines();
        return;
      }

      // Mode B — valid window (fresh / pending trades): Valid bar + End bar
      // + shaded window between them.
      const win = this._computeValidWindow();
      if (!win) { this._positionVlines(); return; }

      const lastBar = this.bars[this.bars.length - 1];
      const shadeEnd = win.end ? win.end.time : (lastBar && lastBar.time);
      if (shadeEnd != null) {
        const shade = document.createElement('div');
        shade.className = 'ct-vshade';
        this._vlineWrap.appendChild(shade);
        this._vshade = { a: win.validTime, b: shadeEnd, el: shade };
      }

      this._addVline(win.validTime, CC.tp1 || '#22c55e', 'Valid',
        'Setup valid from this candle — entry can be placed.');

      if (win.end) {
        const meta = {
          stop:    [CC.stop      || '#ef4444', 'Stopped', 'Stop hit — setup invalidated.'],
          tp1:     [CC.tp1       || '#22c55e', 'TP1',     'First target touched — setup no longer fresh.'],
          chased:  [CC.discovery || '#f59e0b', 'Chased',  'Price ran away before entry filled — missed.'],
          expired: ['#8b90a0',                 'Expired', 'Time-stop reached — setup no longer valid.'],
        }[win.end.reason] || ['#8b90a0', 'End', ''];
        this._addVline(win.end.time, meta[0], meta[1], meta[2]);
      }
      this._positionVlines();
    }

    // Place each vertical bar (and the shaded window) at its candle's
    // x-coordinate; hide/clamp when scrolled out of view.
    _positionVlines() {
      if (!this.priceChart) return;
      const ts = this.priceChart.timeScale();
      (this._vlines || []).forEach(v => {
        let x = null;
        try { x = ts.timeToCoordinate(v.t); } catch (_) {}
        if (x == null) {
          v.line.style.display = 'none'; v.mark.style.display = 'none'; return;
        }
        v.line.style.display = ''; v.mark.style.display = '';
        v.line.style.left = x + 'px';
        v.mark.style.left = x + 'px';
      });
      if (this._vshade) {
        let xa = null, xb = null;
        try { xa = ts.timeToCoordinate(this._vshade.a); } catch (_) {}
        try { xb = ts.timeToCoordinate(this._vshade.b); } catch (_) {}
        if (xa == null && xb == null) {
          this._vshade.el.style.display = 'none';
        } else {
          // Clamp a missing edge to the chart bounds so the band still shows
          // when one end is scrolled off-screen.
          const w = this.priceWrap ? this.priceWrap.clientWidth : 0;
          if (xa == null) xa = 0;
          if (xb == null) xb = w;
          this._vshade.el.style.display = '';
          this._vshade.el.style.left = Math.min(xa, xb) + 'px';
          this._vshade.el.style.width = Math.abs(xb - xa) + 'px';
        }
      }
    }

    _showError(msg) {
      this.priceWrap.innerHTML = `<div class="ct-error">${msg}</div>`;
    }

    destroy() {
      try { this._ro && this._ro.disconnect(); } catch (_) {}
      try { this.priceChart.remove(); } catch (_) {}
      Object.values(this.subPanes).forEach(sp => {
        try { sp.chart.remove(); } catch (_) {}
      });
      this.subPanes = {};
      this.overlaySeries = {};
    }
  }

  function renderChart(container, opts) {
    if (typeof LightweightCharts === 'undefined') {
      container.innerHTML = '<div class="ct-error">Chart library not loaded.</div>';
      return null;
    }
    return new ChartInstance(container, opts);
  }

  // ── Source picker popover ───────────────────────────────────────────
  // Shown when the user clicks a .ticker-chip on /universe edit. Lists
  // the four chart sources and (for the in-app + iframe ones) the
  // available timeframes. Picking a button opens a floating panel via
  // createFloatingPanel().
  let _popover = null;
  function _closePopover() { if (_popover) { _popover.remove(); _popover = null; } }
  document.addEventListener('click', e => {
    if (_popover && !_popover.contains(e.target) &&
        !e.target.classList.contains('ticker-chip')) {
      _closePopover();
    }
  });

  function openSourcePopover(anchor, ctxOpts) {
    _closePopover();
    const symbol = (anchor.dataset.symbol || '').toUpperCase();
    if (!symbol) return;
    injectStyles();
    const pop = document.createElement('div');
    pop.className = 'ct-src-popover';
    pop.innerHTML = `
      <div class="ct-src-symbol">${symbol}</div>
      <div class="ct-src-row">
        <span class="ct-src-name">Quick</span>
        <div class="ct-src-tfs" data-source="quick">
          <button class="ct-src-btn" data-iv="1h">1H</button>
          <button class="ct-src-btn" data-iv="2h">2H</button>
          <button class="ct-src-btn" data-iv="4h">4H</button>
          <button class="ct-src-btn" data-iv="1d">1D</button>
        </div>
      </div>
      <div class="ct-src-row">
        <span class="ct-src-name">Finviz img</span>
        <div class="ct-src-tfs" data-source="finviz_image">
          <button class="ct-src-btn" data-iv="d">D</button>
          <button class="ct-src-btn" data-iv="w">W</button>
          <button class="ct-src-btn" data-iv="m">M</button>
        </div>
      </div>
      <div class="ct-src-row">
        <span class="ct-src-name">TradingView</span>
        <div class="ct-src-tfs" data-source="tradingview">
          <button class="ct-src-btn" data-iv="60">1H</button>
          <button class="ct-src-btn" data-iv="240">4H</button>
          <button class="ct-src-btn" data-iv="D">D</button>
          <button class="ct-src-btn" data-iv="W">W</button>
        </div>
      </div>
      <div class="ct-src-row">
        <span class="ct-src-name">Open ↗</span>
        <div class="ct-src-tfs">
          <a class="ct-src-link" target="_blank" rel="noopener"
             href="https://finviz.com/quote.ashx?t=${encodeURIComponent(symbol)}">
            Finviz quote
          </a>
        </div>
      </div>
    `;
    document.body.appendChild(pop);
    // Position adaptively near the anchor
    const r = anchor.getBoundingClientRect();
    let top = r.bottom + 4;
    let left = r.left;
    const popH = pop.offsetHeight, popW = pop.offsetWidth;
    if (top + popH > window.innerHeight - 10) top = Math.max(8, r.top - popH - 4);
    if (left + popW > window.innerWidth - 10) left = window.innerWidth - popW - 10;
    pop.style.top = top + 'px';
    pop.style.left = Math.max(8, left) + 'px';

    pop.querySelectorAll('.ct-src-btn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const source = btn.parentElement.dataset.source;
        const iv = btn.dataset.iv;
        _closePopover();
        createFloatingPanel({
          symbol,
          source,
          interval: iv,
          indicators: ctxOpts && ctxOpts.indicators,
          persistKey: ctxOpts && ctxOpts.persistKey,
        });
      });
    });
    _popover = pop;
  }

  // Delegated chip binding helper for /universe.
  function bindTickerChips(root, ctxOpts) {
    (root || document).querySelectorAll('.ticker-chip').forEach(chip => {
      if (chip.dataset.bound) return;
      chip.dataset.bound = '1';
      chip.addEventListener('click', e => {
        e.stopPropagation();
        openSourcePopover(chip, ctxOpts || {});
      });
    });
  }

  // ── Floating panel wrapper ──────────────────────────────────────────
  let _panelCounter = 0;
  const PANEL_OFFSET_STEP = 24;

  function createFloatingPanel(opts) {
    injectStyles();
    const symbol = String(opts.symbol || '').toUpperCase();
    const source = opts.source || 'quick';
    const interval = opts.interval || (source === 'finviz_image' ? 'd' : '1d');

    const id = 'chart-panel-' + (++_panelCounter);
    const panel = document.createElement('div');
    panel.className = 'chart-panel ct-floating';
    panel.id = id;
    const offset = (_panelCounter - 1) % 6 * PANEL_OFFSET_STEP;
    // Default geometry tuned per source — TV widget needs more room
    // for its in-iframe toolbar; quick chart starts wide enough for
    // the indicator chip row to fit on one line.
    const w = source === 'tradingview' ? 820
            : source === 'finviz_image' ? 600
            : 720;
    const h = source === 'tradingview' ? 540
            : source === 'finviz_image' ? 460
            : 480;
    panel.style.width = w + 'px';
    panel.style.height = h + 'px';
    panel.style.left = Math.max(20, window.innerWidth - w - 40 - offset) + 'px';
    panel.style.top = (80 + offset) + 'px';

    const sourceLabels = {
      quick: 'Quick', finviz_image: 'Finviz', tradingview: 'TradingView',
    };
    panel.innerHTML = `
      <div class="cp-head">
        <div>
          <span class="cp-title">${symbol}</span>
          <span class="cp-tf">${String(interval).toUpperCase()}</span>
          <span class="cp-source">${sourceLabels[source] || source}</span>
        </div>
        <div class="cp-actions">
          <button class="cp-btn pin" title="Pin (border highlight)">📌</button>
          <button class="cp-btn close" title="Close (Esc)">×</button>
        </div>
      </div>
      <div class="cp-body"></div>
      <div class="cp-resize"></div>
    `;
    document.body.appendChild(panel);
    const body = panel.querySelector('.cp-body');

    panel.querySelector('.cp-btn.close').addEventListener('click', () => closePanel(panel));
    panel.querySelector('.cp-btn.pin').addEventListener('click', () => panel.classList.toggle('pinned'));

    // Drag via titlebar (excluding action buttons)
    const head = panel.querySelector('.cp-head');
    head.addEventListener('mousedown', e => {
      if (e.target.closest('.cp-btn')) return;
      const sx = e.clientX, sy = e.clientY;
      const sl = panel.offsetLeft, st = panel.offsetTop;
      const onMove = ev => {
        panel.style.left = Math.max(0, Math.min(window.innerWidth - 60,
                                                 sl + ev.clientX - sx)) + 'px';
        panel.style.top  = Math.max(0, Math.min(window.innerHeight - 40,
                                                 st + ev.clientY - sy)) + 'px';
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      e.preventDefault();
    });
    // Resize via bottom-right grip
    const grip = panel.querySelector('.cp-resize');
    grip.addEventListener('mousedown', e => {
      const sx = e.clientX, sy = e.clientY;
      const sw = panel.offsetWidth, sh = panel.offsetHeight;
      const onMove = ev => {
        panel.style.width  = Math.max(360, sw + ev.clientX - sx) + 'px';
        panel.style.height = Math.max(280, sh + ev.clientY - sy) + 'px';
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      e.preventDefault(); e.stopPropagation();
    });

    // Mark as the "active" panel on any interaction so keyboard
    // shortcuts know which one to drive.
    panel.addEventListener('mousedown', () => _markActive(panel));

    if (source === 'quick') {
      panel._chartInstance = renderChart(body, {
        symbol, interval,
        indicators: opts.indicators || [],
        persistKey: opts.persistKey || null,
      });
    } else if (source === 'finviz_image') {
      // Finviz chart image — `ta=1` bakes SMA(20/50/200) + RSI + MACD
      // into the PNG. p=d/w/m for daily/weekly/monthly. Intraday needs
      // Elite, which we don't subscribe to. Append timestamp to bust
      // the browser cache when the user re-opens the same chart.
      const p = String(interval).toLowerCase()[0] || 'd';
      const url = `https://finviz.com/chart.ashx?t=${encodeURIComponent(symbol)}` +
                  `&ta=1&p=${p}&s=l&ts=${Date.now()}`;
      body.innerHTML = `
        <div class="ct-finviz-wrap">
          <img src="${url}" alt="${symbol} chart"
               onerror="this.replaceWith(Object.assign(document.createElement('div'),{
                 className:'ct-error',innerHTML:'Finviz image failed to load.'
               }))">
          <div class="ct-finviz-foot">
            Finviz <strong>${p.toUpperCase()}</strong> chart with
            SMA(20/50/200) + RSI + MACD baked in (free tier).
            <a href="https://finviz.com/quote.ashx?t=${encodeURIComponent(symbol)}"
               target="_blank" rel="noopener">Open full quote ↗</a>
          </div>
        </div>
      `;
    } else if (source === 'tradingview') {
      // TradingView free Widget — full TV chart inside an iframe with
      // 100+ indicators and drawing tools. No datafeed adapter needed
      // (TV supplies the data). symbol: include exchange prefix when
      // possible — naked symbols sometimes resolve to the wrong listing.
      const tvSymbol = encodeURIComponent(symbol.includes(':') ? symbol : symbol);
      const url = `https://www.tradingview.com/widgetembed/` +
        `?frameElementId=tv-${id}` +
        `&symbol=${tvSymbol}` +
        `&interval=${encodeURIComponent(interval)}` +
        `&hidesidetoolbar=0&hidetoptoolbar=0&theme=dark&style=1` +
        `&timezone=America%2FNew_York` +
        `&withdateranges=1&allow_symbol_change=1&saveimage=1` +
        `&hideideas=1`;
      body.innerHTML = `
        <iframe src="${url}" frameborder="0" allowtransparency="true"
                scrolling="no" allowfullscreen
                style="width:100%;height:100%;display:block;"></iframe>
      `;
    }

    _markActive(panel);
    return panel;
  }

  function closePanel(panel) {
    if (!panel) return;
    if (panel._chartInstance) {
      try { panel._chartInstance.destroy(); } catch (_) {}
    }
    panel.remove();
    if (_activePanel === panel) _activePanel = null;
  }

  // ── Keyboard shortcuts ──────────────────────────────────────────────
  // Track the most-recently interacted-with floating panel so timeframe
  // / Esc shortcuts know which chart to drive. Without this, shortcuts
  // would always hit the last panel in DOM order — which is rarely the
  // one the user is actually looking at.
  let _activePanel = null;
  function _markActive(panel) { _activePanel = panel; }

  function _isTypingTarget(el) {
    if (!el) return false;
    const tag = (el.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select' ||
           el.isContentEditable;
  }

  document.addEventListener('keydown', e => {
    if (_isTypingTarget(document.activeElement)) return;

    if (e.key === 'Escape') {
      // Esc closes the active unpinned panel (or, lacking one, the
      // most recent unpinned panel in DOM order).
      const target = (_activePanel && !_activePanel.classList.contains('pinned'))
        ? _activePanel
        : [...document.querySelectorAll('.chart-panel.ct-floating:not(.pinned)')].pop();
      if (target) {
        closePanel(target);
        e.preventDefault();
      }
      return;
    }

    // Timeframe shortcuts route to the active panel's quick-chart instance.
    const ivMap = { '1': '1h', '2': '2h', '4': '4h', 'd': '1d', 'D': '1d' };
    const iv = ivMap[e.key];
    if (iv && _activePanel && _activePanel._chartInstance) {
      _activePanel._chartInstance.setInterval(iv);
      e.preventDefault();
    }
  });

  // ── Public API ──────────────────────────────────────────────────────
  // Fill an element with the trade-marker legend (colors honor CHART_COLORS).
  // mode: 'window' (pending — Valid→invalidation band) or 'events' (detail —
  // real fill/exit stamps). Defaults to 'events'.
  function renderTradeLegend(el, mode) {
    if (!el) return;
    const CC = window.CHART_COLORS || {};
    const items = (mode === 'window') ? [
      ['Valid',   CC.tp1       || '#22c55e', 'Setup is valid from here — entry can be placed'],
      ['window',  'rgba(34,197,94,0.35)',    'Shaded band = the window during which the setup stays valid'],
      ['Stopped', CC.stop      || '#ef4444', 'Stop hit — setup invalidated'],
      ['TP1',     CC.tp1       || '#22c55e', 'First target touched — setup no longer fresh'],
      ['Chased',  CC.discovery || '#f59e0b', 'Price ran away before entry filled — missed'],
      ['Expired', '#8b90a0',                 'Time-stop reached — setup no longer valid'],
    ] : [
      ['Found',  CC.discovery || '#f59e0b', 'Where the strategy discovered the setup — look forward from here'],
      ['EP',     CC.entry     || '#4a9eff', 'Entry filled (price reached the entry level)'],
      ['TP1',    CC.tp1       || '#22c55e', 'First take-profit hit'],
      ['TP2',    CC.tp2       || '#16a34a', 'Second take-profit hit'],
      ['SL',     CC.stop      || '#ef4444', 'Stop-loss hit'],
    ];
    el.innerHTML = items.map(([label, color, tip]) =>
      `<span class="leg-item" title="${tip}">` +
      `<span class="leg-dot" style="background:${color}"></span>${label}</span>`
    ).join('');
  }

  window.ChartTools = {
    INDICATORS,
    FILTER_INDICATOR_MAP,
    filtersToIndicators,
    renderChart,
    renderTradeLegend,
    openSourcePopover,
    bindTickerChips,
    createFloatingPanel,
    closePanel,
  };
})();
