"""
Deprecated: This script tested Anthropic Message Batches API.
The project now uses Gemini only for MCQ generation. Use tests/test_tests_api.py
to validate the test generation endpoint (POST /tests/generate).
"""
import sys

if __name__ == "__main__":
    print("Deprecated: LLM is Gemini-only. Use pytest tests/test_tests_api.py to test the generate endpoint.", file=sys.stderr)
    sys.exit(0)
