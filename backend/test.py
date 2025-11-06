#!/usr/bin/env python3
"""
Simple text extraction from PDF using Tesseract OCR.
Extracts text page by page with Arabic + English support.
"""

import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import io
from pathlib import Path

# Configuration
input_pdf = "/home/cubez/Desktop/OCR/input_pdfs/1749-000-022-008 (2).pdf"
output_dir = Path("/home/cubez/Desktop/OCR/output/")
output_dir.mkdir(parents=True, exist_ok=True)

print(f"📄 Extracting text from: {Path(input_pdf).name}")
print(f"🔍 Using Tesseract OCR with Arabic + English")

try:
    doc = fitz.open(input_pdf)
    total_pages = len(doc)
    print(f"📑 Total pages: {total_pages}\n")
    
    all_text = []
    
    for page_num in range(total_pages):
        print(f"  Processing page {page_num + 1}/{total_pages}...", end=" ")
        page = doc[page_num]
        
        # Convert page to high-resolution image for better OCR
        # dpi=300 is good for OCR (higher = better quality but slower)
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))
        
        # Run Tesseract OCR with Arabic + English language support
        # You can change lang to just 'ara' or just 'eng' if needed
        page_text = pytesseract.image_to_string(img, lang='ara+eng')
        
        # Add page separator
        all_text.append(f"{'='*60}")
        all_text.append(f"PAGE {page_num + 1}")
        all_text.append(f"{'='*60}")
        all_text.append(page_text)
        all_text.append("\n")
        
        print(f"✓ ({len(page_text)} chars)")
    
    doc.close()
    
    # Combine all text
    combined_text = '\n'.join(all_text)
    
    # Save to file
    output_file = output_dir / f"{Path(input_pdf).stem}_extracted.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(combined_text)
    
    print(f"\n✅ Extraction completed!")
    print(f"📄 Total characters extracted: {len(combined_text):,}")
    print(f"� Output saved to: {output_file}")
    
    # Show preview
    print(f"\n{'='*60}")
    print("PREVIEW (first 500 characters):")
    print(f"{'='*60}")
    print(combined_text[:500])
    print("...")
    
except FileNotFoundError:
    print(f"\n❌ Error: PDF file not found at {input_pdf}")
    print("   Please check the file path.")
    
except Exception as e:
    print(f"\n❌ Error during extraction: {e}")
    import traceback
    traceback.print_exc()


