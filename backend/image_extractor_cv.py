#!/usr/bin/env python3
"""
Hybrid Image Extractor - CV First, LLM Fallback
================================================

Uses computer vision (layoutparser) for fast, accurate detection.
Falls back to LLM only when CV fails.

Usage:
    python3 image_extractor_cv.py input.pdf output_images/
    python3 image_extractor_cv.py input_pdfs/ output_images/ --dpi 300
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple
import tempfile

import numpy as np
import cv2
from pdf2image import convert_from_path
from dotenv import load_dotenv
from pypdf import PdfReader

# Try to import layoutparser
try:
    # Workaround for PIL/Detectron2 compatibility
    from PIL import Image as PILImage
    if not hasattr(PILImage, "LINEAR") and hasattr(PILImage, "BILINEAR"):
        PILImage.LINEAR = PILImage.BILINEAR
    if not hasattr(PILImage, "NEAREST") and hasattr(PILImage, "Resampling"):
        PILImage.NEAREST = PILImage.Resampling.NEAREST
        PILImage.BILINEAR = PILImage.Resampling.BILINEAR
        PILImage.BICUBIC = PILImage.Resampling.BICUBIC
    
    import layoutparser as lp
    from layoutparser.models import Detectron2LayoutModel
    import torch
    HAS_LAYOUTPARSER = True
except ImportError:
    HAS_LAYOUTPARSER = False
    print("[WARNING] layoutparser not available. Install with: pip install 'layoutparser[detectron2]'")

load_dotenv()


def load_model(score_thresh: float = 0.7):
    """Load PubLayNet detector for figure/table detection."""
    if not HAS_LAYOUTPARSER:
        return None
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[MODEL] Using device: {device}")
    
    model = Detectron2LayoutModel(
        config_path="lp://PubLayNet/faster_rcnn_R_50_FPN_3x/config",
        label_map={0: "text", 1: "title", 2: "list", 3: "table", 4: "figure"},
        extra_config=["MODEL.ROI_HEADS.SCORE_THRESH_TEST", score_thresh],
        device=device,
    )
    return model


def dedupe_boxes(boxes: List[Tuple[int,int,int,int]], iou_thresh: float = 0.5) -> List[Tuple[int,int,int,int]]:
    """Simple NMS-like deduplication."""
    if not boxes:
        return boxes
    
    # Sort by area (descending)
    boxes = sorted(boxes, key=lambda b: (b[2]-b[0])*(b[3]-b[1]), reverse=True)
    kept = []
    
    for bx in boxes:
        x0, y0, x1, y1 = bx
        area_x = (x1-x0) * (y1-y0)
        ok = True
        
        for by in kept:
            X0, Y0, X1, Y1 = by
            # Calculate IoU
            inter_x0 = max(x0, X0)
            inter_y0 = max(y0, Y0)
            inter_x1 = min(x1, X1)
            inter_y1 = min(y1, Y1)
            
            iw = max(0, inter_x1 - inter_x0)
            ih = max(0, inter_y1 - inter_y0)
            inter = iw * ih
            
            area_y = (X1-X0) * (Y1-Y0)
            union = area_x + area_y - inter + 1e-6
            iou = inter / union
            
            if iou > iou_thresh:
                ok = False
                break
        
        if ok:
            kept.append(bx)
    
    return kept


def detect_figures_cv(img_bgr: np.ndarray, model, pad_px: int = 8) -> List[Tuple[int,int,int,int]]:
    """Use layoutparser to detect figure regions (charts, diagrams, photos - NOT tables)."""
    if model is None:
        return []
    
    h, w = img_bgr.shape[:2]
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    
    # Detect layout
    layout = model.detect(img_rgb)
    
    boxes = []
    for blk in layout:
        # ONLY extract figures, NOT tables (tables are already in HTML)
        if blk.type == "figure":
            x1, y1, x2, y2 = map(int, blk.block.coordinates)
            
            # Add padding
            x0 = max(0, x1 - pad_px)
            y0 = max(0, y1 - pad_px)
            x1 = min(w, x2 + pad_px)
            y1 = min(h, y2 + pad_px)
            
            if x1 > x0 and y1 > y0:
                boxes.append((x0, y0, x1, y1))
    
    # Deduplicate
    boxes = dedupe_boxes(boxes, iou_thresh=0.55)
    return boxes


def rasterize_page(pdf_path: Path, page_num: int, dpi: int = 300) -> np.ndarray:
    """Rasterize PDF page to numpy array."""
    pil_images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_num + 1,
        last_page=page_num + 1
    )
    if not pil_images:
        raise ValueError(f"Failed to rasterize page {page_num}")
    
    rgb = np.array(pil_images[0])
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return bgr


def is_actually_figure(crop: np.ndarray, model) -> bool:
    """
    Second-pass validation: analyze the crop itself to confirm it's a figure, not a table.
    Returns True if it's a real figure (chart/diagram/photo), False if it's a table.
    """
    if model is None:
        return True  # If no model, assume it's valid
    
    # Analyze the crop itself
    h, w = crop.shape[:2]
    
    # Skip if crop is too small
    if h < 50 or w < 50:
        return False
    
    # Convert to RGB for layoutparser
    crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    
    # Detect layout elements within the crop
    try:
        layout = model.detect(crop_rgb)
        
        # Count what's in the crop
        table_area = 0
        figure_area = 0
        total_area = h * w
        
        for blk in layout:
            blk_area = blk.block.area
            
            if blk.type == "table":
                table_area += blk_area
            elif blk.type == "figure":
                figure_area += blk_area
        
        # If more than 50% of the crop is detected as table, reject it
        if table_area > 0.5 * total_area:
            return False
        
        # If it has significant table content and no figures, reject it
        if table_area > 0.3 * total_area and figure_area < 0.1 * total_area:
            return False
        
        return True  # Otherwise, keep it as a figure
    
    except Exception as e:
        # If detection fails, be conservative and keep it
        return True


def save_crops(
    img_bgr: np.ndarray,
    boxes: List[Tuple[int,int,int,int]],
    output_dir: Path,
    pdf_stem: str,
    page_num: int,
    model  # Pass model for second-pass validation
) -> List[Dict[str, Any]]:
    """Save cropped regions as PNGs, with second-pass validation to filter out tables."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_images = []
    
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        crop = img_bgr[y0:y1, x0:x1].copy()
        
        # Quality check: not mostly white
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        non_white_ratio = np.sum(gray < 250) / gray.size
        if non_white_ratio < 0.05:
            print(f"      [SKIP] Region {i}: mostly empty")
            continue
        
        # SECOND-PASS VALIDATION: Check if it's actually a figure
        if not is_actually_figure(crop, model):
            print(f"      [SKIP] Region {i}: detected as table on second pass")
            continue
        
        filename = f"{pdf_stem}_page_{page_num + 1:03d}_fig_{i + 1}.png"
        filepath = output_dir / filename
        
        cv2.imwrite(str(filepath), crop)
        
        file_size_kb = filepath.stat().st_size / 1024
        
        saved_images.append({
            'filename': filename,
            'path': str(filepath),
            'id': f'fig_{i + 1}',
            'type': 'figure',
            'description': f'Figure {i + 1} from page {page_num + 1}',
            'coords_pixels': [x0, y0, x1, y1],
            'size_px': [crop.shape[1], crop.shape[0]],
            'size_kb': round(file_size_kb, 2),
            'method': 'cv_double_pass'
        })
        
        print(f"      ✅ {filename} ({crop.shape[1]}x{crop.shape[0]}px, {file_size_kb:.1f}KB)")
    
    return saved_images


