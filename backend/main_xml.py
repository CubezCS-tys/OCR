import os
import argparse
from pathlib import Path
from google import genai
from google.genai.errors import APIError
from dotenv import load_dotenv
import tempfile
from pypdf import PdfReader, PdfWriter

# Load environment variables from a .env file (if present)
load_dotenv()

def create_converter_prompt(filename):
    """
    Generates the detailed system prompt for the model to convert a PDF page
    titled `filename` into valid JATS XML (NISO JATS 1.3).
    """
    return f"""
    You are an expert document structure analyst and JATS XML converter. Your task is to convert the provided PDF page titled '{filename}' into well-structured, valid JATS XML.

    **IMPORTANT GUIDELINES:**

    1.  **Content Accuracy**
        * Extract all text, numbers, and data EXACTLY as shown in the PDF.
        * Do NOT translate numbers between Arabic/English numerals.
        * Do NOT modify dates, measurements, or numeric values.
        * Preserve the original language and script of all content.


    2.  **JATS Document Structure**
        Produce a complete, well-formed JATS XML document:
        ```xml
        <!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD v1.3 20210610//EN" "JATS-archivearticle1-3.dtd">
        <article xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article" xml:lang="AUTO">
          <front>
            <article-meta>
              <title-group>
                <article-title>Title extracted from PDF or '{filename}'</article-title>
              </title-group>
              <custom-meta-group>
                <custom-meta>
                  <meta-name>css</meta-name>
                  <meta-value><![CDATA[
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
                  ]]></meta-value>
                </custom-meta>
              </custom-meta-group>
            </article-meta>
          </front>
          <body>
            <!-- Structured content extracted from the PDF -->
          </body>
        </article>
        ```
    3.  **Sectioning & Hierarchy**
        * Map headings to nested `<sec>` blocks:
          - Level 1 heading → `<sec><title>…</title> … </sec>`
          - Level 2 heading → nested `<sec>` inside its parent `<sec>`, etc.
        * Normal text becomes `<p>…</p>`.
        * Preserve logical order and hierarchy exactly as inferred from the PDF.

    4.  **Lists**
        * Bulleted lists → `<list list-type="bullet">` with child `<list-item><p>…</p></list-item>`.
        * Numbered lists → `<list list-type="order">` with the same structure as above.
        * Definition lists (if identifiable) → `<def-list>` with `<def-item><term>…</term><def>…</def></def-item>`.

    5.  **Tables**
        * Represent tables as:
          ```xml
          <table-wrap id="tblN">
            <caption><title>IF PRESENT</title></caption>
            <table frame="all" rules="all">
              <thead>…</thead>  <!-- only if headers exist -->
              <tbody>
                <tr>
                  <td>…</td>
                  …
                </tr>
              </tbody>
            </table>
          </table-wrap>
          ```
        * Maintain original structure and alignment where possible via logical row/column order.
        * Do NOT include CSS or visual styling attributes beyond standard JATS attributes like `frame`/`rules`.

    6.  **Figures, Images, and Diagrams**
        * Insert placeholders for any non-text visuals:
          ```xml
          <fig id="figN">
            <caption>
              <title>Figure N. BRIEF TITLE IF PRESENT</title>
              <p>[IMAGE: Brief description of what the image shows]</p>
            </caption>
            <alt-text>Brief accessible description matching the placeholder.</alt-text>
          </fig>
          ```
        * Do NOT embed or reference actual image files.
        * If the PDF labels figures (e.g., “Figure 1”), preserve the numbering and wording.

    7.  **Mathematics**
        * **Display (block) equations** → `<disp-formula><tex-math>$$ … $$</tex-math></disp-formula>`
        * **Inline equations** → `<inline-formula><tex-math>$ … $</tex-math></inline-formula>`
        * Preserve mathematics accurately; do NOT simplify or alter notation.
        * Use TeX within `<tex-math>` exactly as extracted; do not add MathJax or other rendering scripts.

    8.  **Language and Direction**
        * For Arabic text or pages primarily in Arabic, set `xml:lang="ar"` on the `<article>` root (and on sub-elements if language switches).
        * Preserve Right-to-Left reading order naturally via the text itself; do not add HTML-specific attributes like `dir`.
        * For mixed LTR/RTL runs, preserve the characters as-is; if necessary, use Unicode bidi marks (U+200F RIGHT-TO-LEFT MARK, U+200E LEFT-TO-RIGHT MARK) inline to maintain correct ordering.

    9.  **Inline Semantics**
        * Use `<italic>`, `<bold>`, `<underline>`, `<monospace>` when the PDF clearly conveys such emphasis.
        * For hyperlinks that appear in the text, use `<ext-link xlink:href="URL">label</ext-link>` (only if the URL is explicitly present).

    10. **Footnotes and Endnotes (if present)**
        * Represent as:
          ```xml
          <fn-group>
            <fn id="fnN"><p>Footnote text…</p></fn>
          </fn-group>
          ```
        * Inline callouts may be represented with superscripted markers inside the relevant `<p>`.

    11. **Citations/References (if present on the page)**
        * If a references list exists on this page, wrap in `<ref-list>` with `<ref id="R1">…</ref>`.
        * If only in-text citations appear, keep them as plain text inside `<p>` unless full reference metadata is available.

    12. **Entity Handling**
        * Use UTF-8 characters directly; avoid HTML entities unless required for validity.
        * Escape XML-reserved characters: `&`, `<`, `>`, `"` appropriately.

    13. **Output Requirements**
        * Produce a complete, valid JATS XML document as a single output, starting with the JATS 1.3 DOCTYPE shown above.
        * Include the correct `xmlns:xlink` namespace on `<article>`.
        * Ensure the XML is **well-formed** (proper nesting, closed tags) and **valid** per JATS conventions used here.
        * Extract **ALL** content from the page—ensure completeness.
        * Output **ONLY** the XML—no explanations, no comments, no markdown code fences.

    **Balance:** Extract faithfully while applying correct JATS semantics. Use the simplest valid JATS structures that accurately reflect the page content.
    """


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

            except APIError as e:
                print(f"Error generating content for {pdf_file.name}: {e}")
            finally:
                # 4. Delete the uploaded file from the service
                client.files.delete(name=uploaded_file.name)
                print("Cleanup complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated PDF to Structured JATS XML Converter using Gemini.")
    parser.add_argument("input_dir", help="Path to the folder containing PDF files.")
    parser.add_argument("output_dir", nargs='?', default="output_jats", help="Path to the folder where JATS XML files will be saved (default: output_jats).")
    parser.add_argument("--force", action="store_true", help="Force re-processing of all PDFs, even if output HTML already exists.")
    parser.add_argument("--per-page", action="store_true", help="Process each PDF page separately, creating one HTML file per page.")
    
    args = parser.parse_args()
    
    convert_pdf_folder(args.input_dir, args.output_dir, force=args.force, per_page=args.per_page)