"""A copy of a deck that runs without the internet: the reveal.js it loads from the web, pinned, fetched and checked.

    uv run --project scripts python scripts/offline_deck.py copy FOLDER --out DIR [--json]   # writes the offline copy
    uv run --project scripts python scripts/offline_deck.py pin NAME VERSION                 # pins a package's version

The decks here load reveal.js and its plugins from cdn.jsdelivr.net (`https://cdn.jsdelivr.net/npm/reveal.js@5/…`),
which a room without internet can't reach. `copy` writes a copy of the deck in FOLDER into DIR, laid out as a room kit
holds it, every page pointing at the copies in vendor/ instead of the CDN:

    DIR/<folder>/                     the deck: its pages, styles and scripts load vendor/ instead of the CDN
    DIR/assets/                       the presentations' assets, which every deck's pages link to
    DIR/vendor/<package>-<version>/   each package the deck loads from the CDN, as npm published that version

Each package a deck may load is pinned in scripts/offline_deck.toml: its version, and npm's integrity of its tarball
(sha512, the registry's own). The tarball is fetched from the npm registry the first time it is needed, kept in
scripts/.cache/ (gitignored, so a machine fetches each version once), and checked against its pin every time it is used:
one that doesn't match is fetched again, and never used. `pin NAME VERSION` writes a pin, with the integrity the registry
gives for that version, and fetches and checks it; a pin is never typed by hand.

`copy` stops, writing nothing, when a page loads a script from the web that no pin covers (a new plugin, another CDN),
or asks for a version its pin doesn't satisfy (`reveal.js@6` against 5.2.1): without its scripts the deck doesn't run.
Pin the package, then copy again. Anything else a page loads from the web and no pin covers (a stylesheet, a web font,
an image, a frame) is named as a note: the deck runs, and shows without it. Links (`<a href>`, the QR codes' addresses) still lead to the web, as they should. The
copy is the same every time for the same deck and pins, and the deck itself is never changed.

The hub's `room_kit.py` runs `copy` for a training's deck (from `decks.py deck-of`) and copies DIR into the kit's
`presentation/`.

Exit codes: 0 done; 2 usage; 5 DIR has files in it; 65 the deck needs a script no pin satisfies, or a tarball doesn't
match its pin; 66 no such deck, or no such package or version on the registry; 69 the registry can't be reached (and the
package is not in the cache yet); 78 scripts/offline_deck.toml can't be read.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import posixpath
import re
import sys
import tarfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

import decks

ROOT = Path(__file__).resolve().parents[1]  # this repository, presentations/
PINS = ROOT / "scripts" / "offline_deck.toml"
CACHE = ROOT / "scripts" / ".cache" / "npm"
REGISTRY = "https://registry.npmjs.org/"
DONE, USAGE, CONFLICT, DATA, NO_INPUT, UNAVAILABLE, CONFIG = 0, 2, 5, 65, 66, 69, 78
# A package on the CDN, as a deck loads it: https://cdn.jsdelivr.net/npm/<name>[@<version or range>]/<path>
CDN = re.compile(r"https://cdn\.jsdelivr\.net/npm/(?P<name>(?:@[a-z0-9][\w.~-]*/)?[a-z0-9][\w.~-]*?)(?:@(?P<spec>[^/\"'\s)]+))?/")
REWRITTEN = (".html", ".htm", ".css", ".js", ".mjs")  # the files whose addresses are pointed at vendor/
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?")
# What code loads from the web: a module a script imports, which it can't run without; and what a style loads (another
# stylesheet, a font, an image), which the page shows without
IMPORTS = re.compile(r"""(?:\bfrom\s*["']|\bimport\s*\(\s*["'])(https?://[^"')\s]+)""")
STYLE_LOADS = re.compile(r"""(?:@import\s+(?:url\(\s*)?["']?|url\(\s*["']?)(https?://[^"')\s]+)""")
PIN_HEADER = """\
# The packages a deck may load from cdn.jsdelivr.net, pinned for its offline copy (scripts/offline_deck.py): each one's
# version, and npm's integrity of that version's tarball, which every copy checks. Written by `offline_deck.py pin NAME
# VERSION`, never by hand.
"""

Fetch = Callable[[str], bytes]


class Stop(Exception):
    """A refusal, with the exit code it ends the command with."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Pin:
    name: str
    version: str
    integrity: str  # sha512-<base64>, as the registry gives it

    @property
    def folder(self) -> str:
        """The package's folder in vendor/: `reveal.js-5.2.1`; a scoped one, `@scope/name`, as `scope-name-1.0.0`."""
        return f"{self.name.lstrip('@').replace('/', '-')}-{self.version}"

    @property
    def tarball(self) -> str:
        """The registry's address of the version's tarball (an unscoped name's, or a scoped one's)."""
        return f"{REGISTRY}{self.name}/-/{self.name.rsplit('/', 1)[-1]}-{self.version}.tgz"


