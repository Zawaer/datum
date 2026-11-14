# Provenance checker for LLM-written answers

LLM answers are the least verifiable part of the system: a rule or a detector computes its number from
geometry, an LLM writes it. `bp/provenance.py` checks every number and every quoted name in an
LLM answer against the source lines the model cited, and flags the answer when they don't match.

```python
from bp.provenance import check
check(answer_text, cited_sources, computed=(), context=())
# -> {"status": "verified" | "partial" | "unverified", "claims": 7, "traced": 7,
#     "numbers": [{"value": 1310.0, "raw": "1,310", "found_in": "sum"}, {"value": 595.0, "raw": "595", "found_in": "f7"}, ...],
#     "quotes":  [{"text": "Office 1", "found_in": "f82"}],
#     "note": "all 7 numbers/names traced to the cited sources"}
```

## What counts as traced

- **A number appears in a cited line.** Formats are normalised (`1 234,5`, `1,234.5`, `1.234,5`, `12 %`,
  `200mm`, `3.5 m2`, `35 1/2"`), and a value only has to match to the precision the answer shows
  (`111.7` matches a source `111.72`). `200 mm` matches `0.2 m`.
- **A number is derived from traced values.** This covers the column sum or average of the answer's own list
  (a "total" line), column sums of the cited lines, per-group sums (for "- Offices (Buero): 17 spaces,
  289.35 m2" it adds up the cited lines that mention *Buero*), counts (number of list lines, cited lines or
  group members), and values the solver recomputed (`computed`). Pairwise sums, differences, products, ratios
  and percentages of traced values are also accepted, but only for numbers shown with decimals or as a %.
  With about 40 values there are about 8,000 pairwise results, so a bare integer would often match one by
  chance.
- **A quoted name** (`'...'`, `"..."`, `‘...’`, `“...”`) or an identifier with digits (`A-801`, `B3`, `E00_OKRD`)
  appears as a substring of a cited line, ignoring case and whitespace. Foot and inch marks (`12' - 0"`) are
  not read as quotes.
- **Not counted:** inline citations (`[f24]`, `f52–f58`), list numbering, the 2 in `m2`, and numbers after
  "rough estimate" (they are reported as `found_in: "estimate"`, since the answer already says they are
  estimates).
- `context` holds lines that were shown to the model but not cited. A number found only there gets
  `found_in: "uncited:<id>"`. It is not invented, but the citation doesn't support it.

**Status:** `verified` means all claims are traced to the cited lines or derived from them. `unverified`
means less than 80 % are. `partial` covers everything in between, plus answers with nothing to check.
The 80 % cut was chosen on the dev split only.

## Where it runs

- **`ifctext`** (free-text IFC answers, `bp/solvers/ifctext.py`): checks the answer against the cited fact lines
  (`[f12] ...`). The rest of the rendered fact sheet is passed as `context`. Each `ifc` evidence item whose fact
  line traced a number or name gets `"verified": true`.
- **`generic`** text path (`bp/solvers/generic.py`): checks the answer against the text of the cited segments of
  each item. `computed` is the recomputed total. An evidence box gets `"verified": true` when its value is
  printed in its own text, or when the answer's number or name was found in it.
- In both, the result carries `provenance`. If the status is `unverified`, confidence is capped at 0.3 and the
  explanation gains one line: `provenance: only 4 of 9 numbers/names traced to the cited sources: 7.46, ...`.
- Rule-based and detector answers are not checked: their evidence is computed, not written. The
  opening_design PDF text path (`bp/ifctext/pdftext.py`) is not wired yet.

## Measured

`python -m bp.provenance` reproduces everything below. It replays every LLM answer of `ifctext@route` on
ifc_bench (dev and test, the 744 questions routed to the LLM; logged runs from the v6 fact sheet) from the on-disk answer cache, so it costs $0.
A cache miss would be an error. Every replayed answer was identical to the logged one. Judge verdicts come
from the logged runs `runs/ifctext_route_{dev,test}.jsonl`. Per-question output is in
`runs/provenance_ifctext.jsonl`.

### Summary table: ifc_bench free-text answers (Haiku, fact sheet)

| split | status | n | share | judge accuracy |
|---|---|---|---|---|
| dev | verified | 317 | 49% | **63.4%** |
| dev | partial | 240 | 37% | 52.1% |
| dev | partial (nothing to check) | 44 | 7% | 79.5% |
| dev | unverified | 51 | 8% | **27.5%** |
| dev | all | 652 | 100% | 57.5% |
| test | verified | 43 | 47% | **41.9%** |
| test | partial | 48 | 52% | 39.6% |
| test | unverified | 1 | 1% | **0.0%** |
| test | all | 92 | 100% | 40.2% |

- On test, all non-verified answers together were judge-correct 38.8 % of the time (49 answers), against
  41.9 % for verified ones. On dev it is 51.9 % (335 answers) against 63.4 %.
- Claims traced: 91 % of 20,867 numbers and names on dev, 97 % of 4,328 on test. 66 % of `ifc` evidence items
  are now marked `verified`.
- The confidence cap improves calibration slightly. Brier score goes from 0.254 to 0.246 on dev and from
  0.280 to 0.277 on test. AUROC goes from 0.48 to 0.53 on dev and from 0.50 to 0.51 on test. Without the cap,
  ifctext gives every non-"not available" answer 0.6.
- **Fabrication test.** In each verified answer, one number was changed to a plausible wrong value in the same
  format (×0.87, ×1.13, ×1.5 or ×0.5, plus 1, 3 or 7). The checker flagged 249 of 357 (70 %): 231 became
  partial and 18 unverified. Most changed integers of 100 and above, and most changed decimals, are caught.
  The misses are mostly small counts (< 10) that some other cited line also contains.

### Generic text path (opening_design)

The generic solver's LLM calls are not cached. These runs were therefore re-scored from the logged evidence
labels, which hold each cited segment's text truncated to 80 characters:

| run | verified | partial (nothing to check) | unverified |
|---|---|---|---|
| generic_opening_final (Haiku) | 58 (97 % correct) | 1 (100 %) | 0 |
| generic_opening_nemotron | 52 (100 %) | 0 | 0 |

These answers are already constrained by construction: the total is recomputed from cited items, and values
are checked against the cited text. The checker therefore agrees with them. The two wrong "verified"
answers counted the right rows of the wrong table, which provenance cannot see.

## What it does and doesn't tell you

The checker finds **unsupported numbers and names**. It does not judge **whether the answer is correct**.
Most wrong ifc_bench answers are faithful to the fact sheet: they answer a slightly different scope, leave
out a group the gold lists, or use different names. That is why 37 to 58 % of verified answers are still
judged wrong, and why verified and partial answers differ by only 2 to 11 points (unverified ones are clearly
worse: 27.5 % on dev). What the checker adds is a per-number trace (`found_in` = fact id → GlobalIds in 3D),
a confidence cap for answers that don't support themselves, and a flag on about seven in ten injected
fabrications.

Known gaps:
- Subset sums are only recognised when the group can be named by a word from the answer line.
- A small integer passes if any cited line contains it.
- Unit conversions are limited to mm/cm/m/km (no ft ↔ m).
- Names are only checked when quoted. Unquoted list labels are not checked.
