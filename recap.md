## 2026-09-28 09:30 — Fix blog links, match menu to categories, add local preview

**The built site's links were already fine; local preview was what could not work. Fixed that plus two real defects, rewired the menu to the real categories, and added `preview.py`.**

- `posts.json`: post URLs now emit `posts/<slug>.html` instead of `/posts/<slug>.html` (`remove_first: "/"`), so links also resolve when the page is served from a subfolder. Excerpts use `strip` instead of `strip_newlines`, which stops sentences from different paragraphs gluing together ("Santa Claus.A direct…").
- `index.html`: the menu is built from the categories in `posts.json`. The bar shows Home, Musings, Danish, Language & Speech, Translation Comparisons, About; the ⋯ menu holds the other five. Every category appears once, and a category that disappears can no longer leave a dead link. About fallback URL made relative.
- `index.html`: the bar now wraps to its own scrollable row below 1160px — with the longer category names it overflowed at 861–1160px — and the ⋯ dropdown is right-aligned so it cannot open off-screen.
- `preview.py` (new): `uv run preview.py` builds `_site/` and serves it at <http://127.0.0.1:4000>; `--build-only` just builds. It mirrors what Jekyll produces so links can be clicked before pushing.
- `README.md`: added a "Preview locally" section explaining that the repo copy of `posts.json` is a template and why plain static serving shows "Could not load posts".

- Verification: headless Chromium against the preview — all 165 post links, 9 category links, About, Home, search and the back link pass; layout checked at 1280/1024/900/861/860/600/390px with no horizontal overflow and the dropdown on screen; relative URLs verified from a subpath; the Liquid template rendered with Liquid 4.0.4 plus kramdown (the stack GitHub Pages uses) produced valid JSON with 166 entries whose slug/title/date/url match the live file.
- Decisions: menu labels are the real category names (user's choice) rather than the original English/Dansk/Japanese/Translation wording; the responsive breakpoint moved up instead of shortening those names. Jekyll itself could not be installed here (native extension build failed), so the template was verified with its Liquid and kramdown components instead.
- Left undone: nothing committed or pushed; `hero.jpg` is still absent by design (the drawn SVG stands in and one 404 is logged); `preview.py` is untracked until you add it.
