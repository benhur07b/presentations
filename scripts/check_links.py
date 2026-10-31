#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["cairosvg>=2.9", "pillow>=13", "pypdf>=6.21", "zxing-cpp>=3.1"]
# ///
"""Check every link the presentations make, as a participant would follow it.

For each deck (a folder with HTML pages, the slides of a reveal.js deck included) and the index page:

- every link, image, stylesheet and script: a file in this repository, or an address on the web that opens
- every QR code: it decodes, its address opens, and the address typed under it (the caption) is the one it opens
- every link to a quiz on bnhr.xyz/quizzes: a delivery on the quizzes site runs that quiz and round, so the page does not
  say "This quiz isn't open"; a quiz that several deliveries run, linked without ?delivery=, is noted, since the page
  then asks which training
- with --pdfs, the links inside the PDF decks too

Read-only: it changes nothing. Exit 0 when every link holds, 1 when any does not, 2 on a usage error. Sites that turn
scripts away (403, 429, 999, Cloudflare's 52x) cannot be checked from here: they are listed as notes, to open by hand.

    uv run scripts/check_links.py                          # every deck and the index page
    uv run scripts/check_links.py 2026-11-09-qgis-for-sflma-mapping   # one deck, before it is shown
    uv run scripts/check_links.py --pdfs --json links.json # the PDF decks too, and every link as JSON

QR codes are drawn with cairosvg, which needs the Cairo library (on Debian or Ubuntu: apt install libcairo2).
"""

import argparse
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://bnhr.xyz/presentations/"
QUIZZES = "https://bnhr.xyz/quizzes/"
SKIPPED = ("mailto:", "tel:", "javascript:", "data:", "#")
# Answers that say a site turned the script away, not that the page is gone
TURNED_AWAY = {401, 403, 429, 444, 999} | set(range(520, 531))
# Tags with no end tag, which must not count toward a caption's depth
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# A <link> the browser only warms up a connection with: not a page to open
HINTS = {"preconnect", "dns-prefetch"}


@dataclass
class Link:
    file: str
    line: int
    kind: str  # "link" (href or src), "QR code", "PDF link"
    url: str | None
    local: bool = False
    caption: str | None = None
    status: int | None = None
    problem: str | None = None
    note: str | None = None
    found: list[str] = field(default_factory=list)


class Page(HTMLParser):
    """A page's links (href and src), and each QR image with the address typed in the caption after it"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, int]] = []
        self.qrs: list[dict] = []
        self._caption: dict | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if not (tag == "link" and HINTS & set((a.get("rel") or "").split())):
            self.links += [(a[key], self.getpos()[0]) for key in ("href", "src") if a.get(key)]
        classes = (a.get("class") or "").split()
        if tag == "img" and "qr" in classes:
            self.qrs.append({"src": a.get("src"), "line": self.getpos()[0], "caption": ""})
        if tag == "p" and "qr-caption" in classes and self.qrs:
            self._caption, self._depth = self.qrs[-1], 1
        elif self._caption is not None and tag not in VOID:
            self._depth += 1
            if tag == "b":  # the caption's bold label ("1 · The test") is not part of the address
                self._caption["caption"] += "\x00"

    def handle_endtag(self, tag):
        if self._caption is None or tag in VOID:
            return
        if tag == "b":
            self._caption["caption"] += "\x01"
        self._depth -= 1
        if self._depth == 0 or tag == "p":
            self._caption = None

    def handle_data(self, data):
        if self._caption is not None:
            self._caption["caption"] += data


def read_page(html: str) -> Page:
    """The page's links and QR codes. reveal.js keeps a deck's slides as Markdown in <textarea data-template>, which
    Python's parser reads as text, so each template's HTML and Markdown links are read on their own, at their lines."""
    page = Page()
    page.feed(html)
    for match in re.finditer(r"<textarea[^>]*\bdata-template\b[^>]*>(.*?)</textarea>", html, re.S):
        offset = html.count("\n", 0, match.start(1))
        slides = Page()
        slides.feed(match.group(1))
        page.links += [(value, line + offset) for value, line in slides.links]
        page.qrs += [{**qr, "line": qr["line"] + offset} for qr in slides.qrs]
        for link in re.finditer(r"\]\((\S+?)\)", match.group(1)):
            page.links.append((link.group(1), offset + match.group(1).count("\n", 0, link.start()) + 1))
    return page


def caption_address(caption: str) -> str | None:
    """The address a QR caption shows, if it shows one: its text outside the bold label, without spaces"""
    text = re.sub(r"\s+", "", re.sub(r"\x00.*?\x01", "", caption, flags=re.S))
    return text if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?", text) else None


def decode_qr(path: Path) -> str | None:
    import cairosvg
    import zxingcpp
    from PIL import Image

    image = cairosvg.svg2png(url=str(path), output_width=800, background_color="white") if path.suffix == ".svg" else path.read_bytes()
    found = zxingcpp.read_barcodes(Image.open(io.BytesIO(image)))
    return found[0].text if found else None


def bare(url: str) -> str:
    return re.sub(r"^https?://", "", url).rstrip("/")


def request(url: str) -> urllib.request.Request:
    """A request as a browser would send it: some sites, bnhr.xyz among them, refuse Python's own User-Agent"""
    return urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (presentations link check)"})


