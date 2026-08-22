# frontend

Single-page React (Vite + Tailwind) UI for the patent clearance run: describe an
invention, watch the agent's progress, read the coverage matrix and suggestions.

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## Mock vs. real endpoint

The page posts `{"description": "..."}` to `POST /api/analyse`. Until that
endpoint exists, it renders `src/mockData.js` instead.

- Default source: `VITE_USE_MOCK` in `.env` (`true` = mock, `false` = real).
  Copy `.env.example` to `.env` to change it.
- Runtime override: the **Use mock data** checkbox in the header.
- `VITE_API_TARGET` (default `http://localhost:5000`) is where the dev server
  proxies `/api`, i.e. the Flask app.

## Response shape

```js
{
  elements:  [{ id, label, text }],
  patents:   [{ id, number, title, assignee }],
  coverage:  { [elementId]: { [patentId]: { evidence } } },  // present = covered
  uncovered: [elementId],
  suggestions: [{ id, title, reasoning, patent /* patentId */ }],
}
```

Any element/patent pair missing from `coverage` renders as a bright green cell —
that is the whole point of the screen. Covered cells show the evidence text on
hover.
