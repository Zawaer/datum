# Third-party data, models and software

The code in this repository is MIT-licensed (see `LICENSE`). That licence covers **our code only**. The
datasets, model weights and libraries below keep their own licences, and some of them are stricter than MIT.

## Dataset (not included in this repository)

The Stoa "Make Blueprints Talk" Junction 2026 dataset is **not redistributed here**: it is for non-commercial
use in the Junction challenge, and every file keeps its own licence and credit (`data/<source>/LICENSE.md` in
the dataset). Questions inherit the licence of the drawing they ask about. Get it from the challenge page.

| source | licence | credit we show |
|---|---|---|
| cubicasa5k | **CC BY-NC-SA 4.0** (non-commercial, share-alike) | CubiCasa5K, (c) 2019 CubiCasa. Kalervo, Ylioinas, Häikiö, Karhu, Kannala: "CubiCasa5K: A Dataset and an Improved Multi-Task Model for Floorplan Image Analysis", SCIA 2019. https://zenodo.org/records/2613548 |
| swiss_dwellings | CC BY 4.0 | Swiss Dwellings v3.0.0 by Matthias Standfest, Michael Franzen, Yvonne Schröder, Luis Gonzalez Medina, Yarilo Villanueva Hernandez, Jan Hendrik Buck, Yen-Ling Tan, Milena Niedzwiecka, Rachele Colmegna (Archilyse AG), https://doi.org/10.5281/zenodo.7788422. Drawings rendered by the dataset authors; Archilyse AG does not endorse them. |
| ifc_models | per file (CC BY 4.0, CC BY-ND 3.0, MIT, GPL-3.0, KIT "unrestricted use", ...) | the per-file credit, e.g. "Molio Demo-hus, (C) original authors (unnamed) - buildingSMART Community Sample-Test-Files contributors, CC BY 4.0" |
| ifc_bench | models per file; questions CC BY 4.0 | IFC-Bench v2, (c) 2025 Sylvain Hellin (Hellin, Nousias & Borrmann, GNI 2026), https://huggingface.co/datasets/sylvainhellin/ifc-bench |
| opening_design | CC BY-SA 4.0 or MIT, per file | OpeningDesign (Madison, WI) and the project team named in each title block |
| habs | public domain (US federal works) | Historic American Buildings Survey, Library of Congress (courtesy) |
| finna | CC BY 4.0 | Helsinki City Archives / Architecture & Design Museum, via Finna, per file |
| europeana, wikimedia | per file (PDM, CC0, CC BY, CC BY-SA, CC BY-NC, ...) | per file |

### Images in this repository that show dataset drawings

The screenshots in `docs/img/` and `docs/deck/img/` (and `app/static/og.png`) show dataset drawings with the
credit line visible at the bottom. **These images are not MIT-licensed**: each one carries the licence of the
drawing it shows.

| image | drawing | licence of the image |
|---|---|---|
| `docs/img/tour-1.png`, `tour-2.png`, `tour-3.png`, `phone.png`, `design-{before,after}-1440-{empty,count,tour}.png`, `design-{before,after}-1920-area.png`, `design-{before,after}-390-count.png`, `app/static/og.png`, `docs/deck/img/step-1.jpg`, `step-2.jpg`, `step-3.jpg`, `landing.jpg`, `deck-swiss-doors.jpg`, `deck-german-area.jpg`, `deck-correction.jpg`, `feat-3d.jpg`, `feat-3d-card.jpg`, `feat-3d-rise.jpg`, `feat-xray.jpg`, `feat-xray-card.jpg`, `feat-heatmap.jpg`, `feat-takeoff.jpg` | Swiss Dwellings floor plan | CC BY 4.0, credit above |
| `docs/img/tour-4.png`, `docs/img/design-{before,after}-1920-cubicasa.png`, `docs/deck/img/step-4.jpg`, `finnish.jpg`, `deck-finnish-vlm.jpg`, `feat-voice.jpg` | CubiCasa5K plan | **CC BY-NC-SA 4.0**, credit above; non-commercial only, adaptations under the same licence |
| `docs/img/tour-5.png`, `tour-6.png`, `tour-7.png`, `docs/deck/img/step-5b.jpg`, `step-5.jpg`, `step-6.jpg`, `step-7.jpg`, `deck-ifc-walls.jpg` | Molio Demo-hus IFC model (buildingSMART Community Sample-Test-Files) | CC BY 4.0, credit above |
| `docs/deck/deck.pdf`, `docs/deck/deck.html` | embeds the step images above | each embedded image keeps its licence (above); the rest of the deck is MIT |
| `docs/img/scoreboard.png`, `docs/img/design-{before,after}-1440-results.png`, `docs/img/fig-*.png` / `.svg`, `docs/deck/img/feat-ghost.jpg` (answer card only; the question text is from a Swiss Dwellings question, CC BY 4.0), `docs/deck/img/feat-how.jpg` | no drawing (our UI and charts) | MIT |

Every screenshot above shows the drawing's credit line (licence + source) under the drawing; long author lists
are cut with "…" in narrow layouts, and the cropped `feat-*-card.jpg`, `feat-3d-rise.jpg`, `feat-heatmap.jpg`, `feat-takeoff.jpg` and `feat-voice.jpg` carry the short credit line added under the crop; the full credits are in the table above and in `README.md`.

The question texts quoted in `app/tour.json`, `app/server.py` and the docs are short examples from the dataset
and carry the licence of their drawing (above). The result files we commit (`app/frontier.json`,
`app/calibration.json`, `analysis/out/`, `runs/*.summary.md`, `bp/ifctext/judge_labels.json`) hold our own
predictions, scores and aggregates keyed by question id, not the questions, drawings or gold answers.

