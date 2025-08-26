// scripts/main.js
(function () {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // Turn a name/symbol/ticker into a clean slug like "coal-india"
  const toSlug = (s) =>
    String(s || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");

  // Helper to safely read .textContent
  const setText = (sel, val) => { const el = $(sel); if (el) el.textContent = val ?? ""; };

  async function loadJSON(path) {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  }

  function computeSlug(stock) {
    // Prefer explicit slug if present
    if (stock.slug) return toSlug(stock.slug);
    // Try name, then ticker, then symbol-without-exchange
    const sym = stock.symbol || stock.ticker || "";
    const symNoEx = String(sym).split(".")[0];
    return toSlug(stock.name || stock.ticker || symNoEx || sym);
  }

  function fmtCurrency(n) {
    if (!Number.isFinite(+n)) return "";
    return Number(n).toLocaleString();
  }

  function addRow(tbody, stock) {
    const slug = computeSlug(stock);
    const sym = stock.symbol || stock.ticker || "";
    const name = stock.name || sym;
    const buyDate = stock.buy_date || "";
    const qty = stock.qty ?? "";
    const buyPrice = stock.buy_price ?? "";
    const cost = (Number(qty) && Number(buyPrice)) ? (qty * buyPrice) : "";

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${sym}</td>
      <td>${name}</td>
      <td>${buyDate}</td>
      <td>${qty}</td>
      <td>${buyPrice}</td>
      <td>${fmtCurrency(cost)}</td>
      <td>${Array.isArray(stock.tags) ? stock.tags.join(", ") : (stock.tags || "")}</td>
      <td><a class="btn small" href="stock.html?slug=${encodeURIComponent(slug)}">Read report</a></td>
    `;
    tbody.appendChild(tr);
  }

  function addRecentCard(grid, stock) {
    const slug = computeSlug(stock);
    const sym = stock.symbol || stock.ticker || "";
    const name = stock.name || sym;
    const buyDate = stock.buy_date || "";
    const cost = (Number(stock.qty) && Number(stock.buy_price))
      ? (stock.qty * stock.buy_price)
      : null;

    const div = document.createElement("div");
    div.className = "card soft";
    div.innerHTML = `
      <h4>${name}</h4>
      <p class="meta">${sym} • ${buyDate}</p>
      ${cost ? `<p class="meta">Cost: ${fmtCurrency(cost)}</p>` : ""}
      <a class="btn primary" href="stock.html?slug=${encodeURIComponent(slug)}">Read report</a>
    `;
    grid.appendChild(div);
  }

  async function renderPortfolio() {
    // 1) Load stocks
    let stocks = [];
    try {
      stocks = await loadJSON("data/stocks.json");
      if (!Array.isArray(stocks)) throw new Error("stocks.json must be an array");
    } catch (e) {
      console.error(e);
      const table = $("#portfolioTable tbody");
      if (table) table.innerHTML = `<tr><td colspan="8">Failed to load data/stocks.json</td></tr>`;
      return;
    }

    // 2) Table
    const tbody = document.querySelector("#portfolioTable tbody");
    if (tbody) {
      tbody.innerHTML = "";
      stocks.forEach(s => addRow(tbody, s));
    }

    // 3) Recent (take the last 3 by buy_date, if available)
    const grid = $("#recentGrid");
    if (grid) {
      grid.innerHTML = "";
      const withDate = stocks
        .map(s => ({ s, d: Date.parse(s.buy_date || "") || 0 }))
        .sort((a, b) => b.d - a.d)
        .slice(0, 3)
        .map(x => x.s);
      withDate.forEach(s => addRecentCard(grid, s));
    }

    // 4) Footer year
    setText("#year", new Date().getFullYear());
  }

  renderPortfolio();
})();
