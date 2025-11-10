#!/usr/bin/env python3
"""
Quick test to demonstrate pandoc page break preservation.
Creates a simple multi-page HTML and converts to DOCX with page breaks.
"""

from pathlib import Path

# Create test directory
test_dir = Path('test_page_breaks')
test_dir.mkdir(exist_ok=True)

# Create a 3-page test HTML
test_html = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="utf-8">
    <style>
        body {
            font-family: 'Amiri', serif;
            max-width: 800px;
            margin: 40px auto;
            padding: 20px;
            background: #fff;
            color: #000;
            line-height: 1.8;
        }
        h1 {
            color: #2c3e50;
            font-size: 1.8em;
            border-bottom: 2px solid #3498db;
            margin-bottom: 1em;
        }
        .page-break {
            page-break-after: always;
            break-after: page;
            height: 0;
            margin: 0;
            padding: 0;
        }
        @media print {
            .page-break {
                page-break-after: always;
            }
        }
    </style>
</head>
<body dir="rtl">

<!-- ═══ PAGE 1 ═══ -->
<h1>الصفحة الأولى</h1>
<p>هذا هو محتوى الصفحة الأولى من المستند.</p>
<p>يحتوي على عدة فقرات من النص العربي.</p>
<p>والمعادلة الرياضية: $x^2 + y^2 = z^2$</p>

<div class="page-break" style="page-break-after: always; break-after: page;"></div>

<!-- ═══ PAGE 2 ═══ -->
<h1>الصفحة الثانية</h1>
<p>هذا هو محتوى الصفحة الثانية.</p>
<p>يجب أن تظهر في صفحة منفصلة في مستند Word.</p>
<ul>
    <li>عنصر القائمة 1</li>
    <li>عنصر القائمة 2</li>
    <li>عنصر القائمة 3</li>
</ul>

<div class="page-break" style="page-break-after: always; break-after: page;"></div>

<!-- ═══ PAGE 3 ═══ -->
<h1>الصفحة الثالثة</h1>
<p>هذا هو محتوى الصفحة الثالثة والأخيرة.</p>
<table border="1" style="border-collapse: collapse; width: 100%; margin: 1.5em 0;">
    <thead>
        <tr>
            <th style="padding: 8px; background: #d3d3d3;">العمود 1</th>
            <th style="padding: 8px; background: #d3d3d3;">العمود 2</th>
            <th style="padding: 8px; background: #d3d3d3;">العمود 3</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td style="padding: 8px;">قيمة 1</td>
            <td style="padding: 8px;">قيمة 2</td>
            <td style="padding: 8px;">قيمة 3</td>
        </tr>
        <tr>
            <td style="padding: 8px;">قيمة 4</td>
            <td style="padding: 8px;">قيمة 5</td>
            <td style="padding: 8px;">قيمة 6</td>
        </tr>
    </tbody>
</table>

</body>
</html>"""

# Save test HTML
test_html_path = test_dir / 'test_3pages_with_breaks.html'
with open(test_html_path, 'w', encoding='utf-8') as f:
    f.write(test_html)

print(f"✅ Created test HTML: {test_html_path}")
print(f"\n📝 Now converting to DOCX with pandoc...")
print(f"   Run: pandoc {test_html_path} -o {test_dir}/test_output.docx --from=html+tex_math_dollars --metadata lang=ar --metadata dir=rtl")
print(f"\n💡 Or use the convert_to_formats.py script:")
print(f"   python backend/convert_to_formats.py {test_html_path} {test_dir}/test_output.docx --lang ar")
print(f"\n📂 Test directory: {test_dir.absolute()}")