def fetch(url: str) -> tuple[int | None, str | None]:
    """The status a GET answers with, or None and why nothing answered"""
    try:
        with urllib.request.urlopen(request(url), timeout=25) as response:
            return response.status, None
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return None, str(getattr(error, "reason", error))


def collect(pages: list[Path], pdfs: list[Path]) -> list[Link]:
    links: list[Link] = []
    for path in pages:
        file = path.relative_to(ROOT).as_posix()
        base = SITE + path.relative_to(ROOT).as_posix()
        page = read_page(path.read_text(encoding="utf-8"))
        for value, line in page.links:
            if value.startswith(SKIPPED):
                continue
            url = urllib.parse.urljoin(base, value)
            links.append(Link(file, line, "link", url, local=not urllib.parse.urlparse(value).scheme and url.startswith(SITE)))
        for qr in page.qrs:
            image = (path.parent / (qr["src"] or "")).resolve()
            link = Link(file, qr["line"], "QR code", None, caption=caption_address(qr["caption"]))
            if not qr["src"] or not image.is_file():
                link.problem = f"the QR image {qr['src']} is not in the repository"
            elif (encoded := decode_qr(image)) is None:
                link.problem = f"the QR image {qr['src']} does not decode"
            else:
                link.url = encoded
                if link.caption and bare(link.caption) != bare(encoded):
                    link.problem = f"its caption shows {link.caption}, but the code opens {encoded}"
            links.append(link)
    for path in pdfs:
        from pypdf import PdfReader

        for number, pdf_page in enumerate(PdfReader(path).pages, start=1):
            for annotation in pdf_page.get("/Annots") or []:
                action = annotation.get_object().get("/A")
                if action and action.get("/URI"):
                    links.append(Link(path.relative_to(ROOT).as_posix(), number, "PDF link", str(action["/URI"])))
    return links


def check_files(links: list[Link]) -> None:
    for link in links:
        if link.local and link.url and not link.problem:
            path = urllib.parse.unquote(urllib.parse.urlparse(link.url).path).removeprefix("/presentations/")
            target = ROOT / path
            if not (target / "index.html" if target.is_dir() else target).is_file():
                link.problem = f"{path} is not in the repository"


def check_web(links: list[Link]) -> int:
    addresses = sorted({link.url for link in links if link.url and not link.local and not link.problem and link.url.startswith("http")})
    with ThreadPoolExecutor(8) as pool:
        answers = dict(zip(addresses, pool.map(fetch, addresses)))
    for link in links:
        if link.url not in answers or link.problem:
            continue
        link.status, reason = answers[link.url]
        if link.status in TURNED_AWAY:
            link.note = f"{link.status}: the site turned the check away; open it by hand"
        elif link.status is None and any(text in (reason or "") for text in ("Name or service not known", "nodename nor servname")):
            link.problem = f"its domain does not resolve ({reason})"
        elif link.status is None:
            link.note = f"nothing answered ({reason}), as a site that turns scripts away does; open it by hand"
        elif link.status >= 400:
            link.problem = f"it answers {link.status}"
    return len(addresses)


