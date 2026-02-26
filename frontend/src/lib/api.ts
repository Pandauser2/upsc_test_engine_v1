/**
 * API client for FastAPI backend: auth, documents, tests (generate, poll status, get, export).
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "upsc_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function fetchWithAuth(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = getToken();
  const headers: HeadersInit = {
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (!headers["Content-Type"] && options.body && typeof options.body === "string")
    headers["Content-Type"] = "application/json";
  return fetch(apiUrl(path), { ...options, headers });
}

export async function login(email: string, password: string): Promise<{ access_token: string }> {
  const res = await fetch(apiUrl("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Login failed");
  }
  return res.json();
}

export interface DocumentResponse {
  id: string;
  status: string;
  filename: string | null;
  title: string | null;
  total_pages: number | null;
  extracted_pages: number;
  created_at: string;
}

export async function uploadDocument(file: File): Promise<DocumentResponse> {
  const token = getToken();
  if (!token) throw new Error("Not authenticated");
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(apiUrl("/documents/upload"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Upload failed");
  }
  return res.json();
}

export async function getDocument(documentId: string): Promise<DocumentResponse & { extracted_text?: string }> {
  const res = await fetchWithAuth(`/documents/${documentId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Document not found");
  }
  return res.json();
}

export interface TestResponse {
  id: string;
  document_id: string;
  title: string | null;
  status: string;
  failure_reason: string | null;
  partial_reason: string | null;
  questions_generated: number | null;
  target_questions: number | null;
  progress_message: string | null;
}

export interface TestStatusResponse {
  status: string;
  progress: number;
  message: string;
  questions_generated: number;
  target_questions: number;
  elapsed_time: number | null;
}

export interface QuestionResponse {
  id: string;
  generated_test_id: string;
  sort_order: number;
  question: string;
  options: Record<string, string> | Array<{ label: string; text: string }>;
  correct_option: string;
  explanation: string;
  difficulty: string;
}

export interface TestDetailResponse extends TestResponse {
  questions: QuestionResponse[];
}

export async function startGeneration(
  documentId: string,
  numQuestions: number,
  difficulty: string
): Promise<TestResponse> {
  const res = await fetchWithAuth("/tests/generate", {
    method: "POST",
    body: JSON.stringify({
      document_id: documentId,
      num_questions: numQuestions,
      difficulty,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Start generation failed");
  }
  return res.json();
}

export async function getTestStatus(testId: string): Promise<TestStatusResponse> {
  const res = await fetchWithAuth(`/tests/${testId}/status`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Test not found");
  }
  return res.json();
}

export async function getTest(testId: string): Promise<TestDetailResponse> {
  const res = await fetchWithAuth(`/tests/${testId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Test not found");
  }
  return res.json();
}

export async function patchQuestion(
  testId: string,
  questionId: string,
  data: { question?: string; options?: Record<string, string>; correct_option?: string; explanation?: string; difficulty?: string }
): Promise<QuestionResponse> {
  const res = await fetchWithAuth(`/tests/${testId}/questions/${questionId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Update failed");
  }
  return res.json();
}

export async function exportDocx(testId: string): Promise<Blob> {
  const res = await fetchWithAuth(`/tests/${testId}/export`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Export failed");
  }
  return res.blob();
}
