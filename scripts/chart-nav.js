// scripts/chart-nav.js
(function () {
  const canvas = document.getElementById('navChart');
  if (!canvas) return;

  // Parse "YYYY-MM-DD" safely as UTC
  function parseYMD(ymd) {
    if (!ymd || typeof ymd !== 'string') return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd.trim());
    if (!m) return null;
    const y = +m[1], mo = +m[2] - 1, d = +m[3];
    const dt = new Date(Date.UTC(y, mo, d));
    return isNaN(dt) ? null : dt;
  }

  async function jfetch(path) {
    // cache-bust to avoid stale CDN copies
    const res = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  }

  (async function draw() {
    try {
      const [rows, summary] = await Promise.all([
        jfetch('data/nav.json'),
        jfetch('data/nav_summary.json').catch(() => ({}))
      ]);

      if (!Array.isArray(rows) || rows.length === 0) {
        canvas.replaceWith('NAV data not available (empty data/nav.json).');
        return;
      }

      // Auto-detect which key holds absolute NAV
      const keys = Object.keys(rows[0] || {});
      const navKey =
        keys.find(k => k.toLowerCase() === 'nav_usd') ||
        keys.find(k => /^nav(_|$)/i.test(k)); // e.g., nav, nav_inr

      if (!navKey) {
        canvas.replaceWith(`NAV data not available (no 'nav' field). Keys: ${keys.join(', ')}`);
        return;
      }

      let pts = rows
        .map(r => ({ x: parseYMD(r.date), y: Number(r[navKey]) }))
        .filter(p => p.x && Number.isFinite(p.y) && p.y > 0)
        .sort((a, b) => a.x - b.x);

      if (pts.length === 0) {
        canvas.replaceWith(`NAV data not available (no valid '${navKey}' values).`);
        return;
      }

      // Filter from inception_date if provided
      const inceptionStr = summary?.inception_date;
      const inception = inceptionStr ? parseYMD(inceptionStr) : null;
      if (inception) {
        pts = pts.filter(p => p.x >= inception);
        if (pts.length === 0) {
          canvas.replaceWith('NAV data filtered to inception has no points. Check inception_date.');
          return;
        }
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
        data: {
          datasets: [{
            label: 'Portfolio NAV (USD)',
            data: pts,
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.2
          }]
        },
        options: {
          responsive: true,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: true },
            tooltip: {
              callbacks: { label: (ctx) => ` NAV: $${ctx.parsed.y.toLocaleString()}` }
            }
          },
          scales: {
            x: {
              type: 'time',
              min: xMin,
              max: xMax,
              time: { unit: 'month' },
              ticks: { maxTicksLimit: 8 }
            },
            y: {
              beginAtZero: false,
              suggestedMin,
              suggestedMax,
              ticks: { callback: v => '$' + Number(v).toLocaleString() }
            }
          }
        }
      });
    } catch (e) {
      console.error('NAV chart error:', e);
      canvas.replaceWith('NAV error — open console for details.');
    }
  })();
})();
