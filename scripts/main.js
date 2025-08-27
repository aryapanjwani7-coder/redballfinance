// scripts/main.js
(function () {
  const $ = sel => document.querySelector(sel);
  const $$ = sel => Array.from(document.querySelectorAll(sel));

  const toSlug = (s) =>
    String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');

  const jfetch = async (path) => {
    const res = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  };

  const localCur = (symbol) =>
    /\.NS$|\.BO$/i.test(symbol || '') ? 'INR' : 'USD';

  const curSym = (ccy) => ccy === 'INR' ? '₹' : '$';
  const fmt = (n) => Number(n ?? 0).toLocaleString();

  function fromPositions(positions, stocks) {
    const stockBySym = Object.fromEntries(stocks.map(s => [s.symbol || s.ticker, s]));
    return positions.map(p => {
      const s = stockBySym[p.symbol] || {};
      const slug = s.slug || toSlug(s.name || (p.symbol || '').split('.')[0]);
      const name = s.name || (p.symbol || '').split('.')[0];
      const tags = s.tags || [];
      const ccy = localCur(p.symbol);
      return {
        symbol: p.symbol,
        name,
        slug,
        tags,
        buy_date: p.buy_date,
        qty: p.qty,
        buy_price_local: `${curSym(ccy)}${fmt(p.buy_price_local)} ${ccy}`,
        cost_local: `${curSym(ccy)}${fmt(p.cost_local)} ${ccy}`
      };
    });
  }

  function fromStocksOnly(stocks) {
    return stocks.map(s => {
      const slug = s.slug || toSlug(s.name || (s.symbol || s.ticker || '').split('.')[0]);
      const ccy = localCur(s.symbol || s.ticker);
      const cost = (s.qty && s.buy_price) ? s.qty * s.buy_price : 0;
      return {
        symbol: s.symbol || s.ticker,
        name: s.name || (s.symbol || '').split('.')[0],
        slug,
        tags: s.tags || [],
        buy_date: s.buy_date || '',
        qty: s.qty ?? '',
        buy_price_local: (s.buy_price != null) ? `${curSym(ccy)}${fmt(s.buy_price)} ${ccy}` : '',
        cost_local: `${curSym(ccy)}${fmt(cost)} ${ccy}`
      };
    });
  }

  function renderPortfolioTable(rows) {
    const tbody = $('#portfolioTable tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    for (const r of rows) {
      const tr = document.createElement('tr');

      const tSymbol = document.createElement('td'); tSymbol.textContent = r.symbol;
      const tName   = document.createElement('td'); tName.textContent   = r.name;
      const tDate   = document.createElement('td'); tDate.textContent   = r.buy_date || '';
      const tQty    = document.createElement('td'); tQty.textContent    = fmt(r.qty);
      const tBuy    = document.createElement('td'); tBuy.textContent    = r.buy_price_local || '';
      const tCost   = document.createElement('td'); tCost.textContent   = r.cost_local || '';
      const tTags   = document.createElement('td'); tTags.textContent   = Array.isArray(r.tags) ? r.tags.join(', ') : (r.tags || '');

      const tLink = document.createElement('td');
      const a = document.createElement('a');
      a.href = `stock.html?slug=${encodeURIComponent(r.slug)}`;
      a.textContent = 'Read report';
      tLink.appendChild(a);

      tr.append(tSymbol, tName, tDate, tQty, tBuy, tCost, tTags, tLink);
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
      const c = document.createElement('a');
      c.className = 'card card-link';
      c.href = `stock.html?slug=${encodeURIComponent(r.slug)}`;
      c.innerHTML = `
        <h3><span style="text-decoration:underline">${r.name}</span> <span class="meta">(${r.symbol})</span></h3>
        <p class="meta">Bought ${r.buy_date}</p>
        <p class="note">Qty: ${fmt(r.qty)} • Cost: ${r.cost_local}</p>
      `;
      grid.appendChild(c);
    }
  }

  function wireFilters(rows) {
    const search = $('#search');
    const tagFilter = $('#tagFilter');

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

      const useRows = (Array.isArray(positions) && positions.length > 0)
        ? fromPositions(positions, stocks)
        : fromStocksOnly(stocks);

      renderPortfolioTable(useRows);
      renderRecent(useRows);
      wireFilters(useRows);

      const now = new Date();
      const y = $('#year'); if (y) y.textContent = now.getFullYear();
    } catch (e) {
      console.error('main.js error:', e);
    }
  }

  main();
})();
