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
from routes.checkout import router as checkout_router

PROJECT_ROOT_ENV = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.env"))
load_dotenv(PROJECT_ROOT_ENV)

from playwright.async_api import async_playwright
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    pw = async_playwright()
    p_obj = await pw.start()
    app.state.playwright = p_obj
    yield
    await p_obj.stop()

app = FastAPI(
    title="CartIQ Scraper Service",
    description="LLM-powered Query Parser + Platform Scrapers",
    version="1.0.0",
    lifespan=lifespan
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
app.include_router(checkout_router, prefix="/checkout", tags=["Checkout"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "scraper"}
