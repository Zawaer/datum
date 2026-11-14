"""Draw every results figure into docs/img/fig-*.png|svg from runs/*.jsonl.

    .venv/bin/python analysis/figures.py
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

import tables as T  # noqa: E402
from common import (DIV_MID, DIV_NEG, DIV_POS, GPU_USD_PER_HOUR, INK, INK2, MUTED, OURS, PRIOR, SERIES,  # noqa: E402
                    SOURCE_LABEL, SURFACE, TEMPLATE_LABEL, color_of, discover_frontier, exists, fmt_n, label_of,
                    load, save, style, title)

BAR = 0.15  # bar thickness in group units; figure heights below keep this <= ~24 px at 160 dpi


def _pct_axis(ax, axis="y", lo=0, hi=100):
    from matplotlib.ticker import FuncFormatter

    f = FuncFormatter(lambda v, _: f"{v:.0f} %")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(f)
    (ax.set_ylim if axis == "y" else ax.set_xlim)(lo, hi)


def _legend(ax, names, loc="lower right", **kw):
    h = [Patch(facecolor=color_of(n), label=label_of(n)) for n in names]
    ax.legend(handles=h, loc=loc, handlelength=1.0, handleheight=1.0, **kw)


def _top_legend(fig, handles, top_in=1.25):
    """One-row legend under the title block (top_in inches below the figure top)."""
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.015, 1 - top_in / fig.get_figheight()),
               ncol=len(handles), handlelength=1.0, handleheight=1.0, fontsize=14, columnspacing=1.4)


def _rounded_barh(ax, y, w, h, color, left=0):
    """Horizontal bar, square at the baseline, 4px-ish rounded at the data end (drawn as bar + cap)."""
    ax.barh(y, w, height=h, left=left, color=color, linewidth=0, zorder=3)


# ---------------------------------------------------------------- 1
def fig_cost():
    rows = T.overall()
    fig, ax = plt.subplots(figsize=(12, 7.2))
    fig.subplots_adjust(left=0.09, right=0.97, top=0.80, bottom=0.14)
    prior = [r for r in rows if r["run"] == PRIOR]
    pts = [r for r in rows if r["run"] != PRIOR]
    for r in pts:
        local = r["api_usd_per_1k"] <= 0
        x = r["compute_usd_per_1k"] if local else r["api_usd_per_1k"]
        r["_x"] = x
        c = color_of(r["run"])
        ax.errorbar(x, 100 * r["accuracy"], yerr=[[100 * (r["accuracy"] - r["ci_lo"])], [100 * (r["ci_hi"] - r["accuracy"])]],
                    fmt="o", ms=14, color=c, ecolor=c, elinewidth=2.5, capsize=7, capthick=2.5,
                    markeredgecolor=SURFACE, markeredgewidth=2, zorder=4)
        n_txt = f"all {fmt_n(r['n'])} test questions" if r["ci"] == "Wilson" else f"{r['n']}-question sample"
        cost_txt = (f"~${x:.3f} GPU time, $0 API" if local else f"${x:.2f} API")
        dy = {"baseline_sonnet_full400": 30, "baseline_haiku_full400": -48}.get(r["run"], 0)
        ax.annotate(f"{r['system']}  {100 * r['accuracy']:.1f} %\n{cost_txt} · {n_txt}",
                    (x, 100 * r["accuracy"]), xytext=(18, dy), textcoords="offset points", va="center",
                    fontsize=15, color=INK, zorder=5)
    if prior:
        p = prior[0]
        ax.axhspan(100 * p["ci_lo"], 100 * p["ci_hi"], color=MUTED, alpha=0.25, lw=0, zorder=1)
        ax.axhline(100 * p["accuracy"], color=MUTED, lw=2, zorder=2)
        ax.text(1.3e-3, 100 * p["accuracy"] + 1.5, f"Guess the usual answer per question template: {100 * p['accuracy']:.1f} %",
                fontsize=14, color=INK2, va="bottom")
    ax.set_xscale("log")
    ax.set_xlim(1e-3, 3e3)
    _pct_axis(ax, "y", 0, 100)
    ax.set_xlabel("Cost per 1,000 questions (US$, log scale)")
    ax.set_ylabel("Accuracy on the test split")
    from matplotlib.ticker import FuncFormatter

    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:g}"))
    ours = [r for r in rows if r["run"] == OURS][0]
    best = max((r for r in pts if r["run"] != OURS), key=lambda r: r["accuracy"], default=None)
    head = "Higher accuracy than frontier models, at a fraction of a cent"
    sub = (f"Error bars: 95 % CI. Ours: Wilson, all {fmt_n(ours['n'])} test questions. Frontier: n = 400 stratified\n"
           f"sample, re-weighted to the test mix, stratified bootstrap. Our cost = wall-clock at ${GPU_USD_PER_HOUR:.2f}/GPU-hour.")
    title(ax, head, sub)
    h = [Line2D([0], [0], marker="o", ls="", ms=12, color=color_of(r["run"]), label=r["system"]) for r in pts]
    if prior:
        h.append(Line2D([0], [0], color=MUTED, lw=2.5, label="Template prior"))
    ax.legend(handles=h, loc="lower right", fontsize=14)
    save(fig, "fig-1-accuracy-vs-cost")
    plt.close(fig)


# ---------------------------------------------------------------- 2
def fig_strata():
    rows = T.by_stratum()
    sys_ = [OURS] + list(discover_frontier())
    k = len(sys_)
    fig, ax = plt.subplots(figsize=(12, 2.6 + 1.0 * len(rows)))
    fig.subplots_adjust(left=0.30, right=0.93, top=1 - 1.9 / fig.get_figheight(), bottom=0.9 / fig.get_figheight())
    ylabels = []
    for i, r in enumerate(rows):
        y0 = len(rows) - 1 - i
        for j, s in enumerate(sys_):
            if f"{s}:acc" not in r:
                continue
            y = y0 + (k - 1) / 2 * BAR * 1.3 - j * BAR * 1.3
            a, lo, hi = (100 * r[f"{s}:{x}"] for x in ("acc", "lo", "hi"))
            ax.barh(y, a, height=BAR, color=color_of(s), lw=0, zorder=3)
            ax.plot([lo, hi], [y, y], color=INK2, lw=1.5, zorder=4, solid_capstyle="butt")
            if s == OURS:
                ax.text(max(a, hi) + 1.2, y, f"{a:.1f} %", va="center", fontsize=14, color=INK, fontweight="bold")
        ns = " · ".join(fmt_n(r[f"{s}:n"]) for s in sys_ if f"{s}:n" in r)
        typ = r["type"] + (" (LLM judge)" if r["type"] == "text" else "")
        ylabels.append((y0, f"{SOURCE_LABEL.get(r['source'], r['source'])} · {typ}\nn = {ns}"))
    ax.set_yticks([y for y, _ in ylabels], [t for _, t in ylabels], fontsize=14)
    ax.grid(axis="y", visible=False)
    _pct_axis(ax, "x", 0, 108)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Accuracy (thin line: 95 % Wilson CI)")
    title(ax, "Exact on BIM and vector plans; scans and free text are hard",
          "Accuracy by source and question type. n = ours (all test questions) · Sonnet · Haiku (sample).")
    _top_legend(fig, [Patch(facecolor=color_of(s), label=label_of(s)) for s in sys_])
    save(fig, "fig-2-accuracy-by-source-type")
    plt.close(fig)


# ---------------------------------------------------------------- 3
def fig_selective():
    sel = T.selective()
    fig, ax = plt.subplots(figsize=(12, 7.2))
    fig.subplots_adjust(left=0.09, right=0.96, top=0.80, bottom=0.13)
    spec = [("all", "All test questions", SERIES[0]), ("cubicasa", "CubiCasa (raster scans) only", SERIES[6])]
    for key, lab, c in spec:
        t, cov, acc = (np.array(v) for v in sel[key]["curve"])
        ax.step(100 * np.r_[cov], 100 * np.r_[acc], where="post", color=c, lw=2.5, label=lab, zorder=3)
        th = [p for p in sel[key]["thresholds"] if p["threshold"] == T.ROUTER_MIN_CONF][0]
        x, y = 100 * th["coverage"], 100 * th["accuracy_answered"]
        ax.plot(x, y, "o", ms=13, color=c, markeredgecolor=SURFACE, markeredgewidth=2.5, zorder=5)
        tx, ty = (58, 85.5) if key == "all" else (58, 80.5)
        ax.annotate(f"{lab}: answers {x:.1f} %, {y:.1f} % right\n(vs {100 * sel[key]['base_acc']:.1f} % when forced to answer all)",
                    (x, y), xytext=(tx, ty), textcoords="data", fontsize=14, color=INK, va="center",
                    arrowprops=dict(arrowstyle="-", color=INK2, lw=1.2, shrinkB=8))
    ax.set_xlim(102, 0)
    _pct_axis(ax, "y", 76, 100.5)
    from matplotlib.ticker import FuncFormatter

    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f} %"))
    ax.set_xlabel("Coverage: share of questions answered (most confident first)")
    ax.set_ylabel("Accuracy of the answered ones")
    title(ax, "Confidence is honest: abstaining on the unsure few lifts accuracy",
          f"Our answers sorted by the solver's own confidence. Dot = the router's hand-off threshold:\n"
          f"below confidence {T.ROUTER_MIN_CONF} it says \"not sure\" (or asks a fallback) instead of guessing.")
    ax.legend(loc="lower left", handlelength=1.6)
    save(fig, "fig-3-accuracy-vs-coverage")
    plt.close(fig)


# ---------------------------------------------------------------- 4
def _template_systems():
    s = [OURS]
    if "baseline_sonnet_full400" in discover_frontier():
        s.append("baseline_sonnet_full400")
    if exists("generic_cubicasa_300_haiku"):
        s.append("generic_cubicasa_300_haiku")
    return s


def fig_templates():
    rows = [r for r in T.by_template() if f"{OURS}:acc" in r]
    rows.sort(key=lambda r: r[f"{OURS}:acc"])
    sys_ = _template_systems()
    k = len(sys_)
    fig, ax = plt.subplots(figsize=(12, 2.4 + 1.0 * len(rows)))
    fig.subplots_adjust(left=0.24, right=0.95, top=1 - 1.7 / fig.get_figheight(), bottom=0.9 / fig.get_figheight())
    ticks = []
    for i, r in enumerate(rows):
        for j, s in enumerate(sys_):
            if f"{s}:acc" not in r:
                continue
            y = i + (k - 1) / 2 * BAR * 1.3 - j * BAR * 1.3
            a, lo, hi = (100 * r[f"{s}:{x}"] for x in ("acc", "lo", "hi"))
            ax.barh(y, a, height=BAR, color=color_of(s), lw=0, zorder=3)
            ax.plot([lo, hi], [y, y], color=INK2, lw=1.5, zorder=4)
            if s == OURS:
                ax.text(max(a, hi) + 1.2, y, f"{a:.0f} %", va="center", fontsize=14, color=INK, fontweight="bold")
        if f"{PRIOR}:acc" in r:
            p = 100 * r[f"{PRIOR}:acc"]
            ax.plot([p, p], [i - 0.42, i + 0.42], color=INK, lw=2.5, zorder=5, solid_capstyle="butt")
        ns = " · ".join(fmt_n(r[f"{s}:n"]) if f"{s}:n" in r else "0" for s in sys_)
        ticks.append((i, f"{TEMPLATE_LABEL[r['template']]}\nn = {ns}"))
    ax.set_yticks([t[0] for t in ticks], [t[1] for t in ticks], fontsize=14)
    ax.grid(axis="y", visible=False)
    _pct_axis(ax, "x", 0, 108)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Accuracy, exact count (thin line: 95 % Wilson CI)")
    title(ax, "CubiCasa: windows and doors are hard; a constant guess wins on kitchens",
          "Per question template. n = ours · Sonnet direct · Generic VLM pipeline (Haiku).\n"
          "Black tick = guessing the most common answer for that template.")
    h = [Patch(facecolor=color_of(s), label=label_of(s)) for s in sys_]
    h.append(Line2D([0], [0], color=INK, lw=2.5, label="Template prior"))
    ax.legend(handles=h, loc="lower right", handlelength=1.0, fontsize=14)
    save(fig, "fig-4a-cubicasa-templates")
    plt.close(fig)


def fig_error_direction():
    rows = [r for r in T.by_template() if f"{OURS}:acc" in r]
    rows.sort(key=lambda r: r[f"{OURS}:acc"])
    fig, ax = plt.subplots(figsize=(12, 2.4 + 0.6 * len(rows)))
    fig.subplots_adjust(left=0.20, right=0.80, top=1 - 1.7 / fig.get_figheight(), bottom=0.9 / fig.get_figheight())
    for i, r in enumerate(rows):
        u, o, a = (100 * r[f"{OURS}:{x}"] for x in ("under", "over", "acc"))
        ax.barh(i, -u, height=0.32, color=DIV_NEG, lw=0, zorder=3)
        ax.barh(i, o, height=0.32, color=DIV_POS, lw=0, zorder=3)
        if u >= 4:
            ax.text(-u - 1, i, f"{u:.0f} %", ha="right", va="center", fontsize=14, color=INK)
        if o >= 4:
            ax.text(o + 1, i, f"{o:.0f} %", ha="left", va="center", fontsize=14, color=INK)
        ax.text(1.02, i, f"{a:.0f} % exact", transform=ax.get_yaxis_transform(), va="center", fontsize=14, color=INK2)
    ax.axvline(0, color=INK2, lw=1.2, zorder=4)
    ax.set_yticks(range(len(rows)), [TEMPLATE_LABEL[r["template"]] for r in rows], fontsize=15)
    ax.grid(axis="y", visible=False)
    lim = 5 * np.ceil(max(max(100 * r[f"{OURS}:under"], 100 * r[f"{OURS}:over"]) for r in rows) / 5) + 8
    ax.set_xlim(-lim, lim)
    from matplotlib.ticker import FuncFormatter

    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{abs(v):.0f} %"))
    ax.set_xlabel("Share of questions answered too low  |  too high")
    title(ax, "Windows are mostly missed; doors and sinks over-counted",
          "Our CubiCasa detector, all test questions per template: share counted too low (left) or too high (right).")
    ax.legend(handles=[Patch(facecolor=DIV_NEG, label="under-count"), Patch(facecolor=DIV_POS, label="over-count")],
              loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, handlelength=1.0, fontsize=14)
    save(fig, "fig-4b-cubicasa-error-direction")
    plt.close(fig)


def fig_error_hist():
    h = T.error_histogram()
    fig, ax = plt.subplots(figsize=(12, 6.6))
    fig.subplots_adjust(left=0.09, right=0.97, top=0.80, bottom=0.14)
    xs = [r["error"] for r in h]
    for r in h:
        c = DIV_MID if r["error"] == 0 else (DIV_NEG if r["error"] < 0 else DIV_POS)
        ax.bar(r["error"], 100 * r["share"], width=0.62, color=c, lw=0, zorder=3)
        if r["share"] >= 0.005:
            ax.text(r["error"], 100 * r["share"] + 1, f"{100 * r['share']:.1f} %" if r["share"] < 0.1 else
                    f"{100 * r['share']:.0f} %", ha="center", fontsize=13, color=INK)
    ax.set_xticks(xs, [("≤ " if x == xs[0] else "≥ +" if x == xs[-1] else "+" if x > 0 else "") + str(x) for x in xs])
    ax.grid(axis="x", visible=False)
    _pct_axis(ax, "y", 0, 100 * max(r["share"] for r in h) + 8)
    ax.set_xlabel("Predicted count minus true count")
    ax.set_ylabel("Share of CubiCasa questions")
    under = sum(r["share"] for r in h if r["error"] < 0)
    over = sum(r["share"] for r in h if r["error"] > 0)
    off1 = sum(r["share"] for r in h if abs(r["error"]) == 1)
    title(ax, f"When a count is wrong, it is usually off by one",
          f"CubiCasa, ours, all test questions: {100 * under:.1f} % too low, {100 * over:.1f} % too high; "
          f"{100 * off1:.1f} % are off by exactly one.")
    save(fig, "fig-4c-cubicasa-error-histogram")
    plt.close(fig)


# ---------------------------------------------------------------- 5
def fig_language():
    rows = T.by_language()
    rows = [r for r in rows if r[f"{OURS}:n"] >= 30]
    sys_ = [OURS] + list(discover_frontier())
    k = len(sys_)
    fig, ax = plt.subplots(figsize=(12, 7.2))
    fig.subplots_adjust(left=0.09, right=0.97, top=0.76, bottom=0.2)
    w = 0.16
    for i, r in enumerate(rows):
        for j, s in enumerate(sys_):
            if f"{s}:acc" not in r:
                continue
            x = i - (k - 1) / 2 * w * 1.12 + j * w * 1.12
            a, lo, hi = (100 * r[f"{s}:{q}"] for q in ("acc", "lo", "hi"))
            ax.bar(x, a, width=w, color=color_of(s), lw=0, zorder=3)
            ax.plot([x, x], [lo, hi], color=INK2, lw=1.5, zorder=4)
            if s == OURS:
                ax.text(x, max(a, hi) + 1.5, f"{a:.0f}", ha="center", fontsize=14, color=INK, fontweight="bold")
    names = {"en": "English", "fi": "Finnish", "de": "German", "fr": "French", "it": "Italian", "nl": "Dutch",
             "da": "Danish", "et": "Estonian", "sv": "Swedish"}
    ax.set_xticks(range(len(rows)), [f"{names.get(r['lang'], r['lang'])}\n{fmt_n(r[f'{OURS}:n'])}\n"
                                     + " · ".join(str(r[f'{s}:n']) for s in sys_[1:] if f"{s}:n" in r)
                                     for r in rows], fontsize=14)
    ax.grid(axis="x", visible=False)
    _pct_axis(ax, "y", 0, 108)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("Accuracy (thin line: 95 % Wilson CI)")
    tw = T.language_twins()
    title(ax, "Language does not move our answers; the drawing type does",
          f"Our {fmt_n(tw['pairs'])} Finnish/English twin questions (same drawing) get identical answers in "
          f"{100 * tw['same_answer'] / max(1, tw['pairs']):.0f} % of cases.\n"
          "Gaps reflect which sources ask in each language. n under each language: ours, then Sonnet · Haiku.")
    _top_legend(fig, [Patch(facecolor=color_of(s), label=label_of(s)) for s in sys_], top_in=1.35)
    save(fig, "fig-5-accuracy-by-language")
    plt.close(fig)


# ---------------------------------------------------------------- 6
def fig_latency():
    rows = T.latency()
    keep = [r for r in rows if r["run"] != OURS or "slowest" not in r["solver"] or r["solver"].startswith("CubiCasa")]
    keep.sort(key=lambda r: r["p50"])
    fig, ax = plt.subplots(figsize=(12, 2.8 + 0.75 * len(keep)))
    fig.subplots_adjust(left=0.36, right=0.86, top=1 - 2.1 / fig.get_figheight(), bottom=1.0 / fig.get_figheight())
    for i, r in enumerate(keep):
        c = color_of(r["run"])
        v = np.clip(r["values"], 5e-4, None)
        lo, q1, med, q3, hi = np.percentile(v, [5, 25, 50, 75, 95])
        ax.plot([lo, hi], [i, i], color=c, lw=2, zorder=3, solid_capstyle="round")
        ax.barh(i, q3 - q1, left=q1, height=0.3, color=c, lw=0, zorder=3)
        ax.plot([med, med], [i - 0.15, i + 0.15], color=SURFACE, lw=3, zorder=4)
        mt = f"{1000 * med:.0f} ms" if med < 1 else (f"{med:.1f} s" if med < 10 else f"{med:.0f} s")
        ax.text(1.01, i, mt, transform=ax.get_yaxis_transform(),
                va="center", fontsize=14, color=INK, fontweight="bold")
    lab = []
    for r in keep:
        n = r["solver"].replace(" · slowest per drawing", "\n(slowest question per drawing)")
        lab.append(f"{n}  (n = {fmt_n(r['n'])})" if "\n" not in n else n)
    ax.set_yticks(range(len(keep)), lab, fontsize=13)
    ax.grid(axis="y", visible=False)
    ax.set_xscale("log")
    ax.set_xlim(5e-4, 1e3)
    from matplotlib.ticker import FuncFormatter

    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g} s"))
    ax.set_xlabel("Seconds per question (log scale)")
    ax.text(1.01, len(keep) - 0.35, "median", transform=ax.get_yaxis_transform(), fontsize=13, color=INK2)
    title(ax, "Answers in milliseconds, not tens of seconds",
          "Wall-clock per question as logged by eval.py. Box = middle 50 %, whiskers = 5th to 95th percentile.\n"
          "Questions on one drawing share a detector pass, so the slowest one is the cold path.")
    h = [Patch(facecolor=color_of(s), label=label_of(s)) for s in dict.fromkeys(r["run"] for r in keep)]
    _top_legend(fig, h, top_in=1.3)
    save(fig, "fig-6-latency")
    plt.close(fig)


def main():
    style()
    fig_cost()
    fig_strata()
    fig_selective()
    fig_templates()
    fig_error_direction()
    fig_error_hist()
    fig_language()
    fig_latency()


if __name__ == "__main__":
    main()
