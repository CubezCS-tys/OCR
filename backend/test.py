from HocrConverter import HocrConverter


hocr = HocrConverter("/home/cubez/Desktop/OCR/backend/Final/0889-012-135-004/0889-012-135-004.html")  # this can be done by changing .hocr to .html and vice versa
hocr.to_text("output.txt")
hocr.to_pdf("/home/cubez/Desktop/OCR/input_pdfs/0889-012-135-004.png", "output.pdf")