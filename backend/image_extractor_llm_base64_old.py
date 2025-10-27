#!/usr/bin/env python3
"""
LLM-Based Image Extractor (Second Pass)
=========================================

Uses Gemini's multimodal capabilities to directly extract and crop images/figures/charts
from PDF pages. The LLM does both identification AND extraction.

Per-page processing: splits PDF and processes each page individually for consistency.

Usage:
    python3 image_extractor_llm.py input.pdf output_images/
    python3 image_extractor_llm.py input_pdfs/ output_images/
    python3 image_extractor_llm.py input_pdfs/ output_images/ --force
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any
import tempfile
import base64

from google import genai
from google.genai.errors import APIError
from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter

# Load environment variables
load_dotenv()


def create_image_extraction_prompt(page_filename: str) -> str:
    """
    System prompt instructing the LLM to extract images directly.
    """
    return f"""You are an expert image extraction specialist. Your task is to identify and extract ALL figures, charts, diagrams, and images from the provided PDF page '{page_filename}'.

**YOUR TASK:**

1. **Identify Visual Elements:**
   - Figures (photos, illustrations, diagrams, schematics)
   - Charts (bar charts, line graphs, pie charts, scatter plots)
   - Diagrams (flowcharts, network diagrams, architectural diagrams)
   - Tables rendered as images (if they appear as graphics, not text)
   - Scientific visualizations, maps, screenshots
   
2. **DO NOT Extract:**
   - Page numbers, headers, footers
   - Decorative borders or page backgrounds
   - Text-only sections
   - Logos or small icons (unless they are the main content)

3. **Output Instructions:**
   - For EACH image/figure/chart you identify, provide:
     * A unique ID (fig_1, chart_1, diagram_1, etc.)
     * Type classification (figure/chart/diagram/table/photo)
     * Brief description (1 sentence, <80 chars)
     * The actual image data as base64-encoded PNG
   
4. **Output Format (JSON ONLY):**
```json
{{
  "page": "{page_filename}",
  "images": [
    {{
      "id": "fig_1",
      "type": "chart",
      "description": "Bar chart showing quarterly revenue trends",
      "format": "png",
      "data": "<base64-encoded-png-image-data>"
    }},
    {{
      "id": "diagram_1",
      "type": "diagram",
      "description": "System architecture flowchart",
      "format": "png",
      "data": "<base64-encoded-png-image-data>"
    }}
  ]
}}
```

