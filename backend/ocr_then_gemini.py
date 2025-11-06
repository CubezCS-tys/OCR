#!/usr/bin/env python3
"""
Two-step OCR + Gemini conversion:
1. Extract text using Tesseract OCR (better for Arabic)
2. Send PDF + extracted text to Gemini for structured HTML conversion

This combines Tesseract's good Arabic OCR with Gemini's excellent structure analysis.
"""

import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import io
from pathlib import Path
import sys
import os
import google.genai as genai

# Import the converter prompt from main.py
sys.path.insert(0, str(Path(__file__).parent))
from main import create_converter_prompt
from image_extractor import extract_images_from_pdf

# Configuration
input_pdf = "/home/cubez/Desktop/OCR/input_pdfs/1749-000-022-008 (2).pdf"
output_dir = Path("/home/cubez/Desktop/OCR/output_ocr_gemini/")
output_dir.mkdir(parents=True, exist_ok=True)
images_dir = output_dir / "extracted_images"
images_dir.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("STEP 1: Extract Images from PDF")
print("=" * 70)

manifest = None
try:
    print(f"📷 Extracting images from PDF...")
    manifest = extract_images_from_pdf(input_pdf, str(images_dir))
    print(f"✅ Extracted {manifest['total_images_extracted']} images")
    print(f"💾 Images saved to: {images_dir}")
    print(f"💾 Manifest saved to: {images_dir / f'{Path(input_pdf).stem}_manifest.json'}")
except Exception as e:
    print(f"⚠️  Image extraction failed: {e}")
    print("Continuing without images...")
    manifest = {'total_images_extracted': 0, 'pages': []}

print("\n" + "=" * 70)
print("STEP 2: OCR Text Extraction with Tesseract")
print("=" * 70)

try:
    doc = fitz.open(input_pdf)
    total_pages = len(doc)
    print(f"📄 PDF: {Path(input_pdf).name}")
    print(f"📑 Total pages: {total_pages}\n")
    
    # Extract text page by page
    page_texts = []
    
    for page_num in range(total_pages):
        print(f"  Extracting text from page {page_num + 1}/{total_pages}...", end=" ")
        page = doc[page_num]
        
        # Convert page to image at 300 DPI
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))
        
        # Run Tesseract OCR
        page_text = pytesseract.image_to_string(img, lang='ara+eng')
        page_texts.append(page_text)
        
        print(f"✓ ({len(page_text)} chars)")
    
    doc.close()
    
    # Combine all text
    combined_ocr_text = '\n\n'.join([
        f"=== PAGE {i+1} ===\n{text}" 
        for i, text in enumerate(page_texts)
    ])
    
    # Save OCR text for reference
    ocr_file = output_dir / f"{Path(input_pdf).stem}_ocr.txt"
    with open(ocr_file, 'w', encoding='utf-8') as f:
        f.write(combined_ocr_text)
    
    print(f"\n✅ OCR completed: {len(combined_ocr_text):,} characters")
    print(f"💾 OCR text saved to: {ocr_file}")
    
except Exception as e:
    print(f"\n❌ OCR extraction failed: {e}")
    sys.exit(1)

print("\n" + "=" * 70)
print("STEP 3: Send PDF + OCR Text to Gemini for HTML Conversion")
print("=" * 70)

