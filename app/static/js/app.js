/* Progressive enhancement only: the page is fully readable without this file. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Safe DOM builder: text is always set via textContent / createTextNode.
  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
    return n;
  }

  async function post(path, body) {
    const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) {
      let msg = `Request failed (${res.status}).`;
      try {
        const d = (await res.json()).detail;
        if (Array.isArray(d)) msg = d.map((e) => e.msg).join("; ");
        else if (typeof d === "string") msg = d;
      } catch (_) { /* keep default */ }
      throw new Error(msg);
    }
    return res.json();
  }
  const showErr = (box, e) => box.replaceChildren(h("p", { class: "err", role: "alert" }, e.message || "Something went wrong."));

  // ---------- scroll reveal ----------
  document.documentElement.classList.add("ready");
  const reveals = $$(".section .reveal");
  if ("IntersectionObserver" in window && !reduced) {
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }), { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    reveals.forEach((r) => io.observe(r));
  } else reveals.forEach((r) => r.classList.add("in"));

  // ---------- restrained hero pointer parallax ----------
  const art = $("[data-parallax]");
  if (art && !reduced && matchMedia("(hover: hover) and (pointer: fine)").matches) {
    const layers = $$(".layer", art);
    art.addEventListener("pointermove", (e) => {
      const r = art.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      layers.forEach((l) => l.style.transform = `translate(${x * l.dataset.depth}px,${y * l.dataset.depth}px)`);
    });
    art.addEventListener("pointerleave", () => layers.forEach((l) => l.style.transform = ""));
  }

  // ---------- role filter ----------
  const list = $("#claims");
  if (list) {
    const items = $$("li", list);
    const status = $("#filter-status");
    $$(".chip-btn[data-role]").forEach((b) => b.addEventListener("click", () => {
      const role = b.dataset.role;
      $$(".chip-btn[data-role]").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
      const match = (li) => role === "all" || li.dataset.roles.split(" ").includes(role);
      const sorted = [...items].sort((a, b2) => (match(b2) - match(a)) || (a.dataset.order - b2.dataset.order));
      sorted.forEach((li) => {
        list.append(li);
        li.classList.toggle("is-match", role !== "all" && match(li));
        li.classList.toggle("is-dim", role !== "all" && !match(li));
      });
      const n = items.filter(match).length;
      status.textContent = role === "all" ? "Showing all evidence." : `${n} of ${items.length} items match ${b.textContent}; the rest follow.`;
    }));
  }

  // ---------- copy email / print ----------
  const copy = $("#copy-email");
  if (copy) copy.addEventListener("click", async () => {
    const out = $("#copy-status");
    try {
      await navigator.clipboard.writeText(copy.dataset.email);
      out.textContent = "Email address copied."; copy.textContent = "Copied ✓";
    } catch (_) {
      const link = $("#email-link");
      const sel = getSelection(); const r = document.createRange(); r.selectNodeContents(link); sel.removeAllRanges(); sel.addRange(r);
      out.textContent = "Copy is blocked here; the address is selected, press Ctrl+C.";
    }
    setTimeout(() => (copy.textContent = "Copy email"), 2500);
  });
  const pr = $("#print-btn");
  if (pr) pr.addEventListener("click", () => print());

  // ---------- RAG explorer ----------
  const ragForm = $("#rag-form");
  if (ragForm) {
    const out = $("#rag-out"), input = $("#rag-q");
    const run = async () => {
      out.replaceChildren(h("p", { class: "muted" }, "Running…"));
      try {
        const r = await post("/api/playground/rag", { question: input.value });
        const steps = r.steps.map((s) => {
          const extra = [];
          if (s.name === "Plan") extra.push(h("ul", {}, s.data.sub_queries.map((q) => h("li", {}, q))));
          if (s.name === "Retrieve") s.data.results.forEach((x) => {
            extra.push(h("p", { class: "hit" }, h("strong", {}, `“${x.sub_query}” → `),
              x.top.length ? x.top.map((t) => `${t.doc} (score ${t.score}; ${t.matched_terms.join(", ")})`).join(" · ") : "no matching passages"));
          });
          return h("li", {}, h("h4", {}, s.name), h("p", {}, s.detail), extra);
        });
        out.replaceChildren(
          h("ol", { class: "steps" }, steps),
          h("p", { class: "answer" }, h("span", { class: "sr-only" }, "Answer: "), r.answer),
          h("p", { class: "muted" }, r.citations.length ? `Cited: ${r.citations.join(", ")} · illustrative demo` : "No citations — nothing was supported · illustrative demo"));
      } catch (e) { showErr(out, e); }
    };
    ragForm.addEventListener("submit", (e) => { e.preventDefault(); run(); });
    $$("[data-q]", ragForm).forEach((b) => b.addEventListener("click", () => { input.value = b.dataset.q; run(); }));
    run();
  }

  // ---------- ticket hold simulator ----------
  const tOut = $("#t-out");
  if (tOut) {
    const CAP = 5, TTL = 60;
    let actions = [], clock = 0;
    const render = async () => {
      try {
        const r = await post("/api/playground/tickets", { capacity: CAP, ttl: TTL, now: clock, actions });
        const seg = (k) => h("span", { class: `b-${k}`, style: null }, r.balances[k] ? `${k} ${r.balances[k]}` : "");
        const bar = h("div", { class: "bar", role: "img", "aria-label": `available ${r.balances.available}, held ${r.balances.held}, sold ${r.balances.sold}` },
          ["available", "held", "sold"].map(seg));
        ["available", "held", "sold"].forEach((k, i) => { bar.children[i].style.flexGrow = r.balances[k]; bar.children[i].style.flexBasis = "0"; });
        const holds = h("ul", { class: "holds", "aria-label": "Active holds" },
          r.active_holds.length ? r.active_holds.map((x) => h("li", {},
            `${x.hold_id}: ${x.user} ×${x.qty}, expires t=${x.expires}`,
            h("button", { type: "button", class: "btn btn-ghost small", onclick: () => act("confirm", x.hold_id) }, "Confirm"),
            h("button", { type: "button", class: "btn btn-ghost small", onclick: () => act("release", x.hold_id) }, "Release")))
            : h("li", {}, "No active holds"));
        const ledger = r.ledger.length ? h("div", { class: "tablewrap", tabindex: "0", role: "region", "aria-label": "Ledger entries (scrollable)" }, h("table", {},
          h("caption", { class: "sr-only" }, "Ledger entries"),
          h("thead", {}, h("tr", {}, ["#", "t", "Event", "Ref", "Debit (+)", "Credit (−)", "Qty"].map((c) => h("th", { scope: "col" }, c)))),
          h("tbody", {}, r.ledger.map((e) => h("tr", {}, [e.seq, e.at, e.kind, e.ref, e.debit, e.credit, e.qty].map((c) => h("td", {}, c))))))) : h("p", { class: "muted" }, "No ledger entries yet.");
        const log = h("ul", {}, r.outcomes.slice(-5).map((o) => h("li", {}, `t=${o.at}: ${o.text}`)));
        tOut.replaceChildren(
          h("p", {}, `Clock t=${clock}s · `, h("span", { class: `pill ${r.balanced ? "ok" : "bad"}` }, r.balanced ? "Balanced: available + held + sold = 5" : "Imbalance")),
          bar, holds, ledger, h("h4", {}, "Latest outcomes"), log);
      } catch (e) { showErr(tOut, e); }
    };
    const act = (op, hold_id) => { if (actions.length >= 60) return showErr(tOut, new Error("Action limit reached; reset to continue.")); actions.push({ at: clock, op, hold_id }); render(); };
    $("#t-hold").addEventListener("click", () => {
      const user = $("#t-user").value.trim();
      if (!/^[A-Za-z0-9 _-]{1,20}$/.test(user)) return showErr(tOut, new Error("Buyer must be 1–20 letters, digits, spaces, _ or -."));
      if (actions.length >= 60) return showErr(tOut, new Error("Action limit reached; reset to continue."));
      actions.push({ at: clock, op: "hold", user, qty: Number($("#t-qty").value) }); render();
    });
    $("#t-adv").addEventListener("click", () => { clock += 30; render(); });
    $("#t-reset").addEventListener("click", () => { actions = []; clock = 0; render(); });
    render();
  }

  // ---------- flaky analyzer ----------
  const fOut = $("#f-out");
  if (fOut) (async () => {
    try {
      const runs = (await (await fetch("/api/playground/flaky/sample")).json()).runs;
      const grid = h("div", { class: "runs" });
      const verdicts = h("div");
      const tests = [...new Set(runs.map((r) => r.test))];
      tests.forEach((t) => {
        const cells = h("div", { class: "run-cells" });
        runs.forEach((r, i) => {
          if (r.test !== t) return;
          const cell = h("button", { type: "button", class: "cell", "data-o": r.outcome, "aria-label": `${t}, commit ${r.commit}: ${r.outcome}. Activate to flip.` },
            `${r.commit} ${r.outcome === "pass" ? "✓" : "✗"}`);
          cell.addEventListener("click", () => {
            r.outcome = r.outcome === "pass" ? "fail" : "pass";
            cell.dataset.o = r.outcome;
            cell.textContent = `${r.commit} ${r.outcome === "pass" ? "✓" : "✗"}`;
            cell.setAttribute("aria-label", `${t}, commit ${r.commit}: ${r.outcome}. Activate to flip.`);
            analyze();
          });
          cells.append(cell);
        });
        grid.append(h("div", { class: "run-row" }, h("code", {}, t), cells));
      });
      const analyze = async () => {
        try {
          const r = await post("/api/playground/flaky", { runs });
          verdicts.replaceChildren(
            h("div", { class: "tablewrap", tabindex: "0", role: "region", "aria-label": "Verdicts (scrollable)" }, h("table", {}, h("caption", { class: "sr-only" }, "Verdicts"),
              h("thead", {}, h("tr", {}, ["Test", "Verdict", "Runs", "Fails", "Why"].map((c) => h("th", { scope: "col" }, c)))),
              h("tbody", {}, r.verdicts.map((v) => h("tr", {}, h("td", {}, h("code", {}, v.test)),
                h("td", { class: `v v-${v.verdict.replace(/ /g, "-")}` }, v.verdict), h("td", {}, v.runs), h("td", {}, v.failures), h("td", {}, v.reason)))))),
            h("p", { class: "muted" }, "Counts: " + Object.entries(r.summary).map(([k, n]) => `${n} ${k}`).join(", ")),
            h("h4", {}, "Classification rule"), h("ol", { class: "rule" }, r.rule.map((x) => h("li", {}, x))));
        } catch (e) { showErr(verdicts, e); }
      };
      fOut.replaceChildren(grid, verdicts);
      analyze();
    } catch (e) { showErr(fOut, e); }
  })();
})();
