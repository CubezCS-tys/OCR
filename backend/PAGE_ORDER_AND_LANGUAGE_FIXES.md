# Page Order & Language Direction Fixes

## Issues Fixed

### ✅ Issue 1: Page Order Not Preserved in Concurrent Processing

**Problem**: Pages were being combined in completion order (whichever finished first) instead of sequential page order (1, 2, 3...).

**Root Cause**: 
- `as_completed(futures)` returns results in completion order, not submission order
- Lexicographic sorting of `page_10.html` comes before `page_2.html`

**Solutions Implemented**:

**1. In `main.py` (concurrent processing)**:
```python
# OLD: Used as_completed which returns in random completion order
for future in as_completed(futures):
    page_num, success, output = future.result()
    # Pages processed out of order!

# NEW: Store page_num with each future, collect all results, then sort
futures = []
for page_num in range(num_pages):
    future = executor.submit(process_single_page, ...)
    futures.append((page_num, future))  # Store page number!

results = []
for page_num, future in futures:
    result = future.result()
    results.append(result)

# Sort by page number to ensure correct order
results.sort(key=lambda x: x[0])
```

**2. In `convert_pdf_end_to_end.py` (HTML combination)**:
```python
# OLD: Lexicographic sort (page_1, page_10, page_11, ..., page_2)
page_files = sorted(tmp_output_html.glob(f"{pdf_stem}_page_*.html"))

# NEW: Natural/numeric sort (page_1, page_2, page_3, ..., page_10)
def page_sort_key(path):
    match = re.search(r'_page_(\d+)', path.stem)
    return int(match.group(1)) if match else 0

page_files = sorted(tmp_output_html.glob(f"{pdf_stem}_page_*.html"), 
                   key=page_sort_key)
```

**Result**: Pages now ALWAYS appear in correct sequential order (1 → 2 → 3 → ... → N)

---

### ✅ Issue 2: HTML Direction Not Language-Aware

**Problem**: HTML was forcing RTL for all documents, even English ones.

**Solution Implemented in `main.py` (LLM Prompt)**:

Updated the system prompt to instruct Gemini to:

```
4. Language and Direction (CRITICAL):
   * Detect the primary language of the document content
   * For Arabic text: use <html lang="ar" dir="rtl">
   * For English text: use <html lang="en" dir="ltr">
   * Apply direction consistently to <html>, <body>, and content
   * Use the dominant language for document direction
```

**CSS Template Updated**:
```css
/* OLD: Hardcoded RTL */
table { direction: rtl; }
ul, ol { padding-right: 2em; }

/* NEW: Direction-aware */
table { /* inherits from html[dir] */ }
html[dir="rtl"] ul, html[dir="rtl"] ol { padding-right: 2em; padding-left: 0; }
html[dir="ltr"] ul, html[dir="ltr"] ol { padding-left: 2em; padding-right: 0; }
```

**Result**: 
- Arabic PDFs → HTML with `<html lang="ar" dir="rtl">`
- English PDFs → HTML with `<html lang="en" dir="ltr">`

---

### ✅ Issue 3: Word Documents Not Respecting Language Direction

**Problem**: DOCX might force RTL for English documents.

**Already Fixed** (in earlier update to `convert_to_formats.py`):

The conversion script:
1. Detects language from HTML: `lang="en"` or `lang="ar"`
2. Only applies RTL metadata when lang is in `RTL_LANGS = {'ar', 'he', 'fa', 'ur', 'ps'}`
3. For English (`lang="en"`):
   - No `dir=rtl` metadata passed to pandoc
   - No RTL CSS stylesheet
   - No `reference-rtl.docx` template used
   - Result: **LTR Word document**

**Logic**:
```python
# Extract language from HTML
lang = None
m = re.search(r'lang=["\']([a-zA-Z0-9_\-]+)["\']', html_text)
if m:
    lang = m.group(1).lower()  # e.g., "en" or "ar"

# Determine if RTL
RTL_LANGS = {'ar', 'he', 'fa', 'ur', 'ps'}
is_rtl = bool(lang and lang.split('-', 1)[0] in RTL_LANGS)

# Only apply RTL features when is_rtl == True
if is_rtl:
    # Add RTL CSS for EPUB
    # Pass --metadata dir=rtl to pandoc
    # Use reference-rtl.docx if available
else:
    # LTR output (default pandoc behavior)
```

**Result**:
- Arabic HTML → RTL DOCX + EPUB
- English HTML → LTR DOCX + EPUB

