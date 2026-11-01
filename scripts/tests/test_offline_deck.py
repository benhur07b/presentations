"""A deck's offline copy (scripts/offline_deck.py): every CDN address of a pinned package pointed at its copy in vendor/,
each package fetched once and checked against its pin every time, a script the pins don't cover or a version they don't
satisfy refused, and the same copy every time.

The tests never reach the registry: the packages are tarballs made here, as npm packs them, served by a stand-in for
the registry that counts what it is asked for; the pins are written for them in a scratch folder."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

import decks
import offline_deck as od

ROOT = Path(__file__).resolve().parents[2]
PSA = "2026-10-28-python-for-data-management"  # a deck given out: its copy must run as PSA's kit's did
REVEAL = {"dist/reveal.js": "reveal", "dist/reveal.css": "css", "dist/theme/white.css": "theme", "plugin/highlight/highlight.js": "hl",
          "plugin/highlight/monokai.css": "monokai", "plugin/markdown/markdown.js": "md", "plugin/notes/notes.js": "notes", "LICENSE": "MIT"}
COPYCODE = {"plugin/copycode/copycode.js": "cc", "plugin/copycode/copycode.css": "cc-css", "LICENSE": "MIT"}
PAGE = """<!doctype html>
<html><head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/white.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js-copycode/plugin/copycode/copycode.css">
<link rel="icon" href="../assets/favicon.svg"><link rel="canonical" href="https://bnhr.xyz/presentations/deck/">
</head><body><div class="reveal"><div class="slides"><section>Data from https://psa.gov.ph, as <a href="https://cdn.jsdelivr.net/npm/reveal.js@5/">reveal.js</a> says</section></div></div>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/notes/notes.js"></script>
<script src="https://cdn.jsdelivr.net/npm/reveal.js-copycode/plugin/copycode/copycode.js"></script>
<script>Reveal.initialize({ plugins: [RevealNotes, CopyCode] });</script>
</body></html>
"""


def packed(files: dict[str, str]) -> bytes:
    """A package's tarball as npm packs it: every file under package/, gzipped."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"package/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class Registry:
    """The npm registry, stood in: each version's metadata and tarball, and every address asked for."""

    def __init__(self, packages: dict[tuple[str, str], bytes]) -> None:
        self.packages, self.asked = packages, []

    def __call__(self, url: str) -> bytes:
        self.asked.append(url)
        for (name, version), data in self.packages.items():
            pin = od.Pin(name, version, od.integrity_of(data))
            if url == pin.tarball:
                return data
            if url == f"{od.REGISTRY}{name}/{version}":
                return json.dumps({"name": name, "version": version, "dist": {"integrity": pin.integrity, "tarball": pin.tarball}}).encode()
        raise od.Stop(od.NO_INPUT, f"{url} answered 404")


@pytest.fixture
def registry() -> Registry:
    return Registry({("reveal.js", "5.2.1"): packed(REVEAL), ("reveal.js-copycode", "1.4.2"): packed(COPYCODE)})


@pytest.fixture
def repo(tmp_path: Path, registry: Registry) -> Path:
    """A presentations folder with one deck, its assets, and pins for both packages."""
    root = tmp_path / "presentations"
    (root / "scripts").mkdir(parents=True)
    write(root / "deck" / "index.html", PAGE)
    write(root / "deck" / "deck.css", ".reveal { color: navy; }\n")
    write(root / "deck" / "img" / "qr" / "day1.svg", "<svg/>")
    write(root / "deck" / ".gitignore", "index.md\n")
    write(root / "assets" / "favicon.svg", "<svg/>")
    write(root / "other-deck" / "index.html", "<p>another deck: not copied</p>")
    od.write_pins({name: od.Pin(name, version, od.integrity_of(data)) for (name, version), data in registry.packages.items()}, pins(root))
    return root


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def pins(root: Path) -> Path:
    return root / "scripts" / "offline_deck.toml"


def cache(root: Path) -> Path:
    return root / "scripts" / ".cache" / "npm"


def copy(root: Path, registry: Registry, folder: str = "deck") -> od.Copy:
    return od.plan(folder, root, pins(root), cache(root), registry)


def test_a_copy_points_every_cdn_address_at_its_pinned_package_and_holds_it(repo: Path, registry: Registry) -> None:
    made = copy(repo, registry)
    page = made.files["deck/index.html"].decode()
    assert "cdn.jsdelivr.net/npm/reveal.js@5/dist" not in page and "npm/reveal.js-copycode/plugin" not in page
    assert '<script src="../vendor/reveal.js-5.2.1/dist/reveal.js">' in page
    assert 'href="../vendor/reveal.js-copycode-1.4.2/plugin/copycode/copycode.css"' in page
    assert '<a href="../vendor/reveal.js-5.2.1/">' in page  # a link to the package is pointed at its copy too
    assert 'href="https://bnhr.xyz/presentations/deck/"' in page  # links to the web stay as they are
    assert made.packages == {"reveal.js": "5.2.1", "reveal.js-copycode": "1.4.2"}
    assert set(made.files) == {"deck/index.html", "deck/deck.css", "deck/img/qr/day1.svg", "assets/favicon.svg",
                               *(f"vendor/reveal.js-5.2.1/{n}" for n in REVEAL), *(f"vendor/reveal.js-copycode-1.4.2/{n}" for n in COPYCODE)}
    assert made.files["vendor/reveal.js-5.2.1/dist/reveal.js"] == b"reveal" and not made.notes


