#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6.0",
# ]
# ///
"""Check post categories with Jev, TypeSafe AI's typed classifier.

`index.html` currently guesses each post's category at page-load time with a
title regex (see `CATEGORIES` in its `<script>`). That's a rough sort, not a
science. This script asks Jev the same question properly: given a post's
title and an excerpt of its body, which of the site's real categories fits
best - and, importantly, whether none of them do.

Jev returns a typed choice plus a calibrated probability for every option, so
"none of these fit" is a real, checkable answer, not a guess. Posts where Jev
either picks the explicit "new_category" escape option or answers with low
confidence are the candidates worth a new category.

The script also replicates the site's regex heuristic so it can report where
Jev disagrees with what visitors currently see - "using the wrong category".

Requires the `jev` CLI on PATH (https://docs.typesafe.ai). The API key comes
from, in order: the TYPESAFE_API_KEY environment variable if already set,
then the `kli` local secret manager (`kli get TYPESAFE_API_KEY`), then
whatever `jev auth login` already has stored - the script never prints the
key and only ever hands it to the `jev` subprocess's environment.

Usage:
    uv run categorize_posts.py                      # classify every post, print a report
    uv run categorize_posts.py --slug some-post      # just one post
    uv run categorize_posts.py --limit 5             # smoke-test on the first N posts
    uv run categorize_posts.py --dry-run             # show request count/cost, send nothing
    uv run categorize_posts.py --out report.json     # also write the full report as JSON
    uv run categorize_posts.py --write-frontmatter   # add/update `category:` in confident posts
    uv run categorize_posts.py --low-confidence 0.6  # tune the "spans two categories" threshold
    uv run categorize_posts.py --check               # offline: fail if a post lacks a category
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent
POSTS_DIR = REPO / "posts"
FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)

# Pages that live in posts/ but are not posts (mirrors PAGES in index.html).
PAGES = {"about"}

# The real categories, described for Jev. Names match MAIN_CATEGORIES plus
# the other entries of CATEGORIES in index.html, so a report can be compared
# directly against what the site currently shows.
CATEGORIES = {
    "Christmas & Yule": "Seasonal holiday posts: Christmas, Yule, Halloween, New Year.",
    "Translation Comparisons": "Posts that compare different translations of the same work, "
    "e.g. English/Danish/Japanese versions of the same story.",
    "Danish": "Posts specifically about the Danish language, its dialects, or Denmark.",
    "Games": "Posts about video games (fighting games, JRPGs, etc.), their characters, "
    "lore, or in-game speech.",
    "Anime, Manga & Fiction": "Posts about anime, manga, or other fictional franchises "
    "and their characters (not a game, not original writing).",
    "Poetry & Stories": "Original poems, short stories, or other creative fiction written "
    "by the blog's author.",
    "Site Updates": "Announcements or notes about the blog itself, not about language, "
    "translation, or any franchise.",
    "Language & Speech": "General posts about linguistics, grammar, honorifics, pronouns, "
    "dialects, sociolects, or speech patterns - not tied to a specific holiday, franchise, "
    "or the Danish language in particular.",
    "Musings": "General opinions or essays that don't fit any other category - the site's "
    "own catch-all.",
}
# Pinned so reruns give the same answers; bump deliberately.
MODEL = "jev-1.13.0"
NEW_CATEGORY_OPTION = "none_of_the_above"
NEW_CATEGORY_DESC = (
    "None of the existing categories are a good fit for this post; it likely needs a "
    "brand-new category of its own."
)

# The site's current title-regex heuristic (index.html, CATEGORIES/categorize()),
# reproduced so this script can flag posts where Jev disagrees with it.
_REGEX_CATEGORIES = [
    ("Christmas & Yule", re.compile(
        r"xmas|x-mas|christmas|yule|santa|kurisumasu|dickensian christmas|ho ho horrible|"
        r"humbug|moat bells|halloween|hallowe'en|new year", re.I)),
    ("Translation Comparisons", re.compile(
        r"comparison|emperor'?s new clothes|nightingale|little match girl|"
        r"dickensian japanese|translating poetry", re.I)),
    ("Danish", re.compile(r"dansk|danish|d[øo]gnstemning|luk[øo]je", re.I)),
    ("Games", re.compile(
        r"street fighter|elden ring|dark souls|soulsborne|tekken|snk|mokujin|rugal|gouki|"
        r"shungokusatsu|hokuto|king of fists|final fantasy|jrpg|ryuujin|robotto|"
        r"pocket clerks|rock exe|shadow the colossus|dlc|x-men vs|bison|cammy|arisen", re.I)),
    ("Anime, Manga & Fiction", re.compile(
        r"dragon ball|db addendum|db in dk|akatsuki|toriyama|manga|speech patterns|"
        r"honorifics in outer space|human-cyborg|obi-wan|palpatine|martians|silvered ones|"
        r"line individualism|lord of dragons", re.I)),
    ("Poetry & Stories", re.compile(
        r"poem|poems|ægidius|aegidius|philomena|piano the pterodactyl|princess tamaeda|"
        r"random quotes", re.I)),
    ("Site Updates", re.compile(r"^update|^quick update|update post", re.I)),
    ("Language & Speech", re.compile(
        r"keigo|honorific|pronoun|particle|dialect|sociolect|katakana|benefactive|modal|"
        r"watashi|wagahai|thyself|kisama|kono teido|noble women|eccentric speech|polite|"
        r"rudeness|old sport|being!$|writing out the i|i am or ain'?t|"
        r"one word, multiple kanji|gemming|thank you|kikou|kiden", re.I)),
]


def regex_category(title: str) -> str:
    for name, pattern in _REGEX_CATEGORIES:
        if pattern.search(title):
            return name
    return "Musings"


def split_front_matter(text: str) -> tuple[dict, str]:
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    fields = yaml.safe_load(match.group(1)) or {}
    if not isinstance(fields, dict):
        fields = {}
    return fields, match.group(2)


def excerpt_of(body: str, length: int = 700) -> str:
    # Rough markdown strip, good enough to give Jev the gist without noise.
    text = re.sub(r"`{1,3}[^`]*`{1,3}", " ", body)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_~-]{1,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:length]


def load_posts() -> list[dict]:
    posts = []
    for path in sorted(POSTS_DIR.glob("*.md")):
        slug = path.stem
        if slug in PAGES:
            continue
        fields, body = split_front_matter(path.read_text(encoding="utf-8"))
        title = str(fields.get("title") or slug)
        posts.append({
            "slug": slug,
            "path": path,
            "title": title,
            "excerpt": excerpt_of(body),
        })
    return posts


def api_key_env() -> dict[str, str]:
    """Env overrides to hand the `jev` subprocess, without printing the key."""
    import os

    env = dict(os.environ)
    if env.get("TYPESAFE_API_KEY"):
        return env  # already set; jev prefers this over any stored profile anyway
    try:
        result = subprocess.run(
            ["kli", "get", "TYPESAFE_API_KEY"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return env  # kli unavailable; fall back to jev's own stored credentials
    if result.returncode == 0 and result.stdout.strip():
        env["TYPESAFE_API_KEY"] = result.stdout.strip()
    return env


def build_questions_file(tmp_dir: Path) -> Path:
    criteria = dict(CATEGORIES)
    criteria[NEW_CATEGORY_OPTION] = NEW_CATEGORY_DESC
    questions = {
        "questions": {
            "category": {
                "type": "choice",
                "instructions": (
                    "This is a blog post from a linguistics/translation/pop-culture blog. "
                    "Which category best fits it? Judge by the post's actual subject, not "
                    "just words that happen to appear in the title."
                ),
                "criteria": criteria,
            }
        }
    }
    path = tmp_dir / "questions.yaml"
    path.write_text(yaml.safe_dump(questions, sort_keys=False), encoding="utf-8")
    return path


def build_rows_file(tmp_dir: Path, posts: list[dict]) -> Path:
    path = tmp_dir / "rows.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for post in posts:
            f.write(json.dumps({
                "slug": post["slug"],
                "title": post["title"],
                "excerpt": post["excerpt"],
            }) + "\n")
    return path


def run_jev_batch(
    questions_file: Path, rows_file: Path, out_file: Path,
    env: dict[str, str], *, dry_run: bool, limit: int | None,
) -> dict | None:
    cmd = [
        "jev", "batch", "run",
        "-f", str(questions_file),
        "--input", str(rows_file),
        "--input-format", "jsonl",
        "--state-fields", "title,excerpt",
        "--id-field", "slug",
        "--concurrency", "8",
        "--model", MODEL,
        "-o", "jsonl",
    ]
    if dry_run:
        cmd.append("--dry-run")
    else:
        cmd += ["--out", str(out_file)]
    if limit:
        cmd += ["--limit", str(limit)]

    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if dry_run:
        print(result.stdout)
        if result.returncode not in (0,):
            print(result.stderr, file=sys.stderr)
        return None
    if result.returncode not in (0, 7):
        # 7 = some rows failed; still worth reading the partial output.
        print(f"jev batch run failed (exit {result.returncode}):", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        if result.returncode not in (7,):
            sys.exit(result.returncode)
    if result.stderr.strip():
        # Progress/summary lines from jev; useful, not an error by itself.
        print(result.stderr.strip(), file=sys.stderr)
    return {"returncode": result.returncode}


def read_results(out_file: Path) -> dict[str, dict]:
    results = {}
    if not out_file.exists():
        return results
    for line in out_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        results[record["id"]] = record
    return results


def build_report(posts: list[dict], results: dict[str, dict], low_confidence: float) -> dict:
    rows = []
    for post in posts:
        record = results.get(post["slug"])
        current = regex_category(post["title"])
        row = {
            "slug": post["slug"],
            "title": post["title"],
            "current_category": current,
        }
        if record is None:
            row["status"] = "skipped"
        elif record["status"] != "ok":
            row["status"] = "error"
            row["error"] = record.get("error")
        else:
            answer = record["answers"]["category"]
            choice = answer["choice"]
            confidence = answer["confidence"]
            # Only "nothing fits" means a new category. Low confidence between
            # real categories just means the post spans two; take the top pick.
            row.update({
                "status": "ok",
                "jev_category": choice,
                "confidence": confidence,
                "probabilities": answer["probabilities"],
                "needs_new_category": choice == NEW_CATEGORY_OPTION,
                "ambiguous": choice != NEW_CATEGORY_OPTION and confidence < low_confidence,
                "mismatch": choice != NEW_CATEGORY_OPTION and choice != current,
            })
        rows.append(row)
    return {
        "low_confidence_threshold": low_confidence,
        "posts": rows,
    }


def print_report(report: dict) -> None:
    rows = report["posts"]
    ok = [r for r in rows if r["status"] == "ok"]
    errors = [r for r in rows if r["status"] == "error"]
    mismatches = [r for r in ok if r["mismatch"] and not r["ambiguous"]]
    ambiguous = [r for r in ok if r["ambiguous"]]
    needs_new = [r for r in ok if r["needs_new_category"]]

    print(f"\n{len(rows)} posts checked, {len(ok)} classified, {len(errors)} failed.\n")

    if mismatches:
        print(f"-- {len(mismatches)} post(s) filed under the wrong category --")
        for r in mismatches:
            print(f"  {r['slug']}: site shows \"{r['current_category']}\", "
                  f"Jev says \"{r['jev_category']}\" ({r['confidence']:.2f})")
        print()

    if ambiguous:
        print(f"-- {len(ambiguous)} post(s) span two categories; took the top pick --")
        for r in ambiguous:
            top = sorted(r["probabilities"].items(), key=lambda kv: -kv[1])[:2]
            top_str = ", ".join(f"{name}={p:.2f}" for name, p in top)
            print(f"  {r['slug']}: {top_str}")
        print()

    if needs_new:
        print(f"-- {len(needs_new)} post(s) fit no existing category --")
        for r in needs_new:
            top = sorted(r["probabilities"].items(), key=lambda kv: -kv[1])[:3]
            top_str = ", ".join(f"{name}={p:.2f}" for name, p in top)
            print(f"  {r['slug']} (\"{r['title']}\"): best guess \"{r['jev_category']}\" "
                  f"({r['confidence']:.2f}) - top options: {top_str}")
        print()

    if errors:
        print(f"-- {len(errors)} post(s) failed to classify --")
        for r in errors:
            print(f"  {r['slug']}: {r['error']}")
        print()

    if not mismatches and not ambiguous and not needs_new and not errors:
        print("Every classified post matches its current category with good confidence.")


_CATEGORY_LINE = re.compile(r"^category:.*$", re.M)


def set_category_line(front_matter_text: str, category: str) -> str:
    """Insert or replace a `category:` line in raw front-matter YAML text,
    leaving every other line byte-for-byte untouched."""
    # yaml.safe_dump on a bare scalar appends a `...` document-end marker;
    # strip it so only the quoted-if-needed value remains.
    dumped = yaml.safe_dump(category).strip()
    if dumped.endswith("\n..."):
        dumped = dumped[: -len("\n...")]
    elif dumped.endswith("..."):
        dumped = dumped[: -len("...")].rstrip()
    line = f"category: {dumped}"
    if _CATEGORY_LINE.search(front_matter_text):
        return _CATEGORY_LINE.sub(line, front_matter_text, count=1)
    return front_matter_text.rstrip("\n") + f"\n{line}"


def write_frontmatter(report: dict, posts_by_slug: dict[str, dict]) -> None:
    updated, skipped = 0, 0
    for row in report["posts"]:
        if row["status"] != "ok" or row["needs_new_category"]:
            skipped += 1
            continue
        post = posts_by_slug[row["slug"]]
        text = post["path"].read_text(encoding="utf-8")
        match = FRONT_MATTER.match(text)
        if not match:
            skipped += 1
            continue
        new_front = set_category_line(match.group(1), row["jev_category"])
        new_text = f"---\n{new_front}\n---\n{match.group(2)}"
        post["path"].write_text(new_text, encoding="utf-8")
        updated += 1
    print(f"\nWrote `category:` into {updated} post(s); left {skipped} unchanged "
          f"(failed, or fit no existing category).")


def check_posts() -> int:
    """Offline check: every post has a known `category:`. No API calls."""
    problems = []
    for path in sorted(POSTS_DIR.glob("*.md")):
        if path.stem in PAGES:
            continue
        fields, _ = split_front_matter(path.read_text(encoding="utf-8"))
        category = fields.get("category")
        if not category:
            problems.append(f"  {path.stem}: no category")
        elif category not in CATEGORIES:
            problems.append(f"  {path.stem}: unknown category {category!r}")
    if problems:
        print(f"{len(problems)} post(s) need attention:")
        print("\n".join(problems))
        print("\nRun `uv run categorize_posts.py --slug <slug> --write-frontmatter` to fix one.")
        return 1
    print("Every post has a known category.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slug", help="Only check this one post (its filename without .md)")
    parser.add_argument("--limit", type=int, help="Only check the first N posts")
    parser.add_argument("--low-confidence", type=float, default=0.5,
                         help="Confidence below this flags a post for review (default 0.5)")
    parser.add_argument("--out", type=Path, help="Also write the full report as JSON here")
    parser.add_argument("--write-frontmatter", action="store_true",
                         help="Add/update `category:` in confidently-classified posts")
    parser.add_argument("--dry-run", action="store_true",
                         help="Show jev's request count and estimated cost; send nothing")
    parser.add_argument("--check", action="store_true",
                         help="Offline: exit 1 if any post lacks a known category")
    args = parser.parse_args()

    if args.check:
        sys.exit(check_posts())

    posts = load_posts()
    if args.slug:
        posts = [p for p in posts if p["slug"] == args.slug]
        if not posts:
            sys.exit(f"No post with slug {args.slug!r} in {POSTS_DIR}")

    env = api_key_env()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        questions_file = build_questions_file(tmp_dir)
        rows_file = build_rows_file(tmp_dir, posts)
        out_file = tmp_dir / "results.jsonl"

        run_jev_batch(
            questions_file, rows_file, out_file, env,
            dry_run=args.dry_run, limit=args.limit,
        )
        if args.dry_run:
            return

        results = read_results(out_file)

    if args.limit:
        posts = posts[: args.limit]
    report = build_report(posts, results, args.low_confidence)
    print_report(report)

    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nFull report written to {args.out}")

    if args.write_frontmatter:
        write_frontmatter(report, {p["slug"]: p for p in posts})


if __name__ == "__main__":
    main()
