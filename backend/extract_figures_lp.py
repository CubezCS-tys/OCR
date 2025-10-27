import os
import sys
from typing import List, Tuple

import cv2
import numpy as np
from pdf2image import convert_from_path

# Workaround for PIL/Detectron2 compatibility:
# Some Pillow versions moved/resolved old resampling constants (e.g., LINEAR).
# Detectron2's code (used by layoutparser) may reference Image.LINEAR which
# doesn't exist in newer Pillow releases. Provide safe aliases so detectron2
# can import without raising AttributeError.
try:
    from PIL import Image as PILImage
    # Alias LINEAR -> BILINEAR if LINEAR missing
    if not hasattr(PILImage, "LINEAR") and hasattr(PILImage, "BILINEAR"):
        PILImage.LINEAR = PILImage.BILINEAR
    # Ensure common aliases for newer Pillow versions that introduced Resampling enum
    if not hasattr(PILImage, "NEAREST") and hasattr(PILImage, "Resampling"):
        PILImage.NEAREST = PILImage.Resampling.NEAREST
    if not hasattr(PILImage, "BILINEAR") and hasattr(PILImage, "Resampling"):
        PILImage.BILINEAR = PILImage.Resampling.BILINEAR
    if not hasattr(PILImage, "BICUBIC") and hasattr(PILImage, "Resampling"):
        PILImage.BICUBIC = PILImage.Resampling.BICUBIC
except Exception:
    # If PIL is not available at import time, let the downstream imports fail with a clear error.
    pass

import layoutparser as lp
from layoutparser.models import Detectron2LayoutModel
import torch


def pdf_to_bgr_pages(pdf_path: str, dpi: int = 300) -> List[np.ndarray]:
    pil_pages = convert_from_path(pdf_path, dpi=dpi)
    bgr_pages = [cv2.cvtColor(np.array(p), cv2.COLOR_RGB2BGR) for p in pil_pages]
    return bgr_pages


def ensure_dir(d: str):
    os.makedirs(d, exist_ok=True)