def test_the_copy_is_laid_out_as_deck_of_says_a_copy_needs(repo: Path, registry: Registry) -> None:
    tops = {name.split("/")[0] for name in copy(repo, registry).files}
    assert tops == {"deck", *decks.SHARED, "vendor"}


def test_a_page_in_a_subfolder_finds_vendor_from_where_it_is(repo: Path, registry: Registry) -> None:
    write(repo / "deck" / "extra" / "notes.html", '<script src="https://cdn.jsdelivr.net/npm/reveal.js@5.2/dist/reveal.js"></script>')
    assert '<script src="../../vendor/reveal.js-5.2.1/dist/reveal.js">' in copy(repo, registry).files["deck/extra/notes.html"].decode()


def test_each_package_is_fetched_once_and_checked_every_time(repo: Path, registry: Registry) -> None:
    first = copy(repo, registry)
    assert sorted(registry.asked) == sorted(od.Pin(n, v, "").tarball for n, v in first.packages.items())
    registry.asked.clear()
    assert copy(repo, registry).files == first.files  # the same copy, from the cache: nothing asked
    assert registry.asked == []
    kept = cache(repo) / "reveal.js-5.2.1.tgz"
    kept.write_bytes(b"changed on disk")  # a cached tarball that no longer matches its pin is fetched again, never used
    assert copy(repo, registry).files == first.files
    assert registry.asked == [od.Pin("reveal.js", "5.2.1", "").tarball] and od.integrity_of(kept.read_bytes()) == od.integrity_of(packed(REVEAL))


def test_a_tarball_that_doesnt_match_its_pin_is_never_used(repo: Path, registry: Registry, tmp_path: Path) -> None:
    registry.packages[("reveal.js", "5.2.1")] = packed({**REVEAL, "dist/reveal.js": "someone else's"})
    od.write_pins({**od.read_pins(pins(repo)), "reveal.js": od.Pin("reveal.js", "5.2.1", od.integrity_of(packed(REVEAL)))}, pins(repo))
    with pytest.raises(od.Stop, match="doesn't match reveal.js 5.2.1's pin") as stop:
        copy(repo, registry)
    assert stop.value.code == od.DATA and not (cache(repo) / "reveal.js-5.2.1.tgz").exists()


def test_a_script_no_pin_covers_stops_it_and_says_which(repo: Path, registry: Registry) -> None:
    write(repo / "deck" / "index.html", PAGE.replace("</body>", '<script src="https://unpkg.com/mermaid@11/dist/mermaid.min.js"></script>\n'
                                                     '<script type="module">import x from "https://esm.sh/thing@1";</script></body>'))
    with pytest.raises(od.Stop, match="loads these scripts from the web") as stop:
        copy(repo, registry)
    assert stop.value.code == od.DATA
    assert "https://unpkg.com/mermaid@11/dist/mermaid.min.js  (in deck/index.html)" in str(stop.value)
    assert "https://esm.sh/thing@1  (in deck/index.html)" in str(stop.value)


def test_what_a_page_shows_without_is_a_note_not_a_refusal(repo: Path, registry: Registry) -> None:
    fonts = "https://fonts.googleapis.com/css2?family=DM+Sans&display=swap"
    write(repo / "deck" / "index.html", PAGE.replace("</head>", f'<link rel="stylesheet" href="{fonts}">'
                                                     '<style>.title { background: url("https://example.org/map.png"); }</style></head>')
          .replace("</section>", '<img src="https://example.org/photo.jpg"></section>'))
    write(repo / "deck" / "deck.css", '@import url("https://fonts.example.org/x.css");\n')
    notes = copy(repo, registry).notes
    assert notes == [f"deck/deck.css loads https://fonts.example.org/x.css from the web: offline, the page shows without it",
                     f"deck/index.html loads {fonts} from the web: offline, the page shows without it",
                     "deck/index.html loads https://example.org/photo.jpg from the web: offline, the page shows without it",
                     "deck/index.html loads https://example.org/map.png from the web: offline, the page shows without it"]


def test_a_version_the_pin_doesnt_satisfy_stops_it(repo: Path, registry: Registry) -> None:
    write(repo / "deck" / "index.html", PAGE.replace("reveal.js@5/dist/reveal.js", "reveal.js@6/dist/reveal.js"))
    with pytest.raises(od.Stop, match=r"reveal.js@6, which its pin, 5.2.1, doesn't satisfy") as stop:
        copy(repo, registry)
    assert stop.value.code == od.DATA


