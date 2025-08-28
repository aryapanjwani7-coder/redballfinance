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
    // Try many sensible file names so you don't get stuck on exact casing
    const baseFromName = stockMeta?.name ? toSlug(stockMeta.name) : '';
    const symKebab = String(symbol || '').replace(/\./g, '-');
    const candidates = [
      `reports/${slug}.md`,
      `reports/${slug}.markdown`,
      `reports/${symKebab}.md`,
      `reports/${(symbol||'').toUpperCase()}.md`,
      `reports/${(symbol||'')}.md`,
      baseFromName ? `reports/${baseFromName}.md` : null,
    ].filter(Boolean);

    const tried = [];
    for (const path of candidates) {
      try {
        const resp = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
        tried.push(path);
        if (!resp.ok) continue;
        const md = await resp.text();
        $('#report').innerHTML = marked.parse(md);
        const h1 = md.match(/^#\s+(.+)/m);
        const title = h1 ? h1[1].trim() : (stockMeta?.name || symbol || slug || 'Stock Report');
        $('#stockName')?.replaceChildren(document.createTextNode(title));
        document.title = `${title} – Stock Report`;
        console.info('[report] loaded:', path);
        return;
      } catch (e) {
        console.warn('[report] fetch failed:', path, e);
      }
    }
    const title = stockMeta?.name || symbol || slug || 'Stock Report';
    $('#stockName')?.replaceChildren(document.createTextNode(title));
    $('#report')?.replaceChildren(document.createTextNode('Report not found.'));
    console.error('[report] not found. Tried:', tried);
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

  async function drawCashflowBridge(symbol, slug) {
    const el = document.getElementById('cashFlowChart');
    if (!el) return;

    const paths = [
      `data/cashflows/${encodeURIComponent(symbol)}.json`,
      `data/cashflows/${encodeURIComponent(symbol.replace(/\./g,'-'))}.json`,
      slug ? `data/cashflows/${encodeURIComponent(slug)}.json` : null
    ].filter(Boolean);

    let data=null, used=null, tried=[];
    for (const p of paths) {
      try {
        const res = await fetch(`${p}?v=${Date.now()}`, { cache: 'no-store' });
        tried.push(p);
        if (!res.ok) continue;
        data = await res.json(); used=p; break;
      } catch {}
    }
    if (!data) { console.warn('[cashflow] no JSON found. Tried:', tried); return; }

    const years = (data.years || []).slice(0, 3);
    if (years.length < 3) { console.warn('[cashflow] need 3 years for bridge:', data); return; }

    const s0 = Number(years[0].ocf), s1 = Number(years[1].ocf), s2 = Number(years[2].ocf);
    if (![s0,s1,s2].every(n => Number.isFinite(n))) { console.warn('[cashflow] non-numeric totals'); return; }

    const d1 = s1 - s0, d2 = s2 - s1;
    const labels = [years[0].year, `${years[1].year} Δ`, `${years[2].year} Δ`, years[2].year];

    const base = [0, (d1 >= 0 ? s0 : s0 + d1), (d2 >= 0 ? s1 : s1 + d2), 0];
    const pos  = [0, (d1 > 0 ? d1 : 0),        (d2 > 0 ? d2 : 0),        0];
    const neg  = [0, (d1 < 0 ? -d1 : 0),       (d2 < 0 ? -d2 : 0),       0];
    const totals = [s0, 0, 0, s2];

    const ccy = (/\.NS$|\.BO$/i.test(symbol) ? 'INR' : 'USD');
    const sym = (ccy === 'INR' ? '₹' : '$');
    const unit = data.unit || '';

    new Chart(el.getContext('2d'), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'Base', data: base, backgroundColor: 'rgba(0,0,0,0)', stack: 'bridge', borderSkipped: false },
          { label: 'Increase', data: pos, backgroundColor: 'rgba(0, 208, 156, 0.9)', stack: 'bridge', borderSkipped: false },
          { label: 'Decrease', data: neg, backgroundColor: 'rgba(255, 107, 107, 0.9)', stack: 'bridge', borderSkipped: false },
          { label: 'Total', data: totals, backgroundColor: 'rgba(138, 208, 255, 0.85)', stack: 'totals', borderSkipped: false }
        ]
      },
      options: {
        responsive: true,
        scales: {
          x: { stacked: true },
          y: { stacked: false, beginAtZero: true }
        },
        plugins: {
          legend: { display: true },
          tooltip: {
            callbacks: {
              label(ctx) {
                const v = ctx.parsed.y;
                return `${ctx.dataset.label}: ${sym}${Number(v).toLocaleString()} ${ccy}${unit ? ' ' + unit : ''}`;
              }
            }
          }
        }
      }
    });

    const note = document.getElementById('cashFlowNote');
    if (note) {
      note.textContent = `Bridge built from totals: ${years[0].year} ${sym}${s0.toLocaleString()} → ${years[1].year} ${sym}${s1.toLocaleString()} → ${years[2].year} ${sym}${s2.toLocaleString()} (${ccy}${unit ? ' ' + unit : ''}).`;
    }
    console.info('[cashflow] loaded:', used);
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
    }

    await renderReport(symbol, slug, stockMeta);
    await drawPriceChart(symbol, pos?.buy_price_local ?? stockMeta?.buy_price, pos?.buy_date ?? stockMeta?.buy_date);
    await drawCashflowBridge(symbol, slug);
  }

  main();
})();
