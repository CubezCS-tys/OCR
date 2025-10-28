import os
import argparse
from pathlib import Path
from google import genai
from google.genai.errors import APIError
from dotenv import load_dotenv
import tempfile
from pypdf import PdfReader, PdfWriter
import json
from pathlib import Path as PPath
import shutil
import re

# Try to import local extractors (optional). They provide `process_pdf` functions.
try:
    import image_extractor_cv
except Exception:
    image_extractor_cv = None

try:
    import image_extractor_llm
except Exception:
    image_extractor_llm = None

try:
    import image_extractor_pil
except Exception:
    image_extractor_pil = None

# User-provided simple extractor (prefer this if present)
try:
    import image_extractor as custom_image_extractor
except Exception:
    custom_image_extractor = None

# Load environment variables from a .env file (if present)
load_dotenv()

def create_converter_prompt(filename):
    """
    Generates the detailed system prompt for the Gemini model.
    """
    return f"""
    You are an expert document structure analyst and HTML converter. Your task is to convert the provided PDF page titled '{filename}' into well-structured, readable HTML format.

    **IMPORTANT GUIDELINES:**

    1.  **Content Accuracy:**
        * Extract all text, numbers, and data EXACTLY as shown in the PDF
        * Do NOT translate numbers between Arabic/English numerals
        * Do NOT modify dates, measurements, or numeric values
        * Preserve the original language and script of all content

    2.  **Structure & Formatting:**
        * Analyze the document and use appropriate semantic HTML tags (H1, H2, H3, P, UL, OL, TABLE)
        * You may clean up spacing and line breaks for better HTML readability
        * Preserve the logical hierarchy and flow of the document
        * For tables: maintain the original structure, borders, and cell alignment

    3.  **Consistent Styling (REQUIRED):**
        * Use the SAME CSS stylesheet for every page you process
        * Do NOT change colors, font sizes, or spacing between different pages
        * All pages must have a uniform, professional appearance
        * Use the provided CSS template below without modification
        * DO NOT add <link href="https://fonts.googleapis.com/css2?family=Amiri:wght@400;700&display=swap" rel="stylesheet"> to the HTML. Assume the font is already available and just use whats already in the CSS layout.

    4.  **Language and Direction:**
        * For Arabic text: use `<html lang="ar" dir="rtl">`
        * Preserve Right-to-Left reading direction
        * Handle mixed LTR/RTL content appropriately

    5.  **Math/Equations:**
        * **Display Equations (Block):** Wrap in `$$...$$` within a `<div class="equation">`
        * **Inline Math:** Wrap in single `$...$` delimiters
        * Preserve mathematical notation accurately
        * Include MathJax CDN in `<head>` section

    6.  **Images and Figures:**
                * When you encounter an image, diagram, chart, or figure, DO NOT embed binary image data.
                * Instead insert a stable placeholder token exactly in this format:
                    `[IMAGE_PLACEHOLDER:IMAGE_ID:Short description of the image]`
                    where `IMAGE_ID` is a short identifier (e.g., `img_1`, `fig_2`) the post-processor will use to match extracted files.
                * Include relevant context like "Figure 1", "Chart showing...", "Diagram of..." etc.
                * Do NOT attempt to embed or extract the actual image data

    7.  **Standard CSS Template (Use on every page):**
    ```css
    <style>
        body {{
            font-family: 'Amiri', 'Traditional Arabic', serif;
            max-width: 800px;
            margin: 40px auto;
            padding: 20px;
            line-height: 1.8;
            background: #ffffff;
            color: #000000;
        }}
        h1, h2, h3 {{ 
            color: #2c3e50;
            margin-top: 1.5em;
            margin-bottom: 0.8em;
        }}
        h1 {{ font-size: 1.8em; border-bottom: 2px solid #3498db; padding-bottom: 0.3em; }}
        h2 {{ font-size: 1.5em; }}
        h3 {{ font-size: 1.2em; }}
        p {{ margin: 1em 0; }}
        table {{ 
            border-collapse: collapse; 
            width: 100%; 
            margin: 1.5em 0;
            direction: rtl;
        }}
        th, td {{ 
            border: 1px solid #000; 
            padding: 8px 12px; 
            text-align: center;
        }}
        th {{ background-color: #d3d3d3; font-weight: bold; }}
        .equation {{ 
            text-align: center; 
            margin: 1.5em 0; 
            padding: 1em;
            background: #f8f9fa;
        }}
        .image-placeholder {{
            border: 2px dashed #999;
            padding: 2em;
            margin: 1.5em 0;
            text-align: center;
            background: #f0f0f0;
            color: #666;
            font-style: italic;
        }}
        ul, ol {{ margin: 1em 0; padding-right: 2em; }}
        li {{ margin: 0.5em 0; }}
    </style>
    ```

    8.  **MathJax Configuration:**
    ```html
    <script>
        MathJax = {{
            tex: {{ inlineMath: [['$', '$']], displayMath: [['$$', '$$']] }},
            svg: {{ fontCache: 'global' }}
        }};
    </script>
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    ```

    9.  **Output Requirements:**
        * Produce a complete, self-contained HTML file (starting with `<!DOCTYPE html>`)
        * Include the exact CSS and MathJax configuration above
        * Extract ALL content from the page - ensure completeness
        * Output ONLY the HTML - no explanations or markdown code blocks

    **Balance:** Extract accurately while applying good document structure. Maintain perfect consistency in styling across all pages.
    """

