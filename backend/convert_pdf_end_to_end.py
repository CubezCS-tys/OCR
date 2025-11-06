#!/usr/bin/env python3
"""End-to-end: PDF -> HTML + images -> DOCX + EPUB

This wrapper uses the existing `main.py` to convert PDF -> HTML (and optionally extract images),
then runs `convert_to_formats.py` to create DOCX and EPUB from the generated HTML.

Usage example:
    python3 backend/convert_pdf_end_to_end.py /path/to/doc.pdf --outdir out_folder --title "My Title" --author "Me"

Requirements:
- `backend/main.py` and `backend/convert_to_formats.py` present (they are in this repo).
- GEMINI_API_KEY in environment if `main.py` needs it.
- pandoc installed for conversions.
"""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys
import os
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None
import re

THIS_DIR = Path(__file__).resolve().parent
MAIN_PY = THIS_DIR / 'main.py'
CONVERT_PY = THIS_DIR / 'convert_to_formats.py'


def run(cmd, cwd=None, env=None):
    print(f"Running: {' '.join(cmd)}")
    # Stream output by default so the caller (user) sees progress in real time.
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        print(f"Failed to start process: {e}")
        return False
    # Print lines as they arrive
    for line in proc.stdout:
        print(line.rstrip())
    proc.wait()
    if proc.returncode != 0:
        print(f"ERROR: process exited with code {proc.returncode}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description='PDF -> HTML -> DOCX/EPUB end-to-end')
    parser.add_argument('input_dir', help='Path to a folder containing PDF files to process')
    parser.add_argument('--outdir', required=True, help='Output root folder to place per-document outputs')
    parser.add_argument('--title', help='Title metadata for converted outputs')
    parser.add_argument('--author', help='Author metadata for converted outputs')
    parser.add_argument('--epub-math', choices=['mathml','images','mathjax'], default='mathml', help='EPUB math handling strategy')
    parser.add_argument('--extract-images', action='store_true', help='Run image extraction step (recommended)')
    parser.add_argument('--verbose', action='store_true', help='Stream verbose output from subprocesses (main.py, pandoc)')
    parser.add_argument('--force', action='store_true', help='Force re-processing')
    parser.add_argument('--per-page', action='store_true', help='Force per-page processing (automatic for PDFs > 20 pages)')
    parser.add_argument('--max-workers', type=int, default=3, help='Number of concurrent API calls (default: 3, safe for rate limits)')
    parser.add_argument('--requests-per-minute', type=int, default=10, help='API rate limit in requests per minute (default: 10)')
    parser.add_argument('--seed', type=int, default=None, help='Random seed for deterministic LLM outputs (optional)')

    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Input folder not found or not a directory: {input_dir}")
        raise SystemExit(2)

    outroot = Path(args.outdir).resolve()
    outroot.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(input_dir.glob('*.pdf'))
    if not pdf_files:
        print(f"No PDF files found in the directory: {input_dir}")
        raise SystemExit(0)

    for pdf_path in pdf_files:
        print(f"\n=== Processing {pdf_path.name} ===")
        # Create per-document output folder
        doc_out = outroot / pdf_path.stem
        
        # Skip if already converted (unless --force flag is set)
        if not args.force and doc_out.exists():
            # Check if the output folder contains the expected HTML file
            expected_html = doc_out / (pdf_path.stem + '.html')
            if expected_html.exists():
                print(f"  ⏭️  Skipping {pdf_path.name} — already converted (output exists: {doc_out})")
                print(f"      Use --force to re-process this file")
                continue
        
        doc_out.mkdir(parents=True, exist_ok=True)

        # Use a fresh temp workspace per PDF
        with tempfile.TemporaryDirectory(prefix='pdf_e2e_') as td:
            tmpdir = Path(td)
            local_input = tmpdir / 'input'
            local_input.mkdir()
            shutil.copy2(pdf_path, local_input / pdf_path.name)

            tmp_output_html = tmpdir / 'output_html'
            tmp_output_html.mkdir()
            tmp_images_output = tmpdir / 'extracted_images'
            tmp_images_output.mkdir()

            # Build main.py command for this single file
            # Place options before the positional input directory to match expected arg ordering
            opts = []
            if args.force:
                opts.append('--force')
            if args.extract_images:
                opts.append('--extract-images')
                opts += ['--images-output', str(tmp_images_output)]

            # Add max-workers and rate limiting for concurrent processing
            opts += ['--max-workers', str(args.max_workers)]
            opts += ['--requests-per-minute', str(args.requests_per_minute)]
            
            # Add seed if provided (for deterministic outputs)
            if args.seed is not None:
                opts += ['--seed', str(args.seed)]
            
            # Pass verbose flag to main.py so ensure_html_lang_dir() shows debug output
            if args.verbose:
                opts.append('--verbose')

            # Decide whether to run per-page (safer for large PDFs / API limits)
            per_page = args.per_page  # Force per-page if user requested
            num_pages = None
            if not per_page:
                # Auto-enable for PDFs > 20 pages
                try:
                    reader = PdfReader(str(pdf_path))
                    num_pages = len(reader.pages)
                    if num_pages and num_pages > 20:
                        per_page = True
                except Exception:
                    num_pages = None

            if per_page:
                opts.append('--per-page')

            # assemble command: python main.py [opts] --output_dir tmp_output_html input_dir
            main_cmd = [sys.executable, str(MAIN_PY)] + opts + ['--output_dir', str(tmp_output_html), str(local_input)]

            # Stream output if verbose requested so user sees per-page progress from main.py
            ok = run(main_cmd) if args.verbose else run(main_cmd)
            if not ok:
                print(f"main.py failed for {pdf_path.name}; skipping.")
                continue

            # Find produced HTML for this PDF (prefer stem-based file)
            expected_html = tmp_output_html / (pdf_path.stem + '.html')
            if not expected_html.exists():
                html_files = list(tmp_output_html.glob('*.html'))
                if not html_files:
                    print(f"No HTML output found for {pdf_path.name}; skipping.")
                    continue
                expected_html = html_files[0]

            # If we processed per-page, combine page HTMLs into a single document HTML
            if per_page:
                # Natural sort by page number (extract digits from filename)
                def page_sort_key(path):
                    import re
                    match = re.search(r'_page_(\d+)', path.stem)
                    return int(match.group(1)) if match else 0
                
                page_files = sorted(tmp_output_html.glob(f"{pdf_path.stem}_page_*.html"), key=page_sort_key)
                if page_files:
                    head = ''
                    page_divs = []  # Store complete page divs with their own direction
                    head_re = re.compile(r'(?is)<head.*?>(.*?)</head>')
                    body_re = re.compile(r'(?is)<body.*?>(.*?)</body>')
                    html_tag_re = re.compile(r'(?is)<html([^>]*)>')
                    
                    # Default to first page's lang/dir for the document wrapper
                    document_lang = 'en'
                    document_dir = 'ltr'
                    
                    for i, pf in enumerate(page_files):
                        # Try multiple encodings to handle problematic characters
                        txt = None
                        for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
                            try:
                                txt = pf.read_text(encoding=encoding)
                                break
                            except UnicodeDecodeError:
                                continue
                        
                        if txt is None:
                            # Last resort: read as binary and decode with errors='replace'
                            txt = pf.read_bytes().decode('utf-8', errors='replace')
                            print(f"  ⚠️  Warning: Had to use error replacement for {pf.name}")
                        
                        # Extract lang/dir for THIS page
                        page_lang = None
                        page_dir = None
                        html_match = html_tag_re.search(txt)
                        if html_match:
                            html_attrs = html_match.group(1)
                            lang_match = re.search(r'lang=["\']?([a-z]{2})["\']?', html_attrs, re.IGNORECASE)
                            dir_match = re.search(r'dir=["\']?(ltr|rtl)["\']?', html_attrs, re.IGNORECASE)
                            if lang_match:
                                page_lang = lang_match.group(1)
                            if dir_match:
                                page_dir = dir_match.group(1)
                        
                        # First page sets document defaults
                        if i == 0:
                            m = head_re.search(txt)
                            head = m.group(1) if m else ''
                            document_lang = page_lang or 'en'
                            document_dir = page_dir or 'ltr'
                        
                        # Extract body content
                        m2 = body_re.search(txt)
                        body_content = m2.group(1) if m2 else txt
                        
                        # Wrap each page in a div with its own lang/dir attributes
                        # This preserves the direction of each individual page
                        page_attrs = []
                        if page_lang:
                            page_attrs.append(f'lang="{page_lang}"')
                        if page_dir:
                            page_attrs.append(f'dir="{page_dir}"')
                        
                        attrs_str = ' ' + ' '.join(page_attrs) if page_attrs else ''
                        page_div = f'<div class="page"{attrs_str}>\n{body_content}\n</div>'
                        page_divs.append(page_div)
                    
                    # Create combined HTML with document-level defaults and individual page divs
                    # Each page maintains its own direction via the div wrapper
                    combined = f'<!DOCTYPE html>\n<html lang="{document_lang}" dir="{document_dir}">\n<head>' + head + f'''
<style>
/* Page container styling - each page is independent and creates a page break */
.page {{
    page-break-after: always;
    break-after: page;
    margin: 0 auto 2em auto;
    padding: 2em;
    max-width: 21cm;
    min-height: 29.7cm;
    background: white;
    box-sizing: border-box;
}}

/* Remove page break after the last page */
.page:last-child {{
    page-break-after: avoid;
    break-after: avoid;
}}

/* Print-specific styling to ensure proper page breaks */
@media print {{
    .page {{
        margin: 0;
        padding: 2cm;
        max-width: 100%;
        min-height: 100vh;
        page-break-after: always;
        break-after: page;
    }}
    .page:last-child {{
        page-break-after: avoid;
        break-after: avoid;
    }}
}}

/* Screen view: add visual separation between pages */
@media screen {{
    .page {{
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        border: 1px solid #e0e0e0;
    }}
    .page:not(:last-child) {{
        margin-bottom: 2em;
    }}
}}
</style>
</head>\n<body>\n''' + '\n'.join(page_divs) + '\n</body>\n</html>'
                    final_html = doc_out / (pdf_path.stem + '.html')
                    final_html.write_text(combined, encoding='utf-8')
                else:
                    final_html = doc_out / expected_html.name
                    shutil.copy2(expected_html, final_html)
            else:
                final_html = doc_out / expected_html.name
                shutil.copy2(expected_html, final_html)

            # Copy extracted images: prefer images that were embedded into the HTML
            # (main.py's embed_images_inline copies files into tmp_output_html/extracted_images/{pdf_stem}).
            embedded_images_dir = tmp_output_html / 'extracted_images'
            if embedded_images_dir.exists():
                dest_images = doc_out / 'extracted_images'
                if dest_images.exists():
                    shutil.rmtree(dest_images)
                shutil.copytree(embedded_images_dir, dest_images)
            elif tmp_images_output.exists():
                # Fallback to raw extractor output
                dest_images = doc_out / 'extracted_images'
                if dest_images.exists():
                    shutil.rmtree(dest_images)
                shutil.copytree(tmp_images_output, dest_images)

            # Run conversion to formats, placing outputs into the document folder
            conv_cmd = [sys.executable, str(CONVERT_PY), str(final_html), '--outdir', str(doc_out), '--formats', 'docx', 'epub', '--epub-math', args.epub_math]
            if args.title:
                conv_cmd += ['--title', args.title]
            if args.author:
                conv_cmd += ['--author', args.author]

            # Stream conversion logs as well when verbose
            ok2 = run(conv_cmd) if args.verbose else run(conv_cmd)
            if not ok2:
                print(f"convert_to_formats.py failed for {pdf_path.name}; check logs.")
                continue

            print(f"Finished processing {pdf_path.name}. Outputs in: {doc_out}")


if __name__ == '__main__':
    main()
