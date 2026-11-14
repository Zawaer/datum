"""Every input form a judge might upload, for each of Stoa's four example sheets (cache/stoa_forms/<form>/<stem>.*).

forms: hires (the full-resolution PNG), lowres (Stoa's ~2000 px JPG screenshots), png2500 (hires downscaled to 2500 px
on the long side), pdf (the single vector page extracted from the public source PDF), scanpdf (that page rasterised at
150 dpi, greyscale, slightly skewed, blurred and noisy, JPEG-compressed, in a PDF: a scan).

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
FORMS = ("hires", "lowres", "png2500", "pdf", "scanpdf")


def path(stem: str, form: str) -> Path:
    """The file of one example sheet in one input form (the eval uploads this)."""
    hi, lo, _, _ = SRC[stem]
    return {"hires": EX / hi, "lowres": EX / lo, "png2500": OUT / "png2500" / f"{stem}.png",
            "pdf": OUT / "pdf" / f"{stem}.pdf", "scanpdf": OUT / "scanpdf" / f"{stem}.pdf"}[form]


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
        print(stem, {f: round(path(stem, f).stat().st_size / 1e6, 2) for f in FORMS})


if __name__ == "__main__":
    build()
