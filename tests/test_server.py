"""app/server.py smoke tests that need no dataset (conftest.py points BP_DATA at a four-line stand-in when
data/ is absent): pages, static files, path-traversal guards and upload filename sanitising."""
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # fastapi.testclient needs it

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.server as S  # noqa: E402

TRAVERSAL = [
    "../../etc/passwd",
    "../" * 12 + "etc/passwd",
    "/etc/passwd",
    "data/../../../../etc/passwd",
    "data/cubicasa5k/../../../../../etc/passwd",
    "uploads/../../etc/passwd",
    "uploads/../server.py",
    "uploads//etc/passwd",
    "uploads/abc/../../../../etc/passwd",
]


@pytest.fixture(scope="module")
def client():
    return TestClient(S.app)


# ---------------------------------------------------------------- pages and static files
@pytest.mark.parametrize("url", ["/", "/results", "/how"])
def test_pages(client, url):
    if url == "/how" and not (S.STATIC / "how.html").exists():
        pytest.skip("no how.html in this checkout")
    r = client.get(url)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<html" in r.text.lower()


def test_index_references_existing_static_files(client):
    html = client.get("/").text
    refs = set(re.findall(r"""/static/([\w.\-]+)""", html))
    assert refs, "index.html loads nothing from /static"
    for name in refs:
        assert client.get(f"/static/{name}").status_code == 200, name


@pytest.mark.parametrize("name", ["app.js", "app.css", "index.html"])
def test_static(client, name):
    r = client.get(f"/static/{name}")
    assert r.status_code == 200 and r.content


@pytest.mark.parametrize("url", [
    "/static/does-not-exist.js",
    "/static/..%2Fserver.py",
    "/static/%2e%2e%2fserver.py",
    "/static/..%2F..%2FREADME.md",
    "/static/../server.py",
    "/static/....//server.py",
    "/no-such-page",
    "/api/no-such-endpoint",
    "/.env",
    "/.git/config",
])
def test_unknown_and_traversal_paths_404(client, url):
    r = client.get(url)
    assert r.status_code == 404, (url, r.status_code)
    assert "import " not in r.text and "[core]" not in r.text


@pytest.mark.parametrize("url", ["/docs", "/redoc", "/openapi.json"])
def test_api_browser_disabled(client, url):
    r = client.get(url)
    if r.status_code == 200:
        pytest.skip(f"{url} is enabled in this checkout")
    assert r.status_code == 404


# ---------------------------------------------------------------- resolve(): the path guard every file endpoint uses
@pytest.mark.parametrize("path", TRAVERSAL)
def test_resolve_refuses_traversal(path):
    with pytest.raises(HTTPException) as e:
        S.resolve(path)
    assert e.value.status_code == 404


def test_resolve_accepts_inside_paths():
    p = S.resolve("data/cubicasa5k/colorful-10052.png")
    assert p.is_relative_to(S.ROOT.resolve())
    u = S.resolve("uploads/0123456789ab/plan.pdf")
    assert u.is_relative_to(S.UPLOADS.resolve())


@pytest.mark.parametrize("path", TRAVERSAL + ["data/x\x00.png"])
def test_file_endpoint_refuses_traversal(client, path):
    r = client.get("/api/file", params={"path": path})
    assert r.status_code == 404
    assert "root:" not in r.text


def test_drawings_endpoint(client):
    r = client.get("/api/drawings", params={"limit": 3})
    assert r.status_code == 200
    j = r.json()
    assert set(j) >= {"counts", "total", "items"} and len(j["items"]) <= 3


# ---------------------------------------------------------------- uploads: filename sanitising
PNG_1x1 = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """Uploads land in a temp folder, and the preparation step (PIL / PDF work, page descriptions) is stubbed."""
    up = tmp_path / "uploads"
    monkeypatch.setattr(S, "UPLOADS", up)
    monkeypatch.setattr(S, "_prepare", lambda d, p, m: (p, "raster"))
    return up


@pytest.mark.parametrize("name, want", [
    ("plan.png", "plan.png"),
    ("../../../../etc/cron.d/evil.png", "evil.png"),
    ("..\\..\\windows\\evil.png", ".._.._windows_evil.png"),  # no separator survives
    ("my plan (final);rm -rf.png", "my_plan_final_rm_-rf.png"),
    ("Pohjapiirros_äö.png", "Pohjapiirros__.png"),
    ("original.png", "file_original.png"),          # 'original.<ext>' is reserved for the pre-conversion copy
    ("x" * 300 + ".png", "x" * 76 + ".png"),         # at most 80 characters
])
def test_upload_name_sanitised(client, uploads, name, want):
    r = client.post("/api/upload", params={"name": name}, content=PNG_1x1)
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    m = re.fullmatch(r"uploads/([0-9a-f]{12})/(.+)", path)
    assert m, path
    assert m.group(2) == want
    assert re.fullmatch(r"[A-Za-z0-9._-]+", m.group(2))
    stored = list(uploads.rglob("*.png"))
    assert stored and all(p.resolve().is_relative_to(uploads.resolve()) for p in stored)


@pytest.mark.parametrize("name, code", [
    ("plan.exe", 415),
    ("plan", 415),
    ("plan.dwg", 415),
    ("archive.zip", 415),
    ("../../plan.php", 415),
])
def test_upload_refuses_types(client, uploads, name, code):
    r = client.post("/api/upload", params={"name": name}, content=b"MZ\x90\x00")
    assert r.status_code == code
    assert not uploads.exists() or not any(uploads.rglob("*"))


def test_upload_refuses_empty(client, uploads):
    r = client.post("/api/upload", params={"name": "plan.png"}, content=b"")
    assert r.status_code == 400
    assert not any(p.is_file() for p in uploads.rglob("*"))  # the temp file is cleaned up
