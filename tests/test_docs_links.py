"""E2E docs link validation: every relative markdown link in README.md and docs/ must
resolve to an existing file or directory, and every same-page anchor must match a
heading (GitHub-style slug). Code blocks are ignored so example snippets can't false-positive."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD_FILES = [os.path.join(ROOT, "README.md")] + \
    sorted(os.path.join(ROOT, d, f) for d in ("docs", "docs-desktop")
           if os.path.isdir(os.path.join(ROOT, d))
           for f in os.listdir(os.path.join(ROOT, d)) if f.endswith(".md"))

LINK_RE = re.compile(r"\]\(([^)]+)\)")


def _strip_fences(text):
    return re.sub(r"```.*?```", "", text, flags=re.S)


def _strip_code(text):
    return re.sub(r"`[^`\n]*`", "", _strip_fences(text))  # inline code too (for link scanning)


def _slug(heading):
    """GitHub anchor slug: lowercase, drop anything but letters/digits/space/hyphen/underscore, each whitespace char -> '-'.

    Backticks in headings are kept (GitHub renders them and keeps the words), so slugs come from fence-stripped text only."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return re.sub(r"\s", "-", s)


def _headings(text):
    slugs = set()
    for line in _strip_fences(text).splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            slugs.add(_slug(m.group(2)))
    return slugs


def test_all_markdown_files_exist():
    assert MD_FILES, "no markdown files found — docs layout changed?"
    for f in MD_FILES:
        assert os.path.isfile(f), f"missing doc file: {f}"


def test_relative_links_resolve():
    failures = []
    for md in MD_FILES:
        raw = open(md, encoding="utf-8").read()
        text = _strip_code(raw)
        base_dir = os.path.dirname(md)
        slugs = _headings(raw)
        for target in LINK_RE.findall(text):
            target = target.split(" \"")[0]                # drop optional link title
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue                                   # external scheme (http/https/mailto) or bare anchor handled below
            path_part, _, anchor = target.partition("#")
            if not path_part:                              # same-page anchor
                if anchor and anchor not in slugs:
                    failures.append(f"{os.path.relpath(md, ROOT)}: unknown anchor #{anchor}")
                continue
            resolved = os.path.normpath(os.path.join(base_dir, path_part))
            if path_part.endswith("/"):
                ok = os.path.isdir(resolved)
            else:
                ok = os.path.exists(resolved)
            if not ok:
                failures.append(f"{os.path.relpath(md, ROOT)} -> {target}")
            elif anchor and os.path.isfile(resolved):      # cross-file anchor
                other_raw = open(resolved, encoding="utf-8").read()
                if anchor not in _headings(other_raw):
                    failures.append(f"{os.path.relpath(md, ROOT)} -> {target} (no matching heading)")
    assert not failures, "broken doc links:\n" + "\n".join(sorted(failures))
