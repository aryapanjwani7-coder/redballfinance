async function loadJSON(path){
  const res = await fetch(path + "?cb=" + Date.now());
  if(!res.ok) throw new Error("Fetch failed " + path);
  return res.json();
}

function toDate(d){ return new Date(d); }

async function initNAV(){
  const note = document.getElementById("navNote");
  try{
    const nav = await loadJSON("data/nav.json");
    if(!Array.isArray(nav) || nav.length === 0) throw new Error("Empty nav.json");

    const labels = nav.map(r => toDate(r.date));
    const series = nav.map(r => r.nav_index ?? null);

    const ctx = document.getElementById("navChart").getContext("2d");
    new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "NAV (Index = 100)",
          data: series,
          tension: 0.2,
          pointRadius: 0,
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { type: "time", time: { unit: "month" }, ticks: { maxTicksLimit: 8 } },
          y: { beginAtZero: false, ticks: { callback: v => Math.round(v) } }
        },
        plugins: { legend: { display: false } }
      }
    });
    if (note) note.textContent = "Indexed to 100 at first buy date. Auto-updates daily.";
  }catch(e){
    console.error(e);
    if (note) note.textContent = "NAV data not available yet. If this is a fresh setup, generate data once (see steps below).";
  }
}

initNAV();
