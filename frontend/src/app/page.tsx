"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  apiDocsUrl,
  authLogin,
  authMe,
  authRegister,
  documentGet,
  documentUpload,
  documentsList,
  getApiBase,
  referenceQpUpload,
  type DocumentDetailResponse,
  type DocumentResponse,
  type TestDetailResponse,
  type TestResponse,
  testGet,
  testsGenerate,
} from "@/lib/api";

const TOKEN_KEY = "upsc_test_engine_token";
const TERMINAL_TEST = new Set([
  "completed",
  "partial",
  "failed",
  "failed_timeout",
]);

function optionsEntries(
  opts: Record<string, string> | Array<{ label: string; text: string }>
): [string, string][] {
  if (Array.isArray(opts)) {
    return opts.map((o) => [String(o.label).toUpperCase(), o.text] as [string, string]);
  }
  return (Object.entries(opts) as [string, string][])
    .filter(([k]) => /^[A-E]$/i.test(k))
    .map(([k, v]) => [k.toUpperCase(), v] as [string, string])
    .sort(([a], [b]) => a.localeCompare(b));
}

/** Avoid splitting huge strings on every render (main-thread cost). */
function approximateWordCount(text: string | null | undefined): number {
  if (!text?.trim()) return 0;
  if (text.length > 400_000) return Math.max(1, Math.round(text.length / 5));
  return text.split(/\s+/).filter(Boolean).length;
}

function normalizedCorrectOption(raw: string | null | undefined): string {
  const s = (raw ?? "A").toString().trim().toUpperCase();
  return /^[A-E]$/.test(s) ? s : "A";
}

/** Drop huge extracted_text from React state (JSON + reconciliation freezes the UI). */
const MAX_EXTRACTED_TEXT_IN_STATE = 60_000;

function normalizeDocumentDetail(d: DocumentDetailResponse): {
  detail: DocumentDetailResponse;
  wordCount: number;
} {
  const raw = d.extracted_text;
  const wordCount = approximateWordCount(raw);
  if (raw == null || raw.length <= MAX_EXTRACTED_TEXT_IN_STATE) {
    return { detail: d, wordCount };
  }
  return { detail: { ...d, extracted_text: undefined }, wordCount };
}

function extractionProgressPercent(doc: DocumentDetailResponse | null): number {
  if (!doc) return 0;
  const status = (doc.status || "").toLowerCase();
  if (status === "ready" || status === "completed") return 100;
  if (status === "failed" || status === "extraction_failed" || status === "rejected") return 0;
  if (status !== "processing") return 0;
  const totalPages = Number(doc.total_pages ?? 0);
  const progressPage = Number(doc.progress_page ?? 0);
  if (Number.isFinite(totalPages) && totalPages > 0) {
    const ratio = Math.max(0, Math.min(1, progressPage / totalPages));
    return Math.min(95, Math.round(ratio * 100));
  }
  return 0;
}

function generationProgressPercent(test: TestResponse | null): number {
  if (!test) return 0;
  const status = (test.status || "").toLowerCase();
  if (status === "completed") return 100;
  if (status === "failed" || status === "failed_timeout") return 0;
  const total = Number(test.total_mcq ?? 0);
  const done = Number(test.progress_mcq ?? 0);
  if (!Number.isFinite(total) || total <= 0) return 0;
  const ratio = Math.max(0, Math.min(1, done / total));
  const pct = Math.round(ratio * 100);
  if (status === "generating" || status === "pending" || status === "processing") {
    return Math.min(95, pct);
  }
  return pct;
}