## Pretrained models and weights

| model | used for | licence | notes |
|---|---|---|---|
| Qwen3-VL-2B/4B/8B-Instruct (Alibaba Qwen) | generic grounded fallback, fine-tuned VLM solver | Apache-2.0 | Downloaded at run time from Hugging Face, not redistributed. |
| Our Qwen3-VL LoRA adapters | VLM solver | Apache-2.0 base; trained on dataset drawings | Not committed. If ever published, they derive from the training data too: trained on CubiCasa5K (CC BY-NC-SA 4.0), so publish under CC BY-NC-SA 4.0 with the credits above. |
| Ultralytics YOLO11 (`yolo11s.pt`) | starting point for the plan-symbol detector | **AGPL-3.0** (or Ultralytics Enterprise licence) | Downloaded by Ultralytics, not redistributed. |
| Our fine-tuned YOLO11 detector (`cache/cubicasa/weights/best.pt`) | cubicasa solver | **AGPL-3.0** (Ultralytics) **and CC BY-NC-SA 4.0** (CubiCasa5K training data) | Not committed. Do not publish under MIT. |
| Anthropic Claude (Sonnet, Haiku) via the Claude Code CLI | frontier baseline, LLM judge, optional fallback | Anthropic commercial terms (API service) | No weights; needs your own account. |
| Google Gemini 3.1 Pro (API) | frontier baseline only (`bp/solvers/gemini_vlm.py`) | Google Gemini API terms | No weights; needs your own `GEMINI_API_KEY`. |
| NVIDIA Nemotron 3.5 Super VL (NVIDIA API catalog) | baseline only (`bp/solvers/nemotron_vlm.py`) | NVIDIA API terms of use; the open weights are under NVIDIA's open model licence | Called through the hosted API; no weights here; needs your own `NVIDIA_API_KEY`. |
| PaliGemma 2 (Google) | experimental fine-tune, not used by the final system | Gemma Terms of Use | Base downloaded from Hugging Face; our fine-tune is not committed or published. |
| Kokoro-82M (hexgrad) | voice-over of the demo video (`docs/deck/make_video.py`) | Apache-2.0 | Runs locally in a separate venv; neither the model nor the generated audio is committed. |

## Software dependencies

Licences as declared by each project. Python packages are installed from PyPI, three.js and the fonts from CDNs; none of
them is vendored in this repository.

| package | licence | used in |
|---|---|---|
| **PyMuPDF** | **AGPL-3.0** (or Artifex commercial) | PDF reading/rendering: `bp/swiss`, `bp/generic`, `bp/vlm`, `app/server.py` |
| **Ultralytics** | **AGPL-3.0** (or Ultralytics Enterprise) | YOLO detector: `bp/solvers/cubicasa.py`, `bp/cubicasa/infer.py`, `train/cubicasa/` |
| IfcOpenShell | LGPL-3.0 | IFC parsing and geometry: `bp/ifc`, `bp/ifctext` |
| ezdxf | MIT | DXF parsing: `bp/swiss` |
| Shapely | BSD-3-Clause | geometry |
| NumPy, pandas | BSD-3-Clause | |
| Pillow | MIT-CMU (HPND) | images |
| OpenCV (opencv-python-headless) | Apache-2.0 | images |
| lxml | BSD-3-Clause | SVG parsing |
| svgelements | MIT | SVG parsing |
| matplotlib | Matplotlib licence (PSF-based, BSD-compatible) | plots |
| langdetect | Apache-2.0 | language detection |
| FastAPI, Pydantic | MIT | demo server |
| Uvicorn | BSD-3-Clause | demo server |
| PyTorch | BSD-3-Clause | models |
| Hugging Face Transformers, PEFT, TRL, Accelerate, Datasets | Apache-2.0 | VLM inference and LoRA fine-tuning |
| qwen-vl-utils | Apache-2.0 | Qwen3-VL image preprocessing |
| torchvision | BSD-3-Clause | models |
| kokoro (Python package) | Apache-2.0 | video voice-over only, separate venv |
| vLLM | Apache-2.0 | optional VLM serving |
| Playwright | Apache-2.0 | demo recording / screenshots |
| three.js | MIT | 3D viewer (loaded from unpkg) |
| Caddy | Apache-2.0 | demo reverse proxy (`deploy/`) |
| Claude Code CLI (`@anthropic-ai/claude-code`) | Anthropic commercial terms | installed into the demo image by `deploy/Dockerfile` for the frontier-model fallback; not vendored |
| IBM Plex Sans / Mono, Inter (fonts) | SIL Open Font License 1.1 | demo UI and deck, loaded from Google Fonts |

### What the AGPL dependencies mean for this repository

PyMuPDF and Ultralytics are AGPL-3.0. Our own source code stays MIT: we only import these packages, we do not
copy or modify their code, and we do not ship them in this repository. However:

- Anyone who **distributes** a combined build (e.g. a Docker image with PyMuPDF/Ultralytics inside) must do so
  under AGPL-3.0 terms for that combined work, or hold commercial licences from Artifex / Ultralytics.
- Anyone who **runs a modified version** of these libraries as a network service must offer its source (AGPL
  section 13). Our public demo runs them unmodified, and its full source is this public repository.
- The fine-tuned YOLO weights are AGPL-3.0 per Ultralytics and, because of the training data, also
  CC BY-NC-SA 4.0. They are not part of this repository.

A fully permissive build would need to replace PyMuPDF (e.g. with pypdfium2, Apache-2.0/BSD) and the
Ultralytics detector (e.g. RT-DETR via Transformers, or YOLOX, both Apache-2.0).