def load_model(score_thresh: float = 0.5):
    """
    PubLayNet detector (Faster R-CNN R50-FPN).
    Labels: 0=text, 1=title, 2=list, 3=table, 4=figure
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[info] Using device: {device}")
    model = Detectron2LayoutModel(
        config_path="lp://PubLayNet/faster_rcnn_R_50_FPN_3x/config",
        label_map={0: "text", 1: "title", 2: "list", 3: "table", 4: "figure"},
        extra_config=["MODEL.ROI_HEADS.SCORE_THRESH_TEST", score_thresh],
        device=device,
    )
    return model


def clamp_box(x0, y0, x1, y1, w, h, pad=6) -> Tuple[int, int, int, int]:
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)
    return x0, y0, x1, y1


def dedupe_boxes(boxes: List[Tuple[int,int,int,int]], iou_thresh: float = 0.5) -> List[Tuple[int,int,int,int]]:
    """
    Simple NMS-like de-duplication by IoU.
    """
    if not boxes:
        return boxes

    # Sort by area (desc), keep bigger first
    boxes = sorted(boxes, key=lambda b: (b[2]-b[0])*(b[3]-b[1]), reverse=True)
    kept = []
    for bx in boxes:
        x0,y0,x1,y1 = bx
        area_x = (x1-x0)*(y1-y0)
        ok = True
        for by in kept:
            X0,Y0,X1,Y1 = by
            inter_x0 = max(x0, X0); inter_y0 = max(y0, Y0)
            inter_x1 = min(x1, X1); inter_y1 = min(y1, Y1)
            iw, ih = max(0, inter_x1-inter_x0), max(0, inter_y1-inter_y0)
            inter = iw*ih
            area_y = (X1-X0)*(Y1-Y0)
            union = area_x + area_y - inter + 1e-6
            iou = inter / union
            if iou > iou_thresh:
                ok = False
                break
        if ok:
            kept.append(bx)
    return kept


def detect_and_crop(
    img_bgr: np.ndarray,
    model,
    keep_types=("figure",),   # add "table" if you want tables too
    pad_px: int = 8
) -> List[np.ndarray]:
    h, w = img_bgr.shape[:2]
    img_rgb = img_bgr[:, :, ::-1]

    layout = model.detect(img_rgb)

    boxes = []
    for blk in layout:
        if blk.type in keep_types:
            # blk.block.points: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            x1, y1, x2, y2 = map(int, blk.block.coordinates)
            x0, y0, x1, y1 = clamp_box(x1, y1, x2, y2, w, h, pad=pad_px)
            if x1 > x0 and y1 > y0:
                boxes.append((x0, y0, x1, y1))

    # Deduplicate overlapping boxes
    boxes = dedupe_boxes(boxes, iou_thresh=0.55)

    crops = [img_bgr[y0:y1, x0:x1].copy() for (x0,y0,x1,y1) in boxes]
    return crops, boxes


def save_crops(crops: List[np.ndarray], out_dir: str, page_idx: int, prefix: str = "figure") -> List[str]:
    ensure_dir(out_dir)
    paths = []
    for i, crop in enumerate(crops):
        path = os.path.join(out_dir, f"page_{page_idx:03d}_{prefix}_{i:02d}.png")
        cv2.imwrite(path, crop)
        paths.append(path)
    return paths


def process_input(
    input_path: str,
    out_dir: str = "lp_crops",
    dpi: int = 300,
    keep_tables: bool = False,
    score_thresh: float = 0.5,
    pad_px: int = 8
) -> List[str]:
    model = load_model(score_thresh=score_thresh)
    ensure_dir(out_dir)

    pages = []
    if input_path.lower().endswith(".pdf"):
        print(f"[info] Rasterising PDF at {dpi} DPI…")
        pages = pdf_to_bgr_pages(input_path, dpi=dpi)
    else:
        img = cv2.imread(input_path)
        if img is None:
            raise ValueError(f"Could not read image: {input_path}")
        pages = [img]

    all_saved = []
    keep_types = ("figure", "table") if keep_tables else ("figure",)

    for pi, page in enumerate(pages, start=1):
        crops, boxes = detect_and_crop(page, model, keep_types=keep_types, pad_px=pad_px)
        saved = save_crops(crops, out_dir, page_idx=pi, prefix="figure" if not keep_tables else "region")
        print(f"[info] Page {pi}: found {len(crops)} region(s) -> saved {len(saved)}")
        all_saved.extend(saved)
    return all_saved


if __name__ == "__main__":
    # Minimal CLI usage:
    # python extract_figures_lp.py input.pdf lp_out
    # python extract_figures_lp.py scanned_page.jpg lp_out

    if len(sys.argv) < 2:
        print("Usage: python extract_figures_lp.py <input.(pdf|png|jpg|tif)> [out_dir] [--tables] [--dpi 300] [--thresh 0.5] [--pad 8]")
        sys.exit(1)

    input_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) >= 3 and not sys.argv[2].startswith("--") else "lp_crops"

    # defaults
    keep_tables = "--tables" in sys.argv
    dpi = 300
    score_thresh = 0.5
    pad = 8

    # parse simple flags
    if "--dpi" in sys.argv:
        dpi = int(sys.argv[sys.argv.index("--dpi") + 1])
    if "--thresh" in sys.argv:
        score_thresh = float(sys.argv[sys.argv.index("--thresh") + 1])
    if "--pad" in sys.argv:
        pad = int(sys.argv[sys.argv.index("--pad") + 1])

    saved = process_input(
        input_path,
        out_dir=out_dir,
        dpi=dpi,
        keep_tables=keep_tables,
        score_thresh=score_thresh,
        pad_px=pad
    )
    print("\nSaved crops:")
    for p in saved:
        print(p)
