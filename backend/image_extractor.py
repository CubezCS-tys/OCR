import fitz

pdf_path = "/home/k22015806/Desktop/OCR/input_pdfs/1749-000-022-008 (2).pdf"
doc = fitz.open(pdf_path)

extracted_images = []

for page_num in range(doc.page_count):
    page = doc.load_page(page_num)
    image_list = page.get_images(full=True)

    for img_index, img_info in enumerate(image_list):
        xref = img_info[0]
        base_image = doc.extract_image(xref)
        image_data = base_image["image"]
        image_extension = base_image["ext"]

        extracted_images.append({
            "page_number": page_num,
            "image_index_on_page": img_index,
            "image_data": image_data,
            "image_extension": image_extension
        })

print(f"Extracted {len(extracted_images)} images.")

import os

output_dir = "extracted_images"
os.makedirs(output_dir, exist_ok=True)

for image_info in extracted_images:
    page_num = image_info["page_number"]
    img_index = image_info["image_index_on_page"]
    image_data = image_info["image_data"]
    image_extension = image_info["image_extension"]

    filename = f"page_{page_num}_image_{img_index}.{image_extension}"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "wb") as f:
        f.write(image_data)