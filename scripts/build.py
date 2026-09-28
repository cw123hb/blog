#!/usr/bin/env python3
"""Build the static files and update the post list for GitHub Pages."""

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist"

if OUTPUT.exists():
    shutil.rmtree(OUTPUT)
OUTPUT.mkdir()
shutil.copy2(ROOT / "index.html", OUTPUT / "index.html")
shutil.copy2(ROOT / "CNAME", OUTPUT / "CNAME")
shutil.copytree(ROOT / "posts", OUTPUT / "posts")

posts = sorted(f"posts/{path.name}" for path in (ROOT / "posts").glob("*.md"))
manifest = json.dumps(posts, ensure_ascii=False, indent=2) + "\n"
(ROOT / "posts.json").write_text(manifest, encoding="utf-8")
(OUTPUT / "posts.json").write_text(manifest, encoding="utf-8")
print(f"Built {len(posts)} Markdown files in {OUTPUT}")
