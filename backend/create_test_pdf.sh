#!/usr/bin/env bash
# Create test_minimal.pdf with enough text (500+ words) for generation. Run from backend dir.
set -e
if [ -f test_minimal.pdf ]; then
  echo "test_minimal.pdf exists; overwriting with text version."
fi
if [ -x ./venv/bin/python ]; then
  ./venv/bin/python -c "
import pymupdf
doc = pymupdf.open()
page = doc.new_page()
t = 'The Indian Constitution is the supreme law of India. Polity and governance form the backbone. Economy and development are crucial. History provides context. Geography covers physical and human aspects. Science and technology drive progress. Environment and ecology are important. '
page.insert_text((50, 50), (t * 80)[:12000])
doc.save('test_minimal.pdf')
doc.close()
print('Created test_minimal.pdf with text (500+ words)')
"
else
  python3 -c "
try:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    t = 'The Indian Constitution is the supreme law of India. Polity and governance form the backbone. '
    page.insert_text((50, 50), (t * 100)[:12000])
    doc.save('test_minimal.pdf')
    doc.close()
    print('Created test_minimal.pdf with text')
except Exception:
    from PyPDF2 import PdfWriter
    w = PdfWriter()
    w.add_blank_page(612, 792)
    with open('test_minimal.pdf', 'wb') as f: w.write(f)
    print('Created blank test_minimal.pdf (generation will need 500+ words)')
"
fi
