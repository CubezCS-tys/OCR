import fitz
import os
import json
from pathlib import Path


def extract_images_from_pdf(pdf_path: str, output_dir: str) -> dict:
    """
    Extract images embedded in a PDF using PyMuPDF (fitz).

    Writes image files to `output_dir` and returns a manifest dict with the
    structure: { 'pdf_name', 'pdf_stem', 'pages': [ { 'page_num': int, 'images': [ { 'filename','path','id','description' } ] } ] }
    """

    output_dir_p = Path(output_dir)
    output_dir_p.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    pdf_stem = Path(pdf_path).stem
    manifest = {
        'pdf_name': Path(pdf_path).name,
        'pdf_stem': pdf_stem,
        'num_pages': doc.page_count,
        'pages': []
    }

    total = 0
    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        image_list = page.get_images(full=True)
        page_images = []

        for img_index, img_info in enumerate(image_list):
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            image_data = base_image.get('image')
            image_extension = base_image.get('ext', 'png')

            filename = f"{pdf_stem}_page_{page_num + 1:03d}_img_{img_index + 1}.{image_extension}"
            filepath = output_dir_p / filename

            with open(filepath, 'wb') as f:
                f.write(image_data)

            entry = {
                'filename': filename,
                'path': str(filepath),
                'id': f'img_{page_num + 1}_{img_index + 1}',
                'description': f'Image extracted from page {page_num + 1} (index {img_index})'
            }
            page_images.append(entry)
            total += 1

        manifest['pages'].append({'page_num': page_num + 1, 'images': page_images})

    manifest['total_images_extracted'] = total
    manifest_path = output_dir_p / f"{pdf_stem}_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as mf:
        json.dump(manifest, mf, indent=2, ensure_ascii=False)

    print(f"Extracted {total} images to {output_dir_p}")
    return manifest


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Simple PyMuPDF image extractor')
    parser.add_argument('pdf', help='PDF file to extract')
    parser.add_argument('outdir', nargs='?', default='extracted_images', help='Output directory')
    args = parser.parse_args()
    extract_images_from_pdf(args.pdf, args.outdir)