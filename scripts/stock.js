// scripts/stock.js
(function () {
  const $ = sel => document.querySelector(sel);
  const params = new URLSearchParams(location.search);
  const urlSymbol = params.get('symbol');
  const urlSlug   = params.get('slug');

  const toSlug = (s) =>
    String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');

  const curFor = (symbol) => (/\.NS$|\.BO$/i.test(symbol||'')) ? 'INR' : 'USD';
  const symFor = (ccy) => ccy === 'INR' ? '₹' : '$';
  const fmt    = (n) => Number(n ?? 0).toLocaleString();

  const jfetch = async (path) => {
    const res = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  };

  function normalizeLoose(s){return String(s||'').toLowerCase().replace(/[^a-z0-9]+/g,'')}

  async function resolveTarget() {
    const [positions, stocks] = await Promise.all([
      jfetch('data/positions.json').catch(() => []),
      jfetch('data/stocks.json').catch(() => [])
    ]);
    const posBySymbol = Object.fromEntries(positions.map(p => [p.symbol, p]));

    if (urlSymbol) {
      const st = stocks.find(s => (s.symbol || s.ticker) === urlSymbol) || {};
      return { symbol: urlSymbol, pos: posBySymbol[urlSymbol] || null, stockMeta: st, slug: st.slug || toSlug(st.name || urlSymbol.split('.')[0]) };
    }
    if (urlSlug) {
      const want = normalizeLoose(urlSlug);
      for (const p of positions) {
        const base = (p.symbol || '').split('.')[0];
        if (normalizeLoose(base) === want) {
          const st = stocks.find(s => (s.symbol || s.ticker) === p.symbol) || {};
          return { symbol: p.symbol, pos: p, stockMeta: st, slug: st.slug || toSlug(st.name || base) };
        }
      }
      for (const s of stocks) {
        const sSym = s.symbol || s.ticker || '';
        const base = sSym.split('.')[0];
        const cands = [s.slug, s.name, sSym, base].filter(Boolean).map(normalizeLoose);
        if (cands.includes(want)) {
          return { symbol: sSym, pos: posBySymbol[sSym] || null, stockMeta: s, slug: s.slug || toSlug(s.name || base) };
        }
      }
    }
    return null;
  }

  async function renderReport(symbol, slug, stockMeta) {
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
        $('#stockName')?.replaceChildren(document.createTextNode(title));
        document.title = `${title} – Stock Report`;
        return;
      } catch {}
    }
    const title = stockMeta?.name || symbol || slug || 'Stock Report';
    $('#stockName')?.replaceChildren(document.createTextNode(title));
    $('#report')?.replaceChildren(document.createTextNode('Report not found.'));
  }

  async function drawPriceChart(symbol, buyPriceLocal, buyDate) {
    const canvas = $('#priceChart'); if (!canvas) return;
    let quotes;
    try { quotes = await jfetch(`data/quotes/${encodeURIComponent(symbol)}.json`); }
    catch (e) { console.error(e); canvas.replaceWith(`Price fetch failed for ${symbol}.`); return; }

    const pts = quotes
      .filter(r => r && r.date && Number.isFinite(+r.close))
      .map(r => ({ x: new Date(r.date), y: Number(r.close) }))
      .sort((a,b) => a.x - b.x);

    if (!pts.length) { canvas.replaceWith('Price data not available.'); return; }

    const xMin = pts[0].x, xMax = pts[pts.length-1].x;
    const ys = pts.map(p => p.y);
    const buy = Number.isFinite(+buyPriceLocal) ? +buyPriceLocal : NaN;
    const yMin = Math.min(...ys, Number.isFinite(buy) ? buy : Infinity);
    const yMax = Math.max(...ys, Number.isFinite(buy) ? buy : -Infinity);
    const pad = (yMax - yMin) * 0.08 || Math.max(1, yMax * 0.08);
    const suggestedMin = Math.max(0, yMin - pad), suggestedMax = yMax + pad;

    const buyLine = Number.isFinite(buy) ? [{x:xMin,y:buy},{x:xMax,y:buy}] : [];
    const ccy = curFor(symbol);

    new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        datasets: [
          { label: `${symbol} Close (${ccy})`, data: pts, borderWidth: 2, pointRadius: 0, tension: 0.2 },
          ...(buyLine.length ? [{ label: `Buy (${ccy})`, data: buyLine, borderDash:[6,6], borderWidth: 1.5, pointRadius: 0 }] : [])
        ]
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true },
          tooltip: { callbacks: {
            label: (c) => `${c.dataset.label}: ${symFor(ccy)}${c.parsed.y.toLocaleString()}`
          }}
        },
        scales: {
          x: { type: 'time', min:xMin, max:xMax, time:{unit:'month'}, ticks:{maxTicksLimit:8} },
          y: { beginAtZero:false, suggestedMin, suggestedMax }
        }
      }
    });

    const note = $('#priceNote');
    if (note) {
      if (Number.isFinite(buy) && buyDate) {
        note.textContent = `Red dotted line marks buy at ${symFor(ccy)}${fmt(buy)} ${ccy} on ${buyDate}.`;
      } else {
        note.textContent = `Showing ${ccy} price.`;
      }
    }
  }

  async function main() {
    const now = new Date(); const y = $('#year'); if (y) y.textContent = now.getFullYear();

    const chosen = await resolveTarget();
    if (!chosen) {
      const msg = urlSlug
        ? `Unknown slug "${urlSlug}".`
        : (urlSymbol ? `Unknown symbol "${urlSymbol}".` : 'Missing ?slug= or ?symbol=');
      $('#priceChart')?.replaceWith(msg);
      return;
    }
    const { symbol, pos, stockMeta, slug } = chosen;

    $('#ticker') && ($('#ticker').textContent = symbol);
    const ccy = curFor(symbol);

    if (pos) {
      $('#buyDate')  && ($('#buyDate').textContent  = pos.buy_date || '');
      $('#qty')      && ($('#qty').textContent      = fmt(pos.qty));
      $('#buyPrice') && ($('#buyPrice').textContent = `${symFor(ccy)}${fmt(pos.buy_price_local)} ${ccy}`);
      if (Number.isFinite(+pos.cost_local)) {
        $('#cost') && ($('#cost').textContent = `${symFor(ccy)}${fmt(pos.cost_local)} ${ccy}`);
      }
    } else {
      // fallback to stocks.json if positions missing
      const qty = stockMeta?.qty, bp = stockMeta?.buy_price, bd = stockMeta?.buy_date;
      $('#buyDate')  && ($('#buyDate').textContent  = bd || '');
      $('#qty')      && ($('#qty').textContent      = (qty ?? '').toString());
      $('#buyPrice') && ($('#buyPrice').textContent = (bp != null ? `${symFor(ccy)}${fmt(bp)} ${ccy}` : ''));
      if (qty && bp) $('#cost') && ($('#cost').textContent = `${symFor(ccy)}${fmt(qty*bp)} ${ccy}`);
    }

    await renderReport(symbol, slug, stockMeta);
    await drawPriceChart(symbol, pos?.buy_price_local ?? stockMeta?.buy_price, pos?.buy_date ?? stockMeta?.buy_date);
  }

  main();
})();
