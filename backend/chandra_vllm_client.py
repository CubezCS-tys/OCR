#!/usr/bin/env python3
"""
Chandra OCR via vLLM server - Extract text from PDF using Chandra model served by vLLM
"""

import sys
from pathlib import Path
from PIL import Image
import fitz  # PyMuPDF
import io
import base64
import requests
from io import BytesIO

# Configuration
VLLM_SERVER = "http://localhost:8000/v1/chat/completions"
input_pdf = "/home/cubez/Desktop/OCR/input_pdfs/1749-000-022-008 (2).pdf"
output_dir = Path("/home/cubez/Desktop/OCR/output_chandra/")
output_dir.mkdir(parents=True, exist_ok=True)

def image_to_base64(pil_image):
    """Convert PIL image to base64 string"""
    buffered = BytesIO()
    pil_image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"

def call_chandra_vllm(pil_image, prompt="Extract all text from this image with layout preservation."):
    """Call Chandra via vLLM server"""
    
    # Convert image to base64
    image_b64 = image_to_base64(pil_image)
    
    # Prepare request
    payload = {
        "model": "datalab-to/chandra",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_b64
                        }
                    }
                ]
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.0
    }
    
    # Call API
    response = requests.post(VLLM_SERVER, json=payload)
    response.raise_for_status()
    
    # Extract text
    result = response.json()
    return result['choices'][0]['message']['content']

print("=" * 70)
print("Chandra OCR via vLLM Server")
print("=" * 70)

# Check if vLLM server is running
print(f"🔌 Checking vLLM server at {VLLM_SERVER}...")
try:
    health_check = requests.get("http://localhost:8000/health", timeout=5)
    print("✅ vLLM server is running")
except Exception as e:
    print(f"❌ vLLM server not accessible: {e}")
    print("\nStart the server with:")
    print("  bash backend/start_chandra_vllm.sh")
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
    print(f"Processing page {page_num + 1}/{total_pages}...", end=" ", flush=True)
    
    try:
        # Convert PDF page to image
        page = doc[page_num]
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")
        pil_image = Image.open(io.BytesIO(img_bytes))
        
        # Call Chandra via vLLM
        page_text = call_chandra_vllm(
            pil_image,
            prompt="Extract all text from this document page, preserving layout and structure. Use markdown formatting."
        )
        
        all_text.append(f"=== PAGE {page_num + 1} ===\n{page_text}")
        all_markdown.append(f"<!-- Page {page_num + 1} -->\n{page_text}")
        
        print(f"✓ ({len(page_text)} chars)")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        all_text.append(f"=== PAGE {page_num + 1} ===\n[ERROR: {e}]")
        all_markdown.append(f"<!-- Page {page_num + 1} -->\n[ERROR: {e}]")

doc.close()

# Save raw text
text_file = output_dir / f"{Path(input_pdf).stem}_chandra_vllm.txt"
with open(text_file, 'w', encoding='utf-8') as f:
    f.write('\n\n'.join(all_text))

# Save markdown
markdown_file = output_dir / f"{Path(input_pdf).stem}_chandra_vllm.md"
with open(markdown_file, 'w', encoding='utf-8') as f:
    f.write('\n\n'.join(all_markdown))

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"✓ Raw Text: {text_file}")
print(f"✓ Markdown: {markdown_file}")
print(f"📊 Total characters: {sum(len(t) for t in all_text):,}")
print("\nDone!")
