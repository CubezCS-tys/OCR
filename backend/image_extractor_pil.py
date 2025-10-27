#!/usr/bin/env python3
"""
PIL-based Image Extractor (LLM coordinate detection + PIL cropping)

This module uses the LLM coordinate detector (if available) to get normalized
coords, then rasterizes pages with pdf2image (PIL) and crops/saves images using
Pillow (PIL) instead of OpenCV.

Usage:
    python3 image_extractor_pil.py input.pdf output_images/

This is intended as a drop-in alternative to `image_extractor_llm.py` that avoids
OpenCV entirely.
"""

import os
import json
import tempfile
from pathlib import Path
from typing import List, Dict, Any

from pdf2image import convert_from_path
from PIL import Image, ImageStat
from dotenv import load_dotenv
from pypdf import PdfReader

# We optionally reuse the LLM helper from image_extractor_llm if available
try:
    import image_extractor_llm
except Exception:
    image_extractor_llm = None

# Optional genai client usage is delegated to the LLM helper when present
load_dotenv()


def validate_coords(coords: List[float]) -> bool:
    if len(coords) != 4:
        return False
    x0, y0, x1, y1 = coords
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return False
    if (x1 - x0) < 0.02 or (y1 - y0) < 0.02:
        return False
    if (x1 - x0) > 0.98 or (y1 - y0) > 0.98:
        return False
    return True


def crop_and_save_pil(
    pil_img: Image.Image,
    regions: List[Dict[str, Any]],
    output_dir: Path,
    pdf_stem: str,
    page_num: int,
    min_confidence: float = 0.80
) -> List[Dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height = pil_img.size
    saved_images = []

    print(f"    [CROP-PIL] Page dimensions: {width}x{height}px")

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
        px0 = int(x0 * width)
        py0 = int(y0 * height)
        px1 = int(x1 * width)
        py1 = int(y1 * height)

        px0 = max(0, px0)
        py0 = max(0, py0)
        px1 = min(width, px1)
        py1 = min(height, py1)

        if px1 <= px0 or py1 <= py0:
            print(f"      [SKIP] {region.get('id', i)}: invalid pixel bounds")
            continue

        crop = pil_img.crop((px0, py0, px1, py1))

        # Quality check: not mostly white — use histogram
        gray = crop.convert('L')
        hist = gray.histogram()
        # Count pixels with value < 250
        non_white = sum(hist[:250])
        total = sum(hist)
        non_white_ratio = non_white / total if total > 0 else 0
        if non_white_ratio < 0.05:
            print(f"      [SKIP] {region.get('id', i)}: mostly empty (< 5% content)")
            continue

        img_id = region.get('id', f'img_{i}')
        filename = f"{pdf_stem}_page_{page_num + 1:03d}_{img_id}.png"
        filepath = output_dir / filename

        # Save as PNG
        crop.save(filepath, format='PNG')

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
            'size_px': [px1 - px0, py1 - py0],
            'size_kb': round(file_size_kb, 2)
        })

        print(f"      ✅ {filename} ({px1 - px0}x{py1 - py0}px, {file_size_kb:.1f}KB, conf={confidence:.2f})")

    return saved_images


def process_pdf(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 300,
    min_confidence: float = 0.80,
    force: bool = False
) -> Dict[str, Any]:
    """Process PDF using LLM coordinates and PIL cropping."""
    print(f"\n{'='*60}")
    print(f"Processing (PIL): {pdf_path.name}")
    print(f"{'='*60}")

    # We need the LLM helper to request coordinates
    if image_extractor_llm is None:
        print("[ERROR] image_extractor_llm module not available — cannot get LLM coordinates.")
        return {'error': 'missing_llm_helper'}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY not found in environment. LLM-based detection requires a key.")
        return {'error': 'missing_api_key'}

    client = None
    try:
        from google import genai
        client = genai.Client()
    except Exception as e:
        print(f"[ERROR] Could not initialize genai client: {e}")
        return {'error': 'genai_init_failed'}

    reader = PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    print(f"Total pages: {num_pages}")

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

        # Step 1: Get coordinates from LLM (reuse helper)
        llm_data = image_extractor_llm.get_regions_from_llm(client, pdf_path, page_num, pdf_path.stem)
        regions = llm_data.get('regions', []) if isinstance(llm_data, dict) else []

        if not regions:
            print(f"    [INFO] No regions detected")
            manifest['pages'].append({'page_num': page_num + 1, 'images': []})
            continue

        print(f"    [LLM] Detected {len(regions)} region(s)")

        # Step 2: Rasterize page to PIL
        pil_images = convert_from_path(
            str(pdf_path),
            dpi=dpi,
            first_page=page_num + 1,
            last_page=page_num + 1
        )
        if not pil_images:
            print(f"    [ERROR] Failed to rasterize page {page_num}")
            manifest['pages'].append({'page_num': page_num + 1, 'images': []})
            continue

        pil_img = pil_images[0]

        # Step 3: Crop and save using PIL
        saved_images = crop_and_save_pil(
            pil_img, regions, output_dir, pdf_path.stem, page_num, min_confidence
        )

        total_images += len(saved_images)
        manifest['pages'].append({
            'page_num': page_num + 1,
            'images': saved_images
        })

    manifest['total_images_extracted'] = total_images

    manifest_path = output_dir / f"{pdf_path.stem}_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"✅ Extracted {total_images} image(s) from {num_pages} page(s) (PIL)")
    print(f"📄 Manifest: {manifest_path}")
    print(f"{'='*60}\n")

    return manifest


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="PIL-based image extractor (LLM coords)")
    parser.add_argument('input', help="PDF file or directory")
    parser.add_argument('output_dir', nargs='?', default='extracted_images')
    parser.add_argument('--dpi', type=int, default=300, help="Rasterization DPI (default: 300)")
    parser.add_argument('--min-confidence', type=float, default=0.80, help="Min confidence (default: 0.80)")
    parser.add_argument('--force', action='store_true', help="Force re-processing")

    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)

    if input_path.is_file() and input_path.suffix.lower() == '.pdf':
        pdf_files = [input_path]
    elif input_path.is_dir():
        pdf_files = list(input_path.glob('*.pdf'))
    else:
        print(f"Error: {input_path} not valid")
        raise SystemExit(1)

    for pdf in pdf_files:
        try:
            process_pdf(pdf, output_dir, dpi=args.dpi, min_confidence=args.min_confidence, force=args.force)
        except Exception as e:
            print(f"Error processing {pdf}: {e}")
