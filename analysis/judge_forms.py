"""Build the four upload forms of every judge sheet: lowres JPG (~2000 px), ~2500 px PNG, single-page vector PDF,
full-resolution PNG. Output: /data/attachments/s_YTlo5xSrle/judge-qa/forms/<sheet>/<form>.<ext>"""
from pathlib import Path

import pymupdf
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
EX = Path("/data/attachments/s_YTlo5xSrle/stoa-examples")
SRC = EX / "sources"
OUT = Path("/data/attachments/s_YTlo5xSrle/judge-qa/forms")
A28 = SRC / "us_aw_078-24-28_march_2020"
A33 = SRC / "us_aw_078-24-33"
DORM = SRC / "us_daf_dorm_sd_drawings_april_2026"
UK = SRC / "uk_dfe_sen_special_school"
# key: (hires png, provided lowres jpg or None, pdf, 1-based page, upload file stem)
SHEETS = {
    "dormA2": (EX / "dormitory_second_floor_A-2_hires.png", EX / "dormitory_second_floor_A-2.jpg", DORM / "DAF_Dorm_SD_Drawings_April_2026.pdf", 3, "A-2_second_floor_plan"),
    "slab100F": (EX / "foundation_slab_plan_S-100F_hires.png", EX / "foundation_slab_plan_S-100F.jpg", A33 / "AW_078-24-33.pdf", 56, "S-100F_foundation_slab_plan"),
    "pipeM101A": (EX / "piping_plan_M-101A_hires.png", EX / "piping_plan_M-101A.jpg", A28 / "AW_078-24-28_march_2020.pdf", 96, "M-101A_piping_plan"),
    "school00": (EX / "special_school_plan_level_00.png", EX / "special_school_level00_screenshot.jpg", UK / "SEN-DFE-XX-00-D-X-0201-Special_School_Plan_Level_00-A-C01.pdf", 1, "SEN_level_00"),
    "dormA1": (DORM / "us_daf_dorm_sd_drawings_april_2026_p002.png", None, DORM / "DAF_Dorm_SD_Drawings_April_2026.pdf", 2, "A-1_first_floor_plan"),
    "dormA4": (DORM / "us_daf_dorm_sd_drawings_april_2026_p005.png", None, DORM / "DAF_Dorm_SD_Drawings_April_2026.pdf", 5, "A-4_first_floor_common_area"),
    "dormA7": (DORM / "us_daf_dorm_sd_drawings_april_2026_p008.png", None, DORM / "DAF_Dorm_SD_Drawings_April_2026.pdf", 8, "A-7_dormitory_module"),
    "pipeM101F": (A33 / "us_aw_078-24-33_p078.png", None, A33 / "AW_078-24-33.pdf", 78, "M-101F_filter_building_piping"),
    "slabS100A": (A28 / "us_aw_078-24-28_march_2020_p067.png", None, A28 / "AW_078-24-28_march_2020.pdf", 67, "S-100A_pumphouse_slab"),
    "slabS102P": (A33 / "us_aw_078-24-33_p020.png", None, A33 / "AW_078-24-33.pdf", 20, "S-102P_tank_floor_slab"),
    "archA101F": (A33 / "us_aw_078-24-33_p069.png", None, A33 / "AW_078-24-33.pdf", 69, "A-101F_filter_building_floor_plan"),
    "schedA601": (A28 / "us_aw_078-24-28_march_2020_p094.png", None, A28 / "AW_078-24-28_march_2020.pdf", 94, "A-601_door_schedule"),
    "schoolL01": (UK / "uk_dfe_sen-dfe-xx-01-d-x-0202-special_school_plan_level_01-a-c01_p001.png", None, UK / "SEN-DFE-XX-01-D-X-0202-Special_School_Plan_Level_01-A-C01.pdf", 1, "SEN_level_01"),
}
FORMS = ("lowres", "png2500", "pdf", "hires", "scanpdf", "roughscan")
SCAN_FORMS = ("scanpdf", "roughscan", "lowres", "png2500")


def form_path(key: str, form: str) -> Path:
    stem = SHEETS[key][4]
    ext = {"lowres": "jpg", "png2500": "png", "pdf": "pdf", "hires": "png", "scanpdf": "pdf", "roughscan": "jpg"}[form]
    return OUT / key / f"{stem}_{form}.{ext}"


def _scan(im, long_px: int, skew: float, blur: float, noise: float, tint, contrast: float, seed: int):
    """A printed-and-scanned look: greyscale paper tint, lost contrast, slight rotation, blur, sensor noise."""
    import cv2
    import numpy as np

    rng = np.random.default_rng(seed)
    t = im.copy(); t.thumbnail((long_px, long_px), Image.LANCZOS)
    g = np.asarray(t.convert("L"), dtype=np.float32)
    g = 255 - (255 - g) * contrast  # toner never quite black
    h, w = g.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), skew, 1.0)
    g = cv2.warpAffine(g, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=255)
    if blur:
        g = cv2.GaussianBlur(g, (0, 0), blur)
    g = g + rng.normal(0, noise, g.shape) + np.linspace(-6, 6, w)[None, :]  # noise + uneven illumination
    g = np.clip(g, 0, 255)
    rgb = np.stack([g * tint[0], g * tint[1], g * tint[2]], -1).clip(0, 255).astype(np.uint8)
    return Image.fromarray(rgb)


def build_scans(key, im, pdf, page):
    """scanpdf: a 200 dpi-ish image-only PDF (no text layer) of a clean office scan; roughscan: a ~2500 px JPEG of a
    poor scan (1.5 deg skew, blur, noise, yellowed paper, JPEG q55)."""
    import io

    if not form_path(key, "scanpdf").exists():
        s = _scan(im, 4200, 0.4, 0.6, 3.0, (1.0, 1.0, 1.0), 0.92, 1)
        buf = io.BytesIO(); s.convert("L").save(buf, "JPEG", quality=75)
        src = pymupdf.open(pdf)[page - 1]
        o = pymupdf.open(); pg = o.new_page(width=src.rect.width, height=src.rect.height)
        pg.insert_image(pg.rect, stream=buf.getvalue(), keep_proportion=True)
        o.save(form_path(key, "scanpdf"), garbage=4, deflate=True)
    if not form_path(key, "roughscan").exists():
        s = _scan(im, 2500, -1.5, 1.1, 7.0, (1.0, 0.97, 0.88), 0.8, 2)
        s.save(form_path(key, "roughscan"), quality=55)


def build():
    for key, (hi, lo, pdf, page, stem) in SHEETS.items():
        d = OUT / key
        d.mkdir(parents=True, exist_ok=True)
        im = Image.open(hi).convert("RGB")
        if not form_path(key, "hires").exists():
            form_path(key, "hires").write_bytes(hi.read_bytes())
        if not form_path(key, "lowres").exists():
            if lo:
                form_path(key, "lowres").write_bytes(lo.read_bytes())
            else:
                t = im.copy(); t.thumbnail((2000, 2000)); t.save(form_path(key, "lowres"), quality=82)
        if not form_path(key, "png2500").exists():
            t = im.copy(); t.thumbnail((2500, 2500)); t.save(form_path(key, "png2500"), optimize=True)
        if not form_path(key, "pdf").exists():
            src = pymupdf.open(pdf); o = pymupdf.open(); o.insert_pdf(src, from_page=page - 1, to_page=page - 1)
            o.save(form_path(key, "pdf"), garbage=4, deflate=True)
        build_scans(key, im, pdf, page)
        print(key, [f"{form_path(key, f).stat().st_size / 1e6:.1f}MB" for f in FORMS])


if __name__ == "__main__":
    build()
