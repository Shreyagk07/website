import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, load_portfolio

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
LIVE = {
    "red-team": "https://adversarial-red-team-wgkycbgs6hhd6bffq3vltf.streamlit.app/",
    "web-monitor": "https://intelligent-web-monitor-lstnomlxvuraa96sriyqkz.streamlit.app/",
    "agentic-rag": "https://appuction-agentic-rag-g2kdshjlkunoxdvejujqyj.streamlit.app/",
}


# ---------- pages & content integrity ----------
def test_pages_render():
    for path in ("/", "/resume", "/healthz", "/robots.txt", "/sitemap.xml", "/api/portfolio"):
        assert client.get(path).status_code == 200, path
    assert client.get("/nope").status_code == 404
    assert client.get("/api/nope").json() == {"detail": "Not found"}


def test_live_urls_exact_and_only_where_supplied():
    p = load_portfolio()
    for proj in p.projects:
        assert proj.url == LIVE.get(proj.id), proj.id
        assert proj.github is None  # no repository URL was supplied
    html = client.get("/").text
    assert html.count(">Live Demo") == 3
    assert "repository for" not in html


def test_internal_anchors_resolve():
    html = client.get("/").text
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    for target in re.findall(r'href="#([^"]+)"', html):
        assert target in ids, target


def test_static_assets_exist():
    html = client.get("/").text
    for src in set(re.findall(r'(?:src|href)="(/static/[^"]+)"', html)):
        assert client.get(src).status_code == 200, src
    for proj in load_portfolio().projects:
        assert client.get(f"/static/img/{proj.art}.svg").status_code == 200


def test_contact_links_and_factual_guards():
    html = client.get("/").text
    assert 'href="mailto:shreyagk6899@gmail.com"' in html
    assert "6363748036" not in html and "tel:" not in html and "6363748036" not in client.get("/resume").text
    assert "https://github.com/Shreyagk07" in html and "https://www.linkedin.com/in/shreya-gk07" in html
    assert "<form" not in html.split('id="contact"')[1]  # no fake contact form
    blob = client.get("/api/portfolio").text.lower()
    assert "hybrid retrieval" not in blob and "eliminat" not in blob
    ledger = next(x for x in load_portfolio().projects if x.id == "ticket-ledger")
    assert not re.search(r"\d+\s*(tps|rps|req)", ledger.evidence.lower())
    assert "download" not in client.get("/resume").text.lower().replace("downloads", "")  # no resume file supplied


def test_security_headers_and_size_limit():
    r = client.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    big = client.post("/api/playground/rag", content=b"x" * 70_000, headers={"content-type": "application/json"})
    assert big.status_code == 413


def test_portfolio_schema_rejects_dangling_refs():
    from app.models import Portfolio
    data = load_portfolio().model_dump()
    data["claims"][0]["project"] = "missing"
    with pytest.raises(ValueError):
        Portfolio.model_validate(data)


# ---------- contrast ----------
def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


def ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + .05) / (lb + .05)


def test_text_contrast_aa():
    css = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
    t = dict(re.findall(r"--(\w+):(#[0-9a-fA-F]{6})", css))
    for fg in ("wine", "muted", "atlas"):
        for bg in ("bisque", "paper", "butter", "blueberry", "blush"):
            assert ratio(t[fg], t[bg]) >= 4.5, (fg, bg, ratio(t[fg], t[bg]))
    assert ratio(t["bisque"], t["wine"]) >= 4.5 and ratio("#ffffff", t["atlas"]) >= 4.5
    assert ratio(t["wine"], t["sage"]) >= 4.5 and ratio(t["wine"], t["ash"]) >= 4.5


