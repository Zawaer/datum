"""Every input form a judge might upload, for each of Stoa's four example sheets (cache/stoa_forms/<form>/<stem>.*).

forms: hires (the full-resolution PNG), lowres (Stoa's ~2000 px JPG screenshots), png2500 (hires downscaled to 2500 px
on the long side), pdf (the single vector page extracted from the public source PDF), scanpdf (that page rasterised at
150 dpi, greyscale, slightly skewed, blurred and noisy, JPEG-compressed, in a PDF: a scan), scanrough (a worse scan
as a PNG: the page at 200 dpi on grey paper, rotated 1.1 deg, blurred, JPEG artefacts, with green and red hand
markings over the drawing like the dataset's Finnish scans).

Degraded variants for robustness checks (scanrough_v1..v4, also for the A-101F filter building plan, ARCH below):
v1 grey paper + 0.3 deg at 200 dpi; v2 1.5 deg + blur + JPEG q45 at 200 dpi; v3 red / green markings + 0.8 deg on
grey paper at 200 dpi; v4 everything at 150 dpi.

    .venv/bin/python analysis/stoa_forms.py
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

Image.MAX_IMAGE_PIXELS = None
EX = Path("/data/attachments/s_YTlo5xSrle/stoa-examples")
OUT = Path(__file__).resolve().parent.parent / "cache/stoa_forms"
SRC = {  # example sheet -> (hires, lowres, source pdf, 0-based page)
    "dormitory_second_floor_A-2": ("dormitory_second_floor_A-2_hires.png", "dormitory_second_floor_A-2.jpg",
                                   "sources/us_daf_dorm_sd_drawings_april_2026/DAF_Dorm_SD_Drawings_April_2026.pdf", 2),
    "foundation_slab_plan_S-100F": ("foundation_slab_plan_S-100F_hires.png", "foundation_slab_plan_S-100F.jpg",
                                    "sources/us_aw_078-24-33/AW_078-24-33.pdf", 55),
    "piping_plan_M-101A": ("piping_plan_M-101A_hires.png", "piping_plan_M-101A.jpg",
                           "sources/us_aw_078-24-28_march_2020/AW_078-24-28_march_2020.pdf", 95),
    "special_school_plan_level_00": ("special_school_plan_level_00.png", "special_school_level00_screenshot.jpg",
                                     "sources/uk_dfe_sen_special_school/SEN-DFE-XX-00-D-X-0201-Special_School_Plan_Level_00-A-C01.pdf", 0),
}
FORMS = ("hires", "lowres", "png2500", "pdf", "scanpdf", "scanrough")
# extra sheets that only get the degraded variants (their questions live in analysis/judge_questions.jsonl)
ARCH = {"A-101F_filter_building_floor_plan": "sources/us_aw_078-24-33/AW_078-24-33.pdf"}
ARCH_PAGE = {"A-101F_filter_building_floor_plan": 68}
ROUGH = {  # variant -> (dpi, rotation deg, paper grey 0..1, blur px, JPEG quality or None, markings)
    "scanrough": (200, 1.1, 0.86, 0.8, 55, True),
    "scanrough_v1": (200, 0.3, 0.84, 0.0, None, False),
    "scanrough_v2": (200, -1.5, 0.95, 1.2, 45, False),
    "scanrough_v3": (200, 0.8, 0.86, 0.0, 80, True),
    "scanrough_v4": (150, -1.0, 0.82, 0.9, 50, True),
}


def path(stem: str, form: str) -> Path:
    """The file of one example sheet in one input form (the eval uploads this)."""
    if form.startswith("scanrough"):
        return OUT / form / f"{stem}.png"
    hi, lo, _, _ = SRC[stem]
    return {"hires": EX / hi, "lowres": EX / lo, "png2500": OUT / "png2500" / f"{stem}.png",
            "pdf": OUT / "pdf" / f"{stem}.pdf", "scanpdf": OUT / "scanpdf" / f"{stem}.pdf"}[form]


def _markings(im, rng):
    """Green / red hand markings: check marks, circled bits, underlines and scribbled numbers over the drawing."""
    from PIL import ImageDraw

    d = ImageDraw.Draw(im, "RGBA")
    W, H = im.size
    lw = max(2, round(W / 2500 * 3))
    for _ in range(int(rng.integers(14, 22))):
        col = (30, 150, 50, 200) if rng.random() < 0.5 else (210, 30, 30, 200)
        cx, cy = rng.uniform(0.08, 0.85) * W, rng.uniform(0.1, 0.85) * H
        r = rng.uniform(0.01, 0.04) * W
        k = rng.integers(4)
        if k == 0:  # a loose circle / cloud
            pts = [(cx + r * (1 + 0.15 * rng.standard_normal()) * np.cos(t), cy + r * 0.7 * np.sin(t))
                   for t in np.linspace(0, 2 * np.pi * 1.08, 40)]
            d.line(pts, fill=col, width=lw)
        elif k == 1:  # a check mark
            d.line([(cx, cy), (cx + r * 0.3, cy + r * 0.4), (cx + r, cy - r * 0.6)], fill=col, width=lw)
        elif k == 2:  # an underline / strike
            d.line([(cx - r * 2, cy), (cx + r * 2, cy + rng.uniform(-0.2, 0.2) * r)], fill=col, width=lw)
        else:  # a scribbled number or word
            pts = [(cx + i * r * 0.25, cy + r * 0.3 * np.sin(i * 2.1 + rng.random())) for i in range(10)]
            d.line(pts, fill=col, width=lw)
    return im


def rough(pdf_path, page, variant):
    """The page as a rough scan PNG (see ROUGH)."""
    import cv2
    import pymupdf

    dpi, rot, paper, blur, q, marks = ROUGH[variant]
    rng = np.random.default_rng(abs(hash(variant)) % 1000)
    pg = pymupdf.open(pdf_path)[page]
    pix = pg.get_pixmap(dpi=dpi, alpha=False)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if marks:
        im = _markings(im, rng)
    a = np.asarray(im).astype(np.float32)
    a = a * (paper * 255 - 20) / 255 + 20  # grey paper, toner never quite black
    h, w = a.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), rot, 1.0)
    a = cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=(paper * 255,) * 3)
    if blur:
        a = cv2.GaussianBlur(a, (0, 0), blur)
    a = a + rng.normal(0, 5, a.shape[:2])[..., None] + np.linspace(-8, 8, w)[None, :, None]
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if q:
        b = io.BytesIO()
        im.save(b, "JPEG", quality=q)
        im = Image.open(io.BytesIO(b.getvalue())).convert("RGB")
    return im


def build_rough():
    sheets = {stem: (EX / pdf, page) for stem, (_, _, pdf, page) in SRC.items()}
    sheets.update({stem: (EX / pdf, ARCH_PAGE[stem]) for stem, pdf in ARCH.items()})
    for variant in ROUGH:
        for stem, (pdf, page) in sheets.items():
            p = path(stem, variant)
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                rough(pdf, page, variant).save(p)


def build():
    import pymupdf

    for stem, (hi, lo, pdf, page) in SRC.items():
        p = path(stem, "png2500")
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            im = Image.open(EX / hi).convert("RGB")
            im.thumbnail((2500, 2500), Image.LANCZOS)
            im.save(p)
        p = path(stem, "pdf")
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            src = pymupdf.open(EX / pdf)
            doc = pymupdf.open()
            doc.insert_pdf(src, from_page=page, to_page=page)
            doc.save(p, garbage=3, deflate=True)
        p = path(stem, "scanpdf")
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            pg = pymupdf.open(path(stem, "pdf"))[0]
            pix = pg.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
            im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            im = im.rotate(0.6, resample=Image.BICUBIC, expand=False, fillcolor=255).filter(ImageFilter.GaussianBlur(0.7))
            a = np.asarray(im).astype(np.float32)
            rng = np.random.default_rng(0)
            a = np.clip(a * 0.93 + 10 + rng.normal(0, 6, a.shape), 0, 255).astype(np.uint8)  # grey paper, sensor noise
            b = io.BytesIO()
            Image.fromarray(a).save(b, "JPEG", quality=70)
            doc = pymupdf.open()
            r = pg.rect
            np_ = doc.new_page(width=r.width, height=r.height)
            np_.insert_image(np_.rect, stream=b.getvalue())
            doc.save(p)
        print(stem, {f: round(path(stem, f).stat().st_size / 1e6, 2) for f in FORMS if path(stem, f).exists()})


if __name__ == "__main__":
    build()
    build_rough()
