// scripts/chart-nav.js
(function () {
  const canvas = document.getElementById('navChart');
  if (!canvas) return;

  function parseYMD(ymd) {
    if (!ymd || typeof ymd !== 'string') return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd.trim());
    if (!m) return null;
    const dt = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return isNaN(dt) ? null : dt;
  }

  async function jfetch(path) {
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

      const inception = summary?.inception_date ? parseYMD(summary.inception_date) : null;

      const clean = rows
        .map(r => ({ x: parseYMD(r.date), idx: Number(r.nav_index), nifty: r.nifty_index == null ? null : Number(r.nifty_index) }))
        .filter(p => p.x && Number.isFinite(p.idx))
        .filter(p => !inception || p.x >= inception)
        .sort((a, b) => a.x - b.x);

      if (clean.length === 0) {
        canvas.replaceWith('NAV data not available (no valid index values).');
        return;
      }

      const navPts = clean.map(p => ({ x: p.x, y: p.idx }));
      const niftyPts = clean.filter(p => Number.isFinite(p.nifty)).map(p => ({ x: p.x, y: p.nifty }));

      const xMin = clean[0].x, xMax = clean[clean.length - 1].x;
      const allY = navPts.map(p => p.y).concat(niftyPts.map(p => p.y));
      const yMin = Math.min(...allY), yMax = Math.max(...allY);
      const pad = (yMax - yMin) * 0.06 || 2;

      const datasets = [{
        label: 'My portfolio',
        data: navPts,
        borderColor: '#22c55e',
        backgroundColor: 'rgba(34,197,94,.10)',
        borderWidth: 2.5,
        pointRadius: 0,
        tension: 0.2,
        fill: true
      }];
      if (niftyPts.length) {
        datasets.push({
          label: 'Nifty 50',
          data: niftyPts,
          borderColor: '#9ca3af',
          backgroundColor: 'rgba(156,163,175,.05)',
          borderWidth: 1.8,
          borderDash: [6, 5],
          pointRadius: 0,
          tension: 0.2,
          fill: false
        });
      }

      new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { datasets },
        options: {
          responsive: true,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: true },
            tooltip: {
              callbacks: {
                label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)} (${(ctx.parsed.y - 100 >= 0 ? '+' : '')}${(ctx.parsed.y - 100).toFixed(2)}%)`
              }
            }
          },
          scales: {
            x: { type: 'time', min: xMin, max: xMax, time: { unit: 'month' }, ticks: { maxTicksLimit: 8 } },
            y: {
              beginAtZero: false,
              suggestedMin: yMin - pad,
              suggestedMax: yMax + pad,
              ticks: { callback: v => Number(v).toFixed(0) }
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
