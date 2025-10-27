from pdf2image import convert_from_path
import cv2
import numpy as np
from PIL import Image
import os
import sys
from dotenv import load_dotenv
try:
    from google import genai
except Exception:
    genai = None

def extract_figures_from_scanned_pdf(pdf_path="/home/cubez/Desktop/OCR/input_pdfs/0227-041-002-002.pdf", output_folder="extracted_images"):
    # Create output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)

    print(f"Converting PDF to images...")
    # Get poppler path for pdf2image
    # This assumes poppler is installed in a standard location like /usr/bin
    poppler_path = '/usr/bin' if sys.platform == 'linux' else None

    images = convert_from_path(pdf_path, dpi=300, poppler_path=poppler_path)  # Higher DPI for better detection

    print(f"Total pages: {len(images)}")
    figure_count = 0

    for page_num, img in enumerate(images):
        print(f"\nProcessing page {page_num + 1}...")

        # Convert PIL to OpenCV format
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

        # Apply thresholding to separate content from background
        _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)

        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        print(f"  Found {len(contours)} potential regions")

        # Filter contours by size and aspect ratio
        detected = 0
        for i, contour in enumerate(contours):
            area = cv2.contourArea(contour)

            # Filter by area (adjust these thresholds based on your PDFs)
            if area > 50000 and area < img.size[0] * img.size[1] * 0.8:  # Not too small, not whole page
                x, y, w, h = cv2.boundingRect(contour)
                aspect_ratio = w / h

                # Filter out text blocks (usually wide and short)
                # Keep figures/graphs (more square-ish or tall)
                if 0.3 < aspect_ratio < 3.0:  # Not extremely wide or tall
                    # Add padding around the figure
                    padding = 20
                    x_start = max(0, x - padding)
                    y_start = max(0, y - padding)
                    x_end = min(img.size[0], x + w + padding)
                    y_end = min(img.size[1], y + h + padding)

                    # Extract the region
                    figure = img_cv[y_start:y_end, x_start:x_end]

                    output_path = f'{output_folder}/page{page_num + 1}_figure{detected + 1}.png'
                    cv2.imwrite(output_path, figure)
                    print(f"  ✓ Extracted figure {detected + 1}: {w}x{h} pixels -> {output_path}")
                    detected += 1
                    figure_count += 1

        if detected == 0:
            print(f"  No figures detected on page {page_num + 1}")


    print(f"\n{'='*50}")
    print(f"Total figures extracted: {figure_count}")
    print(f"Check '{output_folder}' folder for results")
    return output_folder

def classify_image_with_gemini(image_path, model):
    """Classifies an image using the Gemini model."""
    prompt = "Classify this image as either 'figure', 'graph', 'table', or 'other'."
    uploaded = None
    try:
        # If this `model` looks like the genai Client (has .files and .models), use the upload+models.generate_content flow
        if hasattr(model, 'files') and hasattr(model, 'models'):
            try:
                uploaded = model.files.upload(file=image_path)
            except Exception as e:
                print(f"Failed to upload image {image_path} to model.files: {e}")
                return 'error'

            try:
                response = model.models.generate_content(model='gemini-2.5-flash', contents=[prompt, uploaded])
            except Exception as e:
                print(f"Model call failed for {image_path}: {e}")
                return 'error'
            finally:
                # Best-effort cleanup of uploaded file on the service
                try:
                    name = getattr(uploaded, 'name', None) or getattr(uploaded, 'uri', None)
                    if name:
                        try:
                            model.files.delete(name=name)
                        except Exception:
                            pass
                except Exception:
                    pass

        else:
            # If the provided object supports generate_content directly, use it
            if hasattr(model, 'generate_content'):
                try:
                    response = model.generate_content([prompt, Image.open(image_path)])
                except Exception:
                    try:
                        response = model.generate_content(prompt)
                    except Exception as e:
                        print(f"Model call failed for {image_path}: {e}")
                        return 'error'
            else:
                # Last-resort: try module-level genai.models.generate_content if available
                if 'genai' in globals() and genai is not None and hasattr(genai, 'models'):
                    try:
                        response = genai.models.generate_content(model='gemini-2.5-flash', contents=[prompt, Image.open(image_path)])
                    except Exception as e:
                        print(f"Model call failed for {image_path}: {e}")
                        return 'error'
                else:
                    print(f"No supported generate_content interface found for classification of {image_path}.")
                    return 'error'

        classification = getattr(response, 'text', str(response)).strip().lower()
        if 'figure' in classification:
            return 'figure'
        elif 'graph' in classification:
            return 'graph'
        elif 'table' in classification:
            return 'table'
        else:
            return 'other'
    except Exception as e:
        print(f"Error classifying image {image_path}: {e}")
        return 'error'