@dataclass
class Copy:
    folder: str
    files: dict[str, bytes] = field(default_factory=dict)  # every file of the copy, by its path in DIR
    packages: dict[str, str] = field(default_factory=dict)  # each package vendored, and its version
    notes: list[str] = field(default_factory=list)


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "presentations offline_deck.py"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise Stop(NO_INPUT if error.code == 404 else UNAVAILABLE, f"{url} answered {error.code}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise Stop(UNAVAILABLE, f"{url} can't be reached ({error}): the first copy of a package needs the internet") from error


# ── Pins ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def read_pins(path: Path = PINS) -> dict[str, Pin]:
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8")).get("packages", {})
        pins = {name: Pin(name, entry["version"], entry["integrity"]) for name, entry in table.items()}
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError, AttributeError) as error:
        raise Stop(CONFIG, f"{path} can't be read as the pins ({error!r}): write it again with `offline_deck.py pin NAME VERSION`") from error
    for pin in pins.values():
        if not VERSION.fullmatch(pin.version) or not pin.integrity.startswith("sha512-"):
            raise Stop(CONFIG, f"{path}: {pin.name}'s pin is not a version and a sha512 integrity: pin it again with `offline_deck.py pin`")
    return pins


def write_pins(pins: dict[str, Pin], path: Path = PINS) -> None:
    lines = [PIN_HEADER]
    for name in sorted(pins):
        lines += [f'[packages."{name}"]', f'version = "{pins[name].version}"', f'integrity = "{pins[name].integrity}"', ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def integrity_of(data: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def tarball(pin: Pin, cache: Path = CACHE, fetch: Fetch | None = None) -> bytes:
    """The pinned version's tarball, checked against its pin: from the cache, or fetched from the registry (and kept)
    when the cache has none or one that doesn't match."""
    kept = cache / f"{pin.folder}.tgz"
    if kept.is_file() and integrity_of(data := kept.read_bytes()) == pin.integrity:
        return data
    data = (fetch or fetch_url)(pin.tarball)
    if integrity_of(data) != pin.integrity:
        raise Stop(DATA, f"{pin.tarball} doesn't match {pin.name} {pin.version}'s pin (its integrity is {integrity_of(data)}): "
                         "nothing was used; check the pin with `offline_deck.py pin`")
    cache.mkdir(parents=True, exist_ok=True)
    partial = kept.with_suffix(".part")
    partial.write_bytes(data)
    partial.replace(kept)
    return data


def unpack(pin: Pin, data: bytes) -> dict[str, bytes]:
    """The package's files, by their path in it (npm's top folder, `package/`, left out)."""
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts[1:]
            if not parts or member.name.startswith("/") or ".." in parts:
                raise Stop(DATA, f"{pin.name} {pin.version}'s tarball holds {member.name!r}, outside its package")
            files["/".join(parts)] = archive.extractfile(member).read()
    return files


def satisfies(version: str, spec: str | None) -> bool:
    """Whether the CDN, asked for `spec`, could serve `version`: no spec or `latest` (any), a version or its first parts
    (`5`, `5.2`, `5.x`), or a caret or tilde range (`^5.1.0`, `~5.2`). A pre-release satisfies only its own exact spec."""
    if spec is None or spec == "latest" or spec == version:
        return True
    found = VERSION.fullmatch(version)
    if "-" in version or not found:
        return False
    have = tuple(int(n) for n in found.groups())
    if spec[0] in "^~":
        wanted = spec[1:].split(".")
        if not all(p.isdigit() for p in wanted) or not 1 <= len(wanted) <= 3:
            raise Stop(DATA, f"the deck asks for {spec}, a range offline_deck.py doesn't read: ask for a version, or a caret or tilde range")
        low = tuple(int(p) for p in wanted) + (0,) * (3 - len(wanted))
        if spec[0] == "~":
            fixed = 1 if len(wanted) == 1 else 2  # ~5 is 5.x.x; ~5.2 and ~5.2.1 are 5.2.x
        else:
            fixed = next((i + 1 for i, n in enumerate(low) if n), len(wanted))  # ^5.2.1 is 5.x.x; ^0.2.1 is 0.2.x
        return have >= low and have[:fixed] == low[:fixed]
    wanted = spec.split(".")
    if len(wanted) > 3 or not all(p.isdigit() or p in ("x", "X", "*") for p in wanted):
        raise Stop(DATA, f"the deck asks for {spec}, a range offline_deck.py doesn't read: ask for a version, or a caret or tilde range")
    return all(p in ("x", "X", "*") or int(p) == n for p, n in zip(wanted, have))


# ── The copy ───────────────────────────────────────────────────────────────────────────────────────────────────────


class Loads(HTMLParser):
    """What a page loads from the web, by the tags that load it: what it can't run without (a script), and the rest (a
    stylesheet, a font, an image, a frame), which it shows without; and its inline scripts and styles, which may load
    more."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.needed: list[str] = []
        self.other: list[str] = []
        self.code: list[str] = []
        self.inside: str | None = None

    def handle_endtag(self, tag: str) -> None:
        if tag == self.inside:
            self.inside = None

    def handle_data(self, data: str) -> None:
        if self.inside:
            self.code.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k: v or "" for k, v in attrs}
        self.inside = tag if tag in ("script", "style") else None
        if values.get("style"):
            self.code.append(values["style"])
        web = lambda key: values.get(key, "") if re.match(r"https?://", values.get(key, "")) else ""  # noqa: E731
        if tag == "script" and web("src"):
            self.needed.append(web("src"))
        elif tag == "link" and web("href"):
            rel = set(values.get("rel", "").lower().split())
            if "modulepreload" in rel:
                self.needed.append(web("href"))
            elif {"stylesheet", "icon", "preload", "manifest"} & rel:
                self.other.append(web("href"))
        elif tag in ("img", "iframe", "video", "audio", "source", "embed", "track", "input") and web("src"):
            self.other.append(web("src"))
        elif tag == "object" and web("data"):
            self.other.append(web("data"))


def loads_from_web(path: str, text: str) -> tuple[list[str], list[str]]:
    """What a file of the deck loads from the web: what it needs to run, and what it shows without."""
    needed, other, code = [], [], text
    if path.endswith((".html", ".htm")):  # a page's own text is prose: only its tags and its inline code load anything
        page = Loads()
        page.feed(text)
        needed, other, code = page.needed, page.other, "\n".join(page.code)
    needed += IMPORTS.findall(code)
    other += STYLE_LOADS.findall(code)
    return needed, [u for u in other if u not in needed]


def vendored(text: str, depth: int, pins: dict[str, Pin], used: dict[str, Pin], path: str) -> str:
    """The text with every CDN address of a pinned package pointed at its copy in vendor/, `depth` folders up."""

    def local(match: re.Match) -> str:
        name, spec = match["name"], match["spec"]
        pin = pins.get(name)
        if pin is None:
            return match[0]  # not pinned: left as it is, and named below if the deck needs it
        if not satisfies(pin.version, spec):
            raise Stop(DATA, f"{path} asks the CDN for {name}@{spec}, which its pin, {pin.version}, doesn't satisfy: pin the version "
                             f"the deck asks for (`offline_deck.py pin {name} VERSION`), then copy again")
        used[name] = pin
        return f"{'../' * depth}vendor/{pin.folder}/"

    return CDN.sub(local, text)


def deck_files(top: Path) -> list[Path]:
    """Every file under a folder, in order, but hidden ones (`.gitignore`, `.DS_Store`) and caches."""
    return [p for p in sorted(top.rglob("*"))
            if p.is_file() and not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(top).parts)]


def plan(folder: str, root: Path = ROOT, pins_path: Path = PINS, cache: Path = CACHE, fetch: Fetch | None = None) -> Copy:
    if not re.fullmatch(r"[^/\\.][^/\\]*", folder) or not (root / folder).is_dir():
        raise Stop(NO_INPUT, f"no deck folder {folder!r} in {root}: name a folder of this repository, as `decks.py deck-of ID` prints it")
    if not any((root / folder).glob("*.htm*")):
        raise Stop(NO_INPUT, f"{folder}/ has no page (.html): build the deck first")
    pins = read_pins(pins_path)
    copy, used, needed = Copy(folder), {}, {}
    for top in (folder, *decks.SHARED):
        for path in deck_files(root / top):
            name = path.relative_to(root).as_posix()
            data = path.read_bytes()
            if top == folder and name.endswith(REWRITTEN):
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise Stop(DATA, f"{name} is not UTF-8 text ({error}): save it as UTF-8, as the decks' pages are") from error
                text = vendored(text, len(PurePosixPath(name).parts) - 1, pins, used, name)
                web, other = loads_from_web(name, text)
                for url in web:
                    needed.setdefault(url, name)
                copy.notes += [f"{name} loads {url} from the web: offline, the page shows without it" for url in dict.fromkeys(other)]
                data = text.encode("utf-8")
            copy.files[name] = data
    if needed:
        raise Stop(DATA, "the deck still loads these scripts from the web, so it would not run offline; nothing was written:\n"
                   + "\n".join(f"  {url}  (in {where})" for url, where in sorted(needed.items()))
                   + "\npin each package it loads from cdn.jsdelivr.net (`offline_deck.py pin NAME VERSION`), or load it from the deck's folder")
    for name, pin in sorted(used.items()):
        for path, data in sorted(unpack(pin, tarball(pin, cache, fetch)).items()):
            copy.files[f"vendor/{pin.folder}/{path}"] = data
        copy.packages[name] = pin.version
    for name, text in copy.files.items():  # every address pointed at vendor/ must find its file there
        if name.startswith(f"{folder}/") and name.endswith(REWRITTEN):
            for ref in re.findall(r"""((?:\.\./)+vendor/[^"'\s)?#]+)""", text.decode("utf-8")):
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), ref))
                if not (target in copy.files or ref.endswith("/") and any(f.startswith(f"{target}/") for f in copy.files)):
                    raise Stop(DATA, f"{name} loads {ref}, which its pinned package doesn't have: check the address against the package")
    return copy


