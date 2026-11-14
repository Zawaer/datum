"""Judge-style end-to-end run: 40 construction-professional questions (analysis/judge_questions.jsonl) on 13 sheets,
each asked on four upload forms of the sheet (lowres JPG ~2000 px, ~2500 px PNG, single-page vector PDF, hi-res PNG).

The hi-res form goes through the real web UI with Playwright (upload with the file picker, type the question, press
ask, read the answer the page received, screenshot); the other three forms go through the same HTTP API the page
uses (POST /api/upload, POST /api/ask). Black box: nothing from bp/ is imported.

    .venv/bin/python analysis/judge_run.py --server http://127.0.0.1:3172 --name baseline
    .venv/bin/python analysis/judge_run.py --rescore runs/judge_baseline.jsonl

Scoring (analysis/judge_questions.jsonl): counts exact (or one of "alt"); measures: the first number (or one written with a
unit) within 5 % (hand-estimated golds; 1 % for printed / summed ones) of the gold or an "alt" value ("ok"), within 15 % ("ok15", reported as lenient); text: every token present,
plus "nums_need" of "nums" within "nums_tol"; trick (out of scope): an abstention or an answer saying the sheet does
not show it. Outputs runs/judge_<name>.jsonl, runs/judge_<name>.summary.md, screenshots in
/data/attachments/s_YTlo5xSrle/judge-qa/shots/<name>/.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures as cf
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from judge_forms import FORMS, build, form_path  # noqa: E402

QFILE = ROOT / "analysis/judge_questions.jsonl"
SHOTS = Path("/data/attachments/s_YTlo5xSrle/judge-qa/shots")


# ---------------------------------------------------------------- scoring
def nums_in(x) -> list[float]:
    if isinstance(x, bool) or x is None:
        return []
    if isinstance(x, (int, float)):
        return [float(x)]
    out = []
    x = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", "", str(x))  # 7 650 -> 7650 (space as thousands separator)
    for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", x):
        s = m.group(0)
        # 1,234 thousands separator vs 1,5 decimal comma
        s = s.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s) else s.replace(",", ".")
        try:
            out.append(float(s))
        except ValueError:
            pass
    return out


def fold(s) -> str:
    return re.sub(r"[^a-z0-9@.]+", " ", str(s).lower().replace("”", '"').replace("″", '"')).strip()


NOT_SHOWN = re.compile(r"not (shown|given|specified|indicated|found|stated|listed|provided|on|available|included|"
                       r"present|drawn|visible|labeled|labelled)|no (fire|sprinkler|u-value|price|cost|ceiling|"
                       r"information|data|rating)|none|n/a|cannot|can't|isn't|doesn't|does not|no .* (shown|given)|"
                       r"\bei\b|nicht|keine|unspecified|blank|empty|^0$|\b0 (sprinkler|heads)", re.I)


def score(q: dict, res: dict) -> tuple[int, int]:
    """(strict ok, lenient ok)."""
    ans = res.get("answer")
    t = q["type"]
    if t == "trick":
        if ans is None:
            return 1, 1
        ok = int(bool(NOT_SHOWN.search(str(ans))) or nums_in(ans) == [0.0])
        return ok, ok
    if ans is None:
        return 0, 0
    if t == "text":
        a = fold(ans)
        toks = q.get("tokens") or fold(q["gold"]).split()
        ok = all(re.search(rf"(?<![0-9.]){re.escape(fold(tk))}(?![0-9])" if fold(tk).isdigit() else
                           rf"(?<![a-z0-9]){re.escape(fold(tk))}(?![a-z0-9])", a) for tk in toks)
        if ok and q.get("nums"):
            got = nums_in(ans)
            hit = sum(any(abs(g - n) <= q.get("nums_tol", 0.1) * n for g in got) for n in q["nums"])
            ok = hit >= q.get("nums_need", len(q["nums"]))
        return int(ok), int(ok)
    golds = [float(q["gold"])] + [float(x) for x in q.get("alt", [])]
    got = nums_in(ans)
    if t == "count":
        ok = any(g == n for g in got[:1] for n in golds)  # the first number of the answer is the count
        return int(ok), int(ok)
    # candidates: the answer's first number, plus any number written with a unit (a long room list does not
    # get credit just because one of its many numbers is close)
    cand = got[:1]
    if not isinstance(ans, (int, float)) and len(got) <= 4:
        unit = r"(?:sf|sq\.? ?ft|ft²|ft2|square feet|m²|m2|m³|m3|mm|m|l|liter|litre|litra\w*)"
        x = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", "", str(ans))
        cand += [v for m in re.finditer(rf"(-?\d[\d,]*(?:\.\d+)?)\s*{unit}\b", x, re.I) for v in nums_in(m.group(1))]
    tol = 0.05 if q.get("gold_confidence") in ("approx", "low", "medium") else 0.01  # printed / summed golds: 1 %
    strict = any(abs(g - n) <= tol * abs(n) for g in cand for n in golds)
    lenient = any(abs(g - n) <= 0.15 * abs(n) for g in cand for n in golds)
    return int(strict), int(lenient)


# ---------------------------------------------------------------- API path
def post(url, data, ctype, timeout=400):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def api_upload(server, f: Path) -> dict:
    t0 = time.time()
    try:
        u = post(f"{server}/api/upload?name={urllib.parse.quote(f.name)}", f.read_bytes(), "application/octet-stream")
    except Exception as e:  # noqa: BLE001
        u = {"path": None, "error": repr(e)[:300]}
    u["upload_s"] = round(time.time() - t0, 1)
    return u


def api_ask(server, path, question) -> dict:
    t0 = time.time()
    try:
        r = post(f"{server}/api/ask", json.dumps({"path": path, "question": question}).encode(), "application/json")
    except Exception as e:  # noqa: BLE001
        r = {"answer": None, "error": repr(e)[:300], "method": "error"}
    r["latency_s"] = round(time.time() - t0, 1)
    return r


# ---------------------------------------------------------------- browser path (hi-res form)
async def ui_sheet(browser, server, key, qs, shotdir: Path) -> list[dict]:
    pg = await browser.new_page(viewport={"width": 1600, "height": 950})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    out = []
    f = form_path(key, "hires")
    t0 = time.time()
    await pg.goto(server + "/?tab=upload")
    await pg.wait_for_timeout(800)
    await pg.set_input_files("#file", str(f))
    await pg.wait_for_timeout(1000)
    for _ in range(600):
        if not await pg.is_visible("#loading"):
            break
        await pg.wait_for_timeout(500)
    path = await pg.evaluate("cur && cur.path")
    if not (path or "").startswith("uploads/"):  # upload failed: the page still shows a built-in demo drawing
        path = None
    up_s = round(time.time() - t0, 1)
    for q in qs:
        rec = {"path": path, "upload_s": up_s}
        if not path:
            rec["res"] = {"answer": None, "method": "upload-failed", "error": errs[-1:]}
            out.append(rec)
            continue
        await pg.fill("#q", q["question"])
        t1 = time.time()
        await pg.click("#go")
        res = None
        for _ in range(800):
            if await pg.evaluate("!!(res && res._seq === askSeq)"):
                res = json.loads(await pg.evaluate("JSON.stringify(res)"))
                break
            await pg.wait_for_timeout(250)
        lat = round(time.time() - t1, 1)
        await pg.wait_for_timeout(2500)  # zoom-to-evidence animation
        shot = shotdir / f"{q['id']}.png"
        await pg.screenshot(path=str(shot))
        res = res or {"answer": None, "method": "ui-timeout"}
        res["latency_s"] = lat
        rec.update(res=res, screenshot=str(shot), page_errors=errs[-3:])
        out.append(rec)
    await pg.close()
    return out


async def ui_all(server, by_sheet, shotdir, jobs):
    from playwright.async_api import async_playwright

    shotdir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--use-gl=swiftshader"])
        sem = asyncio.Semaphore(jobs)

        async def one(key, qs):
            async with sem:
                try:
                    return key, await ui_sheet(b, server, key, qs, shotdir)
                except Exception as e:  # noqa: BLE001
                    return key, [{"res": {"answer": None, "method": "ui-error", "error": repr(e)[:300]}} for _ in qs]

        res = await asyncio.gather(*(one(k, v) for k, v in by_sheet.items()))
        await b.close()
    return dict(res)


# ---------------------------------------------------------------- report
def row_line(r):
    res = r["res"]
    a = res.get("answer")
    shown = a if a is not None else (f"(abstain; guess {res.get('tentative_answer')})"
                                     if res.get("tentative_answer") is not None else "(abstain)")
    return shown


def summary(rows, name, commit=""):
    L = [f"# Judge run `{name}`" + (f" (code {commit})" if commit else ""), ""]
    forms = [f for f in FORMS if any(r["form"] == f for r in rows)]
    tot = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        t = tot[r["form"]]
        t[0] += r["ok"]; t[1] += r["ok15"]; t[2] += 1
    L.append("| form | strict | lenient (15 %) | mean s | $ |")
    L.append("|---|---|---|---|---|")
    for f in forms:
        rs = [r for r in rows if r["form"] == f]
        lat = sum(float(r["res"].get("latency_s") or 0) for r in rs) / max(1, len(rs))
        cost = sum(float(r["res"].get("cost_usd") or 0) for r in rs)
        L.append(f"| {f} | {tot[f][0]}/{tot[f][2]} | {tot[f][1]}/{tot[f][2]} | {lat:.1f} | {cost:.3f} |")
    allok = sum(r["ok"] for r in rows)
    L += ["", f"**all forms: {allok}/{len(rows)} strict**", ""]
    # by category and sheet (all forms pooled)
    for field in ("sheet", "category"):
        agg = defaultdict(lambda: [0, 0])
        for r in rows:
            agg[r[field]][0] += r["ok"]; agg[r[field]][1] += 1
        L.append(f"By {field}: " + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(agg.items())))
        L.append("")
    L += ["| id | sheet | lang | question | gold | " + " | ".join(forms) + " | method (hires) | ev | s |",
          "|---|---|---|---|---|" + "---|" * len(forms) + "---|---|---|"]
    by_id = defaultdict(dict)
    for r in rows:
        by_id[r["id"]][r["form"]] = r
    for qid, d in by_id.items():
        r0 = next(iter(d.values()))
        cells = []
        for f in forms:
            r = d.get(f)
            if not r:
                cells.append("")
                continue
            cells.append(("Y " if r["ok"] else ("~ " if r["ok15"] else "- ")) + str(row_line(r))[:40].replace("|", "/"))
        h = d.get("hires") or r0
        g = r0["gold"]
        L.append(f"| {qid} | {r0['sheet']} | {r0['lang']} | {r0['question'][:70]} | {str(g)[:30]}"
                 f"{' ~' if r0['gold_confidence'] in ('approx', 'low') else ''} | " + " | ".join(cells) +
                 f" | {h['res'].get('method')} | {len(h['res'].get('evidence') or [])} | {h['res'].get('latency_s')} |")
    cost = sum(float(r["res"].get("cost_usd") or 0) for r in rows)
    L += ["", f"API cost of all asks ${cost:.3f}. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained."]
    return "\n".join(L) + "\n"


def scrub(obj, secret):
    if not secret:
        return obj
    return json.loads(json.dumps(obj).replace(secret, "<live>").replace(secret.split("//", 1)[-1], "<live>"))


def finish(rows, out: Path, name, commit):
    for r in rows:
        r["ok"], r["ok15"] = score(r, r["res"])
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    s = summary(rows, name, commit)
    out.with_suffix(".summary.md").write_text(s)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:3172")
    ap.add_argument("--name", default=time.strftime("%H%M"))
    ap.add_argument("--forms", default="", help="default: all four locally; lowres,png2500,pdf on --live "
                                                 "(hi-res uploads one at a time only, they can OOM the demo)")
    ap.add_argument("--only", default="", help="comma list of question ids or sheet keys")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--rescore", default="")
    ap.add_argument("--live", action="store_true",
                    help="the deployed demo (base URL read from data/secrets/demo_path.txt, never printed or saved)")
    ap.add_argument("--subset", action="store_true", help="one question per sheet (the first in the file)")
    a = ap.parse_args()
    secret = ""
    if a.live:
        secret = "https://<vm-ip>.sslip.io/" + (ROOT / "data/secrets/demo_path.txt").read_text().strip().strip("/")
        a.server = secret
    qs = [json.loads(x) for x in QFILE.read_text().splitlines() if x.strip()]
    qmap = {q["id"]: q for q in qs}
    import subprocess
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    if a.rescore:
        rows = [{**json.loads(x), **qmap.get(json.loads(x)["id"], {})} for x in Path(a.rescore).read_text().splitlines()
                if x.strip()]
        print(finish(rows, Path(a.rescore), Path(a.rescore).stem.replace("judge_", ""), commit))
        return
    if a.subset:
        seen = set()
        qs = [q for q in qs if not (q["sheet"] in seen or seen.add(q["sheet"]))]
    if a.only:
        keep = set(a.only.split(","))
        qs = [q for q in qs if q["id"] in keep or q["sheet"] in keep]
    build()
    forms = a.forms.split(",") if a.forms else (["lowres", "png2500", "pdf"] if a.live else list(FORMS))
    if a.live:
        a.jobs = 1  # one upload / ask at a time against the shared demo
    by_sheet = defaultdict(list)
    for q in qs:
        by_sheet[q["sheet"]].append(q)
    rows = []
    t0 = time.time()
    # API forms: upload every (sheet, form) once, then ask in parallel
    api_forms = [f for f in forms if f != "hires"]
    paths = {}
    with cf.ThreadPoolExecutor(1 if a.live else 2) as ex:
        futs = {ex.submit(api_upload, a.server, form_path(k, f)): (k, f) for k in by_sheet for f in api_forms}
        for fu in cf.as_completed(futs):
            paths[futs[fu]] = fu.result()
            print(f"uploaded {futs[fu]} -> {paths[futs[fu]].get('path')} {paths[futs[fu]].get('upload_s')}s "
                  f"{'error ' + str(scrub(paths[futs[fu]].get('error'), secret))[:80] if paths[futs[fu]].get('error') else ''}",
                  file=sys.stderr, flush=True)

    def one(job):
        q, f = job
        u = paths[(q["sheet"], f)]
        res = api_ask(a.server, u["path"], q["question"]) if u.get("path") else \
            {"answer": None, "method": "upload-failed", "error": u.get("error")}
        return {**q, "form": f, "path": u.get("path"), "upload_s": u.get("upload_s"), "res": res}

    jobs = [(q, f) for f in api_forms for q in qs]
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for r in ex.map(one, jobs):
            r = scrub(r, secret)
            r["ok"], r["ok15"] = score(r, r["res"])
            rows.append(r)
            print(f"[{'OK' if r['ok'] else '--'}] {r['form']:8} {r['id']} -> {str(r['res'].get('answer'))[:50]} "
                  f"(gold {str(r['gold'])[:20]}; {r['res'].get('method')}, {r['res'].get('latency_s')}s)",
                  file=sys.stderr, flush=True)
    if "hires" in forms:
        ui = asyncio.run(ui_all(a.server, by_sheet, SHOTS / a.name, 1))  # hi-res uploads one at a time (memory)
        for k, recs in ui.items():
            for q, rec in zip(by_sheet[k], recs):
                r = scrub({**q, "form": "hires", **rec}, secret)
                r["ok"], r["ok15"] = score(r, r["res"])
                rows.append(r)
                print(f"[{'OK' if r['ok'] else '--'}] hires    {r['id']} -> {str(r['res'].get('answer'))[:50]} "
                      f"(gold {str(r['gold'])[:20]}; {r['res'].get('method')}, {r['res'].get('latency_s')}s)",
                      file=sys.stderr, flush=True)
    rows = scrub(rows, secret)
    order = {q["id"]: i for i, q in enumerate(qs)}
    rows.sort(key=lambda r: (order[r["id"]], FORMS.index(r["form"])))
    out = ROOT / f"runs/judge_{a.name}.jsonl"
    print(finish(rows, out, a.name, commit))
    print(f"wall {time.time() - t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
