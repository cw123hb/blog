#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["markdown", "pyyaml"]
# ///
"""Build and serve a local copy of Myriad Leaves.

GitHub Pages runs Jekyll on every push: it turns the posts.json template into
the real post list and each posts/*.md into posts/<name>.html. This script does
the same locally, so every link can be clicked before pushing.

    uv run preview.py              # build _site/ and serve it on port 4000
    uv run preview.py --port 8080
    uv run preview.py --build-only
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import shutil
import sys
from datetime import date, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import markdown
import yaml

REPO = Path(__file__).resolve().parent
SITE = REPO / "_site"
EXCERPT_LENGTH = 180
EXTENSIONS = ["tables", "fenced_code", "sane_lists"]
FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)


def split_front_matter(text: str) -> tuple[dict, str]:
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    fields = yaml.safe_load(match.group(1)) or {}
    if not isinstance(fields, dict):
        fields = {}
    return fields, match.group(2)


def iso_date(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else ""


def excerpt_of(rendered: str) -> str:
    # Mirrors the Liquid: markdownify | strip_html | strip | truncate: 180
    text = re.sub(r"<[^>]+>", "", rendered).strip()
    if len(text) > EXCERPT_LENGTH:
        text = text[: EXCERPT_LENGTH - 3] + "..."
    return text


def build() -> int:
    shutil.rmtree(SITE, ignore_errors=True)
    (SITE / "posts").mkdir(parents=True)
    shutil.copy(REPO / "index.html", SITE / "index.html")

    posts = []
    for path in sorted((REPO / "posts").glob("*.md")):
        fields, body = split_front_matter(path.read_text(encoding="utf-8"))
        slug = path.stem
        title = str(fields.get("title") or slug)
        rendered = markdown.markdown(body, extensions=EXTENSIONS)
        (SITE / "posts" / f"{slug}.html").write_text(rendered, encoding="utf-8")
        posts.append({
            "slug": slug,
            "title": title,
            "date": iso_date(fields.get("date")),
            "url": f"posts/{slug}.html",
            "excerpt": excerpt_of(rendered),
            "category": str(fields.get("category") or ""),
        })

    (SITE / "posts.json").write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    return len(posts)


class QuietHandler(SimpleHTTPRequestHandler):
    """Only log failed requests; a full log drowns the preview."""

    def log_message(self, format, *args):
        if len(args) >= 2 and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and serve the site locally.")
    parser.add_argument("--port", type=int, default=4000, help="port to serve on (default 4000)")
    parser.add_argument("--build-only", action="store_true", help="build _site/ and exit")
    args = parser.parse_args()

    print(f"built {build()} posts into {SITE}")
    if args.build_only:
        return

    handler = functools.partial(QuietHandler, directory=SITE)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"serving at http://127.0.0.1:{args.port} (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
