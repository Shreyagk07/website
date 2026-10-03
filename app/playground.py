"""Deterministic, side-effect-free logic for the illustrative playground demos.

None of this calls an LLM, the network, or evaluates user-supplied code.
"""
from __future__ import annotations

import math
import re
from collections import Counter, OrderedDict

from .models import (
    FlakyRequest, FlakyResponse, FlakyVerdict, LedgerEntry, RagRequest, RagResponse,
    RagStep, TicketOutcome, TicketRequest, TicketResponse,
)

# ============================ RAG flow ============================
# Fictional "Lumen Notes" help-centre passages, bundled for the demo only.
RAG_CORPUS = [
    {"id": "DOC-1", "title": "Syncing notes", "text": "Notes sync automatically whenever the device is online. If a sync conflict occurs, the app keeps both versions and marks the newer copy with a conflict badge."},
    {"id": "DOC-2", "title": "Exporting data", "text": "You can export notes as Markdown or PDF from the settings menu. Exports include attachments in a zipped folder."},
    {"id": "DOC-3", "title": "Sharing notebooks", "text": "A notebook can be shared with a link or with named collaborators. Collaborators can be given view or edit permission, and the owner can revoke access at any time."},
    {"id": "DOC-4", "title": "Offline mode", "text": "Offline mode lets you read and edit notes without a connection. Changes are queued and sync when the device reconnects."},
    {"id": "DOC-5", "title": "Account security", "text": "Two-factor authentication can be enabled in account settings. Recovery codes are shown once when two-factor authentication is turned on."},
    {"id": "DOC-6", "title": "Storage limits", "text": "Free accounts include 2 GB of storage for notes and attachments. Paid plans raise the limit, and the app warns you before the limit is reached."},
    {"id": "DOC-7", "title": "Deleting notes", "text": "Deleted notes move to the trash and stay there for 30 days. Notes can be restored from the trash until they are permanently removed."},
]
RAG_SAMPLE_QUESTIONS = [
    "How do I export my notes and what formats are available?",
    "What happens on a sync conflict and can I edit offline?",
    "How long do deleted notes stay in the trash?",
    "What is the CEO salary?",
]
_STOP = set("a an the and or of to in on is are can i my do does what how when for with it be at by this that you your if as from".split())
MIN_SCORE = 1.5


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in _STOP:
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return out


_DOC_TOKENS = {d["id"]: Counter(_tokens(d["title"] + " " + d["text"])) for d in RAG_CORPUS}
_DF = Counter(t for c in _DOC_TOKENS.values() for t in c)
_N = len(RAG_CORPUS)


def _score(q_tokens: list[str], doc_id: str) -> tuple[float, list[str]]:
    tf = _DOC_TOKENS[doc_id]
    matched = sorted({t for t in q_tokens if t in tf})
    s = sum(math.log(1 + _N / _DF[t]) * (1 + math.log(tf[t])) for t in matched)
    return round(s, 2), matched


def _best_sentence(doc: dict, q_tokens: list[str]) -> str:
    sentences = re.split(r"(?<=\.)\s+", doc["text"])
    return max(sentences, key=lambda s: len(set(_tokens(s)) & set(q_tokens)))


def run_rag(req: RagRequest) -> RagResponse:
    q = req.question.strip()
    parts = [p.strip(" ?.") for p in re.split(r"\?|\band\b|,|;", q) if _tokens(p)][:3] or [q]
    steps = [RagStep(
        name="Plan",
        detail=f"Split the question into {len(parts)} sub-quer{'y' if len(parts) == 1 else 'ies'}.",
        data={"sub_queries": parts})]
    lines, cites, gaps, hits_data = [], [], [], []
    for sub in parts:
        qt = _tokens(sub)
        ranked = sorted(((*_score(qt, d["id"]), d["id"]) for d in RAG_CORPUS), key=lambda r: (-r[0], r[2]))
        top = [{"doc": r[2], "score": r[0], "matched_terms": r[1]} for r in ranked[:2] if r[0] > 0]
        hits_data.append({"sub_query": sub, "top": top})
        if top and top[0]["score"] >= MIN_SCORE:
            doc = next(d for d in RAG_CORPUS if d["id"] == top[0]["doc"])
            lines.append(f"{_best_sentence(doc, qt)} [{doc['id']}]")
            if doc["id"] not in cites:
                cites.append(doc["id"])
        else:
            gaps.append(sub)
    steps.append(RagStep(
        name="Retrieve",
        detail=f"Keyword-weighted ranking (IDF x term frequency) over {len(RAG_CORPUS)} bundled passages. "
               "No embeddings or LLM are used in this demo.",
        data={"results": hits_data}))
    steps.append(RagStep(
        name="Context check",
        detail=f"Each sub-query needs a passage scoring at least {MIN_SCORE}. "
               + ("All sub-queries are supported." if not gaps else f"Unsupported: {', '.join(gaps)}."),
        data={"min_score": MIN_SCORE, "unsupported": gaps}))
    if not lines:
        answer = "I can't answer that from the bundled passages, so I won't guess."
    else:
        answer = " ".join(lines)
        if gaps:
            answer += " (No supporting passage found for: " + "; ".join(gaps) + ".)"
    steps.append(RagStep(
        name="Cited answer",
        detail="Sentences are quoted from retrieved passages with their IDs.",
        data={"citations": cites}))
    return RagResponse(steps=steps, answer=answer, citations=cites)


