# ✨ ENHANCED: convert_to_formats.py Now Supports Page Breaks!

## What's New?

I've added **automatic page break support** directly to `convert_to_formats.py`!

Now you can:
- ✅ **Auto-detect and merge** per-page HTML files
- ✅ **Insert CSS page breaks** between pages
- ✅ **Create 1:1 DOCX** with same page structure as PDF
- ✅ **Single command** - no need for separate merge script

## Quick Examples

### Example 1: Convert directory of per-page HTMLs → DOCX with page breaks

```bash
# You have: output_html/document/document_page_1.html, document_page_2.html, etc.

# Old way (2 steps):
python backend/main.py --per-page input.pdf output_html/
python backend/merge_pages_with_breaks.py output_html/document/ -o document.docx

# NEW way (1 step):
python backend/convert_to_formats.py output_html/document/ --outdir output/ --formats docx
```

**Result**: `output/document.docx` with page breaks! 📄

### Example 2: Specify page break style

```bash
# Use CSS page breaks (default, works well)
python backend/convert_to_formats.py output_html/document/ --outdir output/ --page-break-style css

# Use OpenXML page breaks (more reliable for complex documents)
python backend/convert_to_formats.py output_html/document/ --outdir output/ --page-break-style openxml

# Use both (maximum compatibility)
python backend/convert_to_formats.py output_html/document/ --outdir output/ --page-break-style both
```

### Example 3: Create both DOCX and EPUB

```bash
python backend/convert_to_formats.py output_html/document/ \
    --outdir output/ \
    --formats docx epub \
    --title "My Research Paper" \
    --author "Your Name"
```

### Example 4: Single HTML file (no merging)

```bash
# Works as before for single HTML files
python backend/convert_to_formats.py output_html/document.html \
    --outdir output/ \
    --formats docx
```

## How It Works

### Auto-Detection

The script now automatically detects if you provide:

1. **A directory** → Looks for per-page HTML patterns:
   - `*_page_*.html` (e.g., `doc_page_1.html`)
   - `page_*.html` (e.g., `page_1.html`)
   - `*_p*.html` (e.g., `doc_p1.html`)

2. **A single HTML file** → Processes normally (no merging)

### Merging Process

When per-page HTMLs are detected:

1. ✅ Sorts files by page number
2. ✅ Extracts `<body>` content from each page
3. ✅ Inserts CSS `page-break-after: always` between pages
4. ✅ Preserves `<head>` metadata from first page
5. ✅ Maintains RTL/LTR direction
6. ✅ Converts to DOCX with pandoc

## Full Workflow Example

```bash
# Step 1: OCR PDF to per-page HTMLs
python backend/main.py --per-page --seed 42 \
    "input_pdfs/document.pdf" \
    output_html/

# Step 2: Convert to DOCX with page breaks (NEW!)
python backend/convert_to_formats.py \
    output_html/document/ \
    --outdir final_output/ \
    --formats docx \
    --title "Document Title" \
    --author "Author Name"

# Result: final_output/document.docx with same page structure as PDF!
```

## Command Reference

### Basic Usage

```bash
python backend/convert_to_formats.py INPUT --outdir OUTPUT [OPTIONS]
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `INPUT` | HTML file or directory with per-page HTMLs | Required |
| `--outdir DIR` | Output directory | `converted_formats/` |
| `--formats {docx,epub}` | Output formats | `docx epub` |
| `--merge-pages` | Force merge mode (auto-detected) | Auto |
| `--page-break-style {css,openxml,both}` | Page break type | `css` |
| `--title TEXT` | Document title metadata | Auto from filename |
| `--author TEXT` | Author metadata | None |
| `--cover IMAGE` | EPUB cover image | None |
| `--epub-math {mathml,images,mathjax}` | EPUB math rendering | `mathml` |
| `--verbose` | Debug output | Off |

## Page Break Styles Explained

### CSS (Recommended)

```html
<div style="page-break-after: always; break-after: page;"></div>
```

- ✅ Works in Microsoft Word
- ✅ Works in LibreOffice
- ✅ Clean and standard
- ⚠️ Might not work in very old Word versions

### OpenXML

```html
```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```
```

- ✅ Native Word format (most reliable)
- ✅ Works in all Word versions
- ⚠️ Only for DOCX (not for HTML/EPUB)

### Both

Inserts both CSS and OpenXML page breaks:

- ✅ Maximum compatibility
- ⚠️ Slightly larger file size

## Real-World Example

```bash
# 23-page Arabic research paper
cd /home/cubez/Desktop/OCR