# ---------- RAG demo ----------
def rag(q):
    r = client.post("/api/playground/rag", json={"question": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_rag_cited_and_deterministic():
    q = "How long do deleted notes stay in the trash?"
    a, b = rag(q), rag(q)
    assert a == b and a["illustrative"] is True
    assert a["citations"] == ["DOC-7"] and "30 days" in a["answer"] and "[DOC-7]" in a["answer"]
    assert [s["name"] for s in a["steps"]] == ["Plan", "Retrieve", "Context check", "Cited answer"]


def test_rag_multi_part_and_refusal():
    r = rag("How do I export my notes and what formats are available? Can I edit offline?")
    assert {"DOC-2", "DOC-4"} <= set(r["citations"])
    nope = rag("What is the CEO salary?")
    assert nope["citations"] == [] and "won't guess" in nope["answer"]


@pytest.mark.parametrize("body", [{}, {"question": "hi"}, {"question": "x" * 201}, {"question": "ok ok", "extra": 1}])
def test_rag_validation(body):
    assert client.post("/api/playground/rag", json=body).status_code == 422


# ---------- ticket demo ----------
def tickets(actions, capacity=3, ttl=60, now=None):
    now = now if now is not None else (actions[-1]["at"] if actions else 0)
    return client.post("/api/playground/tickets", json={"capacity": capacity, "ttl": ttl, "now": now, "actions": actions})


def test_tickets_bounded_inventory_and_balance():
    r = tickets([{"at": 0, "op": "hold", "user": "A", "qty": 2}, {"at": 1, "op": "hold", "user": "B", "qty": 2}]).json()
    assert r["balances"] == {"available": 1, "held": 2, "sold": 0} and r["balanced"]
    assert r["outcomes"][1]["ok"] is False and "rejected" in r["outcomes"][1]["text"]


def test_tickets_expiry_confirm_release():
    acts = [{"at": 0, "op": "hold", "user": "A", "qty": 1}, {"at": 5, "op": "hold", "user": "B", "qty": 2},
            {"at": 10, "op": "confirm", "hold_id": "H2"}, {"at": 70, "op": "confirm", "hold_id": "H1"}]
    r = tickets(acts, now=70).json()
    assert r["balances"] == {"available": 1, "held": 0, "sold": 2} and r["balanced"]
    assert any(e["kind"] == "expire" and e["ref"] == "H1" for e in r["ledger"])
    assert r["outcomes"][-1]["ok"] is False  # late confirm rejected
    rel = tickets([{"at": 0, "op": "hold", "user": "A", "qty": 3}, {"at": 1, "op": "release", "hold_id": "H1"}]).json()
    assert rel["balances"]["available"] == 3


def test_tickets_invariant_over_many_sequences():
    import random
    rnd = random.Random(1)
    for _ in range(25):
        t, acts, n = 0, [], 0
        for _ in range(40):
            t += rnd.randint(0, 30)
            op = rnd.choice(["hold", "hold", "confirm", "release"])
            if op == "hold":
                acts.append({"at": t, "op": op, "user": "u", "qty": rnd.randint(1, 4)}); n += 1
            else:
                acts.append({"at": t, "op": op, "hold_id": f"H{rnd.randint(1, max(n, 1))}"})
        r = tickets(acts, capacity=6, ttl=45, now=t + 100).json()
        assert r["balanced"] and sum(r["balances"].values()) == 6


@pytest.mark.parametrize("payload", [
    {"capacity": 0, "ttl": 60, "now": 0, "actions": []},
    {"capacity": 5, "ttl": 1, "now": 0, "actions": []},
    {"capacity": 5, "ttl": 60, "now": 0, "actions": [{"at": 5, "op": "hold", "user": "a"}, {"at": 1, "op": "hold", "user": "a"}]},
    {"capacity": 5, "ttl": 60, "now": 0, "actions": [{"at": 5, "op": "hold", "user": "a"}]},  # now < last action
    {"capacity": 5, "ttl": 60, "now": 9, "actions": [{"at": 5, "op": "hold", "user": "<script>"}]},
    {"capacity": 5, "ttl": 60, "now": 9, "actions": [{"at": 5, "op": "confirm"}]},
    {"capacity": 5, "ttl": 60, "now": 99, "actions": [{"at": 5, "op": "hold", "user": "a"}] * 61},
])
def test_tickets_validation(payload):
    assert client.post("/api/playground/tickets", json=payload).status_code == 422


# ---------- flaky demo ----------
def analyze(runs):
    r = client.post("/api/playground/flaky", json={"runs": runs})
    assert r.status_code == 200, r.text
    return {v["test"]: v for v in r.json()["verdicts"]}


def test_flaky_sample_verdicts():
    sample = client.get("/api/playground/flaky/sample").json()["runs"]
    v = analyze(sample)
    assert v["test_login_valid"]["verdict"] == "stable"
    assert v["test_checkout_total"]["verdict"] == "flaky" and v["test_checkout_total"]["mixed_commits"] == ["a1", "c3"]
    assert v["test_export_pdf"]["verdict"] == "consistently failing"
    assert v["test_search_filters"]["verdict"] == "likely regression"
    assert v["test_session_timeout"]["verdict"] == "flaky"


def test_flaky_rule_edges():
    assert analyze([{"test": "t", "commit": "a", "outcome": "fail"}])["t"]["verdict"] == "consistently failing"
    assert analyze([{"test": "t", "commit": "a", "outcome": "pass"}, {"test": "t", "commit": "b", "outcome": "fail"}])["t"]["verdict"] == "likely regression"
    assert analyze([{"test": "t", "commit": "a", "outcome": "fail"}, {"test": "t", "commit": "b", "outcome": "pass"}])["t"]["verdict"] == "stable"


@pytest.mark.parametrize("runs", [[], [{"test": "t", "commit": "a", "outcome": "maybe"}],
                                  [{"test": "", "commit": "a", "outcome": "pass"}],
                                  [{"test": "t", "commit": "a", "outcome": "pass"}] * 501])
def test_flaky_validation(runs):
    assert client.post("/api/playground/flaky", json={"runs": runs}).status_code == 422


# ---------- resume-update checks ----------
def test_certifications_and_stack_integrity():
    html = client.get("/").text
    certs = load_portfolio().certifications
    assert len(certs) == 5 and all(c in html for c in certs)
    assert 'id="certifications"' in html
    blob = client.get("/api/portfolio").text
    assert "Groq" not in blob and "FAISS" not in blob
    P = {x.id: x for x in load_portfolio().projects}
    assert P["agentic-rag"].stack == ["Python", "LangGraph", "LangChain", "FastAPI", "ChromaDB", "RAGAS", "Langfuse", "Streamlit"]
    assert "pytest" in P["slotsync"].stack and not any("pytest" in x.stack for k, x in P.items() if k != "slotsync")
    tl = " ".join(P["ticket-ledger"].decisions).lower() + P["ticket-ledger"].approach.lower()
    for w in ("row-level locking", "celery", "idempotency keys", "hmac-signed", "reconciliation", "double-entry"):
        assert w in tl
    assert P["ticket-ledger"].stack[-1] == "Locust" and "Celery" in P["ticket-ledger"].stack
    assert P["red-team"].stack == ["Python", "LangGraph", "LangChain", "FastAPI", "Langfuse", "SQL", "Streamlit"]
    assert "45 to 15 minutes" in " ".join(P["orangehrm-qa"].reported)
    assert not re.search(r"\d+(\.\d+)?\s*%", P["testlab"].evidence + P["testlab"].approach)  # no invented mutation score
    exp = {e.role: e for e in load_portfolio().experience}
    assert len(exp["Graduate Engineer Trainee"].points) == 2 and len(exp["Scholar Trainee"].points) == 3 and len(exp["Data Science Intern"].points) == 2
    for s in ("Elders project", "Selenium WebDriver", "healthcare datasets", "PostgreSQL exclusion constraints", "Allure reports"):
        assert s in html
    assert 'href="https://github.com/Shreyagk07"' in html


def test_monitor_and_rag_case_studies():
    P = {x.id: x for x in load_portfolio().projects}
    assert P["web-monitor"].stack == ["Python", "Selenium", "BeautifulSoup", "FastAPI", "Pydantic", "APScheduler", "SQL", "Streamlit"]
    wm = " ".join(P["web-monitor"].decisions).lower()
    assert "self-healing selectors" in wm and "exponential backoff" in wm
    rag = " ".join(P["agentic-rag"].decisions + [P["agentic-rag"].approach]).lower()
    for w in ("sub-queries", "chromadb", "cross-encoder", "corrective retrieval loop", "abstention", "ragas", "semantic caching", "langfuse"):
        assert w in rag
    blob = client.get("/api/portfolio").text.lower()
    assert "eliminat" not in blob and "faiss" not in blob and "groq" not in blob


def test_health_and_port_docs():
    assert (ROOT / "Dockerfile").read_text().count("${PORT:-8000}") == 1
    assert "tests/" in (ROOT / ".dockerignore").read_text() and ".env" in (ROOT / ".dockerignore").read_text()
