/* trade_images.js — generate a per-trade chart image in the browser (Option B).
 *
 * For a selected history row we render the trade on an OFFSCREEN Lightweight
 * Charts instance (same engine as the rest of the app), draw its entry/stop/TP
 * levels + entry/exit markers, screenshot it, and POST the PNG to
 * /api/trade-images/{trade_id}. The server stores it and the row swaps to a
 * thumbnail. No server-side plotting dependency.
 */
(function () {
  const CC = window.CHART_COLORS || {};

  function tiToggleAll(box) {
    document.querySelectorAll('.ti-check').forEach(c => { c.checked = box.checked; });
  }
  function tiLightbox(ev, url) {
    if (ev) ev.preventDefault();
    const box = document.getElementById('ti-lightbox');
    const img = document.getElementById('ti-lightbox-img');
    if (box && img) { img.src = url; box.style.display = 'flex'; }
  }
  const _ep = iso => (iso ? Math.floor(Date.parse(iso) / 1000) : null);
  const _num = v => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };

  function _rowData(tr) {
    const d = tr.dataset;
    const sym = d.symbol || '';
    const isFx = /^[A-Z]{6}$/.test(sym);
    return {
      tr, tradeId: d.tradeId, symbol: sym,
      direction: d.direction || 'long',
      interval: isFx ? '30m' : '1d',
      entry: _num(d.entry), stop: _num(d.stop),
      tp1: _num(d.tp1), tp2: _num(d.tp2), exit: _num(d.exit),
      entered: _ep(d.entered), exited: _ep(d.exited),
    };
  }

  // Render one trade offscreen and return a PNG data URL (or null).
  async function _capture(t) {
    if (!window.ChartTools || !t.symbol) return null;
    const mount = document.createElement('div');
    mount.style.cssText = 'position:absolute;left:-10000px;top:0;width:680px;height:380px;';
    document.body.appendChild(mount);

    const events = [];
    if (t.entered) events.push({ time: t.entered, color: CC.entry || '#4a9eff', label: 'EP', tip: 'Entry' });
    if (t.exited) events.push({ time: t.exited, color: CC.tp1 || '#22c55e', label: 'EX', tip: 'Exit' });

    let inst = null;
    try {
      inst = window.ChartTools.renderChart(mount, {
        symbol: t.symbol, interval: t.interval,
        indicators: ['sma20', 'sma50'],
        limit: t.interval === '1d' ? 140 : 300,
        showTimeframes: false, showChips: false, showLive: false,
        tradeMarkers: { events },
      });
      if (!inst) return null;

      // Plan levels as horizontal lines.
      const _pl = (price, color, style, title) => {
        if (price == null) return;
        try { inst.addPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }); } catch (_) {}
      };
      _pl(t.entry, CC.entry || '#60a5fa', 0, 'Entry');
      _pl(t.stop, CC.stop || '#e05252', 2, 'Stop');
      _pl(t.tp1, CC.tp1 || '#1db87a', 2, 'TP1');
      _pl(t.tp2, CC.tp2 || '#22d3ee', 2, 'TP2');

      // Wait for bars to load (chart_tools loads async in its constructor).
      for (let i = 0; i < 60; i++) {
        if (inst.bars && inst.bars.length) break;
        await new Promise(r => setTimeout(r, 100));
      }
      if (!inst.bars || !inst.bars.length) return null;
      try { inst.priceChart.timeScale().fitContent(); } catch (_) {}
      await new Promise(r => setTimeout(r, 250));   // let it paint

      const canvas = inst.priceChart.takeScreenshot();
      return canvas ? canvas.toDataURL('image/png') : null;
    } catch (e) {
      console.warn('trade image capture failed', e);
      return null;
    } finally {
      try { inst && inst.destroy(); } catch (_) {}
      mount.remove();
    }
  }

  async function _store(tradeId, dataUrl) {
    const r = await fetch('/api/trade-images/' + encodeURIComponent(tradeId), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: dataUrl }),
    });
    if (!r.ok) throw new Error('store failed: HTTP ' + r.status);
    return (await r.json()).url;
  }

  function _showThumb(tr, url) {
    const cell = tr.querySelector('.ti-img-cell');
    if (cell) {
      cell.innerHTML = '<a href="' + url + '" onclick="tiLightbox(event, this.href)">'
        + '<img class="ti-thumb" src="' + url + '?t=' + Date.now() + '" alt="chart"></a>';
    }
    tr.dataset.imgState = 'ok';   // freshly generated at the current version
  }

  async function _generate(t) {
    const dataUrl = await _capture(t);
    if (!dataUrl) throw new Error('could not render ' + t.symbol);
    const url = await _store(t.tradeId, dataUrl);
    _showThumb(t.tr, url);
    return url;
  }

  async function tiGenerateRow(tr) {
    const btn = tr.querySelector('.ti-gen-one');
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try { await _generate(_rowData(tr)); }
    catch (e) { if (btn) { btn.disabled = false; btn.textContent = 'Retry'; } console.warn(e); }
  }

  async function tiGenerateSelected() {
    const rows = [...document.querySelectorAll('.ti-row')]
      .filter(tr => tr.querySelector('.ti-check')?.checked);
    const status = document.getElementById('ti-status');
    if (!rows.length) { if (status) status.textContent = 'Select rows first.'; return; }
    let done = 0, fail = 0;
    for (const tr of rows) {
      if (status) status.textContent = `Generating ${done + fail + 1}/${rows.length}…`;
      try { await _generate(_rowData(tr)); done++; }
      catch (e) { fail++; console.warn(e); }
    }
    if (status) status.textContent = `Done — ${done} generated${fail ? `, ${fail} failed` : ''}.`;
  }

  // Regenerate only what's missing or outdated in the current view (the loaded
  // date range / filter). Up-to-date images (data-img-state="ok") are skipped —
  // this is the "regenerate the range, but cached unless the version changed".
  async function tiGenerateView() {
    const rows = [...document.querySelectorAll('.ti-row')]
      .filter(tr => (tr.dataset.imgState || 'none') !== 'ok');
    const status = document.getElementById('ti-status');
    if (!rows.length) { if (status) status.textContent = 'All images in view are up to date.'; return; }
    let done = 0, fail = 0;
    for (const tr of rows) {
      if (status) status.textContent = `Regenerating ${done + fail + 1}/${rows.length} (missing/outdated)…`;
      try { await _generate(_rowData(tr)); done++; }
      catch (e) { fail++; console.warn(e); }
    }
    if (status) status.textContent = `Done — ${done} generated${fail ? `, ${fail} failed` : ''}, up-to-date skipped.`;
  }

  // expose
  window.tiToggleAll = tiToggleAll;
  window.tiLightbox = tiLightbox;
  window.tiGenerateRow = tiGenerateRow;
  window.tiGenerateSelected = tiGenerateSelected;
  window.tiGenerateView = tiGenerateView;
})();
