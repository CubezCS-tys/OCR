# Two-Pass PDF-to-HTML Pipeline with LLM Image Extraction

## Overview

This directory contains a complete two-pass pipeline for converting PDFs to HTML with intelligent LLM-based image extraction:

**Pass 1: Text, Tables, Equations, Layout** → HTML files (per page)  
**Pass 2: LLM Image Extraction** → PNG images + JSON manifest

## Architecture

### Pass 1: Text Extraction (`main.py`)
- Uses Gemini's multimodal OCR to extract text, tables, math equations
- Preserves layout, RTL direction (Arabic), and structure
- Outputs one HTML file per page (with `--per-page` flag)
- Inserts placeholders where images are detected: `<div class="image-placeholder">[IMAGE: description]</div>`

### Pass 2: LLM Image Extraction (`image_extractor_llm.py`)
- **LLM does BOTH identification AND extraction**: Gemini directly crops and returns images
- Processes each page individually (per-page) for consistency
- LLM returns base64-encoded PNG images in JSON format
- Script decodes and saves images locally
- Generates a manifest JSON with metadata

## Why Two Passes?

### Advantages of LLM-Direct Extraction
✅ **Semantic accuracy**: LLM understands context and identifies meaningful images  
✅ **No local rasterization needed**: LLM handles cropping internally  
✅ **Better quality**: LLM can enhance/clean images during extraction  
✅ **Consistency**: Per-page processing matches Pass 1 approach  
✅ **Simplicity**: No coordinate validation, no OpenCV dependencies for cropping  
✅ **Flexibility**: Run text-only first, extract images only when needed

### Trade-offs
⚠️ **Cost**: Each page requires two API calls (text pass + image extraction pass)  
⚠️ **Latency**: Sequential passes take longer than single-pass extraction  
⚠️ **Base64 overhead**: LLM returns images as base64 in JSON (larger response payloads)  
⚠️ **Quality dependent on LLM**: If LLM misidentifies regions, you get wrong/missing images

## Installation

```bash
# Navigate to backend directory
cd backend

# Install Python dependencies
pip install -r requirements.txt

# Create .env file with API key
echo "GEMINI_API_KEY=your_api_key_here" > .env
```

**Note**: No need for `poppler-utils`, `opencv`, or `pdf2image` for the LLM-direct approach!

## Usage

### Pass 1: Extract Text and Layout

```bash
# Process entire PDF as one HTML file
python main.py input_pdfs/

# Process each page separately (recommended for consistency)
python main.py input_pdfs/ --per-page

# Force re-processing
python main.py input_pdfs/ --per-page --force

# Custom output directory
python main.py input_pdfs/ --output_dir my_output/ --per-page
```

**Output**: `output_html/document_page_001.html`, `document_page_002.html`, etc.

### Pass 2: Extract Images

```bash
# Extract images from a single PDF
python3 image_extractor_llm.py input_pdfs/document.pdf extracted_images/

# Extract from all PDFs in a directory
python3 image_extractor_llm.py input_pdfs/ extracted_images/

# Force re-processing
python3 image_extractor_llm.py input_pdfs/document.pdf extracted_images/ --force
```

**Output**:
- `extracted_images/document_page_001_fig_1.png`
- `extracted_images/document_page_002_chart_1.png`
- `extracted_images/document_manifest.json`

### Example Workflow

```bash
# 1. Extract text and layout (per-page mode)
python3 main.py input_pdfs/research_paper.pdf --per-page

# 2. Extract images using LLM
python3 image_extractor_llm.py input_pdfs/research_paper.pdf extracted_images/

# 3. View results
# - HTML files: output_html/research_paper_page_001.html, etc.
# - Images: extracted_images/research_paper_page_001_fig_1.png, etc.
# - Manifest: extracted_images/research_paper_manifest.json
```

## Understanding the Manifest

The manifest JSON provides complete metadata for all extracted images:

```json
{
  "pdf_name": "document.pdf",
  "pdf_stem": "document",
  "num_pages": 5,
  "total_images_extracted": 3,
  "pages": [
    {
      "page_num": 1,
      "images": [
        {
          "filename": "document_page_001_fig_1.png",
          "path": "/path/to/extracted_images/document_page_001_fig_1.png",
          "id": "fig_1",
          "type": "chart",
          "description": "Bar chart showing quarterly revenue",
          "format": "png",
          "size_kb": 45.3
        }
      ]
    }
  ]
}
```

## How the LLM Extraction Works

### 1. Per-Page Processing

Like `main.py`, the script splits each PDF into individual pages using `pypdf`:
- Creates temporary single-page PDF files
- Uploads each page separately to Gemini
- Processes pages sequentially for consistency

### 2. Prompt Engineering

The script sends a strict system prompt to Gemini asking for JSON output with base64-encoded images:

```
You are an expert image extraction specialist.
Extract ALL figures, charts, diagrams, and images.
Return JSON with base64-encoded PNG data for each image.
```

### 3. LLM Returns Structured JSON with Image Data

