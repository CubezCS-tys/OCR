import os
import argparse
from pathlib import Path
from google import genai
from google.genai.errors import ClientError
from dotenv import load_dotenv
import tempfile
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
import json
from pathlib import Path as PPath
import shutil
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Semaphore
import time
from collections import deque

# User-provided image extractor: prefer `image_extractor.py` in the repo
try:
    import image_extractor as custom_image_extractor
except Exception:
    custom_image_extractor = None

# Load environment variables from a .env file (if present)
load_dotenv()


class RateLimiter:
    """
    Thread-safe rate limiter that ensures no more than max_requests per time_window.
    Uses a sliding window approach with deque to track request timestamps.
    """
    def __init__(self, max_requests=10, time_window=60):
        """
        Args:
            max_requests: Maximum number of requests allowed per time window
            time_window: Time window in seconds (default: 60 for per-minute limiting)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = Lock()
    
    def acquire(self):
        """
        Block until a request slot is available, respecting the rate limit.
        This method is thread-safe and will sleep if necessary to maintain the rate.
        """
        with self.lock:
            now = time.time()
            
            # Remove requests older than the time window
            while self.requests and self.requests[0] <= now - self.time_window:
                self.requests.popleft()
            
            # If we're at the limit, wait until the oldest request expires
            if len(self.requests) >= self.max_requests:
                sleep_time = self.requests[0] + self.time_window - now
                if sleep_time > 0:
                    time.sleep(sleep_time)
                # Clean up again after sleeping
                now = time.time()
                while self.requests and self.requests[0] <= now - self.time_window:
                    self.requests.popleft()
            
            # Record this request
            self.requests.append(now)


def read_pdf_with_fallback(pdf_path, verbose=False):
    """
    Attempt to read a PDF using multiple strategies with fallbacks.
    
    Strategy 1: pypdf with strict=False (lenient parsing)
    Strategy 2: PyMuPDF (fitz) - handles corrupted PDFs better
    Strategy 3: pypdf with strict=True (last resort)
    
    Args:
        pdf_path: Path to the PDF file
        verbose: If True, print debug information
    
    Returns:
        tuple: (reader_object, num_pages, reader_type)
        reader_type will be 'pypdf', 'pymupdf', or None if all failed
    
    Raises:
        Exception if all strategies fail
    """
    pdf_path = str(pdf_path)
    
    # Strategy 1: pypdf with lenient parsing (strict=False)
    try:
        if verbose:
            print(f"  [PDF-READ] Attempting pypdf (strict=False)...")
        reader = PdfReader(pdf_path, strict=False)
        num_pages = len(reader.pages)
        if verbose:
            print(f"  [PDF-READ] ✅ pypdf succeeded: {num_pages} pages")
        return (reader, num_pages, 'pypdf')
    except Exception as e:
        if verbose:
            print(f"  [PDF-READ] ⚠️  pypdf (strict=False) failed: {e}")
    
    # Strategy 2: PyMuPDF (better at handling corrupted PDFs)
    try:
        import fitz  # PyMuPDF
        if verbose:
            print(f"  [PDF-READ] Attempting PyMuPDF...")
        doc = fitz.open(pdf_path)
        num_pages = len(doc)
        if verbose:
            print(f"  [PDF-READ] ✅ PyMuPDF succeeded: {num_pages} pages")
        # Return a wrapper that mimics pypdf interface for page count
        # Note: We'll need to handle page extraction differently for PyMuPDF
        return (doc, num_pages, 'pymupdf')
    except ImportError:
        if verbose:
            print(f"  [PDF-READ] ⚠️  PyMuPDF not installed (pip install PyMuPDF)")
    except Exception as e:
        if verbose:
            print(f"  [PDF-READ] ⚠️  PyMuPDF failed: {e}")
    
    # Strategy 3: pypdf with strict=True (last resort)
    try:
        if verbose:
            print(f"  [PDF-READ] Attempting pypdf (strict=True) as last resort...")
        reader = PdfReader(pdf_path, strict=True)
        num_pages = len(reader.pages)
        if verbose:
            print(f"  [PDF-READ] ✅ pypdf (strict) succeeded: {num_pages} pages")
        return (reader, num_pages, 'pypdf')
    except Exception as e:
        if verbose:
            print(f"  [PDF-READ] ❌ pypdf (strict=True) failed: {e}")
    
    # All strategies failed
    raise Exception(f"All PDF reading strategies failed for {pdf_path}. "
                   f"The file may be severely corrupted. "
                   f"Try: 1) Repair PDF with external tool, 2) Install PyMuPDF (pip install PyMuPDF)")


def extract_page_as_pdf(pdf_reader, page_num, output_path, reader_type='pypdf', verbose=False):
    """
    Extract a single page from a PDF and save it as a separate PDF file.
    Handles both pypdf and PyMuPDF reader types.
    
    Args:
        pdf_reader: The PDF reader object (pypdf or PyMuPDF)
        page_num: Zero-indexed page number
        output_path: Path to save the extracted page
        reader_type: 'pypdf' or 'pymupdf'
        verbose: Print debug info
    
    Returns:
        str: Path to the created single-page PDF
    """
    if reader_type == 'pymupdf':
        # PyMuPDF extraction
        try:
            import fitz
            # Create a new PDF with just this page
            new_doc = fitz.open()
            new_doc.insert_pdf(pdf_reader, from_page=page_num, to_page=page_num)
            new_doc.save(output_path)
            new_doc.close()
            if verbose:
                print(f"  [PDF-EXTRACT] Extracted page {page_num + 1} using PyMuPDF")
            return output_path
        except Exception as e:
            raise Exception(f"PyMuPDF page extraction failed: {e}")
    
    else:  # pypdf
        try:
            writer = PdfWriter()
            writer.add_page(pdf_reader.pages[page_num])
            with open(output_path, 'wb') as f:
                writer.write(f)
            if verbose:
                print(f"  [PDF-EXTRACT] Extracted page {page_num + 1} using pypdf")
            return output_path
        except Exception as e:
            raise Exception(f"pypdf page extraction failed: {e}")


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

    4.  **Language and Direction (CRITICAL - MUST FOLLOW EXACTLY):**
        * **STEP 1 - DETECT PRIMARY LANGUAGE (Smart Detection):**
          - Count only VISIBLE TEXT content when deciding the primary language
          - **IGNORE these when counting:** HTML tags, CSS, JavaScript, numbers, punctuation, URLs, email addresses, DOIs, and citation/reference lists
          - **COUNT only actual prose:** headings, paragraphs, list items, table cells
          - If visible Arabic letters ≥ visible English letters → **Arabic-dominant**
          - If visible English letters > visible Arabic letters → **English-dominant**
          - Examples of what to ignore: "https://example.com", "email@domain.com", "Vol. 2022", "ISBN 978-..."
        
        * **STEP 2 - SET DOCUMENT DIRECTION:** Based on the detected PRIMARY language, set BOTH attributes on the `<html>` tag:
          - **FOR ARABIC-DOMINANT (>50% Arabic):** `<html lang="ar" dir="rtl">` — Reading flows RIGHT to LEFT
          - **FOR ENGLISH-DOMINANT (>50% English):** `<html lang="en" dir="ltr">` — Reading flows LEFT to RIGHT
        
        * **STEP 3 - ENFORCE ON BODY:** ALSO add the `dir` attribute to the `<body>` tag for maximum browser compatibility:
          - **FOR ARABIC-DOMINANT:** `<body dir="rtl">` — Content aligns to the right, lists indent from right
          - **FOR ENGLISH-DOMINANT:** `<body dir="ltr">` — Content aligns to the left, lists indent from left
        
        * **STEP 4 - HANDLE MIXED CONTENT (IMPORTANT):**
          - **PRIMARY STRATEGY - Use semantic containers for language switches:**
            * When you encounter a section in a different language than the document's primary language, wrap it in a `<div>` with explicit `dir` attribute
            * This creates clean language boundaries and proper rendering
          
          - **Examples of when to use `<div>` wrappers:**
            * **Arabic document with English abstract:**
              ```html
              <body dir="rtl">
                <h1>غلق الرهن في القانون الإنجليزي</h1>
                
                <!-- English section gets its own container -->
                <div dir="ltr">
                  <h2>Abstract</h2>
                  <p>The Foreclosure is considered as the most drastic remedy...</p>
                  <p>This remedy allows the mortgagee to acquire ownership...</p>
                  <p><strong>Keywords:</strong> Foreclosure, Redemption, Equitable Right.</p>
                </div>
                
                <!-- Back to Arabic (inherits RTL from body) -->
                <h2>ملخص البحث</h2>
                <p>يعد غلق الرهن في القانون الانجليزي...</p>
              </body>
              ```
            
            * **English document with Arabic quotations:**
              ```html
              <body dir="ltr">
                <p>The author states:</p>
                
                <!-- Arabic quote gets its own container -->
                <div dir="rtl">
                  <blockquote>
                    <p>النص العربي الكامل للاقتباس...</p>
                  </blockquote>
                </div>
                
                <!-- Back to English -->
                <p>This demonstrates the principle...</p>
              </body>
              ```
          
          - **When NOT to use containers:**
            * Single words or names embedded in text (e.g., "Dr. يونس صلاح الدين" in English sentence)
            * Short inline phrases (1-2 words) - Unicode BiDi algorithm handles these
            * Number/date formatting differences
          
          - **Alternative: Paragraph-level `dir` (use sparingly):**
            * Only if document alternates between languages every 1-2 paragraphs AND sections are too short for `<div>` wrappers
            * Example: `<p dir="ltr">This single English paragraph...</p>`
            * Prefer `<div>` wrappers for better semantic structure
          
          - **Decision tree:**
            ```
            Same language as document?
              → No dir attribute needed (inherits from <html>/<body>)
            
            Different language, 3+ consecutive paragraphs?
              → Use <div dir="...">...</div> wrapper
            
            Different language, 1-2 paragraphs only?
              → Add dir="..." to individual <p> tags
            
            Different language, single word/phrase?
              → No dir needed (Unicode BiDi handles it)
            ```
        
        * **STEP 5 - NO HARD ALIGNMENT (CRITICAL):**
          - **NEVER use `text-align:left` or `text-align:right` in inline styles**
          - Use `text-align:start` or `text-align:end` if needed (they respect `dir`)
          - Better yet: let the `dir` attribute control alignment automatically
          - The CSS template already handles list padding based on `dir`—don't override it
          - Hard left/right alignment fights the natural document direction
        
        * **STEP 6 - CONSISTENCY CHECK:**
          - Do NOT add `dir` attributes to every single paragraph unless necessary
          - Only add `dir` when switching languages within a mixed-language document
          - The document-level direction should handle the majority language
        
        * **VISUAL GUIDE:**
          - RTL (Arabic): Content flows ← this way, text aligns right, bullets appear on right side of lists
          - LTR (English): Content flows this way →, text aligns left, bullets appear on left side of lists

    5.  **Math/Equations (CRITICAL - Follow Exactly):**
        * **Math Direction Rule:** Mathematical equations themselves are ALWAYS left-to-right (LTR) by convention, but they must respect the page's overall direction
        * **For Arabic (RTL) pages with math:**
          - The PAGE remains `dir="rtl"` (Arabic text flows right-to-left)
          - Math equations stay in their natural LTR form: `$x = y + z$`
          - The equation will render correctly within the RTL context
          - DO NOT add `dir="ltr"` to every equation - let the math rendering handle it
          - Arabic text before/after equations flows RTL naturally
        * **Inline Math:** Wrap ALL inline mathematical expressions in single dollar signs: `$expression$`
          - Example: "The value of $x = 5$" or "equation $a^2 + b^2$"
          - In Arabic: "القيمة $x = 5$ في المعادلة" (RTL text, LTR math)
          - Do NOT use parentheses or brackets for math
          - ALWAYS use `$...$` for any mathematical symbol, variable, or expression within text
        * **Display Equations (Block):** Wrap in double dollar signs `$$...$$` and place in a `<div class="equation">` 
          - Example: `<div class="equation">$$x^2 + y^2 = z^2$$</div>`
          - The equation div will center in RTL or LTR context automatically
          - DO NOT add `dir="ltr"` to the equation div
        * **Important:** Math-heavy pages should still use the document's primary language direction
          - If an Arabic academic paper has many equations, keep `<html lang="ar" dir="rtl">`
          - If an English math textbook, keep `<html lang="en" dir="ltr">`
          - The presence of math does NOT change the document direction
        * Preserve ALL mathematical notation EXACTLY as shown in the PDF
        * Include MathJax configuration in `<head>` section (see template below)

    6.  **Images and Figures:**
                * When you encounter an image, diagram, chart, or figure, DO NOT embed binary image data.
                * Instead insert a stable placeholder token exactly in this format:
                    `[IMAGE_PLACEHOLDER:IMAGE_ID:Short description of the image]`
                    where `IMAGE_ID` is a short identifier (e.g., `img_1`, `fig_2`) the post-processor will use to match extracted files.
                * Include relevant context like "Figure 1", "Chart showing...", "Diagram of..." etc.
                * Do NOT attempt to embed or extract the actual image data

    7.  **Standard CSS Template (Use Exactly As-Is):**
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
        ul, ol {{ margin: 1em 0; }}
        li {{ margin: 0.5em 0; }}
        /* For RTL languages: add padding-right to lists */
        html[dir="rtl"] ul, html[dir="rtl"] ol {{ padding-right: 2em; padding-left: 0; }}
        /* For LTR languages: add padding-left to lists */
        html[dir="ltr"] ul, html[dir="ltr"] ol {{ padding-left: 2em; padding-right: 0; }}
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
        * Produce a complete, self-contained HTML file starting with `<!DOCTYPE html>`
        * **CRITICAL**: The opening `<html>` tag MUST include both `lang` and `dir` attributes:
          - For Arabic: `<html lang="ar" dir="rtl">`
          - For English: `<html lang="en" dir="ltr">`
        * **ALSO** add the `dir` attribute to the `<body>` tag for maximum compatibility:
          - For Arabic: `<body dir="rtl">`
          - For English: `<body dir="ltr">`
        * Include the exact CSS and MathJax configuration above
        * Extract ALL content from the page - ensure completeness
        * Output ONLY the HTML - no explanations or markdown code blocks
        * Before outputting, double-check that all guidelines have been followed, and that there are no errors or omissions.

    10. **Expected HTML Structure Example (Arabic with English sections):**
    ```html
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="utf-8">
        <style>
            /* CSS from template above */
        </style>
        <script>
            MathJax = {{
                tex: {{ inlineMath: [['$', '$']], displayMath: [['$$', '$$']] }},
                svg: {{ fontCache: 'global' }}
            }};
        </script>
        <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    </head>
    <body dir="rtl">
        <!-- Primary language: Arabic (flows RTL) -->
        <h1>غلق الرهن في القانون الإنجليزي</h1>
        <p>دراسة تحليلية مقارنة بالفقه الإسلامي والقانون المقارن</p>
        
        <!-- English section wrapped in <div dir="ltr"> -->
        <div dir="ltr">
            <h2>Abstract</h2>
            <p>The Foreclosure is considered as the most drastic remedy...</p>
            <p>This allows the mortgagee to acquire ownership...</p>
            <p><strong>Keywords:</strong> Foreclosure, Redemption, Equitable Right.</p>
        </div>
        
        <!-- Back to Arabic (inherits RTL from body) -->
        <h2>ملخص البحث</h2>
        <p>يعد غلق الرهن في القانون الانجليزي...</p>
        <ul>
            <li>النقطة الأولى</li>
            <li>النقطة الثانية</li>
        </ul>
        
        <!-- Mixed content with math -->
        <p>المعادلة $x = 5$ تظهر في النص العربي.</p>
        <div class="equation">$$x^2 + y^2 = z^2$$</div>
    </body>
    </html>
    ```
    
    **Expected HTML Structure Example (English):**
    ```html
    <!DOCTYPE html>
    <html lang="en" dir="ltr">
    <head>
        <meta charset="utf-8">
        <style>
            /* CSS from template above */
        </style>
        <script>
            MathJax = {{
                tex: {{ inlineMath: [['$', '$']], displayMath: [['$$', '$$']] }},
                svg: {{ fontCache: 'global' }}
            }};
        </script>
        <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    </head>
    <body dir="ltr">
        <h1>Page Title</h1>
        <p>English text flows from left to right.</p>
        <ul>
            <li>First point</li>
            <li>Second point</li>
        </ul>
        <p>Text with inline math like $x = 5$ goes here.</p>
        <div class="equation">$$x^2 + y^2 = z^2$$</div>
    </body>
    </html>
    ```

    **Balance:** Extract accurately while applying good document structure. Maintain perfect consistency in styling across all pages.
    """