# ============================ Ticket holds ============================
def simulate_tickets(req: TicketRequest) -> TicketResponse:
    bal = {"available": req.capacity, "held": 0, "sold": 0}
    holds: dict[str, dict] = {}
    ledger: list[LedgerEntry] = []
    outcomes: list[TicketOutcome] = []
    counter = 0

    def post(at, kind, ref, debit, credit, qty):
        bal[debit] += qty
        bal[credit] -= qty
        ledger.append(LedgerEntry(seq=len(ledger) + 1, at=at, kind=kind, ref=ref,
                                  debit=debit, credit=credit, qty=qty))

    def log(at, text, ok):
        outcomes.append(TicketOutcome(seq=len(outcomes) + 1, at=at, text=text, ok=ok))

    def expire(upto):
        for hid in sorted((h for h, v in holds.items() if v["expires"] <= upto),
                          key=lambda h: holds[h]["expires"]):
            v = holds.pop(hid)
            post(v["expires"], "expire", hid, "available", "held", v["qty"])
            log(v["expires"], f"{hid} expired; {v['qty']} returned to available.", True)

    for a in req.actions:
        expire(a.at)
        if a.op == "hold":
            if a.qty > bal["available"]:
                log(a.at, f"{a.user}: hold of {a.qty} rejected, only {bal['available']} available.", False)
                continue
            counter += 1
            hid = f"H{counter}"
            holds[hid] = {"user": a.user, "qty": a.qty, "expires": a.at + req.ttl}
            post(a.at, "hold", hid, "held", "available", a.qty)
            log(a.at, f"{a.user} holds {a.qty} as {hid} until t={a.at + req.ttl}.", True)
            continue
        h = holds.pop(a.hold_id, None)
        if h is None:
            log(a.at, f"{a.op} {a.hold_id} rejected: no active hold (unknown, expired or already settled).", False)
        elif a.op == "confirm":
            post(a.at, "confirm", a.hold_id, "sold", "held", h["qty"])
            log(a.at, f"{a.hold_id} confirmed; {h['qty']} sold.", True)
        else:
            post(a.at, "release", a.hold_id, "available", "held", h["qty"])
            log(a.at, f"{a.hold_id} released; {h['qty']} returned.", True)
    expire(req.now)
    active = [{"hold_id": k, **v} for k, v in holds.items()]
    balanced = sum(bal.values()) == req.capacity and all(v >= 0 for v in bal.values())
    return TicketResponse(ledger=ledger, outcomes=outcomes, balances=bal,
                          active_holds=active, balanced=balanced)


# ============================ Flaky analyzer ============================
FLAKY_RULE = [
    "Group each test's runs by commit (same code).",
    "If any commit has both a pass and a fail: flaky (same code, different outcome).",
    "Else if every run failed: consistently failing.",
    "Else if the latest commit failed after earlier commits passed: likely regression.",
    "Otherwise: stable.",
]
FLAKY_SAMPLE = [
    ("test_login_valid", "a1", "pass"), ("test_login_valid", "a1", "pass"), ("test_login_valid", "b2", "pass"), ("test_login_valid", "c3", "pass"),
    ("test_checkout_total", "a1", "pass"), ("test_checkout_total", "a1", "fail"), ("test_checkout_total", "b2", "pass"), ("test_checkout_total", "b2", "pass"), ("test_checkout_total", "c3", "fail"), ("test_checkout_total", "c3", "pass"),
    ("test_export_pdf", "a1", "fail"), ("test_export_pdf", "b2", "fail"), ("test_export_pdf", "c3", "fail"),
    ("test_search_filters", "a1", "pass"), ("test_search_filters", "a1", "pass"), ("test_search_filters", "b2", "pass"), ("test_search_filters", "c3", "fail"), ("test_search_filters", "c3", "fail"),
    ("test_session_timeout", "a1", "pass"), ("test_session_timeout", "b2", "fail"), ("test_session_timeout", "b2", "pass"), ("test_session_timeout", "c3", "pass"),
]


def flaky_sample() -> dict:
    return {"runs": [{"test": t, "commit": c, "outcome": o} for t, c, o in FLAKY_SAMPLE]}


def analyze_flaky(req: FlakyRequest) -> FlakyResponse:
    by_test: "OrderedDict[str, OrderedDict[str, list[str]]]" = OrderedDict()
    for r in req.runs:
        by_test.setdefault(r.test, OrderedDict()).setdefault(r.commit, []).append(r.outcome)
    verdicts = []
    for test, commits in by_test.items():
        flat = [o for outs in commits.values() for o in outs]
        fails = flat.count("fail")
        mixed = [c for c, outs in commits.items() if "pass" in outs and "fail" in outs]
        order = list(commits)
        last = commits[order[-1]]
        if mixed:
            v, why = "flaky", f"Both outcomes on identical code at: {', '.join(mixed)}."
        elif fails == len(flat):
            v, why = "consistently failing", "Every run failed."
        elif len(order) > 1 and all(o == "fail" for o in last):
            v, why = "likely regression", f"Passed earlier, failing at latest commit {order[-1]}."
        else:
            v, why = "stable", "No mixed-outcome commits and no new failure at the latest commit."
        verdicts.append(FlakyVerdict(test=test, verdict=v, runs=len(flat), failures=fails,
                                     mixed_commits=mixed, reason=why))
    return FlakyResponse(rule=FLAKY_RULE, verdicts=verdicts,
                         summary=dict(Counter(v.verdict for v in verdicts)))
