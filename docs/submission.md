# Submission draft (numbers marked TODO get filled from runs/*.summary.md)

## Project name (≤ 30 chars)
Blueprints That Talk  _(20)_

Alternatives: "Proof, not guesses" · "Drawing Witness" · "Show Your Work"

## Punchline (≤ 200 chars)
Ask a construction drawing or BIM model anything, in any language. Every answer is counted out on the drawing so you can check it in seconds, at a fraction of a cent per question.  _(~185)_

## Description (≤ 5000 chars, markdown)

**The problem.** Quantity takeoff (counting doors, measuring room areas, summing wall lengths) is slow
manual work, and general AI models are not trustworthy at it. A frontier vision model gets areas on Swiss
floor plans right only 37 % of the time and BIM measures 0 % of the time in our tests, and when it is
wrong it looks exactly as confident as when it is right.

**Our approach: answers with proof.** Blueprints That Talk does not ask one big model to guess. A router sends each
question to the cheapest method that can answer it *exactly*, and every method returns its evidence:

- **CAD / vector drawings (DXF, PDF):** we read the geometry and layers directly. Doors, windows, sanitary
  fixtures, room outlines and apartment boundaries become exact counts and areas.
- **BIM models (IFC):** IfcOpenShell computes counts, net areas, lengths and volumes from quantity sets
  and geometry; the answer comes with the GlobalIds of every element that contributed.
- **Raster floor plans (scans, images):** a small symbol detector trained on open annotations finds
  windows, doors, toilets, sinks, showers… and draws a numbered box around each one. TODO: final method.
- **Multilingual:** questions in English, Finnish, German, French, Italian, Danish, Estonian… map onto
  the same typed queries.

**Verification in seconds.** The answer is *counted out on the drawing*: numbered boxes appear one by one
as the count ticks up; for areas each room is traced with its m² and the sum is shown; for BIM the
contributing elements light up in 3D. If the solver missed something or counted something wrong, click it:
the answer recalculates on the spot. That turns a chatbot into a takeoff tool a professional can sign off.

**Honest about uncertainty.** Each answer carries a confidence. When the solver can't map a question
or isn't sure, it says so instead of guessing.

**Cheap by design.** Deterministic code and small local models answer almost every question for
~$0 marginal cost and in milliseconds. A frontier model is only an optional fallback.

### Results (held-out test split, official tolerance: counts exact, measures within 2 %)

| | accuracy | cost / 1,000 questions | time / question |
|---|---|---|---|
| Frontier VLM (Claude Sonnet 5.5, drawing + question) | 67.5 % | $15.67 | ~8 s |
| Guess the most common answer per question type | 40.3 % | $0 | 0 s |
| **Blueprints That Talk** | TODO | TODO (~$0) | TODO |

By source: Swiss floor plans 97.0 % (frontier 61 %), IFC room areas 99.8 % (frontier 0 %), TODO cubicasa.
All numbers come from `eval.py` in the repo; the split is by drawing, so no drawing used for tuning appears in test.

### Why this won't be obsolete next year
Better frontier models will still not be exact, cheap, or checkable. Our solvers return the elements behind the
answer, which is what a construction professional needs to trust a number, and plug in a stronger model
only where geometry can't answer.

## Technologies
Python, IfcOpenShell, ezdxf, PyMuPDF, Shapely, Ultralytics YOLO (TODO confirm), PyTorch, FastAPI, three.js,
Claude (baseline and optional fallback).

## Video (2 min) outline
1. 0:00–0:15: the problem: a frontier model confidently miscounts a plan (show a wrong answer).
2. 0:15–0:50: same question in Finnish on our app: boxes appear and count up to the right answer; ground truth ✓.
3. 0:50–1:10: correct an item by clicking; the answer updates. Area question: rooms trace and sum.
4. 1:10–1:35: BIM model: walls light up in 3D while the length adds up.
5. 1:35–2:00: the table: accuracy vs frontier, $ per 1,000 questions, "every answer comes with proof".

## Credits
Drawings shown are from the Junction dataset with their licences: Swiss Dwellings (Archilyse AG, CC BY 4.0),
CubiCasa5K (CC BY-NC-SA 4.0), IFC sample models (per-file licences, see data/<source>/LICENSE.md).
