# Tools used and challenges entered

_Project name: **Datum** (tagline "blueprints that talk"). The challenge list is locked in (Toivo, Sat 14.11.2026). The tools list is not: it records what we use now, and new tools can still be added if they help. Main challenge: **Stoa, "Make Blueprints Talk"**._

## Challenges we enter with this project

| Challenge | Why we qualify | What to submit |
|---|---|---|
| **Stoa: Make Blueprints Talk** (main) | The whole project | Submission form text in [submission.md](submission.md), deck, demo, video |
| **Verda Compute Track** | Fine-tuned our own vision model (Qwen3-VL-8B + LoRA) on two Verda H100s overnight; it runs live on a Verda GPU as the second opinion for users' own uploads; the public demo is hosted on a Verda CPU VM | Summary + Discord post in [VERDA.md](VERDA.md) (demo and repo links filled in at submission) |
| **Best Use of ElevenLabs** (MLH) | Voice questions in any browser via ElevenLabs Scribe speech-to-text; answers are read back with ElevenLabs text-to-speech | Same repo and demo; a short note on both endpoints |
| **Best Use of CRACI** | The project's CI (`.github/workflows/ci.yml`, 493 tests) runs on CRACI runners (`runs-on: craci`), so every build records its dependencies as a CycloneDX SBOM | Same repo; link to a CRACI build |

**Not entered** (decided Sat 14.11): Codex (used only for one independent audit, too light to compete), Nemotron and Gemini (baselines in our comparison, not part of the product), Gemma (a PaliGemma 2 fine-tune was tried and not shipped), Modal, MariaDB, Aiven, Cloudinary and the other tech challenges (not used).

## Tools and services (current; open to additions)

| Tool | Used for | In the product? |
|---|---|---|
| **Verda** (2× H100 80GB, RTX PRO 6000, CPU VM) | Vision-model fine-tune; live second-opinion model; public demo hosting | Yes |
| **Anthropic Claude Haiku 5.5** | The 110 free-text BIM questions (0.4 % of test), rewriting free-worded questions, classifying an uploaded sheet's title block, reading sheet text that OCR misses, LLM judge for scoring free text | Yes |
| **ElevenLabs** (Scribe speech-to-text, text-to-speech) | Ask by voice; spoken answers | Yes |
| **YOLO11m** (Ultralytics), trained by us on a local RTX 4070 | Symbol detector for scanned / raster plans | Yes |
| **Qwen3-VL-8B + our LoRA** | Independent second opinion on raster plans | Yes |
| IfcOpenShell, ezdxf, Shapely, PyMuPDF | Exact answers from BIM models and CAD layers; vector text and linework of uploaded PDF sheets | Yes |
| OpenCV, Tesseract OCR | Construction-sheet specialists (`bp/sheets/`): walls, rooms, door swings, slab zones, pipe runs; tags and tables on scans | Yes |
| three.js | 3D views (plans rising into 3D, BIM models) | Yes |
| FastAPI, Caddy, Docker | Demo server | Yes |
| **CRACI** | CI runners and build SBOMs | Build only |
| GitHub Actions workflow, pytest | 493 automated tests | Build only |
| Playwright | Demo recordings, screenshots, UI checks | Dev only |
| Claude Sonnet 5.5, Gemini 3.1 Pro, Nemotron 3.5 Super VL | Frontier baselines in the results comparison | No (evaluation only) |
| OpenAI Codex | One independent audit of the evaluation | No (dev only) |
| Claude Code | Development | No (dev only) |

Costs for all of the above: [COSTS.md](COSTS.md).
