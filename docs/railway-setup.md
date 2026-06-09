# Railway Deployment — Step-by-Step Guide

> This document is the runbook for Block B4: migrating the Kitchen Agent backend
> from AWS Lambda to Railway. Follow every section in order. Lambda is
> **not** decommissioned until you have ticked off every item in the
> Verification Checklist.

---

## 1. Create a Railway account and new project

1. Open [railway.app](https://railway.app) in your browser and sign up with
   GitHub. Using GitHub login is strongly recommended — it makes repo
   connection in step 2 one click.
2. After signing in you land on the **dashboard**. Click **New Project**.
3. You will be offered several options. Choose **"Deploy from GitHub repo"**.
   (If you do not see this yet, proceed to section 2 first to authorise the
   GitHub app.)

---

## 2. Connect your GitHub repository

1. If this is your first time, Railway will ask you to **install the Railway
   GitHub App**. Click the link and authorise it for your account (or
   organisation).
2. Choose either **All repositories** or **Only select repositories** and
   include `kitchen_recipes_agentic` (or whatever your repo is named).
3. Back on the Railway "New Project" dialog, search for the repo and click it.
4. Railway detects the `Dockerfile` at the project root automatically and
   shows "Docker" as the build method. You do not need to configure anything
   else here.
5. Click **Deploy Now**. Railway starts an initial build immediately — it will
   fail at first because the environment variables are not set yet. That is
   expected. Proceed to step 3.

---

## 3. Select the Dockerfile as the build method (verify)

Railway should have auto-detected the root `Dockerfile`. To confirm:

1. In your Railway project, click on the **service** (it may be named after
   your repo).
2. Click the **Settings** tab.
3. Under **Build**, confirm **Build Method** is set to **Dockerfile** and
   **Dockerfile Path** is `/Dockerfile` (or `Dockerfile` relative to root).
4. If it shows something else, click the dropdown and select
   **Dockerfile**, then save.

---

## 4. Set environment variables in Railway

This is the most important step. The backend reads secrets from the environment
at startup — they must be in Railway before the service can start.

### How to open the Variables panel
1. Click your service in the Railway project view.
2. Click the **Variables** tab.
3. Click **New Variable** for each item below, or use the **Raw Editor** to
   paste them all at once.

### Variables the backend needs

| Variable | Where to get the value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys | Must start with `sk-ant-` |
| `DATABASE_URL` | [console.neon.tech](https://console.neon.tech) → your project → Connection string | Use the **pooler** URL for a Railway container: `postgresql://...?sslmode=require` |

> **Do NOT set `PORT`** — Railway injects it automatically. Setting it
> manually can cause a conflict.

> **Do NOT add `VITE_*` variables** — those are frontend-only and belong in
> Vercel (see section 7).

### After saving variables
Click **Redeploy** (top-right of the service view) or push a new commit.
Railway will rebuild and start the container.

---

## 5. Find the Railway public URL

Once the deploy goes green (the service card shows a green dot):

1. Click your service.
2. Under the **Settings** tab, look for **Domains** (or click **Generate
   Domain** if none exists yet).
3. Railway generates a URL in the format:
   `https://<random-slug>.up.railway.app`
4. Copy this URL — you will need it for the verification step and for
   repointing Vercel.

---

## 6. Verify the deploy is healthy

Run these commands in your terminal, replacing `<railway-url>` with the URL
from step 5:

```bash
# 1. Health check — should return {"status":"ok"}
curl https://<railway-url>/health

# 2. Stock list — should return a JSON array (possibly empty), NOT HTML
curl https://<railway-url>/stock

# 3. OpenAPI docs — should return the Swagger UI HTML page
curl -s https://<railway-url>/docs | head -5
```

If `/health` returns a 502 or connection error, check:
- The **Logs** tab on your Railway service for Python errors.
- That `DATABASE_URL` is set correctly (common cause: missing `?sslmode=require`).
- That `ANTHROPIC_API_KEY` is set (the app may fail to import if it tries
  to initialise the client at module level).

---

## 7. Verification checklist (tick before decommissioning Lambda)

Complete **all** of these before touching Lambda or Vercel production settings:

- [ ] `curl https://<railway-url>/health` returns `{"status":"ok"}`
- [ ] `curl https://<railway-url>/stock` returns valid JSON (not HTML, not 502)
- [ ] `curl https://<railway-url>/recipes` returns valid JSON
- [ ] Opening `https://<railway-url>/docs` in a browser shows the Swagger UI
- [ ] Scan endpoint works via Postman or curl with a test image:
  ```bash
  curl -X POST https://<railway-url>/scan \
    -F "file=@/path/to/test-image.jpg"
  ```
- [ ] Railway **Logs** tab shows no startup errors or repeated crashes
- [ ] Service has been stable for at least 5 minutes (no restarts in Metrics)

---

## 8. Repoint the frontend (Vercel)

Do this ONLY after the verification checklist above is complete.

1. Open [vercel.com](https://vercel.com) and navigate to your frontend
   project.
2. Go to **Settings** → **Environment Variables**.
3. Find `VITE_API_URL` under the **Production** environment.
4. Change its value from the old Lambda/API-Gateway URL to:
   ```
   https://<railway-url>.up.railway.app
   ```
   (use the exact URL from Railway step 5, with no trailing slash).
5. Click **Save**.
6. Trigger a redeploy: go to **Deployments** → click the three-dot menu on
   the latest deployment → **Redeploy**.
7. After the Vercel build finishes, open the live Vercel URL in your browser
   and test the full flow (scan → review stock → recipes).

> The Vercel Edge **Basic Auth middleware** (`frontend/middleware.js`) is
> unaffected — it wraps the Vercel URL itself and does not care which backend
> `VITE_API_URL` points to.

---

## 9. Remove Mangum and decommission Lambda

**Apply this section ONLY after:**
- The Railway + Vercel end-to-end test is working (section 8 complete), AND
- You have confirmed no traffic is still hitting the Lambda URL.

### 9a. Remove the Mangum handler from `api/main.py`

Apply this exact diff:

```diff
--- a/api/main.py
+++ b/api/main.py
@@ -1,7 +1,6 @@
 """
-Kitchen Agent — FastAPI entry point for Lambda deployment.
+Kitchen Agent — FastAPI entry point (uvicorn on Railway).
 """
 
 from fastapi import FastAPI
 from fastapi.middleware.cors import CORSMiddleware
-from mangum import Mangum
 
@@ -22,5 +21,2 @@ app.include_router(recipes.router, prefix="/recipes", tags=["recipes"])
 @app.get("/health")
 def health():
     return {"status": "ok"}
-
-# Lambda handler
-handler = Mangum(app)
```

After applying the diff, `mangum` can also be removed from `pyproject.toml`
dependencies and from `api/requirements.txt`.

### 9b. Delete the Lambda function and API Gateway

Run these AWS CLI commands (you need `aws` CLI configured with appropriate
permissions):

```bash
# 1. Delete the Lambda function
aws lambda delete-function \
  --function-name kitchen-agent \
  --region ap-southeast-1

# 2. Find your API Gateway ID (look for "kitchen" in the name)
aws apigatewayv2 get-apis --region ap-southeast-1

# 3. Delete the API Gateway (replace <api-id> with the ID from step 2)
aws apigatewayv2 delete-api \
  --api-id <api-id> \
  --region ap-southeast-1

# 4. (Optional) Delete the ECR repository used for Lambda images
aws ecr describe-repositories --region ap-southeast-1
aws ecr delete-repository \
  --repository-name kitchen-agent \
  --region ap-southeast-1 \
  --force
```

> After running these, the old API Gateway URL will return 404. Verify that
> Vercel is already pointing to Railway (`VITE_API_URL`) before deleting.

### 9c. Archive the Lambda Dockerfile

The file `api/Dockerfile` was the Lambda build artifact. Once Railway is live
you can either delete it or move it to `archive/` — it is excluded from the
Railway build by `.dockerignore` either way.

---

## Appendix: CORS on Railway

The current `api/main.py` allows all origins (`allow_origins=["*"]`). Once
Lambda is gone and the only frontend is the known Vercel URL, consider
tightening this:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://your-project.vercel.app",
        "http://localhost:5173",   # local Vite dev server
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

This is a low-priority hardening step — not required to complete B4.

---

## Appendix: Region co-location

Neon Postgres is provisioned in a specific region (check
`console.neon.tech` → your project → **Regions**). For lowest latency,
choose the same Railway region for your service:

- Railway → service → **Settings** → **Region**
- Match it to your Neon region (e.g., `us-east-1` or `ap-southeast-1`).

If they differ by more than one region tier, query latency will increase
noticeably on the scan and recipe endpoints.
