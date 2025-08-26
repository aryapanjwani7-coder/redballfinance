// scripts/stock.js
(function () {
  const $ = sel => document.querySelector(sel);
  const canvas = $('#priceChart');

  // symbol from ?symbol=COALINDIA.NS
  const params = new URLSearchParams(location.search);
  const SYMBOL = params.get('symbol');
  if (!SYMBOL) {
    canvas?.replaceWith('Missing ?symbol= in URL.');
    return;
  }

  // Small helpers
  const jfetch = async (path) => {
    const res = await fetch(path, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  };

  // Populate static bits
  const now = new Date();
  $('#year') && ($('#year').textContent = now.getFullYear());
  $('#ticker') && ($('#ticker').textContent = SYMBOL);

  async function renderReport() {
    try {
      // ✅ relative (no leading slash)
      const resp = await fetch(`reports/${encodeURIComponent(SYMBOL)}.md`, { cache: 'no-store' });
      if (!resp.ok) return;
      const md = await resp.text();
      $('#report').innerHTML = marked.parse(md);
      const h1 = md.match(/^#\s+(.+)/m);
      if (h1) {
        $('#stockName') && ($('#stockName').textContent = h1[1].trim());
        document.title = `${h1[1].trim()} – Stock Report`;
      } else {
        $('#stockName') && ($('#stockName').textContent = SYMBOL);
      }
    } catch {
      $('#stockName') && ($('#stockName').textContent = SYMBOL);
    }
  }

  async function drawChart(meta) {
    if (!canvas) return;

    // ✅ relative path (no leading slash)
    let quotes;
    try {
      quotes = await jfetch(`data/quotes/${encodeURIComponent(SYMBOL)}.json`);
    } catch (e) {
      console.error(e);
      canvas.replaceWith(`Price fetch failed for ${SYMBOL}. Check data/quotes/${SYMBOL}.json`);
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
          { label: `${SYMBOL} Close`, data: points, borderWidth: 2, pointRadius: 0, tension: 0.2 },
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
      // ✅ relative path (no leading slash)
      const stocks = await jfetch('data/stocks.json');
      const meta = stocks.find(s => (s.symbol || s.ticker) === SYMBOL);

      if (meta) {
        $('#buyDate') && ($('#buyDate').textContent = meta.buy_date || '');
        $('#qty') && ($('#qty').textContent = meta.qty ?? '');
        $('#buyPrice') && ($('#buyPrice').textContent = meta.buy_price ?? '');
        if (meta.qty && meta.buy_price) {
          $('#cost') && ($('#cost').textContent = (meta.qty * meta.buy_price).toLocaleString());
        }
        $('#tags') && ($('#tags').textContent = (meta.tags || []).join(', '));
        $('#priceNote') && ($('#priceNote').textContent = meta.buy_date
          ? `Red dotted line marks buy at ${meta.buy_price} on ${meta.buy_date}.`
          : '');
      } else {
        $('#priceNote') && ($('#priceNote').textContent = 'No metadata found for this symbol.');
      }

      await renderReport();
      await drawChart(meta);
    } catch (e) {
      console.error('stock page error:', e);
      canvas?.replaceWith('Stock page error — open console for details.');
    }
  }

  main();
})();
