#!/usr/bin/env python3
"""
LLM-Based Image Extractor (Second Pass) - Coordinate-Based
===========================================================

Uses Gemini to identify image regions and return precise normalized coordinates.
Then crops locally using pdf2image and OpenCV for speed and reliability.

Per-page processing: splits PDF and processes each page individually.

Usage:
    python3 image_extractor_llm.py input.pdf output_images/
    python3 image_extractor_llm.py input_pdfs/ output_images/
    python3 image_extractor_llm.py input_pdfs/ output_images/ --dpi 300 --min-confidence 0.85
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any
import tempfile

import numpy as np
import cv2
from pdf2image import convert_from_path
from google import genai
from google.genai.errors import APIError
from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter

# Load environment variables
load_dotenv()


def create_image_detection_prompt(page_filename: str) -> str:
    """
    Precise system prompt for coordinate-based image detection.
    """
    return f"""You are a highly accurate image region detector for academic and technical documents.

Your task: Identify ALL figures, charts, diagrams, and images in PDF page '{page_filename}' and return PRECISE bounding box coordinates.

**CRITICAL ACCURACY REQUIREMENTS:**

1. **What IS an image (detect these):**
   - PIE CHARTS, BAR CHARTS, LINE GRAPHS (the actual graphical visualization)
   - PHOTOS, ILLUSTRATIONS, DIAGRAMS
   - TABLES rendered as graphics (not text tables)
   - SCIENTIFIC VISUALIZATIONS, MAPS, SCHEMATICS
   - Any VISUAL element that is NOT plain text

2. **What is NOT an image (EXCLUDE these):**
   - Plain text paragraphs (even if they describe a figure)
   - Figure captions like "شكل (1)" or "Figure 1" that are just text
   - Text below/above images that says what the image shows
   - Page numbers, headers, footers
   - Decorative borders or backgrounds

3. **Coordinate Rules - READ CAREFULLY:**
   - Bounding box must surround the VISUAL GRAPHIC ONLY (chart, photo, diagram)
   - Include the ENTIRE visual: don't cut off pie slices, bars, axes, labels ON the chart
   - INCLUDE figure numbers and captions if they are INSIDE a bordered box with the figure
   - EXCLUDE captions if they are separate text below/above the figure
   - For a pie chart: include the pie, legend, and any labels ATTACHED to the pie
   - For a bar chart: include axes, bars, axis labels, and title if part of the chart
   - DO NOT include the paragraph of text that describes what the figure shows

4. **Example - Pie Chart:**
   - ✅ INCLUDE: The pie graphic, legend, embedded labels
   - ❌ EXCLUDE: Text paragraph above saying "المسحية أن نسبة اللمسات..."
   - ❌ EXCLUDE: Separate caption below like "شكل (1) نسبة أداء الهجمة القاطعة..."

5. **Coordinate System:**
   - NORMALIZED coordinates: [x0, y0, x1, y1]
   - Values: 0.0 to 1.0
   - (x0, y0) = top-left corner of the VISUAL GRAPHIC
   - (x1, y1) = bottom-right corner of the VISUAL GRAPHIC
   - Relative to page dimensions

6. **Output Format (JSON ONLY):**
```json
{{
  "page": "{page_filename}",
  "regions": [
    {{
      "id": "chart_1",
      "type": "pie_chart|bar_chart|line_chart|diagram|photo|table",
      "coords": [x0, y0, x1, y1],
      "description": "Pie chart with legend showing percentages",
      "confidence": 0.95
    }}
  ]
}}
```

7. **Quality Standards:**
   - Confidence ≥ 0.80 for regions you return
   - x0 < x1 and y0 < y1
   - Minimum size: 5% of page (avoid tiny icons)
   - If NO visual graphics: return {{"page": "{page_filename}", "regions": []}}

8. **Examples:**

**Example - Page with pie chart and text caption:**
{{"page": "doc_page_3", "regions": [{{"id": "chart_1", "type": "pie_chart", "coords": [0.30, 0.35, 0.70, 0.60], "description": "Pie chart showing performance distribution", "confidence": 0.92}}]}}

**Example - Page with bar chart including axes:**
{{"page": "doc_page_5", "regions": [{{"id": "chart_1", "type": "bar_chart", "coords": [0.15, 0.25, 0.85, 0.65], "description": "Bar chart with axes and labels", "confidence": 0.90}}]}}

