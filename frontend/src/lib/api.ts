/**
 * API base URL and typed helpers for the FastAPI backend.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Base URL without trailing slashes (for links and display). */
export function getApiBase(): string {
  return API_BASE.replace(/\/+$/, "");
}

/** OpenAPI Swagger UI for the configured backend. */
export function apiDocsUrl(): string {
  return `${getApiBase()}/docs`;
}

export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBase()}${p}`;
}

async function parseError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: unknown };
    const d = j.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((x: { msg?: string; loc?: unknown }) => x.msg || JSON.stringify(x))
        .join("; ");
    }
    if (d != null) return JSON.stringify(d);
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

export async function apiJson<T>(
  path: string,
  init: RequestInit & { token?: string | null } = {}
): Promise<T> {
  const { token, headers: h, ...rest } = init;
  const headers = new Headers(h);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const body = rest.body;
  if (body != null && typeof body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(apiUrl(path), { ...rest, headers });
  if (!res.ok) throw new Error(await parseError(res));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function apiForm<T>(
  path: string,
  form: FormData,
  token: string
): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<T>;
}

/** --- Auth --- */
export type UserResponse = { id: string; email: string; role: string };
export type TokenResponse = { access_token: string; token_type: string };

export function authRegister(body: { email: string; password: string }) {
  return apiJson<UserResponse>("/auth/register", { method: "POST", body: JSON.stringify(body) });
}

export function authLogin(body: { email: string; password: string }) {
  return apiJson<TokenResponse>("/auth/login", { method: "POST", body: JSON.stringify(body) });
}

export function authMe(token: string) {
  return apiJson<UserResponse>("/auth/me", { token, method: "GET" });
}

/** --- Documents --- */
export type DocumentResponse = {
  id: string;
  user_id: string;
  source_type: string;
  filename: string | null;
  title: string | null;
  status: string;
  target_questions: number | null;
  created_at: string;
};

export type DocumentDetailResponse = DocumentResponse & {
  extracted_text?: string | null;
  total_pages?: number | null;
  progress_page?: number | null;
};

export type DocumentListResponse = { items: DocumentResponse[]; total: number };

export function documentsList(token: string) {
  return apiJson<DocumentListResponse>("/documents", { token, method: "GET" });
}

export function documentGet(token: string, id: string) {
  return apiJson<DocumentDetailResponse>(`/documents/${id}`, { token, method: "GET" });
}

export function documentUpload(token: string, file: File, numQuestions?: number) {
  const fd = new FormData();
  fd.append("file", file);
  if (numQuestions != null && numQuestions >= 1 && numQuestions <= 20) {
    fd.append("num_questions", String(numQuestions));
  }
  return apiForm<DocumentResponse>("/documents/upload", fd, token);
}

export type ReferenceQpUploadResponse = {
  qp_hash: string;
  style_profile: string;
  cached: boolean;
};

export function referenceQpUpload(token: string, file: File) {
  const fd = new FormData();
  fd.append("file", file);
  return apiForm<ReferenceQpUploadResponse>("/reference-qps/upload", fd, token);
}

/** --- Tests --- */
export type TestGenerateBody = {
  document_id: string;
  num_questions: number;
  difficulty: "EASY" | "MEDIUM" | "HARD";
  export_result?: boolean;
  reference_qp_hash?: string | null;
};

export type TestResponse = {
  id: string;
  document_id: string;
  title: string | null;
  status: string;
  failure_reason?: string | null;
  questions_generated?: number | null;
  target_questions?: number | null;
  progress_mcq?: number | null;
  total_mcq?: number | null;
  progress?: number | null;
  progress_message?: string | null;
  stale?: boolean;
};

export type QuestionResponse = {
  id: string;
  sort_order: number;
  question: string;
  options: Record<string, string> | Array<{ label: string; text: string }>;
  correct_option: string;
  explanation: string;
  difficulty: string;
  topic_id: string;
};

export type TestDetailResponse = TestResponse & { questions: QuestionResponse[] };

export type TestStatusResponse = {
  status: string;
  progress: number;
  message: string;
  questions_generated: number;
  target_questions: number;
  progress_mcq: number;
  total_mcq: number;
};

export function testsGenerate(token: string, body: TestGenerateBody) {
  return apiJson<TestResponse>("/tests/generate", {
    token,
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function testGet(token: string, id: string) {
  return apiJson<TestDetailResponse>(`/tests/${id}`, { token, method: "GET" });
}

export function testStatus(token: string, id: string) {
  return apiJson<TestStatusResponse>(`/tests/${id}/status`, { token, method: "GET" });
}