---

## Files Modified

### 1. `backend/main.py`

**Changes**:
- ✅ Store page_num with futures for ordered collection
- ✅ Sort results by page number after collection
- ✅ Updated LLM prompt: explicit language detection instructions
- ✅ Updated CSS: direction-aware list padding

**Lines Changed**: ~30 lines in concurrent processing section + prompt updates

### 2. `backend/convert_pdf_end_to_end.py`

**Changes**:
- ✅ Natural numeric sort for page HTML files
- ✅ Added `page_sort_key` function using regex extraction

**Lines Changed**: ~8 lines

### 3. `backend/convert_to_formats.py`

**No new changes** - Already has correct language-aware logic from previous update:
- ✅ Detects `lang` attribute from HTML
- ✅ Only applies RTL for RTL languages
- ✅ English defaults to LTR

---

## How It Works Now

### Complete Flow:

**1. PDF Processing (main.py)**:
```
PDF → Gemini API → HTML with correct lang/dir
  Arabic PDF  → <html lang="ar" dir="rtl">...</html>
  English PDF → <html lang="en" dir="ltr">...</html>
```

**2. Page Ordering**:
```
Concurrent processing (any completion order):
  Page 5 done ✓
  Page 2 done ✓
  Page 1 done ✓
  Page 3 done ✓
  ...
  
Results collection & sorting:
  results.sort(by page_num) → [Page 1, Page 2, Page 3, ...]
  
HTML combination:
  sorted(page_*.html, key=numeric_sort) → page_1, page_2, page_3, ...
```

**3. Format Conversion (convert_to_formats.py)**:
```
HTML → detect lang attribute → determine is_rtl

If lang="ar":
  is_rtl = True
  → DOCX with RTL metadata
  → EPUB with RTL CSS + page-progression-direction=rtl

If lang="en":
  is_rtl = False
  → DOCX with default LTR
  → EPUB with default LTR
```

---

## Testing

### Test Case 1: Arabic PDF
```bash
python3 backend/convert_pdf_end_to_end.py arabic_pdfs --outdir output --extract-images --verbose
```

**Expected Output**:
- HTML: `<html lang="ar" dir="rtl">`
- Pages in order: 1, 2, 3, 4, ...
- DOCX: RTL direction
- EPUB: RTL with page-progression-direction=rtl

### Test Case 2: English PDF
```bash
python3 backend/convert_pdf_end_to_end.py english_pdfs --outdir output --extract-images --verbose
```

**Expected Output**:
- HTML: `<html lang="en" dir="ltr">`
- Pages in order: 1, 2, 3, 4, ...
- DOCX: LTR direction (default)
- EPUB: LTR (default)

### Test Case 3: Mixed Folder (Arabic + English)
```bash
python3 backend/convert_pdf_end_to_end.py mixed_pdfs --outdir output --extract-images --verbose
```

**Expected Output**:
- Each PDF processed with its own detected language
- Each output respects its source language direction
- All pages in correct order

---

## Verification Checklist

After running conversion, verify:

### Page Order
```bash
# Check page filenames are sorted correctly
ls -1 output/document_name/tmp_html/*_page_*.html

# Should show: page_1, page_2, page_3, ..., page_10, page_11 (numeric order)
# NOT: page_1, page_10, page_11, ..., page_2 (lexicographic)
```

### HTML Direction
```bash
# Check HTML lang and dir attributes
grep -i 'html.*lang.*dir' output/document_name/document_name.html

# Arabic: Should show <html lang="ar" dir="rtl">
# English: Should show <html lang="en" dir="ltr">
```

### DOCX Direction
- Open in Word
- Arabic: text should flow right-to-left, align right
- English: text should flow left-to-right, align left

### EPUB Direction
- Open in calibre or EPUB reader
- Arabic: pages flip right-to-left, text aligned right
- English: pages flip left-to-right, text aligned left

---

## Summary

**What's Fixed**:
✅ Page order preserved in concurrent processing (numeric sort)
✅ HTML has correct lang/dir based on content language
✅ DOCX respects language direction (RTL for Arabic, LTR for English)
✅ EPUB respects language direction with proper metadata

**No Configuration Needed**:
- Language detection is automatic
- Direction is set automatically
- Page ordering is automatic
- Just run the same command as before!

**Backward Compatible**:
- Existing Arabic PDFs: still work, still RTL
- New English PDFs: now correctly LTR
- Mixed documents: each handled correctly
