# Pandoc and Page Break Preservation: Complete Guide

## TL;DR Answer: **YES, but with limitations**

Pandoc **can** preserve page breaks for 1:1 PDF recreation, but:
- ✅ Works well for **DOCX** (Word documents)
- ⚠️ Limited for **EPUB** (no hard page breaks in reflowable formats)
- ❌ Not applicable for **pure HTML** (web pages don't have pages)

## Current Situation in Your Pipeline

### What You Have Now:
```
PDF → Images → Gemini LLM → HTML (per-page OR whole document) → Pandoc → DOCX/EPUB
```

### Current Behavior:
- **Per-page mode (`--per-page`)**: Creates separate HTML files for each page
  - `page_1.html`, `page_2.html`, etc.
  - No page breaks needed (each file IS a page)
  
- **Whole-document mode**: Creates single HTML with all content
  - All pages concatenated into one HTML
  - **NO page break markers inserted**
  - Pandoc treats it as continuous content

## How to Add Page Breaks for 1:1 Recreation

### Option 1: CSS Page Breaks (For DOCX via Pandoc) ✅ RECOMMENDED

Add page break markers in your HTML between pages:

```html
<!-- End of Page 1 -->
<div style="page-break-after: always;"></div>

<!-- Start of Page 2 -->
<h1>Next Page Content</h1>
```

**Pandoc will respect these CSS page-break properties when converting to DOCX!**

### Implementation in main.py:

#### Step 1: Modify the whole-document processing
When NOT using `--per-page`, you need to insert page break markers between each page's content.

Currently, your main.py processes the whole PDF as one unit. You need to:

1. **Extract each page separately** (like per-page mode does)
2. **Generate HTML for each page** (with LLM)
3. **Merge them with page breaks** between each page
4. **Save as single HTML** with breaks
5. **Convert with pandoc**

#### Step 2: Add page break insertion function

```python
def insert_page_breaks_between_pages(page_htmls):
    """
    Combine multiple page HTML bodies with page breaks between them.
    
    Args:
        page_htmls: List of HTML strings (one per page)
    
    Returns:
        Single HTML string with page breaks
    """
    # Extract body content from each page HTML
    bodies = []
    for html in page_htmls:
        # Extract content between <body> and </body>
        match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
        if match:
            bodies.append(match.group(1))
    
    # Join with page break divs
    page_break = '\n<div style="page-break-after: always; break-after: page;"></div>\n'
    combined_body = page_break.join(bodies)
    
    # Wrap in complete HTML document
    # (Use the structure from first page, but replace body)
    first_html = page_htmls[0]
    
    # Replace body content with combined content
    result = re.sub(
        r'<body[^>]*>.*?</body>',
        f'<body dir="rtl">\n{combined_body}\n</body>',
        first_html,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    return result
```

### Option 2: Raw Pandoc Page Break Markers ✅ ALSO WORKS

Pandoc supports raw page breaks using special div syntax:

```html
<!-- End of Page 1 -->

<div class="page-break"></div>

<!-- Start of Page 2 -->
```

Then when calling pandoc, add custom filter or use:

```bash
pandoc input.html -o output.docx \
  --css page-breaks.css
```

Where `page-breaks.css` contains:
```css
.page-break {
    page-break-after: always;
    break-after: page;
}
```

### Option 3: Pandoc Custom Writer with Raw Breaks

Use Pandoc's `rawBlock` with explicit page breaks:

```html
<div class="page">
  <!-- Page 1 content -->
</div>

<!-- Raw page break for DOCX -->
```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```

<!-- Page 2 content -->
<div class="page">
  <!-- Page 2 content -->
</div>
```

This inserts actual Word XML page breaks that pandoc will preserve.

## Complete Implementation Example

### Enhanced Version of `convert_to_formats.py`:

```python
def add_page_breaks_to_html(html_path: Path, output_path: Path):
    """
    If HTML was generated per-page, this isn't needed.
    But if you want to merge per-page HTMLs into one document with breaks:
    """
    # This would be called if you want to merge page_1.html, page_2.html, etc.
    # into a single document.docx with proper page breaks
    
    # Read all page HTML files
    base_name = html_path.stem.replace('_page_1', '')
    page_files = sorted(html_path.parent.glob(f'{base_name}_page_*.html'))
    
    if not page_files:
        # Single file, no merging needed
        return html_path
    
    # Read all pages
    page_htmls = []
    for page_file in page_files:
        with open(page_file, 'r', encoding='utf-8') as f:
            page_htmls.append(f.read())
    
    # Merge with page breaks
    merged = insert_page_breaks_between_pages(page_htmls)
    
    # Save merged HTML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(merged)
    
    return output_path


def run_pandoc_with_page_breaks(input_html_path: Path, out_path: Path, format: str, **kwargs):
    """
    Enhanced pandoc runner that ensures page breaks are preserved.
    """
    # If converting to DOCX, ensure page breaks are respected
    if format == 'docx':
        # Add CSS that pandoc will convert to Word page breaks
        page_break_css = """
        <style>
        .page-break, [style*="page-break-after: always"] {
            page-break-after: always;
            break-after: page;
        }
        </style>
        """
        
        # Inject CSS into HTML if not already present
        with open(input_html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        if 'page-break-after' not in html_content and '.page-break' not in html_content:
            # Add page break CSS to head
            html_content = html_content.replace('</head>', f'{page_break_css}</head>')
            
            # Save modified HTML
            temp_html = input_html_path.parent / f'{input_html_path.stem}_with_breaks.html'
            with open(temp_html, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            input_html_path = temp_html
    
    # Call original pandoc function
    return run_pandoc(input_html_path, out_path, format, **kwargs)
```

## Practical Usage Scenarios

### Scenario 1: You use `--per-page` mode (current)

```bash
python backend/main.py --per-page input_pdfs/doc.pdf output_html/
```

**Result**: `page_1.html`, `page_2.html`, ..., `page_N.html`

**To get single DOCX with page breaks:**

```python
# NEW: Merge pages script
from pathlib import Path
import re

def merge_pages_to_single_docx(html_dir, output_docx):
    """Merge per-page HTMLs into single DOCX with page breaks"""
    
    # Find all page HTML files
    page_files = sorted(html_dir.glob('*_page_*.html'))
    
    # Read all pages
    page_contents = []
    for page_file in page_files:
        with open(page_file, 'r', encoding='utf-8') as f:
            html = f.read()
            # Extract body content
            match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
            if match:
                page_contents.append(match.group(1).strip())
    
    # Create merged HTML with page breaks
    page_break = '<div style="page-break-after: always;"></div>'
    merged_body = f'\n{page_break}\n'.join(page_contents)
    
    # Use first page as template
    with open(page_files[0], 'r', encoding='utf-8') as f:
        template = f.read()
    
    # Replace body with merged content
    merged_html = re.sub(
        r'(<body[^>]*>).*?(</body>)',
        rf'\1\n{merged_body}\n\2',
        template,
        flags=re.DOTALL
    )
    
    # Save merged HTML
    merged_html_path = html_dir / 'merged_with_breaks.html'
    with open(merged_html_path, 'w', encoding='utf-8') as f:
        f.write(merged_html)
    
    # Convert to DOCX
    from convert_to_formats import run_pandoc
    run_pandoc(merged_html_path, output_docx, 'docx')
    
    print(f"✅ Created {output_docx} with {len(page_files)} pages")

# Usage:
merge_pages_to_single_docx(Path('output_html/doc'), Path('output_html/doc.docx'))
```

### Scenario 2: Whole-document mode (no `--per-page`)

```bash
python backend/main.py input_pdfs/doc.pdf output_html/
```

**Current behavior**: Single HTML with all content, no page breaks

**To add page breaks**: Modify main.py to process page-by-page internally but merge with breaks

## Testing Page Breaks

### Test 1: Verify CSS page breaks work

```bash
# Create test HTML with explicit page breaks
cat > test_pagebreaks.html << 'EOF'
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="utf-8"></head>
<body>
<h1>Page 1</h1>
<p>Content of first page</p>

<div style="page-break-after: always;"></div>

<h1>Page 2</h1>
<p>Content of second page</p>

<div style="page-break-after: always;"></div>

<h1>Page 3</h1>
<p>Content of third page</p>
</body>
</html>
EOF

# Convert to DOCX
pandoc test_pagebreaks.html -o test_pagebreaks.docx

# Open in Word - should see 3 separate pages!
```

### Test 2: Verify with your actual pipeline

```bash
# Generate per-page HTMLs
python backend/main.py --per-page input_pdfs/test.pdf output_html/

# Merge with page breaks (using script above)
python merge_pages.py output_html/test/ output_html/test_merged.docx

# Check DOCX - should have same number of pages as PDF
```

## Limitations and Caveats

### ✅ What Works:
- **DOCX**: Page breaks are fully supported and respected
- **Printed PDF from HTML**: CSS page breaks work for print media
- **RTL content**: Page breaks work with RTL text direction

### ⚠️ Partial Support:
- **EPUB**: Some e-readers support page breaks, but EPUB is meant to be "reflowable"
  - Use `<div class="page-break"></div>` but don't expect exact page matching
  - Better to use chapter breaks instead

### ❌ Doesn't Work:
- **HTML in browser**: Browsers don't have "pages" (except when printing)
- **Markdown**: No page break concept (unless using specific extensions)

## Recommended Approach for Your Pipeline

### For Perfect 1:1 PDF Recreation:

```
1. Use --per-page mode
   ↓
2. Generate one HTML per page
   ↓
3. For DOCX: Merge HTMLs with CSS page breaks
   ↓
4. Convert with pandoc
   ↓
5. Result: DOCX with same page count as original PDF
```

### Implementation Priority:

1. **HIGH PRIORITY**: Add page break insertion when merging per-page HTMLs
2. **MEDIUM PRIORITY**: Test with various documents to ensure breaks appear correctly
3. **LOW PRIORITY**: Add option to control page break style (CSS vs raw OpenXML)

## Code to Add to Your Pipeline

Create a new file `backend/merge_pages_with_breaks.py`:

```python
#!/usr/bin/env python3
"""
Merge per-page HTML files into single document with page breaks.
Useful for creating Word documents that match PDF pagination exactly.
"""

import argparse
import re
from pathlib import Path
from convert_to_formats import run_pandoc

def extract_body_content(html_text):
    """Extract content between <body> tags"""
    match = re.search(r'<body[^>]*>(.*?)</body>', html_text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else html_text

def merge_html_pages_with_breaks(page_files, output_html, page_break_style='css'):
    """
    Merge multiple HTML page files into single HTML with page breaks.
    
    Args:
        page_files: List of Path objects to HTML files
        output_html: Path to save merged HTML
        page_break_style: 'css' or 'openxml' or 'both'
    """
    if not page_files:
        print("No page files to merge")
        return None
    
    # Read all page contents
    page_contents = []
    for page_file in page_files:
        with open(page_file, 'r', encoding='utf-8') as f:
            html = f.read()
            body = extract_body_content(html)
            page_contents.append(body)
    
    # Define page break based on style
    if page_break_style == 'css':
        page_break = '<div style="page-break-after: always; break-after: page;"></div>'
    elif page_break_style == 'openxml':
        # Raw OpenXML for Word (pandoc will preserve this)
        page_break = '```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```'
    else:  # both
        page_break = '''<div style="page-break-after: always; break-after: page;"></div>
```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```'''
    
    # Join with page breaks
    merged_body = f'\n\n{page_break}\n\n'.join(page_contents)
    
    # Use first page as template for <head> and structure
    with open(page_files[0], 'r', encoding='utf-8') as f:
        template = f.read()
    
    # Replace body content with merged content
    merged_html = re.sub(
        r'(<body[^>]*>).*?(</body>)',
        rf'\1\n{merged_body}\n\2',
        template,
        flags=re.DOTALL
    )
    
    # Add page break CSS to head if using CSS style
    if page_break_style in ['css', 'both']:
        page_break_css = '''
    <style>
    [style*="page-break-after: always"] {
        page-break-after: always;
        break-after: page;
    }
    </style>'''
        merged_html = merged_html.replace('</head>', f'{page_break_css}\n</head>')
    
    # Save merged HTML
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(merged_html)
    
    print(f"✅ Merged {len(page_files)} pages into {output_html}")
    return output_html

def main():
    parser = argparse.ArgumentParser(description='Merge per-page HTMLs with page breaks')
    parser.add_argument('html_dir', help='Directory containing page_N.html files')
    parser.add_argument('--output', '-o', help='Output DOCX file')
    parser.add_argument('--page-break-style', choices=['css', 'openxml', 'both'], 
                        default='css', help='Page break style (default: css)')
    parser.add_argument('--html-only', action='store_true', 
                        help='Only create merged HTML, do not convert to DOCX')
    
    args = parser.parse_args()
    
    html_dir = Path(args.html_dir)
    
    # Find all page HTML files
    page_files = sorted(html_dir.glob('*_page_*.html'))
    
    if not page_files:
        print(f"❌ No page HTML files found in {html_dir}")
        return
    
    print(f"Found {len(page_files)} page files")
    
    # Determine output paths
    base_name = page_files[0].stem.replace('_page_1', '')
    merged_html = html_dir / f'{base_name}_merged_with_breaks.html'
    
    # Merge pages
    merged_html = merge_html_pages_with_breaks(page_files, merged_html, args.page_break_style)
    
    if not merged_html:
        return
    
    if args.html_only:
        print(f"✅ Created merged HTML: {merged_html}")
        return
    
    # Convert to DOCX
    if args.output:
        output_docx = Path(args.output)
    else:
        output_docx = html_dir / f'{base_name}.docx'
    
    print(f"Converting to DOCX: {output_docx}")
    success = run_pandoc(merged_html, output_docx, 'docx')
    
    if success:
        print(f"✅ Created {output_docx} with {len(page_files)} pages")
    else:
        print(f"❌ Failed to convert to DOCX")

if __name__ == '__main__':
    main()
```

### Usage:

```bash
# After running per-page OCR:
python backend/main.py --per-page input_pdfs/document.pdf output_html/

# Merge pages into single DOCX with page breaks:
python backend/merge_pages_with_breaks.py output_html/document/ -o output_html/document.docx

# Or just create merged HTML:
python backend/merge_pages_with_breaks.py output_html/document/ --html-only
```

## Conclusion

**Yes, pandoc CAN respect page breaks for 1:1 PDF recreation!**

✅ **Best approach**: 
1. Process PDF per-page (`--per-page`)
2. Merge HTML files with CSS page breaks
3. Convert to DOCX with pandoc
4. Result: Word document with same page structure as original PDF

This gives you the best of both worlds:
- Per-page processing for accuracy
- Single output document for convenience
- Exact page breaks matching original PDF
