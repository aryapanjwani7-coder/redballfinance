// scripts/chart-nav.js
(function () {
  const canvas = document.getElementById('navChart');
  if (!canvas) return;

  // Parse "YYYY-MM-DD" safely as UTC to avoid TZ quirks
  function parseYMD(ymd) {
    if (!ymd || typeof ymd !== 'string') return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd.trim());
    if (!m) return null;
    const y = +m[1], mo = +m[2] - 1, d = +m[3];
    const dt = new Date(Date.UTC(y, mo, d)); // UTC midnight
    return isNaN(dt) ? null : dt;
  }

  async function jfetch(path) {
    // cache-bust to defeat any CDN staleness
    const res = await fetch(`${path}?v=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  }

  (async function draw() {
    try {
      // Load both files
      const [rows, summary] = await Promise.all([
        jfetch('data/nav.json'),
        jfetch('data/nav_summary.json').catch(() => ({}))
      ]);

      // ---- pick nav key automatically (nav_usd preferred) ----
      let pts = [];
      let navKey = null;

      if (Array.isArray(rows) && rows.length > 0) {
        const keys = Object.keys(rows[0] || {});
        navKey =
          keys.find(k => k.toLowerCase() === 'nav_usd') ||
          keys.find(k => /^nav(_|$)/i.test(k)); // nav, nav_inr, etc.

        if (navKey) {
          pts = rows
            .map(r => ({ x: parseYMD(r.date), y: Number(r[navKey]) }))
            .filter(p => p.x && Number.isFinite(p.y) && p.y > 0)
            .sort((a, b) => a.x - b.x);
        }
      }

      // ---- If no valid points (e.g., file has nulls), build a minimal fallback
      //      from summary: starting_cash at inception_date -> latest.nav at latest.date
      if (pts.length === 0 && summary && summary.inception_date && summary.latest?.date && Number.isFinite(+summary.latest?.nav)) {
        const inception = parseYMD(summary.inception_date);
        const latestDate = parseYMD(summary.latest.date);
        const startCash = Number(summary.starting_cash) || Number(summary.latest.nav) || 0;
        const latestNav = Number(summary.latest.nav);

        if (inception && latestDate && latestNav > 0 && startCash > 0) {
          pts = [
            { x: inception, y: startCash },
            { x: latestDate, y: latestNav }
          ].sort((a, b) => a.x - b.x);
        }
      }

      if (pts.length === 0) {
        canvas.replaceWith('NAV data not available (no valid values).');
        return;
      }

      // Filter from inception_date forward if provided
      const inceptionStr = summary?.inception_date;
      const inception = inceptionStr ? parseYMD(inceptionStr) : null;
      if (inception) {
        pts = pts.filter(p => p.x >= inception);
        if (pts.length === 0) {
          canvas.replaceWith('NAV data filtered to inception has no points.');
          return;
        }
      }

      // X range
      const xMin = pts[0].x;
      const xMax = pts[pts.length - 1].x;

      // Y autoscale with padding (will keep adapting as values change)
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
            data: pts,                // [{x: Date, y: Number}]
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
              callbacks: {
                label: (ctx) => ` NAV: $${ctx.parsed.y.toLocaleString()}`
              }
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
