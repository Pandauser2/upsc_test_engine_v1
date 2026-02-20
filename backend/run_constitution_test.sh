#!/usr/bin/env bash
# Upload constitution PDF, wait for extraction, generate 2 questions, print result.
set -e
PORT="${1:-8000}"
BASE="http://127.0.0.1:$PORT"
PDF="${2:-constitution_with_text.pdf}"
EMAIL="constitution_test_$(date +%s)@example.com"

echo "Register $EMAIL"
curl -sf -X POST "$BASE/auth/register" -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\",\"password\":\"testpass123\"}" > /dev/null
echo "Login"
TOKEN=$(curl -sf -X POST "$BASE/auth/login" -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\",\"password\":\"testpass123\"}" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Upload $PDF"
DOC=$(curl -sf -X POST "$BASE/documents/upload" -H "Authorization: Bearer $TOKEN" -F "file=@$PDF")
DOC_ID=$(echo "$DOC" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Doc ID: $DOC_ID"
for i in $(seq 1 15); do
  sleep 2
  D=$(curl -sf "$BASE/documents/$DOC_ID" -H "Authorization: Bearer $TOKEN")
  ST=$(echo "$D" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  echo "  status: $ST"
  [ "$ST" = "ready" ] && break
  [ "$ST" = "extraction_failed" ] && { echo "Extraction failed"; exit 1; }
done
[ "$ST" != "ready" ] && { echo "Timeout"; exit 1; }
echo "Generate 2 questions"
GEN=$(curl -sf -X POST "$BASE/tests/generate" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"document_id\":\"$DOC_ID\",\"num_questions\":2,\"difficulty\":\"MEDIUM\"}")
TEST_ID=$(echo "$GEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Test ID: $TEST_ID"
for i in $(seq 1 24); do
  sleep 5
  T=$(curl -sf "$BASE/tests/$TEST_ID" -H "Authorization: Bearer $TOKEN")
  STATUS=$(echo "$T" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  echo "  poll $i: status=$STATUS"
  [ "$STATUS" = "completed" ] || [ "$STATUS" = "partial" ] && break
  [ "$STATUS" = "failed" ] && { echo "Generation failed"; echo "$T" | python3 -m json.tool 2>/dev/null || echo "$T"; exit 1; }
done
echo ""
echo "=== GENERATED QUESTIONS ==="
echo "$T" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for i, q in enumerate(d.get('questions', [])[:2], 1):
    print(f\"Q{i}. {q.get('question','')}\")
    opts = q.get('options') or []
    if isinstance(opts, list):
        for o in opts:
            print(f\"   {o.get('label','')}: {o.get('text','')}\")
    else:
        for k, v in opts.items():
            print(f\"   {k}: {v}\")
    print(f\"   Correct: {q.get('correct_option','')}\")
    print(f\"   Explanation: {(q.get('explanation') or '')[:200]}...\")
    print()
"
