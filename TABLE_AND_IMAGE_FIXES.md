# Table and Image Placeholder Fixes

## Changes Made

### 1. Responsive Table CSS (✅ COMPLETED)
**File:** `backend/main.py` (lines 550-589)

**Problem:** Tables were overflowing the page width in HTML and DOCX outputs.

**Solution:** Enhanced the table CSS with:
- **Screen view:** Horizontal scrolling for wide tables
  - `display: block; overflow-x: auto;`
  - `-webkit-overflow-scrolling: touch;` for smooth mobile scrolling
  
- **Print/DOCX view:** Fixed table layout to fit content on page
  - `@media print` rules with `table-layout: fixed;`
  - Smaller font size (0.9em) and reduced padding (6px 8px)
  - Word wrapping for long content: `word-wrap: break-word;`
  - Minimum cell width (80px) to prevent crushing

**Result:** Tables now fit on the page in DOCX/PDF output and scroll horizontally in HTML when needed.

---

### 2. Conditional IMAGE_PLACEHOLDER (✅ COMPLETED)
**Files Modified:**
- `backend/main.py` (lines 504-549, 966-975, 1049, 1202-1206, 1264-1265)

**Problem:** The LLM was creating `[IMAGE_PLACEHOLDER:ID:Description]` markers even when `--extract-images` flag was not used, resulting in placeholder text appearing in the final output.

**Solution:** Made the prompt conditional based on the `--extract-images` flag:

#### Changes to `create_converter_prompt()` (line 504):
- Added `extract_images=True` parameter
- Conditional logic for image instructions:
  - **When `extract_images=True`:** Use IMAGE_PLACEHOLDER markers
    ```
    6. **Images:** Use `[IMAGE_PLACEHOLDER:ID:Description]` for images.
    Do not embed binary data.
    ```
  - **When `extract_images=False`:** Describe images inline
    ```
    6. **Images:** When you encounter an image, describe it briefly 
    in the text instead of using placeholders.
    ```

#### Changes to `process_single_page()` (line 966):
- Added `extract_images=True` parameter
- Updated call to `create_converter_prompt()` to pass the flag (line 1049)

#### Changes to `convert_pdf_folder()`:
- Reads `extract_images` flag from function attribute (set by CLI argument)
- Passes flag to `process_single_page()` for per-page processing (line 1202-1206)
- Passes flag to `create_converter_prompt()` for whole-PDF processing (line 1264-1265)

**Result:** 
- **With `--extract-images`:** LLM creates IMAGE_PLACEHOLDER markers → `image_extractor.py` extracts images → `embed_images_inline()` replaces markers with `<img>` tags
- **Without `--extract-images`:** LLM describes images in the text inline, no placeholders created

---

## How It Works

### User Workflow
```bash
# With image extraction (creates placeholders, extracts images, embeds them)
python backend/convert_pdf_end_to_end.py input_pdfs/ --per-page --extract-images

# Without image extraction (describes images in text, no placeholders)
python backend/convert_pdf_end_to_end.py input_pdfs/ --per-page
```

### Internal Flow
```
convert_pdf_end_to_end.py
  ↓ passes --extract-images flag
main.py (argparse)
  ↓ sets convert_pdf_folder.extract_images = args.extract_images
convert_pdf_folder()
  ↓ reads extract_images_flag = getattr(convert_pdf_folder, 'extract_images', False)
  ↓ passes to process_single_page(..., extract_images=extract_images_flag)
process_single_page()
  ↓ passes to create_converter_prompt(..., extract_images=extract_images)
create_converter_prompt()
  ↓ generates conditional prompt based on extract_images flag
  ↓ if True: "Use [IMAGE_PLACEHOLDER:ID:Description]"
  ↓ if False: "describe it briefly in the text"
LLM (Gemini)
  ↓ follows instructions based on prompt
  ↓ if extract_images=True: Creates [IMAGE_PLACEHOLDER:img001:A chart showing...]
  ↓ if extract_images=False: Creates "The figure shows a chart displaying..."
```

---

## Testing

### Test 1: With Image Extraction
```bash
cd /home/cubez/Desktop/OCR
python backend/convert_pdf_end_to_end.py input_pdfs/ --per-page --extract-images --max-workers 100 --requests-per-minute 500
```

**Expected Result:**
- HTML contains `[IMAGE_PLACEHOLDER:...]` markers initially
- After `embed_images_inline()`, placeholders replaced with `<img>` tags
- DOCX/EPUB have embedded images
- Tables fit on page width

### Test 2: Without Image Extraction
```bash
cd /home/cubez/Desktop/OCR
python backend/convert_pdf_end_to_end.py input_pdfs/ --per-page --max-workers 100 --requests-per-minute 500
```

**Expected Result:**
- HTML contains text descriptions of images (e.g., "The figure shows a bar chart...")
- No `[IMAGE_PLACEHOLDER:...]` markers in output
- No images extracted to `extracted_images/`
- Tables still fit on page width

---

## Backward Compatibility

✅ **Fully backward compatible:**
- Default parameter `extract_images=True` maintains existing behavior
- Existing scripts calling `main.py` without `--extract-images` flag will continue to work
- All existing functionality preserved

---

## Files Modified

1. **backend/main.py**
   - Line 504: Modified `create_converter_prompt()` signature
   - Lines 506-549: Added conditional image instruction logic
   - Lines 550-589: Enhanced table CSS
   - Line 966: Modified `process_single_page()` signature
   - Line 1049: Updated call to `create_converter_prompt()`
   - Lines 1202-1206: Pass `extract_images_flag` in thread pool submission
   - Lines 1264-1265: Pass `extract_images_flag` in whole-PDF processing

2. **No changes needed to:**
   - `convert_pdf_end_to_end.py` (already passes flag correctly)
   - `image_extractor.py` (unchanged)
   - `convert_to_formats.py` (unchanged - user prefers original version)

---

## Summary

✅ **Tables now fit on page** - responsive CSS with horizontal scrolling and fixed layout for print
✅ **No IMAGE_PLACEHOLDER artifacts** - conditional prompt based on `--extract-images` flag
✅ **Backward compatible** - existing workflows continue to work
✅ **No breaking changes** - default behavior preserved