def ensure_html_lang_dir(html_content, verbose=False):
    """
    Ensure HTML has proper lang and dir attributes based on content detection.
    This is a fallback in case the LLM doesn't add them.
    Adds dir attribute to both <html> and <body> tags for maximum compatibility.
    
    Detects the DOMINANT language by counting characters in VISIBLE CONTENT ONLY:
    - Strips <script>, <style>, HTML tags, URLs, emails before counting
    - If >50% Arabic characters in visible text: set RTL
    - Otherwise: set LTR
    
    Args:
        html_content: The HTML content to process
        verbose: If True, print debug information about detection and changes
    
    Returns:
        Modified HTML content with proper lang/dir attributes
    """
    # Step 1: Strip non-content elements to get accurate language detection
    content_only = html_content
    
    # Remove <script> blocks
    content_only = re.sub(r'<script[^>]*>.*?</script>', '', content_only, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove <style> blocks
    content_only = re.sub(r'<style[^>]*>.*?</style>', '', content_only, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove URLs (http/https)
    content_only = re.sub(r'https?://\S+', '', content_only, flags=re.IGNORECASE)
    
    # Remove email addresses
    content_only = re.sub(r'\S+@\S+\.\S+', '', content_only)
    
    # Remove HTML tags (keep text content only)
    content_only = re.sub(r'<[^>]+>', '', content_only)
    
    # Remove math notation (between $ signs - these are language-neutral)
    content_only = re.sub(r'\$\$.*?\$\$', '', content_only, flags=re.DOTALL)  # Display math
    content_only = re.sub(r'\$.*?\$', '', content_only)  # Inline math
    
    # Remove LaTeX commands (they look like English but aren't)
    content_only = re.sub(r'\\[a-z]+\{[^}]*\}', '', content_only, flags=re.IGNORECASE)
    content_only = re.sub(r'\\[a-z]+', '', content_only, flags=re.IGNORECASE)
    
    # Remove standalone numbers and mathematical operators
    content_only = re.sub(r'\b[\d\+\-\*/=<>]+\b', '', content_only)
    
    # Remove DOIs, ISSNs, ISBNs (common in citations)
    content_only = re.sub(r'\b(DOI|ISSN|ISBN)[\s:]*[\d\-X]+', '', content_only, flags=re.IGNORECASE)
    
    if verbose:
        print(f"  [LANG-DETECT] Stripped non-content (scripts, styles, URLs, tags)")
        print(f"  [LANG-DETECT] Content sample (first 200 chars): {content_only[:200]}")
    
    # Step 2: Count Arabic vs Latin characters in the cleaned content
    arabic_re = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
    latin_re = re.compile(r"[A-Za-z]")
    
    arabic_chars = len(arabic_re.findall(content_only))
    latin_chars = len(latin_re.findall(content_only))
    total_chars = arabic_chars + latin_chars
    
    # Step 3: Determine dominant language (require >50% for RTL)
    if total_chars == 0:
        # No text content, default to English
        lang = 'en'
        direction = 'ltr'
        dominant = 'unknown (no text found)'
    elif arabic_chars > latin_chars:
        # Arabic is dominant
        lang = 'ar'
        direction = 'rtl'
        dominant = f'Arabic ({arabic_chars}/{total_chars} = {100*arabic_chars/total_chars:.1f}%)'
    else:
        # English/Latin is dominant
        lang = 'en'
        direction = 'ltr'
        dominant = f'English ({latin_chars}/{total_chars} = {100*latin_chars/total_chars:.1f}%)'
    
    if verbose:
        print(f"  [LANG-DETECT] Visible content character count: {arabic_chars} Arabic, {latin_chars} Latin")
        print(f"  [LANG-DETECT] Dominant language: {dominant} → lang='{lang}', dir='{direction}'")
    
    # Check if lang/dir are already set on <html> tag
    has_html_lang = bool(re.search(r'(?i)<html[^>]*\slang=', html_content))
    has_html_dir = bool(re.search(r'(?i)<html[^>]*\sdir=', html_content))
    
    if verbose:
        print(f"  [LANG-DETECT] HTML already has lang={has_html_lang}, dir={has_html_dir}")
    
    # ALWAYS fix/replace lang and dir attributes to match detected language
    if re.search(r'(?i)<html', html_content):
        if has_html_lang:
            # Replace existing lang (might be wrong)
            html_content = re.sub(
                r'(?i)(<html[^>]*\s)lang=["\']?[a-z]{2}["\']?',
                rf'\1lang="{lang}"',
                html_content
            )
            if verbose:
                print(f"  [LANG-DETECT] Replaced lang with \"{lang}\" on <html> tag")
        else:
            # Add lang if missing
            html_content = re.sub(
                r'(?i)(<html)([^>]*)(>)',
                rf'\1 lang="{lang}"\2\3',
                html_content,
                count=1
            )
            if verbose:
                print(f"  [LANG-DETECT] Added lang=\"{lang}\" to <html> tag")
        
        if has_html_dir:
            # Replace existing dir (might be wrong)
            html_content = re.sub(
                r'(?i)(<html[^>]*\s)dir=["\']?(ltr|rtl)["\']?',
                rf'\1dir="{direction}"',
                html_content
            )
            if verbose:
                print(f"  [LANG-DETECT] Replaced dir with \"{direction}\" on <html> tag")
        else:
            # Add dir if missing
            html_content = re.sub(
                r'(?i)(<html)([^>]*)(>)',
                rf'\1 dir="{direction}"\2\3',
                html_content,
                count=1
            )
            if verbose:
                print(f"  [LANG-DETECT] Added dir=\"{direction}\" to <html> tag")
    
    # Also fix dir on <body> tag for extra enforcement
    has_body_dir = bool(re.search(r'(?i)<body[^>]*\sdir=', html_content))
    if re.search(r'(?i)<body', html_content):
        if has_body_dir:
            # Replace existing dir (might be wrong)
            html_content = re.sub(
                r'(?i)(<body[^>]*\s)dir=["\']?(ltr|rtl)["\']?',
                rf'\1dir="{direction}"',
                html_content
            )
            if verbose:
                print(f"  [LANG-DETECT] Replaced dir with \"{direction}\" on <body> tag")
        else:
            # Add dir if missing
            html_content = re.sub(
                r'(?i)(<body)([^>]*)(>)',
                rf'\1 dir="{direction}"\2\3',
                html_content,
                count=1
            )
            if verbose:
                print(f"  [LANG-DETECT] Added dir=\"{direction}\" to <body> tag")
    
    return html_content


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


def process_single_page(client, pdf_file, page_num, num_pages, pdf_reader, reader_type, output_path, force, images_output_root, print_lock, rate_limiter=None, verbose=False, seed=None):
    """
    Process a single PDF page: create temp PDF, upload, generate HTML, save, and embed images.
    Returns (page_num, success, output_filepath) for tracking.
    
    Args:
        pdf_reader: The PDF reader object (can be pypdf or PyMuPDF)
        reader_type: 'pypdf' or 'pymupdf' - indicates which reader was used
        rate_limiter: Optional RateLimiter instance to throttle API calls
        seed: Optional integer seed for deterministic LLM outputs
    """
    with print_lock:
        print(f"  📄 Starting page {page_num + 1}/{num_pages}...")
    
    # Create a temporary file for the single-page PDF
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_pdf:
        tmp_pdf_path = tmp_pdf.name
    
    # Extract single page using the appropriate method with fallback
    extraction_success = False
    try:
        extract_page_as_pdf(pdf_reader, page_num, tmp_pdf_path, reader_type, verbose)
        extraction_success = True
    except Exception as e:
        with print_lock:
            print(f"  ⚠️  Error extracting page {page_num + 1} with {reader_type}: {e}")
        
        # If pypdf failed, try PyMuPDF fallback for this page
        if reader_type == 'pypdf':
            try:
                import fitz
                with print_lock:
                    print(f"  🔄 Retrying page {page_num + 1} with PyMuPDF fallback...")
                
                # Open the original PDF with PyMuPDF just for this page
                pymupdf_doc = fitz.open(str(pdf_file))
                extract_page_as_pdf(pymupdf_doc, page_num, tmp_pdf_path, 'pymupdf', verbose)
                pymupdf_doc.close()
                extraction_success = True
                
                with print_lock:
                    print(f"  ✅ Page {page_num + 1} extracted successfully using PyMuPDF fallback")
            except Exception as fallback_error:
                with print_lock:
                    print(f"  ❌ PyMuPDF fallback also failed for page {page_num + 1}: {fallback_error}")
        
        if not extraction_success:
            return (page_num, False, None)
    
    # Determine output path for this page
    output_filename = f"{pdf_file.stem}_page_{page_num + 1}.html"
    output_filepath = output_path / output_filename
    
    # Skip if exists and newer (unless force)
    if output_filepath.exists() and not force:
        try:
            if output_filepath.stat().st_mtime >= pdf_file.stat().st_mtime:
                with print_lock:
                    print(f"  ⏭️  Skipping page {page_num + 1} — output exists: {output_filepath}")
                os.unlink(tmp_pdf_path)
                return (page_num, True, output_filepath)
        except Exception:
            pass
    
    # Rate limit before upload (if rate limiter provided)
    if rate_limiter:
        with print_lock:
            print(f"  ⏳ Page {page_num + 1}: Waiting for rate limit slot...")
        rate_limiter.acquire()
        with print_lock:
            print(f"  🚀 Page {page_num + 1}: Rate limit acquired, uploading...")
    
    # Upload the single-page PDF
    try:
        uploaded_file = client.files.upload(file=tmp_pdf_path)
    except APIError as e:
        with print_lock:
            print(f"  ❌ Error uploading page {page_num + 1}: {e}")
        os.unlink(tmp_pdf_path)
        return (page_num, False, None)
    
    # Generate HTML for this page
    system_prompt = create_converter_prompt(f"{pdf_file.name} - Page {page_num + 1}")
    
    try:
        requested_model = 'gemini-2.5-flash'
        # Build generation config with optional seed for deterministic outputs
        config = {}
        if seed is not None:
            config['seed'] = seed
        
        response = client.models.generate_content(
            model=requested_model,
            contents=[system_prompt, uploaded_file],
            config=config if config else None,
        )
        
        html_content = response.text.strip()
        if html_content.startswith("```html"):
            html_content = html_content[7:]
        if html_content.endswith("```"):
            html_content = html_content[:-3]
        
        # Sanitize any invalid UTF-8 characters from the LLM response
        # This prevents UnicodeDecodeError when reading the file later
        try:
            # Try to encode/decode to catch any issues
            html_content = html_content.encode('utf-8', errors='replace').decode('utf-8')
        except Exception as e:
            with print_lock:
                print(f"  ⚠️  Warning: Had to sanitize UTF-8 characters on page {page_num + 1}: {e}")
        
        # Ensure HTML has proper lang/dir attributes (fallback if LLM didn't add them)
        if verbose:
            with print_lock:
                print(f"  [DEBUG] Checking lang/dir attributes for page {page_num + 1}...")
        html_content = ensure_html_lang_dir(html_content, verbose=verbose)
        
        with open(output_filepath, "w", encoding="utf-8", errors='replace') as f:
            f.write(html_content)
        
        with print_lock:
            print(f"  ✅ Saved page {page_num + 1}/{num_pages} to: {output_filepath.name}")
        
        success = True
    
    except APIError as e:
        with print_lock:
            print(f"  ❌ Error generating content for page {page_num + 1}: {e}")
        success = False
    finally:
        client.files.delete(name=uploaded_file.name)
        os.unlink(tmp_pdf_path)
    
    # If images were extracted earlier for this page, try to embed them via helper
    if success:
        try:
            manifest_path = images_output_root / f"{pdf_file.stem}_manifest.json"
            if manifest_path.exists():
                embed_images_inline(output_filepath, manifest_path, images_output_root, pdf_file.stem, page_num=page_num + 1)
        except Exception as e:
            with print_lock:
                print(f"  ⚠️  Could not embed images for page {page_num + 1}: {e}")
    
    return (page_num, success, output_filepath)


def convert_pdf_folder(input_dir, output_dir, force=False, per_page=False, max_workers=3, requests_per_minute=10, verbose=False, seed=None):
    """
    Processes all PDF files in the input directory and saves the HTML output.
    If per_page is True, splits each PDF into pages and processes them concurrently.
    max_workers: number of concurrent LLM API calls (default: 3, safe for rate limits)
    requests_per_minute: API rate limit (default: 10)
    seed: Optional integer seed for deterministic LLM outputs
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
            # Only support the project's `image_extractor.py` implementation (user-provided)
            if custom_image_extractor is not None:
                print(f"[INFO] Using custom image_extractor.py for {pdf_file.name}")
                try:
                    # custom extractor should export extract_images_from_pdf(pdf_path, output_dir)
                    custom_image_extractor.extract_images_from_pdf(str(pdf_file), str(images_output_root))
                except Exception as e:
                    print(f"[WARN] custom image_extractor failed for {pdf_file.name}: {e}")
            else:
                print(f"[WARN] --extract-images requested but no local 'image_extractor.py' found; skipping image extraction for {pdf_file.name}.")

        if per_page:
            # Per-page processing: use robust PDF reader with fallbacks
            try:
                pdf_reader, num_pages, reader_type = read_pdf_with_fallback(pdf_file, verbose=verbose)
                print(f"✅ Successfully opened PDF with {reader_type}: {num_pages} pages")
            except Exception as e:
                print(f"[ERROR] All PDF reading strategies failed: {e}")
                print(f"[SKIP] Skipping {pdf_file.name}")
                continue
            
        if per_page:
            # This condition now checks the updated per_page value (might be False from fallback)
            print(f"PDF has {num_pages} pages. Processing with {max_workers} workers ({requests_per_minute} req/min rate limit)...")
            
            print_lock = Lock()  # Thread-safe printing
            
            # Create rate limiter: configurable requests per minute
            rate_limiter = RateLimiter(max_requests=requests_per_minute, time_window=60)
            
            # Calculate estimated time
            estimated_minutes = (num_pages / requests_per_minute) + 1  # +1 for processing overhead
            print(f"⏱️  Estimated time: ~{int(estimated_minutes)} minutes (rate limited to {requests_per_minute} requests/min)")
            
            # Submit all pages to thread pool
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for page_num in range(num_pages):
                    future = executor.submit(
                        process_single_page,
                        client, pdf_file, page_num, num_pages, pdf_reader, reader_type,
                        output_path, force, images_output_root, print_lock, rate_limiter, verbose, seed
                    )
                    futures.append((page_num, future))  # Store page_num with future for ordering
                
                # Track progress as pages complete (in completion order for live feedback)
                completed = 0
                failed = 0
                start_time = time.time()
                results = []
                
                # Collect all results
                for page_num, future in futures:
                    try:
                        result_page_num, success, output_filepath = future.result()
                        results.append((result_page_num, success, output_filepath))
                        completed += 1
                        if not success:
                            failed += 1
                        elapsed = time.time() - start_time
                        avg_per_page = elapsed / completed if completed > 0 else 0
                        remaining = num_pages - completed
                        eta_seconds = remaining * avg_per_page
                        eta_minutes = int(eta_seconds / 60)
                        with print_lock:
                            print(f"\n📊 Progress: {completed}/{num_pages} pages completed ({failed} failed) | ETA: ~{eta_minutes}m")
                    except Exception as e:
                        failed += 1
                        with print_lock:
                            print(f"  ❌ Unexpected error processing page: {e}")
                
                # Sort results by page number to ensure correct order
                results.sort(key=lambda x: x[0])
            
            total_time = time.time() - start_time
            print(f"\n✅ Finished processing {pdf_file.name}: {completed - failed}/{num_pages} pages succeeded in {int(total_time/60)}m {int(total_time%60)}s")
        
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
                
                # Build generation config with optional seed for deterministic outputs
                config = {}
                if seed is not None:
                    config['seed'] = seed
                
                response = client.models.generate_content(
                    model=requested_model,
                    contents=[
                        system_prompt,
                        uploaded_file
                    ],
                    config=config if config else None,
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
                
                # Ensure HTML has proper lang/dir attributes (fallback if LLM didn't add them)
                if verbose:
                    print(f"  [DEBUG] Checking lang/dir attributes for whole-document mode...")
                html_content = ensure_html_lang_dir(html_content, verbose=verbose)
                
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
    parser.add_argument("--extract-images", action="store_true", help="Run image extraction and save images to disk (uses local image_extractor.py).")
    parser.add_argument("--images-output", default="extracted_images", help="Directory to save extracted images/manifests (default: extracted_images)")
    parser.add_argument("--max-workers", type=int, default=3, help="Number of concurrent API calls (default: 3, safe for rate limits)")
    parser.add_argument("--requests-per-minute", type=int, default=10, help="API rate limit in requests per minute (default: 10)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for deterministic LLM outputs (optional, useful for reproducibility)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging for debugging lang/dir detection and other processing steps")
    
    args = parser.parse_args()
    
    # Pass image extraction option through environment of convert function
    # Monkeypatch via attributes on the function (lightweight approach)
    convert_pdf_folder.extract_images = args.extract_images
    convert_pdf_folder.images_output = args.images_output

    convert_pdf_folder(args.input_dir, args.output_dir, force=args.force, per_page=args.per_page, 
                       max_workers=args.max_workers, requests_per_minute=args.requests_per_minute, verbose=args.verbose, seed=args.seed)