# OCR with per-page processing
python backend/main.py --per-page --seed 42 \
    "input_pdfs/1749-000-022-008 (2).pdf" \
    output_html/

# Convert to DOCX with page breaks
python backend/convert_to_formats.py \
    "output_html/1749-000-022-008 (2)/" \
    --outdir final_docs/ \
    --formats docx \
    --title "Research Paper" \
    --page-break-style css

# Result:
# ✅ final_docs/1749-000-022-008 (2).docx
# ✅ 23 pages with proper breaks
# ✅ RTL text preserved
# ✅ Math equations intact
# ✅ Ready to edit in Word!
```

## Troubleshooting

### Issue: "No page HTML files found"

**Cause**: Files don't match expected patterns

**Solution**: Check your filenames:
```bash
ls output_html/document/
# Should see: doc_page_1.html, doc_page_2.html, etc.
```

If files are named differently, rename them:
```bash
# If you have: doc1.html, doc2.html, doc3.html
cd output_html/document/
for f in doc*.html; do
    num=$(echo $f | grep -o '[0-9]*')
    mv "$f" "document_page_${num}.html"
done
```

### Issue: Page breaks not appearing in Word

**Solution 1**: Try OpenXML style
```bash
python backend/convert_to_formats.py dir/ --page-break-style openxml
```

**Solution 2**: Verify pandoc version
```bash
pandoc --version  # Should be 2.0 or higher
```

**Solution 3**: Open in actual Microsoft Word (not just LibreOffice viewer)

### Issue: Content spans multiple pages

**This is normal!** If a page's content is longer than one physical page in Word, it will naturally overflow. The page break happens between *logical* pages from the PDF, not *physical* pages in Word.

## Comparison: Old vs New Workflow

### OLD Workflow (2 scripts)

```bash
# Step 1: OCR
python backend/main.py --per-page input.pdf output_html/

# Step 2: Merge (separate script)
python backend/merge_pages_with_breaks.py output_html/doc/ -o doc.docx
```

### NEW Workflow (1 script!)

```bash
# Step 1: OCR
python backend/main.py --per-page input.pdf output_html/

# Step 2: Convert with auto-merge
python backend/convert_to_formats.py output_html/doc/ --outdir output/
```

**Benefits**:
- ✅ One less script to remember
- ✅ Auto-detects per-page HTMLs
- ✅ Integrated into existing workflow
- ✅ Same options as before (title, author, etc.)

## Integration with convert_pdf_end_to_end.py

The end-to-end script will **automatically** use the enhanced `convert_to_formats.py`:

```bash
python backend/convert_pdf_end_to_end.py \
    input_pdfs/ \
    --outdir output/ \
    --per-page \
    --title "My Document"
```

If you use `--per-page`, it will:
1. Generate per-page HTMLs with `main.py`
2. **Automatically merge with page breaks** when calling `convert_to_formats.py`
3. Create DOCX with proper pagination!

## Summary

**What changed**: `convert_to_formats.py` now has built-in page break support!

**How to use**:
```bash
# Just point it at a directory of per-page HTMLs
python backend/convert_to_formats.py output_html/document/ --outdir output/
```

**Result**: DOCX with same page structure as original PDF!

**No separate merge script needed** - it's all integrated! 🎉