def write(copy: Copy, out: Path) -> None:
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Stop(CONFLICT, f"{out} has files in it: give an empty folder, or one that isn't there yet")
    for name, data in copy.files.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def pin(name: str, version: str, pins_path: Path = PINS, cache: Path = CACHE, fetch: Fetch | None = None) -> Pin:
    """A pin for the version, with the integrity the registry gives for it, its tarball fetched and checked."""
    if not VERSION.fullmatch(version):
        raise Stop(USAGE, f"{version!r} is not a version (as 5.2.1): pin one version, not a range")
    pins = read_pins(pins_path) if pins_path.is_file() else {}
    try:
        meta = json.loads((fetch or fetch_url)(f"{REGISTRY}{urllib.parse.quote(name, safe='@/')}/{version}"))
        integrity = meta["dist"]["integrity"]
    except (ValueError, KeyError, TypeError) as error:
        raise Stop(UNAVAILABLE, f"the registry's answer for {name} {version} has no integrity ({error!r})") from error
    if not integrity.startswith("sha512-"):
        raise Stop(DATA, f"the registry gives {name} {version} no sha512 integrity ({integrity.split('-')[0]}): it can't be checked")
    found = Pin(name, version, integrity)
    tarball(found, cache, fetch)
    pins[name] = found
    write_pins(pins, pins_path)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="offline_deck.py", description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    copy_cmd = commands.add_parser("copy", help="write a copy of a deck that runs without the internet")
    copy_cmd.add_argument("folder", help="the deck's folder in this repository, as decks.py deck-of prints it")
    copy_cmd.add_argument("--out", type=Path, required=True, help="where to write the copy: an empty folder, or one that isn't there")
    copy_cmd.add_argument("--json", action="store_true", help="print what it wrote as JSON")
    pin_cmd = commands.add_parser("pin", help="pin a package's version, with the registry's integrity for it")
    pin_cmd.add_argument("name", help="the package's name on npm, as a deck loads it from cdn.jsdelivr.net (reveal.js)")
    pin_cmd.add_argument("version", help="the version to pin (5.2.1)")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command == "pin":
            found = pin(args.name, args.version, args.root / "scripts" / "offline_deck.toml", args.root / "scripts" / ".cache" / "npm")
            print(f"pinned   {found.name} {found.version}  {found.integrity}")
            return DONE
        copy = plan(args.folder, args.root, args.root / "scripts" / "offline_deck.toml", args.root / "scripts" / ".cache" / "npm")
        write(copy, args.out)
        if args.json:
            print(json.dumps({"folder": copy.folder, "out": str(args.out), "packages": copy.packages, "files": len(copy.files), "notes": copy.notes}))
        else:
            print(f"wrote    {args.out}: {copy.folder}/ and {', '.join(sorted({n.split('/')[0] for n in copy.files} - {copy.folder}))}, "
                  f"{len(copy.files)} files; " + (", ".join(f"{n} {v}" for n, v in copy.packages.items()) or "no package from the CDN"))
            print("\n".join(f"note     {n}" for n in copy.notes) if copy.notes else "", end="\n" if copy.notes else "")
    except Stop as stop:
        print(f"error: {stop}", file=sys.stderr)
        return stop.code
    return DONE


if __name__ == "__main__":
    sys.exit(main())