export default function Home() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [userLabel, setUserLabel] = useState<string | null>(null);

  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [docDetail, setDocDetail] = useState<DocumentDetailResponse | null>(null);
  const [docWordCount, setDocWordCount] = useState(0);

  const [file, setFile] = useState<File | null>(null);
  /** Remount file input after upload so the same PDF can be chosen again if needed. */
  const [fileInputKey, setFileInputKey] = useState(0);

  const [genNumQ, setGenNumQ] = useState<number>(5);
  const [genDifficulty, setGenDifficulty] = useState<"EASY" | "MEDIUM" | "HARD">("MEDIUM");
  const [referenceQpHash, setReferenceQpHash] = useState<string | null>(null);
  const [referenceQpBusy, setReferenceQpBusy] = useState(false);

  const [testSummary, setTestSummary] = useState<TestResponse | null>(null);
  const [testDetail, setTestDetail] = useState<TestDetailResponse | null>(null);

  const [listError, setListError] = useState<string | null>(null);
  const [documentDetailError, setDocumentDetailError] = useState<string | null>(null);
  const [docPollWarning, setDocPollWarning] = useState<string | null>(null);
  const [testPollWarning, setTestPollWarning] = useState<string | null>(null);
  const [busyUpload, setBusyUpload] = useState(false);
  const [busyGenerate, setBusyGenerate] = useState(false);
  /** Last explicit auth action (for password manager hints). */
  const [lastAuthAction, setLastAuthAction] = useState<"login" | "register" | null>(null);

  const docPollFailsRef = useRef(0);
  const testPollFailsRef = useRef(0);
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const selectedDocIdRef = useRef(selectedDocId);
  selectedDocIdRef.current = selectedDocId;

  const clearFeedback = () => {
    setMessage(null);
    setError(null);
  };

  const isGenerationInProgress = (() => {
    const s = (testSummary?.status || "").toLowerCase();
    return s === "pending" || s === "generating";
  })();

  const withErr = async (fn: () => Promise<void>) => {
    clearFeedback();
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const refreshDocuments = useCallback(async (t: string) => {
    const list = await documentsList(t);
    setDocuments(list.items);
    setListError(null);
  }, []);

  useEffect(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
    if (!saved) return;
    setToken(saved);
    authMe(saved)
      .then((u) => setUserLabel(`${u.email} (${u.role})`))
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
      });
  }, []);

  useEffect(() => {
    if (!token) {
      setListError(null);
      return;
    }
    let cancelled = false;
    refreshDocuments(token).catch((e) => {
      if (!cancelled) setListError(e instanceof Error ? e.message : String(e));
    });
    return () => {
      cancelled = true;
    };
  }, [token, refreshDocuments]);

  useEffect(() => {
    docPollFailsRef.current = 0;
    setDocPollWarning(null);
  }, [selectedDocId]);

  useEffect(() => {
    if (!token || !selectedDocId) return;
    let cancelled = false;
    setDocumentDetailError(null);
    documentGet(token, selectedDocId)
      .then((d) => {
        if (!cancelled) {
          const { detail, wordCount } = normalizeDocumentDetail(d);
          setDocDetail(detail);
          setDocWordCount(wordCount);
          setDocumentDetailError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setDocDetail(null);
          setDocWordCount(0);
          setDocumentDetailError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, selectedDocId]);

  /** Sequential poll only while processing — avoids overlapping GETs when responses are slow (large PDFs). */
  useEffect(() => {
    if (!token || !selectedDocId) return;
    if (docDetail?.status !== "processing") return;

    let cancelled = false;

    const loop = async () => {
      while (!cancelled) {
        const t = tokenRef.current;
        const id = selectedDocIdRef.current;
        if (!t || !id) break;
        try {
          const d = await documentGet(t, id);
          if (cancelled) return;
          const { detail, wordCount } = normalizeDocumentDetail(d);
          setDocDetail(detail);
          setDocWordCount(wordCount);
          docPollFailsRef.current = 0;
          setDocPollWarning(null);
          if (d.status !== "processing") {
            await refreshDocuments(t);
            break;
          }
        } catch (e) {
          if (cancelled) return;
          docPollFailsRef.current += 1;
          if (docPollFailsRef.current >= 3) {
            setDocPollWarning(
              e instanceof Error
                ? `Could not refresh document (${e.message}). Check network and API URL.`
                : "Could not refresh document. Check network and API URL."
            );
          }
        }
        await new Promise((r) => setTimeout(r, 2000));
        if (cancelled) return;
      }
    };

    void loop();

    return () => {
      cancelled = true;
    };
  }, [token, selectedDocId, docDetail?.status, refreshDocuments]);

  useEffect(() => {
    testPollFailsRef.current = 0;
    setTestPollWarning(null);
  }, [testSummary?.id]);

  useEffect(() => {
    if (!token || !testSummary?.id) return;
    if (TERMINAL_TEST.has(testSummary.status)) return;

    let cancelled = false;
    const testId = testSummary.id;

    const loop = async () => {
      while (!cancelled) {
        const auth = tokenRef.current;
        if (!auth) break;
        try {
          const row = await testGet(auth, testId);
          if (cancelled) return;
          setTestSummary(row);
          setTestDetail(row);
          testPollFailsRef.current = 0;
          setTestPollWarning(null);
          if (TERMINAL_TEST.has(row.status)) break;
        } catch (e) {
          if (cancelled) return;
          testPollFailsRef.current += 1;
          if (testPollFailsRef.current >= 3) {
            setTestPollWarning(
              e instanceof Error
                ? `Could not refresh test (${e.message}). Token may have expired.`
                : "Could not refresh test. Token may have expired."
            );
          }
        }
        await new Promise((r) => setTimeout(r, 2000));
        if (cancelled) return;
      }
    };

    void loop();

    return () => {
      cancelled = true;
    };
  }, [token, testSummary?.id, testSummary?.status]);

  const handleRegister = () =>
    withErr(async () => {
      setLastAuthAction("register");
      await authRegister({ email, password });
      setMessage("Registered. Now log in with the same email and password.");
    });

  const handleLogin = () =>
    withErr(async () => {
      setLastAuthAction("login");
      const t = await authLogin({ email, password });
      setToken(t.access_token);
      localStorage.setItem(TOKEN_KEY, t.access_token);
      const u = await authMe(t.access_token);
      setUserLabel(`${u.email} (${u.role})`);
      setMessage("Logged in.");
      await refreshDocuments(t.access_token);
    });

  const handleLogout = () => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUserLabel(null);
    setDocuments([]);
    setSelectedDocId(null);
    setDocDetail(null);
    setDocWordCount(0);
    setTestSummary(null);
    setTestDetail(null);
    setListError(null);
    setDocumentDetailError(null);
    setDocPollWarning(null);
    setTestPollWarning(null);
    setMessage("Logged out.");
    setError(null);
  };

  const handleUpload = () =>
    withErr(async () => {
      if (!token) throw new Error("Log in first.");
      if (!file) throw new Error("Choose a PDF file.");
      setBusyUpload(true);
      try {
        const created = await documentUpload(token, file);
        setSelectedDocId(created.id);
        const full = await documentGet(token, created.id);
        const { detail, wordCount } = normalizeDocumentDetail(full);
        setDocDetail(detail);
        setDocWordCount(wordCount);
        setDocumentDetailError(null);
        setMessage(`Uploaded "${created.filename || "document"}". Extraction runs in the background.`);
        setFile(null);
        setFileInputKey((k) => k + 1);
        await refreshDocuments(token);
      } finally {
        setBusyUpload(false);
      }
    });

  const handleGenerate = () =>
    withErr(async () => {
      if (!token) throw new Error("Log in first.");
      if (!selectedDocId) throw new Error("Select a document (or upload one).");
      if (isGenerationInProgress) {
        throw new Error("A generation is already in progress. Please wait for it to finish.");
      }
      setBusyGenerate(true);
      try {
        const latest = await documentGet(token, selectedDocId);
        if (latest.id !== selectedDocId) {
          throw new Error("Document selection changed. Please try again.");
        }
        if (latest.status !== "ready") {
          throw new Error(
            `Document must be status "ready" (current: ${latest.status}). Wait for extraction or fix errors.`
          );
        }
        const normalized = normalizeDocumentDetail(latest);
        setDocDetail(normalized.detail);
        setDocWordCount(normalized.wordCount);
        const t = await testsGenerate(token, {
          document_id: selectedDocId,
          num_questions: genNumQ,
          difficulty: genDifficulty,
          export_result: false,
          reference_qp_hash: referenceQpHash,
        });
        setTestSummary(t);
        setTestDetail(null);
        setMessage(`Generation started (test id: ${t.id}). Polling for results…`);
      } finally {
        setBusyGenerate(false);
      }
    });

  const handleReferenceQpSelect = async (selected: File | null) => {
    if (!token) {
      setError("Log in first.");
      return;
    }
    if (!selected) {
      setReferenceQpHash(null);
      return;
    }
    setReferenceQpBusy(true);
    try {
      const resp = await referenceQpUpload(token, selected);
      setReferenceQpHash(resp.qp_hash || null);
      setMessage(resp.cached ? "Reference QP style loaded from cache." : "Reference QP style extracted.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setReferenceQpHash(null);
    } finally {
      setReferenceQpBusy(false);
    }
  };

  const handleSelectDoc = (id: string) => {
    setSelectedDocId(id);
    setDocDetail(null);
    setDocWordCount(0);
    setDocumentDetailError(null);
    setTestSummary(null);
    setTestDetail(null);
    clearFeedback();
  };

  const handleRefreshDoc = () =>
    withErr(async () => {
      if (!token || !selectedDocId) return;
      const d = await documentGet(token, selectedDocId);
      const { detail, wordCount } = normalizeDocumentDetail(d);
      setDocDetail(detail);
      setDocWordCount(wordCount);
      setDocumentDetailError(null);
      setMessage("Document refreshed.");
    });

  const apiBase = getApiBase();
  const extractionProgress = extractionProgressPercent(docDetail);
  const generationProgress = generationProgressPercent(testSummary);
  const generationTotal = Number(testSummary?.total_mcq ?? 0);
  const generationDone = Number(testSummary?.progress_mcq ?? 0);
  const generationInProgress =
    (testSummary?.status || "").toLowerCase() === "generating" ||
    (testSummary?.status || "").toLowerCase() === "pending" ||
    (testSummary?.status || "").toLowerCase() === "processing";
  const extractionIcon =
    docDetail?.status === "ready"
      ? "✅"
      : docDetail?.status === "extraction_failed" || docDetail?.status === "rejected"
        ? "⚠️"
        : "⏳";

  return (
    <main>
      <h1>UPSC Test Engine</h1>
      <p className="sub">
        Upload a PDF, wait until extraction is <strong>ready</strong>, then generate MCQs. API base:{" "}
        <code>{apiBase}</code>
      </p>

      {(listError || documentDetailError || docPollWarning || testPollWarning) && (
        <div className="card" style={{ borderColor: "var(--danger)" }}>
          {listError && <p className="err">Documents: {listError}</p>}
          {documentDetailError && <p className="err">Selected document: {documentDetailError}</p>}
          {docPollWarning && <p className="err">{docPollWarning}</p>}
          {testPollWarning && <p className="err">{testPollWarning}</p>}
        </div>
      )}

      <h2>1. Account</h2>
      <div className="card">
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete={lastAuthAction === "register" ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div className="row">
          <button type="button" onClick={handleRegister}>
            Register
          </button>
          <button type="button" onClick={handleLogin}>
            Log in
          </button>
          <button type="button" className="secondary" onClick={handleLogout} disabled={!token}>
            Log out
          </button>
        </div>
        {userLabel && <p className="ok">Signed in as {userLabel}</p>}
        {message && <p className="ok">{message}</p>}
        {error && <p className="err">{error}</p>}
      </div>

      <h2>2. Upload PDF</h2>
      <div className="card">
        <label htmlFor="pdf">PDF file (max 100 pages)</label>
        <input
          key={fileInputKey}
          id="pdf"
          type="file"
          accept="application/pdf,.pdf"
          disabled={!token}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <p className="hint">
          How many MCQs to create is set in <strong>step 4</strong> when you run Generate — not at upload time.
        </p>
        <div className="row">
          <button type="button" disabled={!token || !file || busyUpload} onClick={handleUpload}>
            {busyUpload ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>

      <h2>3. Documents</h2>
      <div className="card">
        {!token && <p className="muted">Log in to list documents.</p>}
        {token && !listError && documents.length === 0 && <p>No documents yet. Upload a PDF above.</p>}
        {token &&
          documents.map((d) => (
            <div key={d.id} className="row" style={{ marginTop: "0.5rem" }}>
              <button
                type="button"
                className={selectedDocId === d.id ? "secondary" : ""}
                onClick={() => handleSelectDoc(d.id)}
              >
                {d.filename || d.id.slice(0, 8)}… — {d.status}
              </button>
            </div>
          ))}
        {selectedDocId && documentDetailError && !docDetail && (
          <p className="err" style={{ marginTop: "0.75rem" }}>
            {documentDetailError}
          </p>
        )}
        {selectedDocId && docDetail && (
          <>
            <div className="extract-progress">
              <div className="extract-progress-row">
                <span className="extract-progress-icon" aria-hidden="true">
                  {extractionIcon}
                </span>
                <strong>Extraction progress</strong>
                <span className="extract-progress-pct">{extractionProgress}%</span>
              </div>
              <div className="extract-progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={extractionProgress}>
                <div className="extract-progress-fill" style={{ width: `${extractionProgress}%` }} />
              </div>
              <p className="hint" style={{ marginTop: "0.35rem" }}>
                Real progress from backend page extraction; capped at 95% until status becomes ready.
              </p>
            </div>
            <pre className="meta">
              id: {docDetail.id}
              {"\n"}
              status: {docDetail.status}
              {"\n"}
              pages: {docDetail.progress_page ?? 0}/{docDetail.total_pages ?? "?"}
              {"\n"}
              words (approx): {docWordCount}
              {docDetail.extracted_text == null && docWordCount > 0
                ? "\n(full text omitted in UI for performance; server still has it)"
                : ""}
            </pre>
            <div className="row">
              <button type="button" className="secondary" onClick={handleRefreshDoc} disabled={!token}>
                Refresh document
              </button>
            </div>
            {docDetail.status === "processing" && (
              <p className="ok">Extracting text… this page refreshes the document every few seconds.</p>
            )}
            {docDetail.status === "extraction_failed" && (
              <p className="err">Extraction failed. Try another PDF or check server logs.</p>
            )}
            {docDetail.status === "rejected" && (
              <p className="err">Document rejected (e.g. over page limit).</p>
            )}
          </>
        )}
      </div>

      <h2>4. Generate MCQs</h2>
      <div className="card">
        <p className="hint" style={{ marginBottom: "0.65rem" }}>
          Use the fields below for this test run only (1–20 questions, difficulty).
        </p>
        <label htmlFor="genNum">Number of questions (1–20)</label>
        <input
          id="genNum"
          type="number"
          min={1}
          max={20}
          value={genNumQ}
          disabled={!token}
          onChange={(e) => setGenNumQ(Math.min(20, Math.max(1, Number(e.target.value) || 1)))}
        />
        <label htmlFor="diff">Difficulty</label>
        <select
          id="diff"
          value={genDifficulty}
          disabled={!token}
          onChange={(e) => setGenDifficulty(e.target.value as "EASY" | "MEDIUM" | "HARD")}
        >
          <option value="EASY">EASY</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="HARD">HARD</option>
        </select>
        <label htmlFor="referenceQp">Optional: Upload Reference Question Paper (PDF)</label>
        <input
          id="referenceQp"
          type="file"
          accept="application/pdf,.pdf"
          disabled={!token || referenceQpBusy}
          onChange={(e) => void handleReferenceQpSelect(e.target.files?.[0] ?? null)}
        />
        <p className="hint">
          Style: <strong>{referenceQpHash ? "PYQ-matched" : "Default"}</strong>
        </p>
        <div className="row">
          <button
            type="button"
            disabled={!token || !selectedDocId || docDetail?.status !== "ready" || busyGenerate || isGenerationInProgress}
            onClick={handleGenerate}
          >
            {busyGenerate ? "Starting…" : "Generate test"}
          </button>
        </div>
        {isGenerationInProgress && (
          <p className="hint" style={{ marginTop: "0.75rem" }}>
            Generation is already in progress for this test. Please wait until it completes.
          </p>
        )}
        {docDetail && docDetail.status !== "ready" && token && (
          <p className="err" style={{ marginTop: "0.75rem" }}>
            Generation is enabled only when the selected document is <strong>ready</strong> (needs extracted text and
            enough words per server rules).
          </p>
        )}
      </div>

      <h2>5. Test result</h2>
      <div className="card">
        {!testSummary && <p>No test run yet.</p>}
        {testSummary && (
          <>
            <div className="extract-progress">
              <div className="extract-progress-row">
                <span className="extract-progress-icon" aria-hidden="true">
                  {(testSummary.status || "").toLowerCase() === "completed"
                    ? "✅"
                    : (testSummary.status || "").toLowerCase() === "failed" ||
                        (testSummary.status || "").toLowerCase() === "failed_timeout"
                      ? "⚠️"
                      : "⏳"}
                </span>
                <strong>Generation progress</strong>
                <span className="extract-progress-pct">
                  {generationTotal > 0 ? `${generationDone}/${generationTotal}` : "estimating..."}
                </span>
              </div>
              <div
                className="extract-progress-track"
                role="progressbar"
                aria-label="Generation progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={generationProgress}
              >
                <div className="extract-progress-fill" style={{ width: `${generationProgress}%` }} />
              </div>
              {generationTotal > 0 ? (
                <p className="hint" style={{ marginTop: "0.35rem" }}>
                  {generationProgress}% - {generationDone} of {generationTotal} questions created
                </p>
              ) : (
                <p className="hint" style={{ marginTop: "0.35rem" }}>
                  Progress will appear once total question count is available.
                </p>
              )}
              {generationInProgress && generationTotal > 0 && (
                <p className="hint" style={{ marginTop: "0.2rem" }}>
                  Timer-based estimate is capped at 95% until completion.
                </p>
              )}
            </div>
            <pre className="meta">
              test id: {testSummary.id}
              {"\n"}
              status: {testSummary.status}
              {testSummary.stale ? " (stale — may time out)" : ""}
              {"\n"}
              {testSummary.progress_message ?? ""}
              {testSummary.failure_reason ? `\nfailure: ${testSummary.failure_reason}` : ""}
            </pre>
            {testDetail?.questions && testDetail.questions.length > 0 && (
              <div>
                {testDetail.questions.map((q) => (
                  <div key={q.id} className="q">
                    <h3>
                      {q.sort_order}. {q.question}
                    </h3>
                    <ul className="opts">
                      {optionsEntries(q.options).map(([label, text]) => {
                        const correct = normalizedCorrectOption(q.correct_option);
                        return (
                          <li key={label}>
                            <strong>{label}.</strong> {text}
                            {label === correct ? " ✓" : ""}
                          </li>
                        );
                      })}
                    </ul>
                    <p>
                      <strong>Answer:</strong> {normalizedCorrectOption(q.correct_option)} ·{" "}
                      <strong>Explanation:</strong> {q.explanation ?? ""}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <p className="api-hint">
        API docs:{" "}
        <a href={apiDocsUrl()} target="_blank" rel="noreferrer">
          {apiDocsUrl()}
        </a>
        . Override base URL with <code>NEXT_PUBLIC_API_URL</code>.
      </p>
    </main>
  );
}