try:
    # Initialize Gemini client
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY not found in environment")
        print("Set it with: export GEMINI_API_KEY=your_key")
        sys.exit(1)
    
    client = genai.Client()
    print("✓ Gemini client initialized")
    
    # Upload the PDF
    print(f"📤 Uploading PDF to Gemini...")
    uploaded_file = client.files.upload(file=input_pdf)
    print(f"✓ PDF uploaded")
    
    # Create enhanced prompt with OCR text and image information
    base_prompt = create_converter_prompt(Path(input_pdf).name)
    
    # Build image information for the prompt
    image_info = ""
    if manifest and manifest.get('total_images_extracted', 0) > 0:
        image_info = "\n**EXTRACTED IMAGES (use placeholders):**\n\n"
        image_info += f"I have extracted {manifest['total_images_extracted']} images from the PDF.\n"
        image_info += "For each image, use the format: [IMAGE_PLACEHOLDER:IMAGE_ID:description]\n\n"
        for page_data in manifest['pages']:
            if page_data['images']:
                image_info += f"Page {page_data['page_num']}:\n"
                for img in page_data['images']:
                    img_id = img['id']
                    image_info += f"  - Use placeholder: [IMAGE_PLACEHOLDER:{img_id}:description of image]\n"
        image_info += "\nThe post-processor will replace these placeholders with actual <img> tags.\n"
    
    enhanced_prompt = f"""{base_prompt}

**IMPORTANT - OCR TEXT PROVIDED:**

I have already extracted the text from this PDF using Tesseract OCR. 
The extracted text is provided below. Use this text as a REFERENCE for accuracy,
especially for Arabic text and mathematical equations.

However, you should STILL:
1. Analyze the PDF's visual structure (headings, paragraphs, tables, lists)
2. Use the OCR text to verify and correct any text extraction
3. Apply proper HTML semantic structure based on the document layout
4. Detect the correct language and direction for each section

**EXTRACTED OCR TEXT (for reference):**

{combined_ocr_text[:10000]}

{'...(text truncated, total ' + str(len(combined_ocr_text)) + ' chars)' if len(combined_ocr_text) > 10000 else ''}

{image_info}

**YOUR TASK:**
Convert the PDF to well-structured HTML, using the OCR text above to ensure 
accurate text extraction (especially Arabic), while maintaining the document's 
visual structure and applying proper semantic HTML tags. Include the extracted 
images at their appropriate locations in the document.
"""
    
    # Call Gemini API
    print(f"🤖 Processing with Gemini (gemini-2.5-flash)...")
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[enhanced_prompt, uploaded_file],
    )
    
    # Extract HTML
    html_content = response.text.strip()
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    
    # Save HTML
    html_file = output_dir / f"{Path(input_pdf).stem}.html"
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # Clean up
    client.files.delete(name=uploaded_file.name)
    
    print(f"\n✅ HTML conversion completed!")
    print(f"💾 HTML saved to: {html_file}")
    print(f"📊 HTML size: {len(html_content):,} characters")
    
    print("\n" + "=" * 70)
    print("STEP 4: Embed Images into HTML")
    print("=" * 70)
    
    # Import the embed function from main.py
    from main import embed_images_inline
    
    # Embed images using the same approach as main.py
    manifest_file = images_dir / f"{Path(input_pdf).stem}_manifest.json"
    if manifest_file.exists():
        print(f"� Embedding {manifest['total_images_extracted']} images into HTML...")
        embed_images_inline(
            output_filepath=html_file,
            manifest_path=manifest_file,
            images_output_root=images_dir,
            pdf_stem=Path(input_pdf).stem
        )
    else:
        print("⚠️  No manifest found, skipping image embedding")
    
    print("\n" + "=" * 70)
    print("STEP 5: Convert HTML to Word (DOCX)")
    print("=" * 70)
    
    # Import conversion functions from convert_to_formats.py
    sys.path.insert(0, str(Path(__file__).parent))
    from convert_to_formats import ensure_pandoc, copy_assets_and_prepare, run_pandoc
    
    # Check if pandoc is installed
    if not ensure_pandoc():
        print("⚠️  Pandoc not installed. Skipping DOCX conversion.")
        print("   Install with: sudo apt install pandoc")
    else:
        try:
            import tempfile
            
            # Create temporary directory for pandoc processing
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)
                
                print(f"📄 Converting HTML to DOCX...")
                
                # Prepare HTML and copy assets to temp dir
                prepared_html = copy_assets_and_prepare(html_file, tmpdir_path, verbose=False)
                
                # Output DOCX path
                docx_file = output_dir / f"{Path(input_pdf).stem}.docx"
                
                # Run pandoc conversion
                run_pandoc(
                    input_html_path=prepared_html,
                    out_path=docx_file,
                    format='docx',
                    title=Path(input_pdf).stem,
                    lang='ar'  # Set to Arabic for proper RTL handling
                )
                
                print(f"✅ DOCX created: {docx_file}")
                print(f"📊 DOCX size: {docx_file.stat().st_size:,} bytes")
                
        except Exception as e:
            print(f"⚠️  DOCX conversion failed: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"✓ Images: {images_dir} ({manifest.get('total_images_extracted', 0)} images)")
    print(f"✓ OCR Text: {ocr_file}")
    print(f"✓ HTML Output: {html_file}")
    if ensure_pandoc() and (output_dir / f"{Path(input_pdf).stem}.docx").exists():
        print(f"✓ DOCX Output: {output_dir / f'{Path(input_pdf).stem}.docx'}")
    print("\nAll outputs saved to: " + str(output_dir))
    
except Exception as e:
    print(f"\n❌ Gemini processing failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