if __name__ == '__main__':
    # Run the extraction
    out_folder = extract_figures_from_scanned_pdf()

    # Collect extracted image files
    image_files = []
    for fname in sorted(os.listdir(out_folder)):
        if fname.lower().endswith(('.png', '.jpg', '.jpeg')):
            image_files.append(os.path.join(out_folder, fname))

    # Try to use an existing `model` if available in globals; otherwise, initialize a genai Client
    # using the same simple pattern as `main.py` (load .env, require GEMINI_API_KEY, call genai.Client()).
    model = globals().get('model', None)
    if model is None:
        # Ensure .env values are loaded (no-op if already loaded)
        try:
            load_dotenv()
        except Exception:
            pass

        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            print("Error: GEMINI_API_KEY not found in environment. Please create a .env file with GEMINI_API_KEY=your_key or export the variable in your shell.")
        else:
            if genai is None:
                print("google.genai package not available (import failed). Install the official Google GenAI SDK or provide a `model` object in globals.")
            else:
                try:
                    client = genai.Client()
                    model = client
                    print("Initialized Gemini Client; will call client.models.generate_content with 'gemini-2.5-flash'.")
                except Exception as e:
                    print(f"Error initializing genai.Client(): {e}\nProvide a `model` object in globals if you prefer custom initialization.")

    classified_images = []
    if model is not None:
        for image_path in image_files:
            classification = classify_image_with_gemini(image_path, model)
            classified_images.append({'image_path': image_path, 'classification': classification})
            print(f"Image: {image_path}, Classification: {classification}")
    else:
        print(f"Found {len(image_files)} extracted images but no model to classify them.")

    # classified_images now holds the classification results if run
    # ---- Post-processing: delete unwanted classes and embed remaining images into HTML ----
    def delete_and_embed(classified_images, drop_classes=None, images_folder='extracted_images', html_folder=None, embed_mode='replace'):
        """Delete images whose classification is in drop_classes and embed the remaining
        images into HTML files in html_folder.

        - drop_classes: list of class names to delete (e.g., ['table'])
        - images_folder: folder where images live (used to compute relative paths)
        - html_folder: folder containing HTML files to update; if None, attempts common locations
        - embed_mode: 'replace' to replace the first .image-placeholder, 'append' to append at end of body
        """
        if drop_classes is None:
            drop_classes = ['table']

        drop_set = set([c.strip().lower() for c in drop_classes])

        # Determine html folder default
        if html_folder is None:
            # prefer a common output dir used by main.py
            candidates = ['run4_sep_img', 'output_html', 'output']
            html_folder = next((d for d in candidates if os.path.isdir(d)), None)

        removed = []
        kept = []
        for item in classified_images:
            cls = item['classification']
            path = item['image_path']
            if cls in drop_set:
                try:
                    os.remove(path)
                    removed.append(path)
                    print(f"Removed (class={cls}): {path}")
                except Exception as e:
                    print(f"Failed to remove {path}: {e}")
            else:
                kept.append(item)

        # Embed kept images into HTMLs if html_folder available
        if html_folder and os.path.isdir(html_folder):
            print(f"Embedding {len(kept)} images into HTML files in: {html_folder}")
            import re

            for item in kept:
                img_path = item['image_path']
                # attempt to infer page number from filename e.g., page25_ or _page_25
                basename = os.path.basename(img_path)
                m = re.search(r'page[_-]?(\d+)', basename, re.IGNORECASE)
                page_num = None
                if m:
                    page_num = int(m.group(1))

                # find candidate HTML files for this page
                matched_html = None
                if page_num is not None:
                    # common patterns: *_page_{n}.html or *page_{n}.html
                    pattern1 = f"_page_{page_num}.html"
                    pattern2 = f"page_{page_num}.html"
                    pattern3 = f"page{page_num}_"
                    for fname in os.listdir(html_folder):
                        if fname.endswith('.html') and (pattern1 in fname or pattern2 in fname or pattern3 in fname):
                            matched_html = os.path.join(html_folder, fname)
                            break

                # fallback: pick the only html file if folder has one, else skip
                if matched_html is None:
                    html_files = [os.path.join(html_folder, f) for f in os.listdir(html_folder) if f.endswith('.html')]
                    if len(html_files) == 1:
                        matched_html = html_files[0]
                    elif len(html_files) == 0:
                        print(f"No HTML files found in {html_folder}; skipping embedding for {img_path}")
                        continue
                    else:
                        # multiple htmls and no page match — skip to avoid guessing
                        print(f"Multiple HTML files found but no match for page {page_num}; skipping embedding for {img_path}")
                        continue

                # Read and modify the HTML
                try:
                    with open(matched_html, 'r', encoding='utf-8') as f:
                        html = f.read()

                    rel_path = os.path.relpath(img_path, os.path.dirname(matched_html))
                    img_tag = f'<div class="image-placeholder"><img src="{rel_path}" alt="Figure"/></div>'

                    if embed_mode == 'replace' and 'class="image-placeholder"' in html:
                        # replace first placeholder div's inner text or entire div
                        html = re.sub(r'<div class="image-placeholder">.*?</div>', img_tag, html, count=1, flags=re.S)
                    else:
                        # append before </body> if present, else at end
                        if '</body>' in html:
                            html = html.replace('</body>', img_tag + '\n</body>')
                        else:
                            html = html + '\n' + img_tag

                    with open(matched_html, 'w', encoding='utf-8') as f:
                        f.write(html)

                    print(f"Embedded {basename} into {matched_html}")
                except Exception as e:
                    print(f"Failed to embed {img_path} into {matched_html}: {e}")
        else:
            if html_folder:
                print(f"HTML folder specified but not found: {html_folder}. Skipping embedding.")
            else:
                print("No HTML folder detected; skipping embedding step.")

        return {'removed': removed, 'kept': [k['image_path'] for k in kept]}

    # If script invoked directly with CLI, perform deletion/embedding based on args
    try:
        import argparse
        parser = argparse.ArgumentParser(description='Post-process classified images: delete and embed into HTML.')
        parser.add_argument('--images-folder', default='extracted_images', help='Folder with extracted images')
        parser.add_argument('--html-folder', default=None, help='Folder with HTML files (defaults to run4_sep_img/output_html)')
        parser.add_argument('--drop', default='table', help="Comma-separated classes to delete (default: 'table')")
        parser.add_argument('--embed-mode', choices=['replace', 'append'], default='replace', help='How to embed images into HTML')
        args = parser.parse_args()

        # If classified_images variable is empty (no model), build a simple list from images-folder
        if not classified_images:
            imgs = []
            if os.path.isdir(args.images_folder):
                for fn in sorted(os.listdir(args.images_folder)):
                    if fn.lower().endswith(('.png', '.jpg', '.jpeg')):
                        imgs.append({'image_path': os.path.join(args.images_folder, fn), 'classification': 'unknown'})
            classified_images = imgs

        drop_classes = [s.strip() for s in args.drop.split(',') if s.strip()]
        result = delete_and_embed(classified_images, drop_classes=drop_classes, images_folder=args.images_folder, html_folder=args.html_folder, embed_mode=args.embed_mode)
        print('Post-process result:', result)
    except Exception:
        # If argparse isn't appropriate in this context, skip interactive post-processing
        pass