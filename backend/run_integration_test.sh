#!/usr/bin/env bash
# Integration test against local server. Usage: ./run_integration_test.sh [PORT]
# Default port 8001. Server must already be running.
set -e
PORT="${1:-8001}"
BASE="http://127.0.0.1:$PORT"
echo "Testing $BASE ..."

# 1. Health
curl -sf "$BASE/" > /dev/null && echo "OK GET /" || { echo "FAIL GET /"; exit 1; }

# 2. Register (unique email so script is repeatable)
EMAIL="inttest_$(date +%s)@example.com"
REG=$(curl -sf -X POST "$BASE/auth/register" -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\",\"password\":\"testpass123\"}")
echo "OK POST /auth/register"

# 3. Login
LOGIN=$(curl -sf -X POST "$BASE/auth/login" -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\",\"password\":\"testpass123\"}")
TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "OK POST /auth/login"

# 4. Topics
curl -sf "$BASE/topics" -H "Authorization: Bearer $TOKEN" > /dev/null && echo "OK GET /topics" || { echo "FAIL GET /topics"; exit 1; }

# 5. Create document via PDF upload (paste endpoint removed)
[ -x ./create_test_pdf.sh ] && ./create_test_pdf.sh
if [ ! -f test_minimal.pdf ]; then
  python3 -c "
try:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    t = 'The Indian Constitution is the supreme law of India. Polity and governance form the backbone. Economy and development are crucial. History provides context. Geography covers physical and human aspects. Science and technology drive progress. Environment and ecology are important. '
    page.insert_text((50, 50), (t * 80)[:12000])
    doc.save('test_minimal.pdf')
    doc.close()
except Exception:
    from PyPDF2 import PdfWriter
    w = PdfWriter()
    w.add_blank_page(612, 792)
    with open('test_minimal.pdf', 'wb') as f: w.write(f)
"
fi
DOC=$(curl -sf -X POST "$BASE/documents/upload" -H "Authorization: Bearer $TOKEN" -F "file=@test_minimal.pdf")
DOC_ID=$(echo "$DOC" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "OK POST /documents/upload -> $DOC_ID"
# Wait for extraction to finish (poll doc status)
for i in $(seq 1 12); do
  sleep 2
  D=$(curl -sf "$BASE/documents/$DOC_ID" -H "Authorization: Bearer $TOKEN")
  ST=$(echo "$D" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  echo "  doc status: $ST"
  [ "$ST" = "ready" ] && break
  [ "$ST" = "extraction_failed" ] && echo "WARN extraction_failed; generation may fail"
done

# 6. Start generation (num_questions and difficulty required)
GEN=$(curl -sf -X POST "$BASE/tests/generate" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"document_id\":\"$DOC_ID\",\"num_questions\":3,\"difficulty\":\"MEDIUM\"}")
TEST_ID=$(echo "$GEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "OK POST /tests/generate -> $TEST_ID"

# 7. Poll until completed or 90s
for i in $(seq 1 18); do
  sleep 5
  T=$(curl -sf "$BASE/tests/$TEST_ID" -H "Authorization: Bearer $TOKEN")
  STATUS=$(echo "$T" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  NQ=$(echo "$T" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('questions',[])))")
  echo "  poll $i: status=$STATUS questions=$NQ"
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "partial" ]; then
    echo "OK Test finished with status=$STATUS, questions=$NQ"
    exit 0
  fi
  if [ "$STATUS" = "failed" ]; then
    echo "FAIL Test failed"
    exit 1
  fi
done
echo "TIMEOUT Test still generating after 90s"
exit 1