@pytest.mark.parametrize(("spec", "ok"), [
    (None, True), ("latest", True), ("5", True), ("5.2", True), ("5.2.1", True), ("5.x", True), ("5.2.x", True), ("*", True),
    ("^5.1.0", True), ("^5", True), ("~5.2.0", True), ("~5", True), ("5.2.1", True),
    ("6", False), ("5.3", False), ("5.2.0", False), ("^5.3.0", False), ("~5.1.0", False), ("^4.6.0", False), ("4.x", False),
])
def test_what_the_cdn_could_serve_for_a_spec(spec: str | None, ok: bool) -> None:
    assert od.satisfies("5.2.1", spec) is ok


def test_caret_on_a_zero_major_is_the_minor_and_a_pre_release_only_its_own_spec() -> None:
    assert od.satisfies("0.2.5", "^0.2.1") and not od.satisfies("0.3.0", "^0.2.1")
    assert od.satisfies("6.0.0-beta.1", "6.0.0-beta.1") and not od.satisfies("6.0.0-beta.1", "6")
    with pytest.raises(od.Stop, match="a range offline_deck.py doesn't read"):
        od.satisfies("5.2.1", ">=5 <6")


def test_an_address_the_package_doesnt_have_stops_it(repo: Path, registry: Registry) -> None:
    write(repo / "deck" / "index.html", PAGE.replace("plugin/notes/notes.js", "plugin/notes/speaker.js"))
    with pytest.raises(od.Stop, match="loads ../vendor/reveal.js-5.2.1/plugin/notes/speaker.js, which its pinned package doesn't have"):
        copy(repo, registry)


def test_it_writes_only_into_an_empty_folder_and_never_changes_the_deck(repo: Path, registry: Registry, tmp_path: Path) -> None:
    before = (repo / "deck" / "index.html").read_bytes()
    made = copy(repo, registry)
    out = tmp_path / "out"
    od.write(made, out)
    assert {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} == set(made.files)
    assert (repo / "deck" / "index.html").read_bytes() == before
    with pytest.raises(od.Stop, match="has files in it") as stop:
        od.write(made, out)
    assert stop.value.code == od.CONFLICT


def test_a_folder_that_isnt_a_deck_here_is_refused(repo: Path, registry: Registry) -> None:
    for folder in ("../presentations/deck", "missing", "scripts"):
        with pytest.raises(od.Stop) as stop:
            copy(repo, registry, folder)
        assert stop.value.code == od.NO_INPUT


def test_pin_writes_the_registrys_integrity_and_checks_the_tarball(repo: Path, registry: Registry) -> None:
    registry.packages[("reveal.js", "5.3.0")] = packed(REVEAL)
    found = od.pin("reveal.js", "5.3.0", pins(repo), cache(repo), registry)
    assert od.read_pins(pins(repo))["reveal.js"] == found == od.Pin("reveal.js", "5.3.0", od.integrity_of(packed(REVEAL)))
    assert (cache(repo) / "reveal.js-5.3.0.tgz").is_file()
    assert pins(repo).read_text(encoding="utf-8").startswith(od.PIN_HEADER)
    with pytest.raises(od.Stop) as stop:
        od.pin("reveal.js", "^5", pins(repo), cache(repo), registry)
    assert stop.value.code == od.USAGE


def test_the_command_writes_the_copy_and_answers_as_json(repo: Path, registry: Registry, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(od, "fetch_url", registry)
    out = tmp_path / "copy"
    assert od.main(["--root", str(repo), "copy", "deck", "--out", str(out), "--json"]) == od.DONE
    answer = json.loads(capsys.readouterr().out)
    assert answer == {"folder": "deck", "out": str(out), "packages": {"reveal.js": "5.2.1", "reveal.js-copycode": "1.4.2"},
                      "files": len(copy(repo, registry).files), "notes": []}
    assert (out / "vendor" / "reveal.js-5.2.1" / "LICENSE").is_file()
    assert od.main(["--root", str(repo), "copy", "deck", "--out", str(out)]) == od.CONFLICT
    assert od.main(["--root", str(repo), "copy", "other", "--out", str(tmp_path / "x")]) == od.NO_INPUT


def test_psas_deck_runs_offline_from_its_copy(registry: Registry, tmp_path: Path) -> None:
    # This repository pins the versions PSA's kit ran (reveal.js 5.2.1, copycode 1.4.2); the deck given out, copied with
    # packages made here under those versions, loads every script and stylesheet from vendor/
    real = od.read_pins(ROOT / "scripts" / "offline_deck.toml")
    assert {name: p.version for name, p in real.items()} == dict(registry.packages.keys())
    scratch = tmp_path / "pins.toml"
    od.write_pins({n: od.Pin(n, v, od.integrity_of(data)) for (n, v), data in registry.packages.items()}, scratch)
    made = od.plan(PSA, ROOT, scratch, tmp_path / "cache", registry)
    page = made.files[f"{PSA}/index.html"].decode()
    assert "cdn.jsdelivr.net" not in page and made.packages == {"reveal.js": "5.2.1", "reveal.js-copycode": "1.4.2"}
    assert '<script src="../vendor/reveal.js-5.2.1/dist/reveal.js"></script>' in page and not made.notes
