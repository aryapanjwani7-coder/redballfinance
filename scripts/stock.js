const params = new URLSearchParams(location.search);
const slug = params.get('slug');

function $ (sel, el=document){ return el.querySelector(sel); }
function formatMoney(n){ return n?.toLocaleString(undefined,{style:'currency',currency:'INR'}) ?? '—'; }
function formatDate(d){ try { return new Date(d).toLocaleDateString(); } catch(e){ return d || '—'; } }

async function loadMeta(){
  const res = await fetch('data/stocks.json?cb='+Date.now());
  const list = await res.json();
  const item = list.find(s => s.slug === slug);
  if(!item){
    $('#report').innerHTML = `<p>Report not found.</p>`;
    document.title = 'Report not found';
    return null;
  }
  $('#stockName').textContent = item.name;
  $('#ticker').textContent = item.ticker;
  $('#buyDate').textContent = `Bought: ${formatDate(item.buy_date)}`;
  $('#tags').innerHTML = (item.tags||[]).map(t=>`<span class="tag">${t}</span>`).join(' ');
  $('#qty').textContent = item.qty ?? '—';
  $('#buyPrice').textContent = formatMoney(item.buy_price);
  $('#cost').textContent = formatMoney((item.qty||0) * (item.buy_price||0));
  $('#note').textContent = item.note || '';
  document.title = `${item.ticker} – ${item.name} | Report`;
  $('#titleTag').setAttribute('content', `${item.ticker} – ${item.name} report`);
  $('#year').textContent = new Date().getFullYear();
  return item;
}

async function loadReport(slug){
  try{
    const md = await (await fetch(`reports/${slug}.md?cb=${Date.now()}`)).text();
    const html = marked.parse(md);
    $('#report').innerHTML = html;
  }catch(e){
    $('#report').innerHTML = `<p>Report markdown not found yet.</p>`;
  }
}

(async function init(){
  if(!slug){
    $('#report').innerHTML = `<p>No slug provided.</p>`;
    return;
  }
  const item = await loadMeta();
  if(item) await loadReport(slug);
})();
