// scripts/chart-nav.js
(async function drawNAV() {
  const canvas = document.getElementById('navChart');
  if (!canvas) return;

  try {
    // ✅ relative path (no leading slash)
    const res = await fetch('data/nav.json', { cache: 'no-store' });
    if (!res.ok) {
      canvas.replaceWith(`NAV fetch failed (${res.status}). Check data/nav.json path.`);
      return;
    }
    const rows = await res.json();

    const pts = rows
      .filter(r => r && r.date && Number.isFinite(+r.nav_usd) && +r.nav_usd > 0)
      .map(r => ({ x: new Date(r.date), y: Number(r.nav_usd) }))
      .sort((a, b) => a.x - b.x);

    if (pts.length === 0) {
      canvas.replaceWith('NAV data not available (no valid points in data/nav.json).');
      return;
    }

    const xMin = pts[0].x;
    const xMax = pts[pts.length - 1].x;

    const ys = pts.map(p => p.y);
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);
    const pad = (yMax - yMin) * 0.05 || Math.max(1, yMax * 0.05);
    const suggestedMin = Math.max(0, yMin - pad);
    const suggestedMax = yMax + pad;

    new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [{
        label: 'Portfolio NAV (USD)',
        data: pts, borderWidth: 2, pointRadius: 0, tension: 0.2
      }]},
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true },
          tooltip: { callbacks: { label: (c) => ` NAV: $${c.parsed.y.toLocaleString()}` } }
        },
        scales: {
          x: { type: 'time', min: xMin, max: xMax, time: { unit: 'month' }, ticks: { maxTicksLimit: 8 } },
          y: { beginAtZero: false, suggestedMin, suggestedMax,
               ticks: { callback: v => '$' + Number(v).toLocaleString() } }
        }
      }
    });
  } catch (e) {
    console.error('NAV chart error:', e);
    canvas.replaceWith('NAV error — open console for details.');
  }
})();
