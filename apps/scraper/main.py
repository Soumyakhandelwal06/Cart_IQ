"""
Main FastAPI application — Agentic Quick Commerce Scraper/Parser Service
"""
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.parse import router as parse_router
from routes.scrape import router as scrape_router
from routes.auth import router as auth_router

load_dotenv()

app = FastAPI(
    title="CartIQ Scraper Service",
    description="LLM-powered Query Parser + Platform Scrapers",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(parse_router, prefix="/parse", tags=["Parser"])
app.include_router(scrape_router, prefix="/scrape", tags=["Scraper"])
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "scraper"}
