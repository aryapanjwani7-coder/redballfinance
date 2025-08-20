async function loadJSON(path){
  const res = await fetch(path + "?cb=" + Date.now());
  if(!res.ok) throw new Error("Failed to load " + path);
  return res.json();
}

function fmtDateISO(d){ return new Date(d); }

async function initNAV(){
  try{
    const nav = await loadJSON("data/nav.json");
    const labels = nav.map(r => fmtDateISO(r.date));
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
          y: { ticks: { callback: v => v.toFixed ? v.toFixed(0) : v } }
        },
        plugins: { legend: { display: false } }
      }
    });
  }catch(e){
    console.error(e);
    const el = document.getElementById("navChart");
    el.insertAdjacentHTML("afterend", `<p class="note">NAV data not available yet.</p>`);
  }
}

initNAV();
