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

            # Decide whether to run per-page (safer for large PDFs / API limits)
            per_page = False
            num_pages = None
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
                page_files = sorted(tmp_output_html.glob(f"{pdf_path.stem}_page_*.html"))
                if page_files:
                    head = ''
                    bodies = []
                    head_re = re.compile(r'(?is)<head.*?>(.*?)</head>')
                    body_re = re.compile(r'(?is)<body.*?>(.*?)</body>')
                    for i, pf in enumerate(page_files):
                        txt = pf.read_text(encoding='utf-8')
                        if i == 0:
                            m = head_re.search(txt)
                            head = m.group(1) if m else ''
                        m2 = body_re.search(txt)
                        bodies.append(m2.group(1) if m2 else txt)
                    combined = '<!DOCTYPE html>\n<html>\n<head>' + head + '</head>\n<body>\n' + '\n<hr/>\n'.join(bodies) + '\n</body>\n</html>'
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
