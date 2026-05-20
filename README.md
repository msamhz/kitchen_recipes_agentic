# Kitchen — AI Kitchen Assistant

A mobile-first PWA that scans ingredients, tracks your pantry, ranks recipes by expiry urgency, and builds a smart shopping list.

**Live app:** https://frontend-gold-rho-90.vercel.app (password protected)

---

## Architecture

```
Frontend (React PWA)          Backend (FastAPI on AWS Lambda)
──────────────────────        ──────────────────────────────
Vercel (static hosting)  →→→  API Gateway → Lambda (ECR image)
frontend/                      api/                → Neon Postgres (ap-southeast-1)
```

- **Frontend:** Vite + React + Tailwind v4, deployed on Vercel
- **Backend:** FastAPI + Mangum, containerised and deployed on AWS Lambda (ap-southeast-1)
- **Database:** Neon Postgres
- **AI:** Anthropic Claude (scan, parse, rate recipes)

---

## Environment variables

Create a `.env` file at the project root (never commit this):

```
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://...
```

For local frontend dev, create `frontend/.env.local`:

```
VITE_API_URL=https://<your-api-gateway-url>
```

---

## Development workflow

### Frontend (React UI)

```bash
# Install dependencies (first time only)
cd frontend && npm install

# Start local dev server — hot-reloads, hits live Lambda API
npm run dev
# → http://localhost:5173

# Deploy to Vercel when ready
NODE_TLS_REJECT_UNAUTHORIZED=0 vercel --prod --yes
```

### Backend (FastAPI / Python)

```bash
# After editing any file in api/

# Build Docker image
docker build -t kitchen-api -f api/Dockerfile .

# Push to ECR
docker tag kitchen-api:latest <ECR_URI>:latest
docker push <ECR_URI>:latest

# Update Lambda
aws lambda update-function-code \
  --function-name kitchen-agent \
  --image-uri <ECR_URI>:latest \
  --region ap-southeast-1

# Wait for it to go live
aws lambda wait function-updated \
  --function-name kitchen-agent \
  --region ap-southeast-1
```

Replace `<ECR_URI>` with your ECR repository URI (stored in `.env` / AWS console).

### Save and push changes

```bash
git add <files>
git commit -m "your message"
git push
```

---

## Project structure

```
api/                  FastAPI app (Lambda handler)
  main.py             App entry point + CORS middleware
  routes/
    scan.py           POST /scan — image → ingredients via Claude
    stock.py          GET/POST/PATCH/DELETE /stock
    recipes.py        GET/POST /recipes, /shopping-list, /parse-url
  db.py               Neon Postgres connection
  requirements.txt

frontend/             React PWA
  src/
    pages/
      ScanPage.jsx    Camera scan + confirmation flow
      StockPage.jsx   Pantry — compact cards, search, expiry urgency
      RecipesPage.jsx Recipes — difficulty/time filters, expiry bar, Mark Cooked, URL import
      ShoppingPage.jsx Shopping list — cart-style, mark as bought
    components/
      TabBar.jsx
    api.js            All fetch calls to the backend
  middleware.js       Vercel Edge Middleware — Basic Auth gate
  vite.config.js

tools/                Local Python scripts (dev / data ingest)
  add_recipe.py       Parse + save a recipe from text/URL/YouTube
  scan_image.py       Test image scanning locally
  db_init.py          Schema init (local SQLite for dev)

workflows/            Markdown SOPs for the WAT framework
.env                  API keys and URLs — never commit
```

---

## Key API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/scan` | Scan image(s), return detected ingredients + expiry |
| GET | `/stock` | List all pantry ingredients |
| POST | `/stock/upsert` | Add/update ingredients after scan |
| PATCH | `/stock/:id` | Edit name, expiry, storage, in_stock |
| DELETE | `/stock/:id` | Remove ingredient |
| POST | `/stock/mark-used` | Set ingredients out of stock (after cooking) |
| GET | `/recipes` | All recipes, ranked by expiry urgency |
| POST | `/recipes` | Create a new recipe |
| DELETE | `/recipes/:id` | Delete a recipe |
| GET | `/recipes/shopping-list` | Missing ingredients + recipe pairs |
| POST | `/recipes/parse-url` | Parse recipe from URL or YouTube link |

---

## Releases

| Tag | Description |
|-----|-------------|
| v1.0.0 | React PWA — scan, pantry, recipes, shopping list |
