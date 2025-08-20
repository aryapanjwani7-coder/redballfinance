const $ = (sel, el=document) => el.querySelector(sel);
const $$ = (sel, el=document) => [...el.querySelectorAll(sel)];

const state = {
  stocks: [],
  filtered: []
};

function formatMoney(n){ return n?.toLocaleString(undefined,{style:'currency',currency:'INR'}) ?? '—'; }
function formatDate(d){ try { return new Date(d).toLocaleDateString(); } catch(e){ return d || '—'; } }

function renderTable(rows){
  const tbody = $('#portfolioTable tbody');
  tbody.innerHTML = rows.map(s => {
    const cost = s.qty * s.buy_price;
    const tags = (s.tags||[]).map(t=>`<span class="tag">${t}</span>`).join(' ');
    const reportLink = s.slug ? `<a href="stock.html?slug=${encodeURIComponent(s.slug)}">Open</a>` : '—';
    return `<tr>
      <td><strong>${s.ticker}</strong></td>
      <td>${s.name}</td>
      <td>${formatDate(s.buy_date)}</td>
      <td>${s.qty}</td>
      <td>${formatMoney(s.buy_price)}</td>
      <td>${formatMoney(cost)}</td>
      <td>${tags}</td>
      <td>${reportLink}</td>
    </tr>`;
  }).join('');
}

function renderRecent(stocks){
  const container = $('#recentGrid');
  // Sort by buy_date desc, take 6
  const recent = [...stocks].sort((a,b)=>new Date(b.buy_date)-new Date(a.buy_date)).slice(0,6);
  container.innerHTML = recent.map(s=>`
    <div class="card-mini">
      <div class="tag">${s.ticker}</div>
      <h4>${s.name}</h4>
      <p class="note">${s.thesis_short || ''}</p>
      <a href="stock.html?slug=${encodeURIComponent(s.slug)}">Read report →</a>
    </div>
  `).join('');
}

function populateTags(stocks){
  const unique = [...new Set(stocks.flatMap(s => s.tags || []))];
  const sel = $('#tagFilter');
  unique.sort().forEach(t=>{
    const opt = document.createElement('option');
    opt.value = t; opt.textContent = t;
    sel.appendChild(opt);
  });
}

function applyFilters(){
  const q = $('#search').value.trim().toLowerCase();
  const tag = $('#tagFilter').value;
  state.filtered = state.stocks.filter(s=>{
    const matchesQ = !q || (s.ticker.toLowerCase().includes(q) || s.name.toLowerCase().includes(q));
    const matchesTag = !tag || (s.tags||[]).includes(tag);
    return matchesQ && matchesTag;
  });
  renderTable(state.filtered);
}

async function init(){
  $('#year').textContent = new Date().getFullYear();

  const res = await fetch('data/stocks.json?cachebust='+Date.now());
  state.stocks = await res.json();
  state.filtered = state.stocks;

  populateTags(state.stocks);
  renderTable(state.stocks);
  renderRecent(state.stocks);

  $('#search').addEventListener('input', applyFilters);
  $('#tagFilter').addEventListener('change', applyFilters);
}

init();