def check_quizzes(links: list[Link]) -> None:
    """A quiz link opens a quiz some delivery runs, in a round it has: the quizzes site's listing says which"""
    quiz_links = [(link, m) for link in links if link.url and not link.problem and (m := re.match(rf"{re.escape(QUIZZES)}([a-z0-9-]+)/([a-z0-9-]+)/(?:([a-z-]+)/)?(?:\?(.*))?$", link.url))]
    if not quiz_links:
        return
    try:
        with urllib.request.urlopen(request(QUIZZES + "cohorts.json"), timeout=25) as response:
            listing = json.load(response)
    except (OSError, ValueError) as error:
        for link, _ in quiz_links:
            link.problem = f"the quizzes listing could not be read ({error}), so the quiz could not be checked"
        return
    runs: dict[tuple[str, str], list[tuple[str, list[str]]]] = {}
    for delivery in listing.get("cohorts", []) + listing.get("selfPaced", []):
        quizzes = [q for day in delivery.get("days", []) for q in day["quizzes"]] + delivery.get("quizzes", [])
        for quiz in quizzes:
            runs.setdefault((delivery["courseId"], quiz["id"]), []).append((delivery["id"], quiz["rounds"]))
    for link, m in quiz_links:
        course, quiz, round_, query = m.groups()
        deliveries = runs.get((course, quiz), [])
        named = urllib.parse.parse_qs(query or "").get("delivery", [None])[0]
        if named:
            deliveries = [d for d in deliveries if d[0] == named]
        link.found = [d for d, _ in deliveries]
        if not deliveries:
            link.problem = f"no delivery on the quizzes site runs {course}/{quiz}" + (f" as {named}" if named else "") + ", so its page says it isn't open"
        elif not any((round_ or "check-in") in rounds or (round_ is None and len(rounds) == 1) for _, rounds in deliveries):
            link.problem = f"{course}/{quiz} has no round {round_ or '(none)'} in {', '.join(link.found)}"
        elif len(deliveries) > 1 and not named:
            link.note = f"{len(deliveries)} deliveries run {course}/{quiz} ({', '.join(link.found)}), so its page asks which training"


def report(links: list[Link], checked: int) -> int:
    """One line per address and finding, with where it is, so a link on every page of a PDF is one line"""
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for link in links:
        for level, text in (("problem", link.problem), ("note", link.note)):
            if text:
                grouped.setdefault((level, link.url or "", text), []).append(f"{link.file}:{link.line}")
    for (level, url, text), where in sorted(grouped.items()):
        shown = ", ".join(where[:3]) + (f" and {len(where) - 3} more" if len(where) > 3 else "")
        print(f"{level}: {url or '(no address)'}: {text}  [{shown}]")
    problems = sum(1 for level, _, _ in grouped if level == "problem")
    kinds = {kind: sum(1 for link in links if link.kind == kind) for kind in ("link", "QR code", "PDF link")}
    counted = ", ".join(f"{n} {kind}{'s' if n != 1 else ''}" for kind, n in kinds.items() if n)
    print(f"{len(links)} links checked ({counted}; {checked} web addresses): {problems or 'no'} problem{'s' if problems != 1 else ''}, {len(grouped) - problems} note{'s' if len(grouped) - problems != 1 else ''}")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog="Exit 0: every link holds; 1: a problem; 2: a usage error.")
    parser.add_argument("decks", nargs="*", help="deck folders to check (default: every deck and the index page)")
    parser.add_argument("--pdfs", action="store_true", help="check the links inside the PDF decks too")
    parser.add_argument("--json", type=Path, metavar="PATH", help="also write every link checked, with its finding, as JSON")
    args = parser.parse_args()
    folders = [ROOT / d.rstrip("/") for d in args.decks] or sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in {"assets", "scripts"})
    missing = [f.name for f in folders if not f.is_dir()]
    if missing:
        parser.error(f"no deck folder {', '.join(missing)} in {ROOT}")
    pages = ([] if args.decks else [ROOT / "index.html"]) + [p for f in folders for p in sorted(f.glob("*.html"))]
    pdfs = [p for f in folders for p in sorted(f.glob("*.pdf"))] if args.pdfs else []
    print(f"Checking {len(pages)} pages{f' and {len(pdfs)} PDFs' if pdfs else ''} in {len(folders)} folders…", file=sys.stderr)
    links = collect(pages, pdfs)
    check_files(links)
    checked = check_web(links)
    check_quizzes(links)
    if args.json:
        args.json.write_text(json.dumps([asdict(link) for link in links], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return report(links, checked)


if __name__ == "__main__":
    sys.exit(main())
