// scripts/chart-nav.js
(async function drawNAV() {
  const canvas = document.getElementById('navChart');
  if (!canvas) return;

  try {
    const res = await fetch('data/nav.json', { cache: 'no-store' });
    if (!res.ok) {
      canvas.replaceWith(`NAV fetch failed (${res.status}). Check data/nav.json path.`);
      return;
    }
    const rows = await res.json();
    if (!Array.isArray(rows) || rows.length === 0) {
      canvas.replaceWith('NAV data not available (empty nav.json).');
      return;
    }

    // Auto-detect the nav key: prefer nav_usd, else any key that starts with "nav"
    const sample = rows[0] || {};
    const keys = Object.keys(sample);
    const navKey =
      keys.find(k => k.toLowerCase() === 'nav_usd') ||
      keys.find(k => /^nav(_|$)/i.test(k)); // e.g., nav, nav_inr, navIndex (we’ll filter later)

    if (!navKey) {
      canvas.replaceWith(`NAV data not available (no 'nav' field found). Keys: ${keys.join(', ')}`);
      return;
    }

    // Build points from whatever navKey is; only keep positive finite numbers
    const pts = rows
      .map(r => ({ x: new Date(r.date), y: Number(r[navKey]) }))
      .filter(p => p.x instanceof Date && !isNaN(p.x) && Number.isFinite(p.y) && p.y > 0)
      .sort((a, b) => a.x - b.x);

    if (pts.length === 0) {
      canvas.replaceWith(`NAV data not available (no valid '${navKey}' values > 0).`);
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
      data: { datasets: [{ label: 'Portfolio NAV', data: pts, borderWidth: 2, pointRadius: 0, tension: 0.2 }] },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true },
          tooltip: { callbacks: { label: (c) => ` NAV: ${c.parsed.y.toLocaleString()}` } }
        },
        scales: {
          x: { type: 'time', min: xMin, max: xMax, time: { unit: 'month' }, ticks: { maxTicksLimit: 8 } },
          y: { beginAtZero: false, suggestedMin, suggestedMax, ticks: { callback: v => Number(v).toLocaleString() } }
        }
      }
    });
  } catch (e) {
    console.error('NAV chart error:', e);
    canvas.replaceWith('NAV error — open console for details.');
  }
})();
