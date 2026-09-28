# Myriad Leaves — TLDR

**What it is.** A static blog at **www.myriadleaves.eu** (custom domain via
`CNAME`). Source: `github.com/cw123hb/blog`, published from the **`main`**
branch with **GitHub Pages + Jekyll**. There is no `.github/workflows` and no
`_config.yml` — it uses the default Jekyll build. `_site/` is gitignored.

## How it hangs together

- **Posts** live in `posts/*.md` with YAML front matter: `title`, `date`
  (`YYYY-MM-DD`), `slug`, `tags`, `description`, and optional `category`.
  Template: `_templates/post.md`. The filename is the slug and the URL.
- **`posts.json`** is a Jekyll template (`permalink: /posts.json`). On each
  build it scans `posts/*.md` and emits JSON: `slug`, `title`, `date`, `url`,
  `excerpt` (180 chars), `category`.
- **`index.html`** is a client-side app. It fetches `posts.json` to build the
  list, category pages, and search, then fetches `posts/<slug>.html` per post.
  A post without `category:` gets one guessed from its title by regex.
- **Categories** (9): Christmas & Yule, Translation Comparisons, Danish, Games,
  Anime Manga & Fiction, Poetry & Stories, Site Updates, Language & Speech,
  Musings. Top-bar main ones: Musings, Danish, Language & Speech, Translation
  Comparisons.
- **Tooling:**
  - `preview.py` — a local Jekyll stand-in. `uv run preview.py` builds `_site/`
    and serves <http://127.0.0.1:4000>; `--build-only` just builds. Needed
    because opening `index.html` directly fails ("Could not load posts").
  - `categorize_posts.py` — uses the Jev CLI to classify posts into the real
    categories. `--write-frontmatter` adds/updates `category:`; `--check` is an
    offline "every post has a category" gate; writes `category_report.json`.

## Adding a new post

1. Copy `_templates/post.md` → `posts/your-post-name.md` (this name becomes the
   URL).
2. Fill in title, date (`YYYY-MM-DD`), slug (match the filename), description,
   category, and the Markdown body.
3. Preview: `uv run preview.py`, then open <http://127.0.0.1:4000> and click
   through every link.
4. Optional: `uv run categorize_posts.py --slug your-post-name --write-frontmatter`
   to set the category properly.
5. Commit to `main` and push.

## Publishing

Push to `main` → GitHub Pages runs Jekyll → it regenerates `posts.json` and each
`posts/<slug>.html` → the live site updates. Only the Markdown is committed; the
built output is not.

## Editing tips

Keep the filename the same when editing so existing links and archive routes
keep working. `about.md` lives in `posts/` but is treated as a page, not a post.
