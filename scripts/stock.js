// scripts/stock.js

// Read slug from URL (?slug=your-stock-slug)
const params = new URLSearchParams(location.search);
const slug = params.get('slug');

// Tiny helpers
function $ (sel, el=document){ return el.querySelector(sel); }
function formatMoney(n){ return n?.toLocaleString(undefined,{style:'currency',currency:'INR'}) ?? '—'; }
function formatDate(d){ try { return new Date(d).toLocaleDateString(); } catch(e){ return d || '—'; } }

let metaItem = null;

// Generic JSON loader with cache-bust
async function loadJSON(path){
  const res = await fetch(path + "?cb=" + Date.now());
  if(!res.ok) throw new Error("Fetch failed " + path);
  return res.json();
}

// Load metadata for this stock (from data/stocks.json) and fill the header
async function loadMeta(){
  const list = await loadJSON('data/stocks.json');
  const item = list.find(s => s.slug === slug);
  if(!item) throw new Error("Report not found for slug " + slug);
  metaItem = item;

  $('#stockName').textContent = item.name;
  $('#ticker').textContent   = item.ticker;
  $('#buyDate').textContent  = `Bought: ${formatDate(item.buy_date)}`;
  $('#tags').innerHTML       = (item.tags||[]).map(t=>`<span class="tag">${t}</span>`).join(' ');
  $('#qty').textContent      = item.qty ?? '—';
  $('#buyPrice').textContent = formatMoney(item.buy_price);
  $('#cost').textContent     = formatMoney((item.qty||0) * (item.buy_price||0));
  $('#note').textContent     = item.note || '';

  document.title             = `${item.ticker} – ${item.name} | Report`;
  $('#titleTag')?.setAttribute('content', `${item.ticker} – ${item.name} report`);
  $('#year').textContent     = new Date().getFullYear();
}

// Load the markdown report and render with marked.js
async function loadReport(){
  try{
    const md = await (await fetch(`reports/${slug}.md?cb=${Date.now()}`)).text();
    const html = marked.parse(md);
    $('#report').innerHTML = html;
  }catch{
    $('#report').innerHTML = `<p>Report markdown not found yet.</p>`;
  }
}

// Draw the local price chart (from data/quotes/<symbol>.json) + buy price line
async function drawPriceChart(){
  const note = $('#priceNote');
  try{
    const sym = encodeURIComponent(metaItem.symbol || metaItem.ticker);
    const quotes = await loadJSON(`data/quotes/${sym}.json`);
    if(!quotes.length) throw new Error('No quotes');

    const labels = quotes.map(r => new Date(r.date));
    const closeSeries = quotes.map(r => r.close);

    // Base dataset = close prices
    const datasets = [{
      label: "Close price",
      data: closeSeries,
      tension: 0.2,
      pointRadius: 0,
      borderWidth: 2
    }];

    // Optional dashed line at your buy price (flat across the whole chart)
    const buyPriceNum = Number(metaItem.buy_price);
    if (!Number.isNaN(buyPriceNum) && buyPriceNum > 0){
      datasets.push({
        label: "Buy price",
        data: quotes.map(() => buyPriceNum),
        borderWidth: 1,
        borderDash: [6, 4],
        pointRadius: 0,
        borderColor: "red" // make it obvious; remove if you prefer auto colors
      });
    }

    const ctx = document.getElementById('priceChart').getContext('2d');
    new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { type: 'time', time: { unit: 'month' }, ticks: { maxTicksLimit: 8 } },
          y: { beginAtZero: false }
        },
        plugins: {
          legend: { display: true } // shows "Close price" + "Buy price"
        }
      }
    });

    if (note) note.textContent = "Auto-updated daily from cached closes.";
  }catch(e){
    console.error(e);
    if (note) note.textContent = "Price data not available yet. Make sure data/quotes/<symbol>.json exists.";
  }
}

// Bootstrap the page
(async function init(){
  if(!slug){
    $('#report').innerHTML = `<p>No slug provided.</p>`;
    return;
  }
  try{
    await loadMeta();
    await loadReport();
    await drawPriceChart();
  }catch(e){
    console.error(e);
    $('#report').innerHTML = `<p>${e.message}</p>`;
  }
})();
