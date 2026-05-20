# Kitchen — Frontend

React PWA built with Vite + Tailwind v4.

## Setup

```bash
npm install
```

Create `frontend/.env.local`:

```
VITE_API_URL=https://<your-api-gateway-url>
```

## Dev

```bash
npm run dev       # http://localhost:5173
```

## Deploy to Vercel

```bash
# First time — needs SSL workaround on some corporate networks
NODE_TLS_REJECT_UNAUTHORIZED=0 vercel --prod --yes

# Update a Vercel env var
echo "value" | NODE_TLS_REJECT_UNAUTHORIZED=0 vercel env add VAR_NAME production
```

## Auth

The app is protected by Vercel Edge Middleware (`middleware.js`) using HTTP Basic Auth.  
The password is stored as `AUTH_PASSWORD` in the Vercel project environment — not in this repo.

## Pages

| Page | File | Description |
|------|------|-------------|
| Scan | `src/pages/ScanPage.jsx` | Camera/file scan, expiry extraction, confirm to pantry |
| Pantry | `src/pages/StockPage.jsx` | Ingredient cards, search, expiry urgency, inline edit |
| Recipes | `src/pages/RecipesPage.jsx` | Difficulty/time filters, expiry bar, Mark Cooked, URL import |
| Shopping | `src/pages/ShoppingPage.jsx` | Cart-style list, mark as bought |