def embed_images_inline(output_filepath: Path, manifest_path: Path, images_output_root: Path, pdf_stem: str, page_num: int = None):
    """
    Replace placeholder tokens in an HTML file with <figure> tags referencing extracted images.

    - output_filepath: Path to the generated HTML file
    - manifest_path: Path to the manifest JSON produced by the extractor
    - images_output_root: root dir where images were extracted
    - pdf_stem: stem name of the PDF (used for organizing copied images)
    - page_num: if provided, only embed images for that page (1-indexed)
    """
    try:
        if not manifest_path.exists():
            return
        with open(manifest_path, 'r', encoding='utf-8') as mf:
            manifest = json.load(mf)
    except Exception as e:
        print(f"[WARN] Could not load manifest {manifest_path}: {e}")
        return

    # Collect images for the given page or for whole document
    images = []
    if page_num is not None:
        page_manifest = next((p for p in manifest.get('pages', []) if p.get('page_num') == page_num), None)
        if page_manifest:
            images = page_manifest.get('images', []) or []
    else:
        for p in manifest.get('pages', []):
            for img in p.get('images', []):
                images.append(img)

    if not images:
        # nothing to embed
        return

    # Ensure destination dir exists inside output folder
    dest_dir = output_filepath.parent / 'extracted_images' / pdf_stem
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Map ids to copied paths and descriptions. Also build page-indexed lists and filename stems
    img_map = {}
    images_by_page = {}
    filename_map = {}
    all_images_ordered = []

    for img in images:
        raw_path = img.get('path') or img.get('filename') or ''
        src_path = Path(raw_path)
        if not src_path.exists():
            alt = images_output_root / raw_path
            if alt.exists():
                src_path = alt
        if not src_path.exists():
            # try using filename only inside images_output_root
            alt2 = images_output_root / Path(raw_path).name
            if alt2.exists():
                src_path = alt2
        if not src_path.exists():
            print(f"[WARN] Extracted image file not found: {raw_path}")
            continue
        try:
            dst = dest_dir / src_path.name
            shutil.copy2(src_path, dst)
        except Exception as e:
            print(f"[WARN] Could not copy image {src_path} -> {dst}: {e}")
            continue
        rel = os.path.relpath(dst, start=output_filepath.parent).replace(os.sep, '/')
        img_id = str(img.get('id') or img.get('filename') or src_path.stem)
        desc = img.get('description') or img.get('caption') or img_id
        # Strip auto-generated extractor captions like "Image extracted from page 16 (index 0)"
        try:
            if isinstance(desc, str) and re.search(r'Image extracted from page', desc, flags=re.IGNORECASE):
                desc = ''
        except Exception:
            pass
        entry = { 'rel': rel, 'desc': desc, 'page_num': img.get('page_num') or img.get('page') }
        img_map[img_id] = entry
        filename_map[Path(img.get('filename','')).stem] = entry
        pnum = entry['page_num']
        if pnum is None:
            # try to infer page from filename (common pattern)
            m = re.search(r'page_(\d+)', Path(rel).stem)
            pnum = int(m.group(1)) if m else None
            entry['page_num'] = pnum
        if pnum is not None:
            images_by_page.setdefault(int(pnum), []).append(entry)
        all_images_ordered.append(entry)

    # Read existing HTML
    try:
        with open(output_filepath, 'r', encoding='utf-8') as f:
            html = f.read()
    except Exception as e:
        print(f"[WARN] Could not read HTML to embed images: {e}")
        return

    # Replacement counters for ordered fallback
    page_counters = {p:0 for p in images_by_page.keys()}
    global_counter = 0

    # Flexible regex: allow optional surrounding brackets and capture id and desc
    pattern = re.compile(r"\[?IMAGE_PLACEHOLDER:([^:\]\s]+):([^\]\n<]*)\]?", flags=re.IGNORECASE)

    def _repl(match):
        nonlocal global_counter
        iid = match.group(1)
        # Try exact id match
        entry = img_map.get(iid)
        if entry is None:
            # Try filename stem match
            entry = filename_map.get(iid)
        if entry is None:
            # Try numeric/order mapping if page-specific
            if page_num is not None and int(page_num) in images_by_page:
                p = int(page_num)
                idx = page_counters.get(p, 0)
                if idx < len(images_by_page[p]):
                    entry = images_by_page[p][idx]
                    page_counters[p] = idx + 1
            # Global fallback: next in ordered list
            if entry is None and global_counter < len(all_images_ordered):
                entry = all_images_ordered[global_counter]
                global_counter += 1
        if not entry:
            # No mapping found — leave placeholder intact
            return match.group(0)
        # If description is empty or auto-caption was stripped, omit figcaption
        desc_val = entry.get('desc') or ''
        if desc_val:
            return f'<figure><img src="{entry["rel"]}" alt="{desc_val}" loading="lazy"/><figcaption>{desc_val}</figcaption></figure>'
        else:
            return f'<figure><img src="{entry["rel"]}" alt="" loading="lazy"/></figure>'

    new_html, n = pattern.subn(_repl, html)
    if n > 0:
        try:
            with open(output_filepath, 'w', encoding='utf-8') as f:
                f.write(new_html)
            print(f"✅ Replaced {n} image placeholder(s) with actual <figure> tags in {output_filepath.name}")
            return
        except Exception as e:
            print(f"[WARN] Could not write updated HTML after replacing placeholders: {e}")

    # Fallback: append an Extracted Figures section
    images_html = '\n<hr/>\n<h2>Extracted Figures</h2>\n<div class="extracted-images">\n'
    for entry in all_images_ordered:
        desc_val = entry.get('desc') or ''
        if desc_val:
            images_html += f'<figure><img src="{entry["rel"]}" alt="{desc_val}" loading="lazy"/><figcaption>{desc_val}</figcaption></figure>\n'
        else:
            images_html += f'<figure><img src="{entry["rel"]}" alt="" loading="lazy"/></figure>\n'
    images_html += '</div>\n'
    try:
        with open(output_filepath, 'a', encoding='utf-8') as f:
            f.write(images_html)
        print(f"✅ Appended {len(all_images_ordered)} extracted image(s) to {output_filepath.name}")
    except Exception as e:
        print(f"[WARN] Could not append extracted images to HTML: {e}")


