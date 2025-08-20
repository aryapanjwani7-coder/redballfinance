# Red Ball Finance – Paper Portfolio

Public, transparent paper portfolio with a detailed write-up for every buy.

## Dev
No build step. Just static files.

- `data/stocks.json` is the source of truth for holdings.
- Each holding has a `slug` that maps to `reports/<slug>.md`.
- The portfolio table & recent cards are rendered from `stocks.json`.
- Individual report pages render markdown via [marked](https://github.com/markedjs/marked).

## Add a new stock
1. Create a new report: copy `reports/template.md` → `reports/<your-slug>.md` and fill it out.
2. Add an entry to `data/stocks.json` with the same `slug`, ticker, buy date, qty, and buy price.
3. Commit & push. GitHub Pages will auto-deploy.

## Roadmap ideas
- Live prices (serverless function + quote API) and P/L.
- Chart thumbnails per stock.
- RSS/email updates when a new report drops.
- Tags/filters for “Dividend”, “Turnaround”, etc.
