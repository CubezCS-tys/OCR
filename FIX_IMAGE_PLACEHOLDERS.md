# How to Fix IMAGE_PLACEHOLDER Issues in Your Output

## Problem

You're seeing text like `IMAGE_PLACEHOLDER:4-Image` in your DOCX instead of actual images.

## Root Causes

1. **Image extraction not running** - Images aren't being extracted from PDF
2. **Images not being embedded** - Placeholders not replaced with actual `<img>` tags
3. **Path mismatch** - Images extracted but paths don't match placeholders
4. **Pandoc limitation** - Pandoc can't find the images during conversion

## Solution 1: Complete Workflow (RECOMMENDED)

Run the full pipeline with proper image handling:

```bash
cd /home/cubez/Desktop/OCR/backend

# Step 1: Generate HTML with placeholders
python3 main.py \
  ../input_pdfs/ \
  ../output_html/ \
  --per-page \
  --seed 42 \
  --max-workers 10 \
  --requests-per-minute 15 \
  --verbose

# Step 2: Extract images separately (if not done)
python3 image_extractor.py ../input_pdfs/your_document.pdf ../output_html/extracted_images/

# Step 3: Embed images back into HTML
# (This should happen automatically, but let's verify)

# Step 4: Convert to DOCX with images
python3 convert_to_formats.py \
  ../output_html/your_document/ \
  --outdir ../final_output/ \
  --formats docx \
  --verbose
```

## Solution 2: Use convert_pdf_end_to_end.py WITH --extract-images

```bash
python3 convert_pdf_end_to_end.py /home/cubez/Desktop/OCR/input_pdfs \
  --outdir Final \
  --extract-images \    # ← CRITICAL: This must be included!
  --max-workers 10 \
  --requests-per-minute 15 \
  --force \
  --per-page \
  --verbose
```

**Key Points:**
- ✅ `--extract-images` flag is **required** for image extraction
- ✅ Start with lower workers (10) and rate limits (15) to avoid API errors
- ✅ Check console output for image extraction messages

## Solution 3: Manual Image Fix (If Images Were Extracted)

If images were extracted but placeholders weren't replaced:

```bash
cd /home/cubez/Desktop/OCR/backend

# Check if images exist
ls ../Final/your_document/extracted_images/

# If images exist, manually embed them
python3 -c "
from main import embed_images_inline
from pathlib import Path

# Update paths to your actual files
html_file = Path('../Final/your_document/your_document.html')
images_dir = Path('../Final/your_document/extracted_images')
pdf_stem = 'your_document'

embed_images_inline(html_file, images_dir, pdf_stem)
"

# Then re-convert to DOCX
python3 convert_to_formats.py \
  ../Final/your_document/your_document.html \
  --outdir ../Final/your_document/ \
  --formats docx
```

## Solution 4: Tell the LLM to Skip Image Placeholders

If you don't care about images and just want clean text:

### Option A: Modify the prompt to not use placeholders

Edit `backend/main.py` around line 541 and change:

```python
# FROM:
6. **Images:** Use `[IMAGE_PLACEHOLDER:ID:Description]`. Do not embed binary data.

# TO:
6. **Images:** Describe the image content in the text instead of using placeholders.
   Example: "Figure 1 shows a diagram of the kinematic analysis..."
```

### Option B: Remove placeholders from HTML before conversion

```bash
# Quick sed command to remove IMAGE_PLACEHOLDER markers
cd /home/cubez/Desktop/OCR/Final/your_document/

# Backup first
cp your_document.html your_document.html.backup

# Remove placeholders
sed -i 's/\[IMAGE_PLACEHOLDER:[^]]*\]//g' your_document.html

# Convert to DOCX
cd ../../backend
python3 convert_to_formats.py \
  ../Final/your_document/your_document.html \
  --outdir ../Final/your_document/ \
  --formats docx
```

## Diagnostic: Check What's Happening

### Check 1: Are images being extracted?

```bash
cd /home/cubez/Desktop/OCR

# Look for extracted images
find Final/ -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" | head -20

# Check image extraction output in logs
grep -i "extract" Final/*/convert_log.txt
grep -i "image" Final/*/convert_log.txt
```

### Check 2: What placeholders are in your HTML?

```bash
cd /home/cubez/Desktop/OCR

# Find all IMAGE_PLACEHOLDER markers
grep -o 'IMAGE_PLACEHOLDER[^]]*' Final/your_document/your_document.html

# Count them
grep -c 'IMAGE_PLACEHOLDER' Final/your_document/your_document.html
```

### Check 3: Are images referenced correctly?

```bash
cd /home/cubez/Desktop/OCR

# Check if HTML has <img> tags
grep -o '<img src="[^"]*"' Final/your_document/your_document.html | head -10

# Check if paths exist
# (The img src paths should match extracted image locations)
```

## Expected Workflow (What Should Happen)

### When --extract-images is used:

1. ✅ PDF → Images extracted to `extracted_images/`
2. ✅ PDF → Gemini → HTML with `[IMAGE_PLACEHOLDER:...]` markers
3. ✅ `embed_images_inline()` replaces placeholders with `<img>` tags
4. ✅ HTML → Pandoc → DOCX with images embedded

### Console output should show:

```
Extracting images from document.pdf...
✅ Extracted 15 images from document.pdf
Processing page 1/23...
✅ Replaced 3 image placeholder(s) with actual <figure> tags in document_page_5.html
Running: pandoc document.html -o document.docx ...
✅ DOCX written: Final/document/document.docx
```

## Quick Test: Verify Image Extraction Works

```bash
cd /home/cubez/Desktop/OCR/backend

# Test with a simple PDF
python3 image_extractor.py \
  ../input_pdfs/your_test.pdf \
  ../test_images/

# Check output
ls ../test_images/
# Should see: your_test_page_001_img_1.png, etc.
```

## If Nothing Works: Simplest Solution

**Just remove the placeholders and describe images in text:**

The LLM is already seeing the images in the PDF. Ask it to **describe them instead of using placeholders**:

1. Edit `backend/main.py` line ~541
2. Change the image instruction to:
   ```
   6. **Images:** When you see an image, describe its content briefly in the text.
      Example: "[Figure 1: A kinematic diagram showing the three stages of weapon movement]"
   ```
3. Re-run your pipeline

This way you get clean DOCX without placeholder artifacts!

## Summary

### Best Fix (Your Use Case):

```bash
# Ensure --extract-images is included
python3 convert_pdf_end_to_end.py /home/cubez/Desktop/OCR/input_pdfs \
  --outdir Final \
  --extract-images \
  --max-workers 10 \
  --requests-per-minute 15 \
  --force \
  --per-page \
  --verbose
```

### Check logs for:
- "Extracting images from..."
- "✅ Extracted N images..."
- "✅ Replaced N image placeholder(s)..."

If you see these messages, images should work. If not, the image extraction step is failing.

### Alternative: Skip Images Entirely

If you don't need images in the DOCX:
1. Don't use `--extract-images`
2. Modify prompt to describe images in text instead of placeholders
3. Cleaner output, no placeholder artifacts!

Let me know which approach you prefer!