def convert_pdf_folder(input_dir, output_dir, force=False, per_page=False):
    """
    Processes all PDF files in the input directory and saves the HTML output.
    If per_page is True, splits each PDF into pages and saves one HTML file per page.
    """
    print("Initializing Gemini Client...")
    try:
        # Ensure GEMINI_API_KEY is present (loaded from environment or .env)
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("Error: GEMINI_API_KEY not found in environment.\nPlease create a .env file with GEMINI_API_KEY=your_key or export the variable in your shell.")
            return

        # The genai client picks up the key from the environment automatically
        client = genai.Client()
        # Try to list available models for this project/account (best-effort) to help debugging
        try:
            available = client.models.list()
            print("Available models (first 10):", [m.name for m in available[:10]])
        except Exception:
            # Not critical — some client versions or permissions may not allow listing
            print("Could not list available models (permission or client limitation).")
    except Exception as e:
        print(f"Error initializing Gemini Client. Ensure GEMINI_API_KEY is set.\nDetails: {e}")
        return

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    pdf_files = list(input_path.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in the directory: {input_dir}")
        return

    print(f"Found {len(pdf_files)} PDF files to process.")

    for pdf_file in pdf_files:
        print(f"\n--- Processing: {pdf_file.name} ---")

        # Determine images output root (can be set via CLI flags)
        images_output_root = Path(getattr(convert_pdf_folder, 'images_output', 'extracted_images'))
        images_output_root.mkdir(parents=True, exist_ok=True)

        # Optionally run image extraction before LLM processing, so manifests/images exist
        if getattr(convert_pdf_folder, 'extract_images', False):
            # Prefer user-provided `image_extractor.py` if present
            if custom_image_extractor is not None:
                print(f"[INFO] Using custom image_extractor.py for {pdf_file.name}")
                try:
                    # custom extractor returns a manifest dict and writes files
                    custom_image_extractor.extract_images_from_pdf(str(pdf_file), str(images_output_root))
                except Exception as e:
                    print(f"[WARN] custom image_extractor failed for {pdf_file.name}: {e}")
            else:
                method = getattr(convert_pdf_folder, 'images_method', 'cv')
                print(f"[INFO] Image extraction requested (method={method})")
                try:
                    if method == 'cv' and image_extractor_cv is not None:
                        # image_extractor_cv.process_pdf(pdf_path: Path, output_dir: Path, dpi, score_thresh, force)
                        image_extractor_cv.process_pdf(pdf_file, images_output_root, dpi=300, score_thresh=0.7, force=force)
                    elif method == 'llm' and image_extractor_llm is not None:
                        # image_extractor_llm.process_pdf(pdf_path: Path, output_dir: Path, dpi, min_confidence, force)
                        image_extractor_llm.process_pdf(pdf_file, images_output_root, dpi=300, min_confidence=0.80, force=force)
                    elif method == 'pil' and image_extractor_pil is not None:
                        # image_extractor_pil.process_pdf(pdf_path: Path, output_dir: Path, dpi, min_confidence, force)
                        image_extractor_pil.process_pdf(pdf_file, images_output_root, dpi=300, min_confidence=0.80, force=force)
                    else:
                        print(f"[WARN] Requested image extraction method '{method}' unavailable. Missing module or invalid choice.")
                except Exception as e:
                    print(f"[WARN] Image extraction failed for {pdf_file.name}: {e}")

        if per_page:
            # Per-page processing: split PDF and process each page individually
            reader = PdfReader(str(pdf_file))
            num_pages = len(reader.pages)
            print(f"PDF has {num_pages} pages. Processing each page separately...")

            for page_num in range(num_pages):
                print(f"\n  Processing page {page_num + 1}/{num_pages}...")
                
                # Create a single-page PDF
                writer = PdfWriter()
                writer.add_page(reader.pages[page_num])
                
                # Write to a temporary file
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_pdf:
                    writer.write(tmp_pdf)
                    tmp_pdf_path = tmp_pdf.name
                
                # Determine output path for this page
                output_filename = f"{pdf_file.stem}_page_{page_num + 1}.html"
                output_filepath = output_path / output_filename
                
                # Skip if exists and newer (unless force)
                if output_filepath.exists() and not force:
                    try:
                        if output_filepath.stat().st_mtime >= pdf_file.stat().st_mtime:
                            print(f"  Skipping page {page_num + 1} — output exists: {output_filepath}")
                            os.unlink(tmp_pdf_path)
                            continue
                    except Exception:
                        pass
                
                # Upload the single-page PDF
                try:
                    uploaded_file = client.files.upload(file=tmp_pdf_path)
                    print(f"  Uploaded page {page_num + 1}. URI: {uploaded_file.uri}")
                except APIError as e:
                    print(f"  Error uploading page {page_num + 1}: {e}")
                    os.unlink(tmp_pdf_path)
                    continue
                
                # Generate HTML for this page
                system_prompt = create_converter_prompt(f"{pdf_file.name} - Page {page_num + 1}")
                
                try:
                    requested_model = 'gemini-2.5-flash'
                    response = client.models.generate_content(
                        model=requested_model,
                        contents=[system_prompt, uploaded_file],
                    )
                    
                    html_content = response.text.strip()
                    if html_content.startswith("```html"):
                        html_content = html_content[7:]
                    if html_content.endswith("```"):
                        html_content = html_content[:-3]
                    
                    with open(output_filepath, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    
                    print(f"  ✅ Saved page {page_num + 1} to: {output_filepath}")
                
                except APIError as e:
                    print(f"  Error generating content for page {page_num + 1}: {e}")
                finally:
                    client.files.delete(name=uploaded_file.name)
                    os.unlink(tmp_pdf_path)
                # If images were extracted earlier for this page, try to embed them via helper
                try:
                    manifest_path = images_output_root / f"{pdf_file.stem}_manifest.json"
                    if manifest_path.exists():
                        embed_images_inline(output_filepath, manifest_path, images_output_root, pdf_file.stem, page_num=page_num + 1)
                except Exception as e:
                    print(f"  [WARN] Could not embed images for page {page_num + 1}: {e}")
        
        else:
            # Original behavior: process entire PDF as one
            # Determine output path for this PDF
            output_filename = pdf_file.stem + ".html"
            output_filepath = output_path / output_filename

            # Skip if output exists and is newer than the PDF, unless force is True
            if output_filepath.exists() and not force:
                pdf_mtime = pdf_file.stat().st_mtime
                out_mtime = output_filepath.stat().st_mtime
                if out_mtime >= pdf_mtime:
                    print(f"Skipping {pdf_file.name} — output already exists and is up-to-date: {output_filepath}")
                    continue

            # 1. Upload the PDF File
            try:
                uploaded_file = client.files.upload(file=str(pdf_file))
                print(f"File uploaded successfully. URI: {uploaded_file.uri}")
            except APIError as e:
                print(f"Error uploading file {pdf_file.name}: {e}")
                continue
            
            # 2. Configure the Prompt and Model Call
            system_prompt = create_converter_prompt(pdf_file.name)
            
            try:
                # We use a powerful model like gemini-2.5-pro for complex OCR and structure analysis
                # Request a flash model. If your account doesn't have access, the service
                # can automatically route or fall back to another model (e.g., a 'pro' variant).
                requested_model = 'gemini-2.5-flash'
                #requested_model = 'gemini-2.5-pro'
                response = client.models.generate_content(
                    model=requested_model,
                    contents=[
                        system_prompt,
                        uploaded_file
                    ],
                )
                # Some service responses include which model actually handled the request.
                # Print that if available to help diagnose routing/fallback behavior.
                used_model = getattr(response, 'model', None) or getattr(response, 'model_name', None)
                if used_model:
                    print(f"Requested model: {requested_model} -> Used model: {used_model}")
                else:
                    print(f"Requested model: {requested_model} (server did not return the actual used model in the response)")
                
                # 3. Clean and Save the HTML Output
                html_content = response.text.strip()
                
                # Clean up potential markdown code fences that the model might wrap the HTML in
                if html_content.startswith("```html"):
                    html_content = html_content[7:]
                if html_content.endswith("```"):
                    html_content = html_content[:-3]
                
                with open(output_filepath, "w", encoding="utf-8") as f:
                    f.write(html_content)

                print(f"✅ Success! Saved HTML to: {output_filepath}")

                # Try to embed any extracted images (whole-PDF images)
                try:
                    manifest_path = images_output_root / f"{pdf_file.stem}_manifest.json"
                    if manifest_path.exists():
                        embed_images_inline(output_filepath, manifest_path, images_output_root, pdf_file.stem, page_num=None)
                except Exception as e:
                    print(f"[WARN] Could not embed extracted images into HTML: {e}")

            except APIError as e:
                print(f"Error generating content for {pdf_file.name}: {e}")
            finally:
                # 4. Delete the uploaded file from the service
                client.files.delete(name=uploaded_file.name)
                print("Cleanup complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated PDF to Structured HTML Converter using Gemini.")
    parser.add_argument("input_dir", help="Path to the folder containing PDF files.")
    parser.add_argument("--output_dir", default="output_html", help="Path to the folder where HTML files will be saved (default: output_html).")
    parser.add_argument("--force", action="store_true", help="Force re-processing of all PDFs, even if output HTML already exists.")
    parser.add_argument("--per-page", action="store_true", help="Process each PDF page separately, creating one HTML file per page.")
    parser.add_argument("--extract-images", action="store_true", help="Run image extraction and save images to disk (uses installed extractor modules).")
    parser.add_argument("--images-method", choices=["cv","llm","pil"], default="cv", help="Which image extraction method to use when --extract-images is set (cv=layoutparser, llm=LLM coordinate detection, pil=PIL cropping with LLM coords).")
    parser.add_argument("--images-output", default="extracted_images", help="Directory to save extracted images/manifests (default: extracted_images)")
    
    args = parser.parse_args()
    
    # Pass image extraction options through environment of convert function
    # Monkeypatch via attributes on the function (lightweight approach)
    convert_pdf_folder.extract_images = args.extract_images
    convert_pdf_folder.images_method = args.images_method
    convert_pdf_folder.images_output = args.images_output

    convert_pdf_folder(args.input_dir, args.output_dir, force=args.force, per_page=args.per_page)