5. **Quality Standards:**
   - Extract complete images (don't crop off labels/legends)
   - Maintain aspect ratio
   - Ensure sufficient resolution for readability
   - If a figure has a caption below it, you may include caption in description

6. **Special Cases:**
   - If NO images found: return {{"page": "{page_filename}", "images": []}}
   - If page is text-only: return {{"page": "{page_filename}", "images": []}}

**CRITICAL:** Output ONLY the JSON. No explanations, no markdown wrappers, just pure JSON.
"""


def extract_images_from_page(
    client,
    pdf_path: Path,
    page_num: int,
    output_dir: Path,
    pdf_stem: str,
    force: bool = False
) -> List[Dict[str, Any]]:
    """
    Process a single PDF page: upload to LLM, get extracted images, save them.
    
    Returns:
        List of saved image metadata
    """
    print(f"\n  Processing page {page_num + 1}...")
    
    # Create a single-page PDF using pypdf (same approach as main.py)
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_num])
    
    # Write to temporary file
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_pdf:
        writer.write(tmp_pdf)
        tmp_pdf_path = tmp_pdf.name
    
    saved_images = []
    
    try:
        # Upload the single-page PDF
        print(f"    [API] Uploading page {page_num + 1}...")
        uploaded_file = client.files.upload(file=tmp_pdf_path)
        print(f"    [API] Uploaded. URI: {uploaded_file.uri}")
        
        # Create prompt
        page_filename = f"{pdf_stem}_page_{page_num + 1}"
        system_prompt = create_image_extraction_prompt(page_filename)
        
        # Call LLM to extract images
        print(f"    [API] Requesting image extraction...")
        try:
            # Try stable model first, fallback to experimental if needed
            # gemini-1.5-flash is more stable, gemini-2.0-flash-exp has more features but can be overloaded
            response = client.models.generate_content(
                model='gemini-2.5-flash',  # More stable than 2.0-flash-exp
                contents=[system_prompt, uploaded_file],
            )
            
            response_text = response.text.strip()
            
            # Clean up markdown code fences if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            elif response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            response_text = response_text.strip()
            
            # Parse JSON
            try:
                data = json.loads(response_text)
                images = data.get('images', [])
                
                if not images:
                    print(f"    [INFO] No images found on page {page_num + 1}")
                else:
                    print(f"    [SUCCESS] LLM extracted {len(images)} image(s)")
                    
                    # Save each extracted image
                    for img_data in images:
                        img_id = img_data.get('id', f'img_{len(saved_images)}')
                        img_type = img_data.get('type', 'unknown')
                        description = img_data.get('description', '')
                        img_format = img_data.get('format', 'png')
                        base64_data = img_data.get('data', '')
                        
                        if not base64_data:
                            print(f"      [SKIP] {img_id}: No image data provided")
                            continue
                        
                        # Decode base64 and save
                        try:
                            img_bytes = base64.b64decode(base64_data)
                            filename = f"{pdf_stem}_page_{page_num + 1:03d}_{img_id}.{img_format}"
                            filepath = output_dir / filename
                            
                            # Ensure output directory exists
                            output_dir.mkdir(parents=True, exist_ok=True)
                            
                            with open(filepath, 'wb') as f:
                                f.write(img_bytes)
                            
                            # Get file size for reporting
                            file_size_kb = len(img_bytes) / 1024
                            
                            saved_images.append({
                                'filename': filename,
                                'path': str(filepath),
                                'id': img_id,
                                'type': img_type,
                                'description': description,
                                'format': img_format,
                                'size_kb': round(file_size_kb, 2)
                            })
                            
                            print(f"      ✅ Saved: {filename} ({file_size_kb:.1f} KB)")
                        
                        except Exception as e:
                            print(f"      [ERROR] Failed to decode/save {img_id}: {e}")
                            continue
            
            except json.JSONDecodeError as e:
                print(f"    [ERROR] Failed to parse LLM response as JSON: {e}")
                print(f"    [DEBUG] Response length: {len(response_text)} chars")
                # Try to save partial response for debugging
                if "data" in response_text and "iVBO" in response_text:
                    print(f"    [DEBUG] Response contains base64 image data but JSON is malformed")
                    print(f"    [DEBUG] This usually means the response was truncated or too large")
                    # Show first and last 200 chars to diagnose
                    print(f"    [DEBUG] Start: {response_text[:200]}")
                    print(f"    [DEBUG] End: ...{response_text[-200:]}")
                else:
                    print(f"    [DEBUG] Response preview: {response_text[:500]}...")
        
        except APIError as e:
            print(f"    [ERROR] API error during extraction: {e}")
    
    finally:
        # Cleanup
        try:
            client.files.delete(name=uploaded_file.name)
        except:
            pass
        os.unlink(tmp_pdf_path)
    
    return saved_images


def process_pdf(
    pdf_path: Path,
    output_dir: Path,
    force: bool = False
) -> Dict[str, Any]:
    """
    Process a PDF: extract images from all pages using LLM-based extraction.
    Per-page processing for consistency.
    
    Returns:
        Manifest dict with all extracted images
    """
    print(f"\n{'='*60}")
    print(f"Processing: {pdf_path.name}")
    print(f"{'='*60}")
    
    # Initialize Gemini client
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found. Set it in .env file.")
    
    client = genai.Client()
    
    # Count pages
    reader = PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    print(f"Total pages: {num_pages}")
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        'pdf_name': pdf_path.name,
        'pdf_stem': pdf_path.stem,
        'num_pages': num_pages,
        'pages': []
    }
    
    total_images = 0
    
    # Process each page individually
    for page_num in range(num_pages):
        print(f"\n--- Page {page_num + 1}/{num_pages} ---")
        
        saved_images = extract_images_from_page(
            client=client,
            pdf_path=pdf_path,
            page_num=page_num,
            output_dir=output_dir,
            pdf_stem=pdf_path.stem,
            force=force
        )
        
        total_images += len(saved_images)
        manifest['pages'].append({
            'page_num': page_num + 1,
            'images': saved_images
        })
    
    manifest['total_images_extracted'] = total_images
    
    # Save manifest JSON
    manifest_path = output_dir / f"{pdf_path.stem}_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"✅ Extracted {total_images} image(s) from {num_pages} page(s)")
    print(f"📄 Manifest saved: {manifest_path}")
    print(f"{'='*60}\n")
    
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="LLM-based image extractor: Gemini extracts images directly (per-page processing)."
    )
    parser.add_argument(
        'input',
        help="Path to a PDF file or directory containing PDFs"
    )
    parser.add_argument(
        'output_dir',
        nargs='?',
        default='extracted_images',
        help="Output directory for extracted images and manifest (default: extracted_images)"
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help="Force re-processing even if output exists"
    )
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    
    # Collect PDF files
    if input_path.is_file() and input_path.suffix.lower() == '.pdf':
        pdf_files = [input_path]
    elif input_path.is_dir():
        pdf_files = list(input_path.glob('*.pdf'))
        if not pdf_files:
            print(f"No PDF files found in {input_path}")
            return
    else:
        print(f"Error: {input_path} is not a valid PDF file or directory")
        return
    
    print(f"Found {len(pdf_files)} PDF file(s) to process")
    
    # Process each PDF
    for pdf_path in pdf_files:
        try:
            process_pdf(
                pdf_path=pdf_path,
                output_dir=output_dir,
                force=args.force
            )
        except Exception as e:
            print(f"\n❌ Error processing {pdf_path.name}: {e}")
            import traceback
            traceback.print_exc()
            continue


if __name__ == '__main__':
    main()