**Example - Text-only page:**
{{"page": "doc_page_1", "regions": []}}

**CRITICAL REMINDER:**
- Detect the VISUAL GRAPHIC (pie chart, bar chart, photo) NOT the text describing it
- Coordinates surround the GRAPHIC ONLY
- Output ONLY valid JSON, no explanations
"""


def validate_coords(coords: List[float]) -> bool:
    """Validate normalized coordinates."""
    if len(coords) != 4:
        return False
    x0, y0, x1, y1 = coords
    # Check range and ordering
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return False
    # Minimum size: 2% in each dimension
    if (x1 - x0) < 0.02 or (y1 - y0) < 0.02:
        return False
    # Maximum size: 98% (avoid full-page selections)
    if (x1 - x0) > 0.98 or (y1 - y0) > 0.98:
        return False
    return True


def get_regions_from_llm(
    client,
    pdf_path: Path,
    page_num: int,
    pdf_stem: str
) -> Dict[str, Any]:
    """
    Upload single-page PDF to LLM and get image region coordinates.
    """
    # Create single-page PDF
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_num])
    
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_pdf:
        writer.write(tmp_pdf)
        tmp_pdf_path = tmp_pdf.name
    
    try:
        # Upload
        print(f"    [API] Uploading page {page_num + 1}...")
        uploaded_file = client.files.upload(file=tmp_pdf_path)
        
        # Create prompt
        page_filename = f"{pdf_stem}_page_{page_num + 1}"
        system_prompt = create_image_detection_prompt(page_filename)
        
        # Call LLM
        print(f"    [API] Requesting coordinate detection...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[system_prompt, uploaded_file],
        )
        
        response_text = response.text.strip()
        
        # Clean markdown fences
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
            return data
        except json.JSONDecodeError as e:
            print(f"    [ERROR] JSON parse error: {e}")
            print(f"    [DEBUG] Response: {response_text[:500]}...")
            return {"regions": []}
    
    except APIError as e:
        print(f"    [ERROR] API error: {e}")
        return {"regions": []}
    
    finally:
        try:
            client.files.delete(name=uploaded_file.name)
        except:
            pass
        os.unlink(tmp_pdf_path)


def rasterize_page(pdf_path: Path, page_num: int, dpi: int = 300) -> np.ndarray:
    """
    Rasterize a single PDF page to numpy array (BGR format).
    """
    pil_images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_num + 1,
        last_page=page_num + 1
    )
    if not pil_images:
        raise ValueError(f"Failed to rasterize page {page_num}")
    
    # Convert PIL RGB -> OpenCV BGR
    rgb = np.array(pil_images[0])
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return bgr


def crop_and_save_regions(
    img_bgr: np.ndarray,
    regions: List[Dict[str, Any]],
    output_dir: Path,
    pdf_stem: str,
    page_num: int,
    min_confidence: float = 0.80
) -> List[Dict[str, Any]]:
    """
    Crop regions from rasterized page and save as PNGs.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    height, width = img_bgr.shape[:2]
    saved_images = []
    
    print(f"    [CROP] Page dimensions: {width}x{height}px")
    
    for i, region in enumerate(regions):
        confidence = region.get('confidence', 0.0)
        if confidence < min_confidence:
            print(f"      [SKIP] {region.get('id', i)}: confidence {confidence:.2f} < {min_confidence}")
            continue
        
        coords = region.get('coords', [])
        if not validate_coords(coords):
            print(f"      [SKIP] {region.get('id', i)}: invalid coords {coords}")
            continue
        
        x0, y0, x1, y1 = coords
        
        # Convert to pixels
        px0 = int(x0 * width)
        py0 = int(y0 * height)
        px1 = int(x1 * width)
        py1 = int(y1 * height)
        
        # Clamp to bounds
        px0 = max(0, px0)
        py0 = max(0, py0)
        px1 = min(width, px1)
        py1 = min(height, py1)
        
        if px1 <= px0 or py1 <= py0:
            print(f"      [SKIP] {region.get('id', i)}: invalid pixel bounds")
            continue
        
        # Crop
        crop = img_bgr[py0:py1, px0:px1].copy()
        
        # Quality check: not mostly white
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        non_white_ratio = np.sum(gray < 250) / gray.size
        if non_white_ratio < 0.05:
            print(f"      [SKIP] {region.get('id', i)}: mostly empty (< 5% content)")
            continue
        
        # Save
        img_id = region.get('id', f'img_{i}')
        filename = f"{pdf_stem}_page_{page_num + 1:03d}_{img_id}.png"
        filepath = output_dir / filename
        
        cv2.imwrite(str(filepath), crop)
        
        file_size_kb = filepath.stat().st_size / 1024
        
        saved_images.append({
            'filename': filename,
            'path': str(filepath),
            'id': img_id,
            'type': region.get('type', 'unknown'),
            'description': region.get('description', ''),
            'coords_normalized': coords,
            'coords_pixels': [px0, py0, px1, py1],
            'confidence': confidence,
            'size_px': [crop.shape[1], crop.shape[0]],  # width, height
            'size_kb': round(file_size_kb, 2)
        })
        
        print(f"      ✅ {filename} ({crop.shape[1]}x{crop.shape[0]}px, {file_size_kb:.1f}KB, conf={confidence:.2f})")
    
    return saved_images


