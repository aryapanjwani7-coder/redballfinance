const params = new URLSearchParams(location.search);
const slug = params.get('slug');

function $ (sel, el=document){ return el.querySelector(sel); }
function formatMoney(n){ return n?.toLocaleString(undefined,{style:'currency',currency:'INR'}) ?? '—'; }
function formatDate(d){ try { return new Date(d).toLocaleDateString(); } catch(e){ return d || '—'; } }

// If you also want your own Chart.js price line as a fallback, keep this flag true
const ENABLE_LOCAL_PRICE_LINE = false;

let metaItem = null;

async function loadMeta(){
  const res = await fetch('data/stocks.json?cb='+Date.now());
  const list = await res.json();
  const item = list.find(s => s.slug === slug);
  if(!item){
    $('#report').innerHTML = `<p>Report not found.</p>`;
    document.title = 'Report not found';
    return null;
  }
  metaItem = item;

  // Populate header + snapshot
  $('#stockName').textContent = item.name;
  $('#ticker').textContent = item.ticker;
  $('#buyDate').textContent = `Bought: ${formatDate(item.buy_date)}`;
  $('#tags').innerHTML = (item.tags||[]).map(t=>`<span class="tag">${t}</span>`).join(' ');
  $('#qty').textContent = item.qty ?? '—';
  $('#buyPrice').textContent = formatMoney(item.buy_price);
  $('#cost').textContent = formatMoney((item.qty||0) * (item.buy_price||0));
  $('#note').textContent = item.note || '';

  document.title = `${item.ticker} – ${item.name} | Report`;
  $('#titleTag')?.setAttribute('content', `${item.ticker} – ${item.name} report`);
  $('#year').textContent = new Date().getFullYear();
  return item;
}

async function loadReport(slug){
  try{
    const md = await (await fetch(`reports/${slug}.md?cb=${Date.now()}`)).text();
    // marked is already loaded in stock.html
    const html = marked.parse(md);
    $('#report').innerHTML = html;
  }catch(e){
    $('#report').innerHTML = `<p>Report markdown not found yet.</p>`;
  }
}

/** Derive TradingView symbol if not provided explicitly. */
function toTradingViewSymbol(item){
  if (item.tvSymbol && typeof item.tvSymbol === 'string') return item.tvSymbol.trim();

  const sym = (item.symbol || item.ticker || '').trim();
  if (!sym) return ''; // nothing to show

  // common India mappings
  if (sym.endsWith('.NS')) return `NSE:${sym.replace('.NS','')}`;
  if (sym.endsWith('.BO')) return `BSE:${sym.replace('.BO','')}`;

  // fall back to raw symbol (works for many global tickers already in TV format)
  return sym;
}

/** Render TradingView widget (waits for tv.js if needed). */
function renderTradingView(item){
  const container = document.getElementById('tv_chart');
  if (!container) return;

  const tvSymbol = toTradingViewSymbol(item);
  if (!tvSymbol){
    container.insertAdjacentHTML('afterend', `<p class="note">No TradingView symbol found for this stock.</p>`);
    return;
  }

  // Ensure tv.js is available
  const start = Date.now();
  (function waitForTV(){
    if (window.TradingView && typeof window.TradingView.widget === 'function'){
      // Use a unique container id to avoid collisions if you ever add multiple widgets
      const cid = 'tv_chart_' + Math.random().toString(36).slice(2,8);
      container.id = cid;

      // Create the widget
      new TradingView.widget({
        width: "100%",
        height: 420,
        symbol: tvSymbol,        // <-- auto-picked per stock
        interval: "D",
        timezone: "Asia/Singapore",
        theme: "dark",
        style: "1",              // 1 = bars; 3 = area; 9 = Heikin Ashi, etc.
        locale: "en",
        hide_side_toolbar: false,
        allow_symbol_change: false,
        studies: [],
        container_id: cid
      });
    } else if (Date.now() - start < 8000) {
      // try again for up to ~8s
      setTimeout(waitForTV, 120);
    } else {
      container.insertAdjacentHTML('afterend', `<p class="note">Couldn’t load the TradingView widget. Please refresh.</p>`);
    }
  })();
}

/** Optional local price line as fallback (reads your JSON built by GH Actions). */
async function renderLocalPriceLine(item){
  if (!ENABLE_LOCAL_PRICE_LINE) return;
  try{
    const sym = encodeURIComponent(item.symbol || item.ticker);
    const res = await fetch(`data/quotes/${sym}.json?cb=${Date.now()}`);
    if(!res.ok) throw new Error('No quotes');
    const quotes = await res.json();
    if(!quotes.length) throw new Error('Empty quotes');

    // Lazy-load Chart.js only if needed
    if (!window.Chart){
      await new Promise((resolve, reject)=>{
        const s = document.createElement('script');
        s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4';
        s.onload = resolve; s.onerror = reject;
        document.body.appendChild(s);
      });
    }

    const wrap = document.createElement('section');
    wrap.className = 'card soft';
    wrap.innerHTML = `
      <h3>Price (backup)</h3>
      <canvas id="priceChart" height="120"></canvas>
      <p class="note">Static fallback from cached JSON.</p>
    `;
    const main = document.querySelector('main.container');
    main.insertBefore(wrap, main.firstChild.nextSibling); // after hero card if present

    const ctx = document.getElementById('priceChart').getContext('2d');
    new Chart(ctx, {
      type: 'line',
      data: {
        labels: quotes.map(r => new Date(r.date)),
        datasets: [{ data: quotes.map(r => r.close), tension: 0.2, pointRadius: 0, borderWidth: 2 }]
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        scales: { x: { type: 'time', time: { unit: 'month' } }, y: {} },
        plugins: { legend: { display: false } }
      }
    });
  }catch(e){
    // silently ignore; TradingView is primary
  }
}

(async function init(){
  if(!slug){
    $('#report').innerHTML = `<p>No slug provided.</p>`;
    return;
  }
  const item = await loadMeta();
  if(item){
    await loadReport(slug);
    renderTradingView(item);
    renderLocalPriceLine(item); // optional backup
  }
})();
