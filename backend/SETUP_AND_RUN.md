# How to Start the Backend Server (Step by Step) — Mac

Follow these steps exactly. Do them in order.

---

## Step 1: Open Terminal

Open **Terminal** (Applications → Utilities → Terminal, or press `Cmd + Space`, type `Terminal`, press Enter). You should see a prompt (e.g. `%`).

---

## Step 2: Go to the Backend Folder

Type this command and press **Enter** (replace the path with your actual project path if different):

```bash
cd upsc-test-engine/backend
```

If your project is somewhere else, use the full path, for example:

```bash
cd /Users/rajeshmukherjee/Desktop/04_Data_Science/Projects/datascience_2025/Cursor_test_project/upsc-test-engine/backend
```

Check that you are in the right place: run `ls`. You should see files like `requirements.txt`, `start_server.sh`, and a folder named `app`.

---

## Step 3: Create a Virtual Environment (First Time Only)

A virtual environment keeps this project’s Python packages separate from the rest of your system.

Run:

```bash
python3 -m venv venv
```

(On some systems the command is `python -m venv venv`. If `python3` says "command not found", try `python`.)

This creates a folder called `venv` in the backend directory. You only need to do this once per project.

---

## Step 4: Activate the Virtual Environment

```bash
source venv/bin/activate
```

When it’s active, your prompt usually starts with `(venv)`, for example: `(venv) %`.

---

## Step 5: Install Dependencies

With the virtual environment still active, run:

```bash
pip install -r requirements.txt
```

Wait until it finishes. If you see any red error messages, read them; often they say a tool (e.g. Python or pip) is missing or the wrong version.

**Optional — OCR for image-only PDF pages:** If PDFs have pages that are images (e.g. scanned docs, infographics), install Tesseract so the app can run OCR on those pages. On Mac: `brew install tesseract`. Without it, image-only pages yield no text (extraction still works for text-layer pages).

---

## Step 6: Create a `.env` File (Optional but Recommended)

The app can run without a `.env` file (it will use defaults and mock LLM). To set your own config (e.g. Claude API key):

1. In the same `backend` folder, create a file named exactly `.env` (with the dot at the start).
2. Add one line per setting. For example:

```env
CLAUDE_API_KEY=sk-ant-your-key-here
```

Replace `sk-ant-your-key-here` with your real API key from [console.anthropic.com](https://console.anthropic.com).  
You can also set things like `DATABASE_URL`, `SECRET_KEY`, etc., if you need them later.

Save the file in the `backend` folder (same folder as `requirements.txt`).

---

## Step 7: Start the Server

With the virtual environment still active and your current directory still `backend`, run:

```bash
./start_server.sh
```

Or manually:

```bash
pip install -q -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

You should see something like:

```text
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

That means the server is running. Leave this terminal open; closing it will stop the server.

---

## Step 8: Test That It’s Working

Open a **new** terminal (or a browser):

1. **Browser:** Go to: **http://localhost:8000**  
   You should see something like: `{"status":"ok","message":"UPSC Test Engine API"}`.

2. **API docs:** Go to: **http://localhost:8000/docs**  
   You should see the Swagger UI with endpoints like `/auth/register`, `/auth/login`, `/topics`, `/tests/...`.

---

## Step 9: Stop the Server

In the terminal where the server is running, press **Ctrl + C**. The server will stop.

---

## Quick Checklist

- [ ] Terminal open  
- [ ] `cd` into `upsc-test-engine/backend`  
- [ ] `python3 -m venv venv` (first time only)  
- [ ] `source venv/bin/activate`  
- [ ] `pip install -r requirements.txt`  
- [ ] (Optional) Create `backend/.env` with `CLAUDE_API_KEY=...`  
- [ ] `./start_server.sh`  
- [ ] Open http://localhost:8000 or http://localhost:8000/docs to test  

## How to test on your end

### 1. Start the server

From the **backend** folder, with the virtual environment activated:

```bash
./start_server.sh
```

Or: `python -m uvicorn app.main:app --reload --port 8000`

Leave this terminal open. The API will be at **http://localhost:8000**.

---

### 2. Quick health check

- **Browser:** Open **http://localhost:8000** — you should see `{"status":"ok","message":"UPSC Test Engine API"}`.
- **API docs:** Open **http://localhost:8000/docs** — Swagger UI with all endpoints.

---

### 3. Test via Swagger UI (recommended)

1. Open **http://localhost:8000/docs**.
2. **Register:** `POST /auth/register` — body e.g. `{"email":"you@example.com","password":"yourpassword"}`.
3. **Login:** `POST /auth/login` — same body → copy the `access_token` from the response.
4. **Authorize:** Click **Authorize**, paste `Bearer <your_access_token>`, then **Authorize**.
5. **Upload a PDF:** `POST /documents/upload` — choose a PDF file (must have **at least 500 words** of extractable text for generation).
6. **Get document ID:** From the upload response, copy `id`.
7. **Wait for extraction:** Call `GET /documents/{document_id}` until `status` is `ready` (or `extraction_failed`).
8. **Generate questions:** `POST /tests/generate` — body `{"document_id":"<id>","num_questions":2}`.
9. **Get test:** `GET /tests/{test_id}` from the generate response — poll until `status` is `completed` (or `partial`), then read `questions`.

**Note:** Generation requires the document to have at least **500 words** of extracted text (config: `MIN_EXTRACTION_WORDS` in `.env`). If your PDF has less, you’ll get a 400 error. Use a real PDF with plenty of text (e.g. a chapter or article), or for a quick test set `MIN_EXTRACTION_WORDS=200` in `.env` and restart the server.

---

### 4. Test via integration script

With the server running (e.g. on port 8000), open **another terminal**:

```bash
cd upsc-test-engine/backend
./run_integration_test.sh 8000
```

This will: register a new user, create a test PDF if missing, upload it, wait for extraction, start generation (3 questions), and poll until the test completes (about 1–2 minutes with mock LLM). If you see **"500 words required"**, use a real PDF with 500+ words of text, or set `MIN_EXTRACTION_WORDS=200` in `.env` and restart the server for a quick test.

---

### 5. Optional: OCR for image-only PDFs

If your PDFs are **scans or image-only pages**, install **Tesseract** so the app can run OCR on those pages:

- **Mac:** `brew install tesseract`
- **Linux:** `sudo apt install tesseract-ocr` (or equivalent)

Without Tesseract, image-only pages stay empty; text-layer PDFs work as before. The app does not crash if Tesseract is missing.

---

### 6. Local extraction test (no server)

To check that PDF extraction (and optional OCR) works without starting the server:

```bash
cd upsc-test-engine/backend
./venv/bin/python test_extraction_local.py
```

This runs: missing file → error; text PDF → extracted text; blank PDF → no crash (OCR fallback may run).

---

## If Something Goes Wrong

- **“python3: command not found”**  
  Install Python 3 (e.g. from [python.org](https://www.python.org/downloads/)) or try `python` instead of `python3`.

- **“No module named 'app'” or “No module named 'uvicorn'”**  
  Make sure you are in the `backend` directory and the virtual environment is activated, then run `pip install -r requirements.txt` again.

- **“Address already in use”**  
  Port 8000 is in use. Stop the other program using it, or run on another port:  
  `python -m uvicorn app.main:app --reload --port 8001`  
  Then use http://localhost:8001.

- **“.env not loading”**  
  Put `.env` in the `backend` folder (same folder as `requirements.txt` and `app/`).
