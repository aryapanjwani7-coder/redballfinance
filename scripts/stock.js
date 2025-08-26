// scripts/stock.js
(function () {
  // --- helpers ---
  const $ = sel => document.querySelector(sel);
  const params = new URLSearchParams(location.search);
  const SYMBOL = params.get('symbol'); // e.g. COALINDIA.NS
  if (!SYMBOL) {
    console.error('Missing ?symbol= in URL');
    $('#priceChart')?.replaceWith('Missing symbol.');
    return;
  }

  // populate simple page bits early
  const now = new Date(); $('#year') && ($('#year').textContent = now.getFullYear());
  $('#ticker') && ($('#ticker').textContent = SYMBOL);

  async function loadJSON(path) {
    const res = await fetch(path, { cache: 'no-store' });
    if (!res.ok) throw new Error(`Fetch failed ${res.status} ${path}`);
    return res.json();
  }

  async function renderReportIfPresent() {
    try {
      const mdUrl = `/reports/${encodeURIComponent(SYMBOL)}.md`;
      const res = await fetch(mdUrl, { cache: 'no-store' });
      if (!res.ok) return; // optional
      const md = await res.text();
      $('#report').innerHTML = marked.parse(md);
      // Title from first heading if present
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

  async function drawPriceChart(meta) {
    // fetch quotes
    const quotes = await loadJSON(`/data/quotes/${encodeURIComponent(SYMBOL)}.json`);
    const points = quotes
      .filter(r => r && r.date && Number.isFinite(+r.close))
      .map(r => ({ x: new Date(r.date), y: Number(r.close) }))
      .sort((a, b) => a.x - b.x);

    const canvas = $('#priceChart');
    if (!canvas) return;

    if (points.length === 0) {
      console.error(`No price points in /data/quotes/${SYMBOL}.json`);
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
          {
            label: `${SYMBOL} Close`,
            data: points,
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.2
          },
          ...(buyLine.length ? [{
            label: 'Buy Price',
            data: buyLine,
            borderDash: [6, 6],
            borderWidth: 1.5,
            pointRadius: 0
          }] : [])
        ]
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true },
          tooltip: {
            callbacks: {
              label: (ctx) => (
                ctx.dataset.label === 'Buy Price'
                  ? ` Buy: ${ctx.parsed.y}`
                  : ` Close: ${ctx.parsed.y.toLocaleString()}`
              )
            }
          }
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
      // get meta (buy info) from stocks.json
      const stocks = await loadJSON('/data/stocks.json');
      const meta = stocks.find(s => (s.symbol || s.ticker) === SYMBOL);

      if (meta) {
        $('#buyDate') && ($('#buyDate').textContent = meta.buy_date || '');
        $('#qty') && ($('#qty').textContent = meta.qty ?? '');
        $('#buyPrice') && ($('#buyPrice').textContent = meta.buy_price ?? '');
        if (meta.qty && meta.buy_price) {
          $('#cost') && ($('#cost').textContent = (meta.qty * meta.buy_price).toLocaleString());
        }
        $('#tags') && ($
