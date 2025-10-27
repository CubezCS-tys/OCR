# Quick Start Guide: Two-Pass PDF Extraction

## Complete Workflow

### Step 1: Extract Text, Tables, and Equations
```bash
cd backend
python3 main.py input_pdfs/ --per-page
```

**What this does:**
- Splits each PDF into individual pages
- Sends each page to Gemini for text/table/equation extraction
- Generates one HTML file per page with consistent styling
- Inserts placeholders where images are detected

**Output:** `output_html/document_page_001.html`, `document_page_002.html`, etc.

---

### Step 2: Extract Images
```bash
python3 image_extractor_llm.py input_pdfs/ extracted_images/
```

**What this does:**
- Splits each PDF into individual pages (same as Pass 1)
- Sends each page to Gemini for image identification and extraction
- LLM returns base64-encoded PNG images in JSON format
- Saves extracted images and creates a manifest

**Output:** 
- `extracted_images/document_page_001_fig_1.png`
- `extracted_images/document_page_001_chart_1.png`
- `extracted_images/document_manifest.json`

---

## Example: Processing a Research Paper

```bash
# Full workflow for a 10-page research paper
cd backend

# Pass 1: Text extraction (per-page for consistency)
python3 main.py input_pdfs/research_paper.pdf --per-page

# Output:
# - output_html/research_paper_page_001.html
# - output_html/research_paper_page_002.html
# - ... (10 HTML files total)

# Pass 2: Image extraction
python3 image_extractor_llm.py input_pdfs/research_paper.pdf extracted_images/

# Output:
# - extracted_images/research_paper_page_002_fig_1.png (figure from page 2)
# - extracted_images/research_paper_page_005_chart_1.png (chart from page 5)
# - extracted_images/research_paper_page_007_diagram_1.png (diagram from page 7)
# - extracted_images/research_paper_manifest.json (metadata)
```

---

## Manifest File Example

The `*_manifest.json` file contains complete metadata:

```json
{
  "pdf_name": "research_paper.pdf",
  "pdf_stem": "research_paper",
  "num_pages": 10,
  "total_images_extracted": 5,
  "pages": [
    {
      "page_num": 2,
      "images": [
        {
          "filename": "research_paper_page_002_fig_1.png",
          "path": "/full/path/to/extracted_images/research_paper_page_002_fig_1.png",
          "id": "fig_1",
          "type": "diagram",
          "description": "System architecture diagram",
          "format": "png",
          "size_kb": 67.3
        }
      ]
    },
    {
      "page_num": 5,
      "images": [
        {
          "filename": "research_paper_page_005_chart_1.png",
          "path": "/full/path/to/extracted_images/research_paper_page_005_chart_1.png",
          "id": "chart_1",
          "type": "chart",
          "description": "Performance comparison bar chart",
          "format": "png",
          "size_kb": 45.2
        }
      ]
    }
  ]
}
```

---

## Common Commands

### Force Re-processing (both passes)
```bash
# Re-do text extraction even if HTML exists
python3 main.py input_pdfs/ --per-page --force

# Re-do image extraction even if images exist
python3 image_extractor_llm.py input_pdfs/ extracted_images/ --force
```

### Process Multiple PDFs
```bash
# Place all PDFs in input_pdfs/ directory
python3 main.py input_pdfs/ --per-page
python3 image_extractor_llm.py input_pdfs/ extracted_images/

# Both scripts will process all *.pdf files in the directory
```

### Custom Output Directories
```bash
# Text extraction to custom directory
python3 main.py input_pdfs/ --output_dir my_html_output/ --per-page

# Image extraction to custom directory
python3 image_extractor_llm.py input_pdfs/ my_image_output/
```

---

## What You Get

### From Pass 1 (Text)
- **Per-page HTML files** with:
  - Extracted text (preserves Arabic RTL, language, formatting)
  - Tables (converted to HTML `<table>` elements)
  - Math equations (rendered with MathJax)
  - Consistent CSS styling across all pages
  - Image placeholders: `<div class="image-placeholder">[IMAGE: ...]</div>`

### From Pass 2 (Images)
- **PNG image files**: Cropped figures, charts, diagrams
- **JSON manifest**: Complete metadata for all images
  - Which page each image came from
  - Image type (figure/chart/diagram/table)
  - Brief description
  - File size and path

---

## Integration Ideas (Future)

### Replace Placeholders with Actual Images
Using the manifest, you can:
1. Parse each HTML file
2. Find `<div class="image-placeholder">` tags
3. Replace with `<img src="path/to/extracted_image.png">`
4. Match using page numbers and descriptions

### Embed Images Inline
Convert PNGs to base64 and embed directly in HTML:
```html
<img src="data:image/png;base64,iVBORw0KG..." alt="Figure 1">
```

### Create Combined Document
Merge all per-page HTML files into one master document with images embedded.

---

## Tips for Best Results

### Text Extraction (Pass 1)
✅ Use `--per-page` for multi-page documents to ensure consistency  
✅ Check first few HTML outputs to verify formatting is correct  
✅ If styles vary between pages, review the prompt in `main.py`

### Image Extraction (Pass 2)
✅ Works best on clean, well-formatted PDFs  
✅ LLM may skip very small icons or decorative elements (by design)  
✅ Check manifest to see what was detected and why  
✅ For scanned/low-quality PDFs, consider CV-based extractor instead

### Cost Optimization
💡 Run Pass 1 first, review which pages actually have images  
💡 Only run Pass 2 on pages with placeholders (selective extraction)  
💡 For large batches, consider local CV detector + LLM for edge cases

---

## Troubleshooting

**"GEMINI_API_KEY not found"**
→ Create `.env` file: `echo "GEMINI_API_KEY=your_key" > .env`

**"No images found on any pages"**
→ Check if PDF actually contains images (vs. just text/tables)
→ Try opening PDF manually to verify

**"JSON parsing error"**
→ LLM returned malformed response; check error output
→ Try with a simpler PDF first to verify setup

**"Images look wrong"**
→ LLM might have misidentified regions
→ Check manifest descriptions to see what LLM thought it was
→ Consider using CV-based extractor for that document

---

## Next Steps

1. **Test the pipeline**: Run both passes on a sample PDF
2. **Review outputs**: Check HTML files and extracted images
3. **Adjust prompts**: Fine-tune prompts in `main.py` and `image_extractor_llm.py` if needed
4. **Integrate**: Use manifest to replace placeholders with actual images
5. **Scale up**: Process your full document collection

For detailed documentation, see `README_IMAGE_EXTRACTION.md`
