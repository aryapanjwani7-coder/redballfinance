// scripts/stock.js
(function () {
  const $ = sel => document.querySelector(sel);

  // ---- URL params ----
  const params = new URLSearchParams(location.search);
  const urlSymbol = params.get('symbol');   // e.g. COALINDIA.NS
  const urlSlug   = params.get('slug');     // e.g. coal-india

  // ---- helpers ----
  const toSlug = (s) =>
    String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');

  const jfetch = async (path) => {
    const res = await fetch(path, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  };

  const now = new Date();
  $('#year') && ($('#year').textContent = now.getFullYear());

  function pickMetaBySlugOrSymbol(stocks, slug, symbol) {
    // Try exact symbol first if provided
    if (symbol) {
      const bySym = stocks.find(s => (s.symbol || s.ticker) === symbol);
      if (bySym) return { meta: bySym, symbol: bySym.symbol || bySym.ticker, slugGuess: slug || null };
    }

    if (!slug) return null;

    // Build candidate slug for each stock
    for (const s of stocks) {
      const sym = s.symbol || s.ticker || '';
      const parts = String(sym).split('.');
      const symNoEx = parts[0]; // e.g. COALINDIA from COALINDIA.NS
      const candidates = [
        s.slug,
        s.name,
        s.ticker,
        s.symbol,
        symNoEx
      ].filter(Boolean).map(toSlug);

      const want = toSlug(slug);
      if (candidates.includes(want)) {
        return { meta: s, symbol: sym, slugGuess: want };
      }
    }
    return null;
  }

  async function renderReport(meta, symbol, slugGuess) {
    const tryPaths = [];
    if (symbol) tryPaths.push(`reports/${encodeURIComponent(symbol)}.md`);
    if (slugGuess) tryPaths.push(`reports/${encodeURIComponent(slugGuess)}.md`);

    for (const path of tryPaths) {
      try {
        const resp = await fetch(path, { cache: 'no-store' });
        if (!resp.ok) continue;
        const md = await resp.text();
        $('#report').innerHTML = marked.parse(md);
        // use H1 as title if present
        const h1 = md.match(/^#\s+(.+)/m);
        const title = h1 ? h1[1].trim() : (meta?.name || symbol || slugGuess || 'Stock Report');
        $('#stockName') && ($('#stockName').textContent = title);
        document.title = `${title} – Stock Report`;
        return;
      } catch {}
    }
    // fallback
    const title = meta?.name || symbol || slugGuess || 'Stock Report';
    $('#stockName') && ($('#stockName').textContent = title);
    $('#report') && ($('#report').textContent = 'Report not found.');
  }

  async function drawPriceChart(symbol, meta) {
    const canvas = $('#priceChart');
    if (!canvas) return;

    let quotes;
    try {
      quotes = await jfetch(`data/quotes/${encodeURIComponent(symbol)}.json`);
    } catch (e) {
      console.error(e);
      canvas.replaceWith(`Price fetch failed for ${symbol}. Check data/quotes/${symbol}.json`);
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
    const buyPrice = Number(meta?.buy_price);
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
  }

  async function main() {
    try {
      const stocks = await jfetch('data/stocks.json');

      // Decide which stock this page is for
      const chosen = pickMetaBySlugOrSymbol(stocks, urlSlug, urlSymbol);
      if (!chosen) {
        const msg = urlSlug
          ? `Unknown slug "${urlSlug}".`
          : (urlSymbol ? `Unknown symbol "${urlSymbol}".` : 'Missing ?slug= or ?symbol=');
        $('#priceChart')?.replaceWith(msg);
        return;
      }

      const { meta, symbol, slugGuess } = chosen;

      // Populate header/meta
      $('#ticker') && ($('#ticker').textContent = symbol);
      $('#buyDate') && ($('#buyDate').textContent = meta.buy_date || '');
      $('#qty') && ($('#qty').textContent = meta.qty ?? '');
      $('#buyPrice') && ($('#buyPrice').textContent = meta.buy_price ?? '');
      if (meta.qty && meta.buy_price) {
        $('#cost') && ($('#cost').textContent = (meta.qty * meta.buy_price).toLocaleString());
      }
      $('#tags') && ($('#tags').textContent = Array.isArray(meta.tags) ? meta.tags.join(', ') : (meta.tags || '') );
      $('#priceNote') && ($('#priceNote').textContent =
        meta.buy_date ? `Red dotted line marks buy at ${meta.buy_price} on ${meta.buy_date}.` : '');

      await renderReport(meta, symbol, slugGuess);
      await drawPriceChart(symbol, meta);
    } catch (e) {
      console.error('stock page error:', e);
      $('#priceChart')?.replaceWith('Stock page error — open console for details.');
    }
  }

  main();
})();