def process_pdf(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 300,
    score_thresh: float = 0.7,
    force: bool = False
) -> Dict[str, Any]:
    """Process PDF with CV-based figure detection."""
    print(f"\n{'='*60}")
    print(f"Processing: {pdf_path.name}")
    print(f"{'='*60}")
    
    if not HAS_LAYOUTPARSER:
        print("ERROR: layoutparser not installed. Cannot proceed.")
        return {'error': 'layoutparser not available'}
    
    # Load model
    print("[MODEL] Loading layoutparser model...")
    model = load_model(score_thresh=score_thresh)
    
    # Count pages
    reader = PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    print(f"Total pages: {num_pages}")
    print(f"DPI: {dpi}, Score threshold: {score_thresh}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        'pdf_name': pdf_path.name,
        'pdf_stem': pdf_path.stem,
        'num_pages': num_pages,
        'dpi': dpi,
        'score_threshold': score_thresh,
        'method': 'layoutparser_cv',
        'pages': []
    }
    
    total_images = 0
    
    for page_num in range(num_pages):
        print(f"\n--- Page {page_num + 1}/{num_pages} ---")
        
        # Rasterize
        print(f"    [RASTER] Rendering at {dpi} DPI...")
        img_bgr = rasterize_page(pdf_path, page_num, dpi=dpi)
        print(f"    [RASTER] Page size: {img_bgr.shape[1]}x{img_bgr.shape[0]}px")
        
        # Detect figures
        print(f"    [CV] Detecting figures...")
        boxes = detect_figures_cv(img_bgr, model, pad_px=8)
        
        if not boxes:
            print(f"    [INFO] No figures detected")
            manifest['pages'].append({'page_num': page_num + 1, 'images': []})
            continue
        
        print(f"    [CV] Detected {len(boxes)} figure(s)")
        
        # Save crops (with second-pass validation)
        saved_images = save_crops(img_bgr, boxes, output_dir, pdf_path.stem, page_num, model)
        
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
        description="CV-based image extractor using layoutparser (fast & accurate)"
    )
    parser.add_argument('input', help="PDF file or directory")
    parser.add_argument('output_dir', nargs='?', default='extracted_images')
    parser.add_argument('--dpi', type=int, default=300, help="Rasterization DPI (default: 300)")
    parser.add_argument('--score-thresh', type=float, default=0.7, help="Detection confidence (default: 0.7)")
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
            process_pdf(pdf_path, output_dir, args.dpi, args.score_thresh, args.force)
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    main()
