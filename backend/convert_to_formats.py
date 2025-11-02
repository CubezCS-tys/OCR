#!/usr/bin/env python3
"""
Convert HTML (with extracted images) to DOCX and EPUB using pandoc.

This script copies the input HTML and any local images it references into a
temporary working directory, then calls `pandoc` to produce the desired output
formats. Pandoc must be installed on the system.

Usage:
    python3 backend/convert_to_formats.py input.html --outdir output_formats --formats docx epub --title "My Title"

Notes:
- Pandoc is required (https://pandoc.org/installing.html). On Debian/Ubuntu:
  sudo apt install pandoc
- For EPUB cover image, pass --cover path/to/cover.jpg
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def find_image_refs(html_text: str):
    return IMG_SRC_RE.findall(html_text)


def ensure_pandoc():
    from shutil import which
    return which('pandoc') is not None


def copy_assets_and_prepare(input_html: Path, tmpdir: Path):
    """Copy HTML and locally referenced images into tmpdir, inject RTL CSS/meta when Arabic is detected.
    Return path to the modified HTML placed in tmpdir.
    """
    with open(input_html, 'r', encoding='utf-8') as f:
        html = f.read()

    img_paths = find_image_refs(html)
    # Map original src -> new basename in tmpdir so we can rewrite <img> references
    src_map = {}

    for src in img_paths:
        # Skip data URIs
        if src.strip().startswith('data:'):
            continue

        # Only handle local file references (relative or absolute)
        src_path = Path(src)
        if not src_path.is_absolute():
            # Interpret relative paths relative to the HTML file
            src_path = (input_html.parent / src_path).resolve()

        if src_path.exists() and src_path.is_file():
            # Choose a dest name in tmpdir; avoid collisions by adding suffix when needed
            base_name = src_path.name
            dest = tmpdir / base_name
            counter = 1
            while dest.exists():
                # Append a numeric suffix before the extension
                stem = Path(base_name).stem
                suf = Path(base_name).suffix
                new_name = f"{stem}_{counter}{suf}"
                dest = tmpdir / new_name
                counter += 1
            try:
                shutil.copy2(src_path, dest)
                src_map[src] = dest.name
            except Exception as e:
                print(f"[WARN] Could not copy image {src_path} -> {dest}: {e}")
        else:
            print(f"[WARN] Referenced image not found or not a file: {src}")

    # Detect Arabic characters to decide whether to force RTL
    arabic_re = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
    has_arabic = bool(arabic_re.search(html))

    modified_html = html

    # Ensure meta charset present
    if '<meta charset' not in modified_html.lower():
        # insert into <head> if possible
        if '<head' in modified_html.lower():
            modified_html = re.sub(r'(?i)(<head[^>]*>)', r"\1\n<meta charset=\"utf-8\">", modified_html, count=1)
        else:
            modified_html = '<meta charset="utf-8">\n' + modified_html

    # Inject RTL attributes and CSS when Arabic detected
    if has_arabic:
        # Add lang and dir to <html> when missing
        if re.search(r'(?i)<html[^>]*dir=', modified_html) is None:
            if re.search(r'(?i)<html', modified_html):
                # Keep any existing attributes then add lang/dir/style so tags remain well-formed
                modified_html = re.sub(
                    r'(?i)<html([^>]*)>',
                    r'<html\1 lang="ar" dir="rtl" style="direction:rtl;unicode-bidi:embed;">',
                    modified_html,
                    count=1,
                )
            else:
                modified_html = '<html lang="ar" dir="rtl" style="direction:rtl;unicode-bidi:embed;">\n' + modified_html + '\n</html>'

        # Ensure body has dir attribute
        if re.search(r'(?i)<body[^>]*dir=', modified_html) is None:
            if re.search(r'(?i)<body', modified_html):
                # Place any existing attributes first, then add dir/style
                modified_html = re.sub(
                    r'(?i)<body([^>]*)>',
                    r'<body\1 dir="rtl" style="direction:rtl;unicode-bidi:embed;text-align:right;">',
                    modified_html,
                    count=1,
                )
            else:
                # wrap content in body
                modified_html = re.sub(r'(?i)<html[^>]*>', r'\g<0>\n<body dir="rtl" style="direction:rtl;unicode-bidi:embed;text-align:right;">', modified_html, count=1)
                if '</body>' not in modified_html.lower():
                    modified_html = modified_html + '\n</body>'

        # Inject small RTL CSS into head
        rtl_css = '<style>body{direction:rtl;unicode-bidi:embed;text-align: right;} img{max-width:100%;height:auto;}</style>'
        if re.search(r'(?i)<head[^>]*>', modified_html):
            modified_html = re.sub(r'(?i)(<head[^>]*>)', r"\1\n" + rtl_css, modified_html, count=1)
        else:
            modified_html = rtl_css + '\n' + modified_html

    # Write modified HTML into tmpdir
    # Rewrite image src attributes in the modified_html to point to files copied into tmpdir
    # This ensures pandoc (with resource-path set to tmpdir) will find and embed them
    for original_src, new_name in src_map.items():
        # handle both double and single quoted src attributes
        modified_html = modified_html.replace(f'src="{original_src}"', f'src="{new_name}"')
        modified_html = modified_html.replace(f"src='{original_src}'", f"src='{new_name}'")

    dst_html = tmpdir / input_html.name
    with open(dst_html, 'w', encoding='utf-8') as outf:
        outf.write(modified_html)

    return dst_html


def run_pandoc(input_html_path: Path, out_path: Path, format: str, title: str = None, author: str = None, cover: Path = None, epub_math: str = 'mathml', lang: str = None, reference_doc: Path = None, epub_stylesheet: Path = None):
    args = ['pandoc', str(input_html_path), '-o', str(out_path)]
    # Tell pandoc to accept TeX math inside HTML (dollar delimiters)
    from_arg = 'html+tex_math_dollars'
    args += [f'--from={from_arg}']
    # Use resource-path so pandoc can find images in the working dir
    args += ['--resource-path', str(input_html_path.parent)]
    # Language metadata. Only set base direction to RTL when the language is an RTL language.
    RTL_LANGS = {'ar', 'he', 'fa', 'ur', 'ps'}
    if lang:
        args += ['--metadata', f'lang={lang}']
        # only set dir=rtl when lang is known to be an RTL language
        if lang.split('-', 1)[0] in RTL_LANGS:
            args += ['--metadata', 'dir=rtl']
    if title:
        args += ['--metadata', f'title={title}']
    if author:
        args += ['--metadata', f'author={author}']
    if format == 'epub' and cover:
        args += ['--epub-cover-image', str(cover)]
    # For EPUB include a table of contents by default
    if format == 'epub':
        args += ['--toc']
        # EPUB-specific math handling strategies
        # epub_math: 'mathml' (convert TeX to MathML, best for EPUB3 readers),
        # 'images' (render math as images via webtex), or 'mathjax' (leave JS hooks).
        if epub_math == 'mathml':
            # Prefer EPUB3 and MathML conversion
            args += ['--mathml', '--to=epub3']
        elif epub_math == 'images':
            # Use webtex image URLs for math (requires internet or a local webtex service)
            args += ['--webtex', '--to=epub3']
        elif epub_math == 'mathjax':
            # Keep math as TeX and include MathJax hooks (not ideal for EPUB readers)
            args += ['--mathjax', '--to=epub3']
        # Ensure epub3 page progression direction is set for RTL reading when appropriate
        if lang and lang.split('-', 1)[0] in RTL_LANGS:
            args += ['--metadata', 'page-progression-direction=rtl']
        # If an EPUB stylesheet was provided, include it
        if epub_stylesheet:
            # --epub-stylesheet was removed in newer pandoc; use --css instead
            args += ['--css', str(epub_stylesheet)]

    # For DOCX, allow using a reference docx with RTL styles
    if format == 'docx' and reference_doc:
        if Path(reference_doc).exists():
            args += ['--reference-doc', str(reference_doc)]

    print(f"Running: {' '.join(args)}")
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Pandoc failed (exit {r.returncode}):\nSTDOUT: {r.stdout}\nSTDERR: {r.stderr}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description='Convert HTML + images to DOCX and EPUB via pandoc')
    parser.add_argument('input_html', help='Path to the input HTML file')
    parser.add_argument('--outdir', default='converted_formats', help='Output directory')
    parser.add_argument('--formats', nargs='+', choices=['docx', 'epub'], default=['docx', 'epub'], help='Formats to produce')
    parser.add_argument('--title', help='Title metadata')
    parser.add_argument('--author', help='Author metadata')
    parser.add_argument('--cover', help='Path to cover image file (for EPUB)')
    parser.add_argument('--epub-math', choices=['mathml','images','mathjax'], default='mathml', help='EPUB math handling strategy (default: mathml)')

    args = parser.parse_args()

    input_html = Path(args.input_html)
    if not input_html.exists():
        print(f"Input HTML not found: {input_html}")
        raise SystemExit(2)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not ensure_pandoc():
        print("Error: pandoc not found on PATH. Install pandoc to use this script.")
        raise SystemExit(3)

    cover = Path(args.cover) if args.cover else None
    if cover and not cover.exists():
        print(f"Warning: cover image not found: {cover}; continuing without cover")
        cover = None

    # Create temp workspace
    with tempfile.TemporaryDirectory(prefix='html_convert_') as td:
        tmpdir = Path(td)
        work_html = copy_assets_and_prepare(input_html, tmpdir)

        # Read prepared HTML and detect language. Prefer an explicit lang attribute.
        try:
            with open(work_html, 'r', encoding='utf-8') as _fh:
                _text = _fh.read()
        except Exception:
            _text = ''

        # Try to extract a lang attribute from the HTML (e.g. <html lang="en">)
        lang = None
        m = re.search(r'(?i)lang=["\']([a-zA-Z0-9_\-]+)["\']', _text)
        if m:
            lang = m.group(1).lower()
        else:
            # Fallback: detect Arabic-script characters and mark as Arabic
            arabic_re = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
            if arabic_re.search(_text):
                lang = 'ar'

        # Decide whether the document should be treated as RTL based on language
        RTL_LANGS = {'ar', 'he', 'fa', 'ur', 'ps'}
        is_rtl = bool(lang and lang.split('-', 1)[0] in RTL_LANGS)

        # Prepare an EPUB RTL stylesheet inside the tempdir only when document is RTL
        epub_stylesheet = None
        if is_rtl:
            rtl_css = ("html, body, p, div, li, span {direction: rtl !important; unicode-bidi: embed !important; text-align: right !important;}\n"
                       "img{max-width:100%;height:auto;}\n")
            try:
                epub_stylesheet_path = tmpdir / 'rtl.css'
                with open(epub_stylesheet_path, 'w', encoding='utf-8') as cssf:
                    cssf.write(rtl_css)
                epub_stylesheet = epub_stylesheet_path
            except Exception:
                epub_stylesheet = None

        # Search for an RTL reference.docx only when we need RTL DOCX styling
        reference_doc = None
        if is_rtl:
            candidates = [
                input_html.parent / 'reference-rtl.docx',
                Path.cwd() / 'reference-rtl.docx',
                Path(__file__).parent / 'reference-rtl.docx',
            ]
            for c in candidates:
                if c.exists():
                    reference_doc = c
                    break

        results = []
        for fmt in args.formats:
            out_name = input_html.stem + ('.docx' if fmt == 'docx' else '.epub')
            out_path = outdir / out_name
            ok = run_pandoc(
                work_html,
                out_path,
                fmt,
                title=args.title,
                author=args.author,
                cover=cover,
                epub_math=args.epub_math,
                lang=lang,
                reference_doc=reference_doc,
                epub_stylesheet=epub_stylesheet,
            )
            results.append((fmt, ok, out_path))

    # Report
    for fmt, ok, path in results:
        if ok:
            print(f"✅ {fmt.upper()} written: {path}")
        else:
            print(f"❌ {fmt.upper()} failed: {path}")


if __name__ == '__main__':
    main()
