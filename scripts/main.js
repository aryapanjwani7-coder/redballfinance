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

  function mergePositionsAndStocks(positions, stocks) {
    const stockBySym = Object.fromEntries(stocks.map(s => [s.symbol || s.ticker, s]));
    return positions.map(p => {
      const s = stockBySym[p.symbol] || {};
      const slug = s.slug || toSlug(s.name || (p.symbol || '').split('.')[0]);
      const name = s.name || (p.symbol || '').split('.')[0];
      const tags = s.tags || [];
      return {
        symbol: p.symbol,
        name,
        slug,
        tags,
        buy_date: p.buy_date,
        qty: p.qty,
        buy_price_local: p.buy_price_local,
        cost_local: p.cost_local
      };
    });
  }

  function renderPortfolioTable(rows) {
    const tbody = $('#portfolioTable tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    for (const r of rows) {
      const tr = document.createElement('tr');

      const tSymbol = document.createElement('td');
      tSymbol.textContent = r.symbol;

      const tName = document.createElement('td');
      tName.textContent = r.name;

      const tDate = document.createElement('td');
      tDate.textContent = r.buy_date || '';

      const tQty = document.createElement('td');
      tQty.textContent = Number(r.qty ?? 0).toLocaleString();

      const tBuyPrice = document.createElement('td');
      tBuyPrice.textContent = (r.buy_price_local ?? '').toString();

      const tCost = document.createElement('td');
      tCost.textContent = Number(r.cost_local ?? 0).toLocaleString();

      const tTags = document.createElement('td');
      tTags.textContent = Array.isArray(r.tags) ? r.tags.join(', ') : (r.tags || '');

      const tReport = document.createElement('td');
      const a = document.createElement('a');
      a.href = `stock.html?slug=${encodeURIComponent(r.slug)}`;
      a.textContent = 'Read report';
      tReport.appendChild(a);

      tr.append(tSymbol, tName, tDate, tQty, tBuyPrice, tCost, tTags, tReport);
      tbody.appendChild(tr);
    }
  }

  function renderRecent(rows) {
    const grid = $('#recentGrid');
    if (!grid) return;
    grid.innerHTML = '';

    // sort by buy_date desc, pick top 6
    const sorted = rows
      .filter(r => r.buy_date)
      .sort((a, b) => new Date(b.buy_date) - new Date(a.buy_date))
      .slice(0, 6);

    for (const r of sorted) {
      const card = document.createElement('a');
      card.className = 'card card-link';
      card.href = `stock.html?slug=${encodeURIComponent(r.slug)}`;
      card.innerHTML = `
        <h3>${r.name} <span class="meta">(${r.symbol})</span></h3>
        <p class="meta">Bought ${r.buy_date}</p>
        <p class="note">Qty: ${Number(r.qty ?? 0).toLocaleString()} • Cost: ${Number(r.cost_local ?? 0).toLocaleString()}</p>
      `;
      grid.appendChild(card);
    }
  }

  function wireFilters(rows) {
    const search = $('#search');
    const tagFilter = $('#tagFilter');

    // Build tag options
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

      renderPortfolioTable(merged);
      renderRecent(merged);
      wireFilters(merged);

      // Footer year
      const now = new Date();
      $('#year') && ($('#year').textContent = now.getFullYear());
    } catch (e) {
      console.error('main.js error:', e);
    }
  }

  main();
})();
