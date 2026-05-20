"""
Kitchen Agent — FastAPI entry point for Lambda deployment.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from api.routes import scan, stock, recipes

app = FastAPI(title="Kitchen Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scan.router,    prefix="/scan",    tags=["scan"])
app.include_router(stock.router,   prefix="/stock",   tags=["stock"])
app.include_router(recipes.router, prefix="/recipes", tags=["recipes"])

@app.get("/health")
def health():
    return {"status": "ok"}

# Lambda handler
handler = Mangum(app)
