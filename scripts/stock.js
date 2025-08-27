// scripts/stock.js
(function () {
  const $ = sel => document.querySelector(sel);

  // URL params (support slug or symbol)
  const params = new URLSearchParams(location.search);
  const urlSymbol = params.get('symbol');   // e.g., COALINDIA.NS
  const urlSlug   = params.get('slug');     // e.g., coal-india

  // helpers
  const toSlug = (s) =>
    String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');

  const normalizeLoose = (s) =>
    String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ''); // remove hyphens/spaces for lenient comparisons

  const jfetch = async (path) => {
    const res = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  };

  const now = new Date();
  $('#year') && ($('#year').textContent = now.getFullYear());

  /**
   * Resolve the page target:
   * 1) Prefer positions.json (authoritative for buys)
   * 2) Use stocks.json for name/tags/slug/report mapping
   * 3) Be lenient about slug matching (ignore hyphens/spaces)
   */
  async function resolveTarget() {
    const [positions, stocks] = await Promise.all([
      jfetch('data/positions.json').catch(() => []),
      jfetch('data/stocks.json').catch(() => [])
    ]);

    const posBySymbol = Object.fromEntries(positions.map(p => [p.symbol, p]));

    // a) If ?symbol is present, try direct symbol first
    if (urlSymbol) {
      const pos = posBySymbol[urlSymbol] || null;
      const st  = stocks.find(s => (s.symbol || s.ticker) === urlSymbol) || {};
      const slug = st.slug || toSlug(st.name || urlSymbol.split('.')[0]);
      return { symbol: urlSymbol, pos, stockMeta: st, slug };
    }

    // b) If ?slug is present, try to match leniently:
    if (urlSlug) {
      const wantLoose = normalizeLoose(urlSlug);

      // b1) Try positions first: compare against the symbol base (e.g. COALINDIA) loosely
      for (const p of positions) {
        const base = (p.symbol || '').split('.')[0];
        if (normalizeLoose(base) === wantLoose) {
          const st = stocks.find(s => (s.symbol || s.ticker) === p.symbol) || {};
          const slug = st.slug || toSlug(st.name || base);
          return { symbol: p.symbol, pos: p, stockMeta: st, slug };
        }
      }

      // b2) Try stocks: compare wantLoose with slug/name/symbol-base loosely
      for (const s of stocks) {
        const sSym = s.symbol || s.ticker || '';
        const base = sSym.split('.')[0];
        const candidates = [
          s.slug,
          s.name,
          sSym,
          base
        ].filter(Boolean);

        if (candidates.some(c => normalizeLoose(c) === wantLoose)) {
          const pos = posBySymbol[sSym] || null;
          const slug = s.slug || toSlug(s.name || base);
          return { symbol: sSym, pos, stockMeta: s, slug };
        }
      }

      // b3) As a final fallback, try to infer exchange suffix (.NS/.BO) by scanning positions symbols loosely
      for (const p of positions) {
        const base = (p.symbol || '').split('.')[0];
        if (normalizeLoose(base) === wantLoose) {
          const st = stocks.find(s => (s.symbol || s.ticker) === p.symbol) || {};
          const slug = st.slug || toSlug(st.name || base);
          return { symbol: p.symbol, pos: p, stockMeta: st, slug };
        }
      }
    }

    return null;
  }

  async function renderReport(symbol, slug, stockMeta) {
    // Try by symbol, then by slug
    const candidates = [];
    if (symbol) candidates.push(`reports/${encodeURIComponent(symbol)}.md`);
    if (slug)   candidates.push(`reports/${encodeURIComponent(slug)}.md`);

    for (const path of candidates) {
      try {
        const resp = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
        if (!resp.ok) continue;
        const md = await resp.text();
        $('#report').innerHTML = marked.parse(md);
        const h1 = md.match(/^#\s+(.+)/m);
        const title = h1 ? h1[1].trim() : (stockMeta?.name || symbol || slug || 'Stock Report');
        $('#stockName') && ($('#stockName').textContent = title);
        document.title = `${title} – Stock Report`;
        return;
      } catch {}
    }
    const title = stockMeta?.name || symbol || slug || 'Stock Report';
    $('#stockName') && ($('#stockName').textContent = title);
    $('#report') && ($('#report').textContent = 'Report not found.');
  }

  async function drawPriceChart(symbol, buyPriceLocal, buyDate) {
    const canvas = $('#priceChart');
    if (!canvas) return;

    let quotes;
    try {
      quotes = await jfetch(`data/quotes/${encodeURIComponent(symbol)}.json`);
    } catch (e) {
      console.error(e);
      canvas.replaceWith(`Price fetch failed for ${symbol}.`);
      return;
    }

    const points = quotes
      .filter(r => r && r.date && Number.isFinite(+r.close))
      .map(r => ({ x: new Date(r.date), y: Number(r.close) }))
      .sort((a, b) => a.x - b.x);

    if (points.length === 0) {
      canvas.replaceWith('Price data not available.');
      return;
    }

    const xMin = points[0].x;
    const xMax = points[points.length - 1].x;

    const ys = points.map(p => p.y);
    const buyPrice = Number.isFinite(+buyPriceLocal) ? +buyPriceLocal : NaN;
    const yMin = Math.min(...ys, Number.isFinite(buyPrice) ? buyPrice : Infinity);
    const yMax = Math.max(...ys, Number.isFinite(buyPrice) ? buyPrice : -Infinity);
    const pad = (yMax - yMin) * 0.08 || Math.max(1, yMax * 0.08);
    const suggestedMin = Math.max(0, yMin - pad);
    const suggestedMax = yMax + pad;

    const buyLine = Number.isFinite(buyPrice)
      ? [{ x: xMin, y: buyPrice }, { x: xMax, y: buyPrice }]
      : [];

    new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        datasets: [
          { label: `${symbol} Close`, data: points, borderWidth: 2, pointRadius: 0, tension: 0.2 },
          ...(buyLine.length ? [{ label: 'Buy Price', data: buyLine, borderDash: [6,6], borderWidth: 1.5, pointRadius: 0 }] : [])
        ]
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true },
          tooltip: { callbacks: {
            label: (c) => c.dataset.label === 'Buy Price'
              ? ` Buy: ${c.parsed.y}`
              : ` Close: ${c.parsed.y.toLocaleString()}`
          }}
        },
        scales: {
          x: { type: 'time', min: xMin, max: xMax, time: { unit: 'month' }, ticks: { maxTicksLimit: 8 } },
          y: { beginAtZero: false, suggestedMin, suggestedMax }
        }
      }
    });

    // Friendly inline hint if position wasn't found for this symbol
    if (!Number.isFinite(buyPrice) || !buyDate) {
      const note = $('#priceNote');
      if (note) note.textContent = 'Position details not found in positions.json; showing price chart only.';
    }
  }

  async function main() {
    try {
      const chosen = await resolveTarget();
      if (!chosen) {
        const msg = urlSlug
          ? `Unknown slug "${urlSlug}".`
          : (urlSymbol ? `Unknown symbol "${urlSymbol}".` : 'Missing ?slug= or ?symbol=');
        $('#priceChart')?.replaceWith(msg);
        return;
      }

      const { symbol, pos, stockMeta, slug } = chosen;

      // Header meta
      $('#ticker') && ($('#ticker').textContent = symbol);

      if (pos) {
        $('#buyDate')  && ($('#buyDate').textContent  = pos.buy_date || '');
        $('#qty')      && ($('#qty').textContent      = Number(pos.qty ?? 0).toLocaleString());
        $('#buyPrice') && ($('#buyPrice').textContent = pos.buy_price_local ?? '');
        if (Number.isFinite(+pos.cost_local)) {
          $('#cost') && ($('#cost').textContent = Number(pos.cost_local).toLocaleString());
        }
        $('#priceNote') && ($('#priceNote').textContent =
          pos.buy_date ? `Red dotted line marks buy at ${pos.buy_price_local} on ${pos.buy_date}.` : '');
      } else {
        // Fallback to stocks.json if no position found
        const qty = stockMeta?.qty, bp = stockMeta?.buy_price, bd = stockMeta?.buy_date;
        $('#buyDate')  && ($('#buyDate').textContent  = bd || '');
        $('#qty')      && ($('#qty').textContent      = (qty ?? '').toString());
        $('#buyPrice') && ($('#buyPrice').textContent = (bp ?? '').toString());
        if (qty && bp) $('#cost') && ($('#cost').textContent = (qty * bp).toLocaleString());
        $('#priceNote') && ($('#priceNote').textContent =
          bd ? `Red dotted line marks buy at ${bp} on ${bd}.` : 'Position not found in positions.json.');
      }

      await renderReport(symbol, slug, stockMeta);
      await drawPriceChart(symbol, pos?.buy_price_local ?? stockMeta?.buy_price, pos?.buy_date ?? stockMeta?.buy_date);
    } catch (e) {
      console.error('stock page error:', e);
      $('#priceChart')?.replaceWith('Stock page error — open console for details.');
    }
  }

  main();
})();