def process_pdf(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 300,
    min_confidence: float = 0.80,
    force: bool = False
) -> Dict[str, Any]:
    """
    Process PDF: per-page coordinate detection + local cropping.
    """
    print(f"\n{'='*60}")
    print(f"Processing: {pdf_path.name}")
    print(f"{'='*60}")
    
    # Initialize client
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in .env")
    
    client = genai.Client()
    
    # Count pages
    reader = PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    print(f"Total pages: {num_pages}")
    print(f"DPI: {dpi}, Min confidence: {min_confidence}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        'pdf_name': pdf_path.name,
        'pdf_stem': pdf_path.stem,
        'num_pages': num_pages,
        'dpi': dpi,
        'min_confidence': min_confidence,
        'pages': []
    }
    
    total_images = 0
    
    for page_num in range(num_pages):
        print(f"\n--- Page {page_num + 1}/{num_pages} ---")
        
        # Step 1: Get coordinates from LLM
        llm_data = get_regions_from_llm(client, pdf_path, page_num, pdf_path.stem)
        regions = llm_data.get('regions', [])
        
        if not regions:
            print(f"    [INFO] No regions detected")
            manifest['pages'].append({'page_num': page_num + 1, 'images': []})
            continue
        
        print(f"    [LLM] Detected {len(regions)} region(s)")
        
        # Step 2: Rasterize page
        print(f"    [RASTER] Rendering at {dpi} DPI...")
        img_bgr = rasterize_page(pdf_path, page_num, dpi=dpi)
        
        # Step 3: Crop and save
        saved_images = crop_and_save_regions(
            img_bgr, regions, output_dir, pdf_path.stem, page_num, min_confidence
        )
        
        total_images += len(saved_images)
        manifest['pages'].append({
            'page_num': page_num + 1,
            'images': saved_images
        })
    
    manifest['total_images_extracted'] = total_images
    
    # Save manifest
    manifest_path = output_dir / f"{pdf_path.stem}_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"✅ Extracted {total_images} image(s) from {num_pages} page(s)")
    print(f"📄 Manifest: {manifest_path}")
    print(f"{'='*60}\n")
    
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="LLM coordinate-based image extractor (accurate, per-page processing)"
    )
    parser.add_argument('input', help="PDF file or directory")
    parser.add_argument('output_dir', nargs='?', default='extracted_images')
    parser.add_argument('--dpi', type=int, default=300, help="Rasterization DPI (default: 300)")
    parser.add_argument('--min-confidence', type=float, default=0.80, help="Min confidence (default: 0.80)")
    parser.add_argument('--force', action='store_true', help="Force re-processing")
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    
    # Collect PDFs
    if input_path.is_file() and input_path.suffix.lower() == '.pdf':
        pdf_files = [input_path]
    elif input_path.is_dir():
        pdf_files = list(input_path.glob('*.pdf'))
        if not pdf_files:
            print(f"No PDFs found in {input_path}")
            return
    else:
        print(f"Error: {input_path} not valid")
        return
    
    print(f"Found {len(pdf_files)} PDF(s)")
    
    for pdf_path in pdf_files:
        try:
            process_pdf(pdf_path, output_dir, args.dpi, args.min_confidence, args.force)
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    main()
