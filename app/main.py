"""FastAPI app: server-rendered pages, read-only content API, deterministic demo endpoints."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import playground
from .models import (
    FlakyRequest, FlakyResponse, Portfolio, RagRequest, RagResponse, TicketRequest, TicketResponse,
)

BASE = Path(__file__).parent
MAX_BODY = 64 * 1024  # bytes; demo payloads are far smaller

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


@lru_cache
def load_portfolio() -> Portfolio:
    path = Path(os.environ.get("PORTFOLIO_PATH", BASE / "data" / "portfolio.json"))
    return Portfolio.model_validate(json.loads(path.read_text(encoding="utf-8")))


def site_url() -> str:
    return os.environ.get("SITE_URL", "").rstrip("/")


app = FastAPI(title="Shreya G K portfolio", docs_url=None, redoc_url=None, openapi_url=None)
templates = Jinja2Templates(directory=str(BASE / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.middleware("http")
async def guard(request: Request, call_next):
    # Cap request size (Content-Length is enforced by the server for the body it reads).
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
    if length > MAX_BODY:
        return JSONResponse({"detail": "Request body too large"}, status_code=413)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def page(request: Request, name: str, **ctx):
    return templates.TemplateResponse(
        request, name, {"p": load_portfolio(), "site_url": site_url(), **ctx})


@app.get("/", include_in_schema=False)
def index(request: Request):
    p = load_portfolio()
    projects = {x.id: x for x in p.projects}
    return page(
        request, "index.html",
        featured=[x for x in p.projects if x.featured],
        others=[x for x in p.projects if not x.featured],
        projects=projects,
        questions=playground.RAG_SAMPLE_QUESTIONS,
    )


@app.get("/resume", include_in_schema=False)
def resume(request: Request):
    return page(request, "resume.html", projects={x.id: x for x in load_portfolio().projects})


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@app.get("/robots.txt", include_in_schema=False)
def robots():
    sm = f"\nSitemap: {site_url()}/sitemap.xml" if site_url() else ""
    return Response(f"User-agent: *\nAllow: /{sm}\n", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    base = site_url()
    urls = "".join(f"<url><loc>{base}{u}</loc></url>" for u in ("/", "/resume"))
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        media_type="application/xml")


@app.get("/api/portfolio", response_model=Portfolio)
def api_portfolio():
    return load_portfolio()


@app.get("/api/playground/rag/samples")
def rag_samples():
    return {"questions": playground.RAG_SAMPLE_QUESTIONS,
            "passages": playground.RAG_CORPUS}


@app.post("/api/playground/rag", response_model=RagResponse)
def rag(req: RagRequest):
    return playground.run_rag(req)


@app.post("/api/playground/tickets", response_model=TicketResponse)
def tickets(req: TicketRequest):
    return playground.simulate_tickets(req)


@app.get("/api/playground/flaky/sample")
def flaky_sample():
    return playground.flaky_sample()


@app.post("/api/playground/flaky", response_model=FlakyResponse)
def flaky(req: FlakyRequest):
    return playground.analyze_flaky(req)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return templates.TemplateResponse(
        request, "404.html", {"p": load_portfolio(), "site_url": site_url()}, status_code=404)