```json
{
  "page": "document_page_1",
  "images": [
    {
      "id": "fig_1",
      "type": "chart",
      "description": "Bar chart showing quarterly sales",
      "format": "png",
      "data": "iVBORw0KGgoAAAANSUhEUg..."  // base64-encoded PNG
    }
  ]
}
```

### 4. Local Processing

- Parse JSON response
- Decode base64 image data
- Save as PNG files
- Generate manifest with metadata
- Clean up temporary files

## Configuration Options

### `main.py` (Pass 1: Text Extraction)

| Flag | Description | Default |
|------|-------------|---------|
| `input_dir` | Directory containing PDF files | Required |
| `--output_dir` | Output directory for HTML files | `output_html` |
| `--force` | Re-process even if HTML exists | `False` |
| `--per-page` | Process each page separately | `False` |

### `image_extractor_llm.py` (Pass 2: Images)

| Flag | Description | Default |
|------|-------------|---------|
| `input` | PDF file or directory | Required |
| `output_dir` | Output directory for images | `extracted_images` |
| `--force` | Force re-processing | `False` |

## Troubleshooting

### Issue: "GEMINI_API_KEY not found"
**Solution**: Create a `.env` file in the backend directory:
```bash
echo "GEMINI_API_KEY=your_actual_key" > .env
```

### Issue: LLM returns empty images `{"images": []}`
**Possible causes**:
- Page genuinely has no figures/images (text-only page)
- Images are very small or decorative (LLM filtered them out)
- Images are embedded as vector graphics that LLM can't extract

**Solutions**:
- Verify by manually viewing the PDF page
- Try the layoutparser CV-based extractor (`extract_figures_lp.py`) as fallback

### Issue: JSON parsing errors
**Possible causes**:
- LLM returned explanation text instead of pure JSON
- Response was truncated (very large images)

**Solutions**:
- Check the error output for the actual response text
- Script auto-strips markdown code fences, but LLM might add other text
- Try processing a simpler/smaller PDF first to verify setup

### Issue: Images look wrong or corrupted
**Possible causes**:
- Base64 decoding error
- LLM hallucinated/misidentified regions

**Solutions**:
- Check the manifest JSON for the image description
- Compare extracted image with original PDF
- LLM-based extraction quality depends on clear, well-formatted PDFs

### Issue: Slow performance / high costs
**Optimization tips**:
- Process only pages that actually contain images
- Use Pass 1 placeholders to identify which pages need image extraction
- Consider hybrid: CV detector first, LLM only for missed/ambiguous cases

## Advanced: Hybrid Extraction (Future Enhancement)

For cost optimization and better coverage, you can combine:
1. **Local CV detection** (`extract_figures_lp.py`) - fast, deterministic, free
2. **LLM extraction** (`image_extractor_llm.py`) - semantic understanding, handles edge cases

Workflow idea:
```bash
# Run fast CV detector first on all pages
python3 extract_figures_lp.py document.pdf cv_crops/

# Then run LLM only on pages where CV found nothing or low-confidence results
python3 image_extractor_llm.py problematic_pages/ llm_crops/
```

This gives you best of both worlds: speed + cost efficiency + high accuracy.

## File Structure

```
backend/
├── main.py                          # Pass 1: Text/layout extraction
├── image_extractor_llm.py          # Pass 2: LLM-based image extraction
├── extract_figures_lp.py           # Alternative: CV-based extraction
├── requirements.txt                # Python dependencies
├── .env                            # API keys (create this)
├── README_IMAGE_EXTRACTION.md      # This file
│
├── input_pdfs/                     # Your source PDFs
│   └── document.pdf
│
├── output_html/                    # Pass 1 output
│   ├── document_page_001.html
│   └── document_page_002.html
│
└── extracted_images/               # Pass 2 output
    ├── document_page_001_fig_1.png
    ├── document_page_002_fig_1.png
    └── document_manifest.json
```

## Next Steps

1. **Test the pipeline**:
   ```bash
   python main.py input_pdfs/ --per-page
   python image_extractor_llm.py input_pdfs/ extracted_images/
   ```

2. **Integrate images into HTML** (future enhancement):
   - Parse manifest JSON
   - Replace `<div class="image-placeholder">` tags with `<img src="...">`
   - Embed base64 or reference external PNG files

3. **Optimize costs**:
   - Use local CV detector for bulk processing
   - Reserve LLM for complex/ambiguous pages
   - Batch API calls if Gemini supports it

4. **Quality validation**:
   - Manually review first few extractions
   - Adjust `--min-confidence` based on precision/recall
   - Compare LLM results vs. layoutparser on sample docs

## API Cost Estimation

**Gemini Flash pricing** (approximate, check current rates):
- ~$0.075 per 1K input tokens
- Multimodal input (images/PDFs) costs more

**Example**: 50-page PDF
- Pass 1 (text): 50 pages × ~$0.01/page = ~$0.50
- Pass 2 (images): 50 pages × ~$0.01/page = ~$0.50
- **Total**: ~$1.00 per document

**Cost optimization**:
- Use `--per-page` only when needed (consistency issues)
- Skip Pass 2 for text-only documents
- Use local CV detector where possible
