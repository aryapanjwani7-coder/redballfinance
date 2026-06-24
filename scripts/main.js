// scripts/main.js
(function () {
  const $ = sel => document.querySelector(sel);

  const toSlug = (s) =>
    String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');

  // Indian-style rupee formatting (lakh/crore grouping)
  const inr = (n, dp = 0) =>
    '₹' + Number(n ?? 0).toLocaleString('en-IN', { maximumFractionDigits: dp, minimumFractionDigits: dp });
  const pct = (n) => (n == null ? '—' : `${n >= 0 ? '+' : ''}${Number(n).toFixed(2)}%`);
  const signClass = (n) => (n == null ? '' : (n >= 0 ? 'pos' : 'neg'));

  const jfetch = async (path) => {
    const res = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  };

  function mergePositionsAndStocks(positions, stocks) {
    const stockBySym = Object.fromEntries(stocks.map(s => [s.symbol || s.ticker, s]));
    return positions.map(p => {
      const s = stockBySym[p.symbol] || {};
      const slug = s.slug || toSlug(s.name || (p.symbol || '').split('.')[0]);
      const name = s.name || (p.symbol || '').split('.')[0];
      return {
        symbol: p.symbol,
        name,
        slug,
        tags: s.tags || [],
        buy_date: p.buy_date,
        qty: p.qty,
        buy_price_local: p.buy_price_local,
        cost_local: p.cost_local,
        last_price: p.last_price,
        market_value_local: p.market_value_local,
        dividends_local: p.dividends_local,
        pnl_local: p.pnl_local,
        pnl_pct: p.pnl_pct
      };
    });
  }

  function renderPortfolioTable(rows) {
    const tbody = $('#portfolioTable tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    for (const r of rows) {
      const tr = document.createElement('tr');
      const cell = (html, cls) => {
        const td = document.createElement('td');
        if (cls) td.className = cls;
        td.innerHTML = html;
        return td;
      };

      const reportLink = `<a href="stock.html?slug=${encodeURIComponent(r.slug)}">Report</a>`;
      const tags = Array.isArray(r.tags) ? r.tags.join(', ') : (r.tags || '');

      tr.append(
        cell(`<strong>${r.symbol.replace('.NS', '')}</strong><div class="meta">${r.name}</div>`),
        cell(r.buy_date || ''),
        cell(Number(r.qty ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 1 })),
        cell(inr(r.buy_price_local, 2)),
        cell(inr(r.cost_local)),
        cell(inr(r.market_value_local)),
        cell(r.dividends_local ? inr(r.dividends_local) : '—'),
        cell(`${pct(r.pnl_pct)}`, signClass(r.pnl_pct)),
        cell(`<span class="meta">${tags}</span>`),
        cell(reportLink)
      );
      tbody.appendChild(tr);
    }
  }

  function renderRecent(rows) {
    const grid = $('#recentGrid');
    if (!grid) return;
    grid.innerHTML = '';

    const sorted = rows
      .filter(r => r.buy_date)
      .sort((a, b) => new Date(b.buy_date) - new Date(a.buy_date))
      .slice(0, 6);

    for (const r of sorted) {
      const card = document.createElement('a');
      card.className = 'card card-link';
      card.href = `stock.html?slug=${encodeURIComponent(r.slug)}`;
      card.innerHTML = `
        <h3>${r.name} <span class="meta">(${r.symbol.replace('.NS', '')})</span></h3>
        <p class="meta">Bought ${r.buy_date} • ${Number(r.qty ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 1 })} shares</p>
        <p class="note ${signClass(r.pnl_pct)}">Now ${inr(r.market_value_local)} (${pct(r.pnl_pct)})</p>
      `;
      grid.appendChild(card);
    }
  }

  async function renderSummaryCard() {
    try {
      const sum = await jfetch('data/nav_summary.json');
      const L = sum?.latest || {};

      const set = (id, val, cls) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = val;
        if (cls !== undefined) el.className = cls;
      };

      set('navAmt', inr(L.nav));
      set('investedAmt', inr(L.invested));
      set('pnlAmt', `${pct(L.pnl_pct)} (${inr(L.pnl_abs)})`, signClass(L.pnl_pct));
      set('divAmt', L.dividends ? inr(L.dividends) : '—');
      const vsNifty = (L.pnl_pct != null && L.nifty_pnl_pct != null)
        ? L.pnl_pct - L.nifty_pnl_pct : null;
      set('benchAmt',
        L.nifty_pnl_pct == null ? '—' : `${pct(L.nifty_pnl_pct)} (you ${vsNifty >= 0 ? '+' : ''}${vsNifty?.toFixed(2)} pp)`,
        signClass(vsNifty));
      set('asOf', L.date || '—');
    } catch (e) {
      console.warn('summary card: could not read nav_summary.json', e);
    }
  }

  function wireFilters(rows) {
    const search = document.querySelector('#search');
    const tagFilter = document.querySelector('#tagFilter');
    if (!search || !tagFilter) { renderPortfolioTable(rows); return; }

    const tags = Array.from(new Set(rows.flatMap(r => Array.isArray(r.tags) ? r.tags : []))).sort();
    tagFilter.innerHTML = '<option value="">All tags</option>' + tags.map(t => `<option>${t}</option>`).join('');

    function apply() {
      const q = (search.value || '').toLowerCase();
      const t = tagFilter.value || '';
      const filtered = rows.filter(r => {
        const hitQ = !q || r.symbol.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q);
        const hitT = !t || (Array.isArray(r.tags) && r.tags.includes(t));
        return hitQ && hitT;
      });
      renderPortfolioTable(filtered);
    }

    search.addEventListener('input', apply);
    tagFilter.addEventListener('change', apply);
    apply();
  }

  async function main() {
    try {
      const [positions, stocks] = await Promise.all([
        jfetch('data/positions.json').catch(() => []),
        jfetch('data/stocks.json').catch(() => [])
      ]);
      const merged = mergePositionsAndStocks(positions, stocks);

      renderRecent(merged);
      wireFilters(merged);
      await renderSummaryCard();

      const y = document.getElementById('year');
      if (y) y.textContent = new Date().getFullYear();
    } catch (e) {
      console.error('main.js error:', e);
    }
  }

  main();
})();
