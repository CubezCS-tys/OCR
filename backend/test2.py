#!/usr/bin/env python3
"""
Chandra OCR test script - Extract text from PDF using Chandra model
"""

import sys
from pathlib import Path
from PIL import Image
import fitz  # PyMuPDF
import io

from transformers import AutoModel, AutoProcessor
from chandra.model.hf import generate_hf
from chandra.model.schema import BatchInputItem
from chandra.output import parse_markdown

# Configuration
input_pdf = "/home/cubez/Desktop/OCR/input_pdfs/1749-000-022-008 (2).pdf"
output_dir = Path("/home/cubez/Desktop/OCR/output_chandra/")
output_dir.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("Chandra OCR - PDF Text Extraction")
print("=" * 70)

# Load model
print("📦 Loading Chandra model...")
try:
    model = AutoModel.from_pretrained("datalab-to/chandra").cuda()
    model.processor = AutoProcessor.from_pretrained("datalab-to/chandra")
    print("✅ Model loaded on CUDA")
except Exception as e:
    print(f"⚠️  CUDA not available, trying CPU...")
    try:
        model = AutoModel.from_pretrained("datalab-to/chandra")
        model.processor = AutoProcessor.from_pretrained("datalab-to/chandra")
        print("✅ Model loaded on CPU")
    except Exception as e2:
        print(f"❌ Failed to load model: {e2}")
        sys.exit(1)

# Open PDF
print(f"\n📄 Opening PDF: {Path(input_pdf).name}")
doc = fitz.open(input_pdf)
total_pages = len(doc)
print(f"📑 Total pages: {total_pages}\n")

# Process each page
all_text = []
all_markdown = []

for page_num in range(total_pages):
    print(f"Processing page {page_num + 1}/{total_pages}...", end=" ")
    
    try:
        # Convert PDF page to image
        page = doc[page_num]
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")
        pil_image = Image.open(io.BytesIO(img_bytes))
        
        # Create batch for Chandra
        batch = [
            BatchInputItem(
                image=pil_image,
                prompt_type="ocr_layout"
            )
        ]
        
        # Run Chandra OCR
        result = generate_hf(batch, model)[0]
        
        # Parse markdown output
        markdown = parse_markdown(result.raw)
        
        # Extract text
        page_text = result.raw
        all_text.append(f"=== PAGE {page_num + 1} ===\n{page_text}")
        all_markdown.append(f"<!-- Page {page_num + 1} -->\n{markdown}")
        
        print(f"✓ ({len(page_text)} chars)")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        all_text.append(f"=== PAGE {page_num + 1} ===\n[ERROR: {e}]")
        all_markdown.append(f"<!-- Page {page_num + 1} -->\n[ERROR: {e}]")

doc.close()

# Save raw text
text_file = output_dir / f"{Path(input_pdf).stem}_chandra.txt"
with open(text_file, 'w', encoding='utf-8') as f:
    f.write('\n\n'.join(all_text))

# Save markdown
markdown_file = output_dir / f"{Path(input_pdf).stem}_chandra.md"
with open(markdown_file, 'w', encoding='utf-8') as f:
    f.write('\n\n'.join(all_markdown))

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"✓ Raw Text: {text_file}")
print(f"✓ Markdown: {markdown_file}")
print(f"📊 Total characters: {sum(len(t) for t in all_text):,}")
print("\nDone!")

