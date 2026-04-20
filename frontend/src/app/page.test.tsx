/// <reference types="vitest" />
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import Home from "./page";

const apiMock = vi.hoisted(() => ({
  apiDocsUrl: vi.fn(() => "http://localhost:8000/docs"),
  getApiBase: vi.fn(() => "http://localhost:8000"),
  authLogin: vi.fn(),
  authMe: vi.fn(async () => ({ id: "u1", email: "faculty@example.com", role: "faculty" })),
  authRegister: vi.fn(),
  documentGet: vi.fn(),
  documentUpload: vi.fn(),
  documentsList: vi.fn(),
  testGet: vi.fn(),
  testsGenerate: vi.fn(),
}));

vi.mock("@/lib/api", () => apiMock);

const TOKEN = "test-token";
const DOC_ID = "doc-1";

function makeDocDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: DOC_ID,
    user_id: "u1",
    source_type: "pdf",
    filename: "science.pdf",
    title: "science.pdf",
    status: "processing",
    target_questions: 5,
    created_at: "2026-04-19T00:00:00Z",
    extracted_text: "short text",
    total_pages: 20,
    progress_page: 10,
    ...overrides,
  };
}

async function renderAndSelectDocument() {
  window.localStorage.setItem("upsc_test_engine_token", TOKEN);
  apiMock.documentsList.mockResolvedValue({
    items: [
      {
        id: DOC_ID,
        user_id: "u1",
        source_type: "pdf",
        filename: "science.pdf",
        title: "science.pdf",
        status: "processing",
        target_questions: 5,
        created_at: "2026-04-19T00:00:00Z",
      },
    ],
    total: 1,
  });
  render(<Home />);
  const docButton = await screen.findByRole("button", { name: /science\.pdf/i });
  fireEvent.click(docButton);
}

describe("document extraction progress UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  test("in-progress render uses backend page progress (50%)", async () => {
    apiMock.documentGet.mockResolvedValue(makeDocDetail({ status: "processing", total_pages: 20, progress_page: 10 }));
    await renderAndSelectDocument();
    const progress = await screen.findByRole("progressbar");
    expect(progress).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  test("processing progress is capped at 95%", async () => {
    apiMock.documentGet.mockResolvedValue(makeDocDetail({ status: "processing", total_pages: 20, progress_page: 19 }));
    await renderAndSelectDocument();
    const progress = await screen.findByRole("progressbar");
    expect(progress).toHaveAttribute("aria-valuenow", "95");
    expect(screen.getByText("95%")).toBeInTheDocument();
  });

  test("ready status shows 100%", async () => {
    apiMock.documentGet.mockResolvedValue(makeDocDetail({ status: "ready", total_pages: 20, progress_page: 20 }));
    await renderAndSelectDocument();
    const progress = await screen.findByRole("progressbar");
    expect(progress).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  test("zero-division guard: processing with total_pages=0 renders 0%", async () => {
    apiMock.documentGet.mockResolvedValue(makeDocDetail({ status: "processing", total_pages: 0, progress_page: 0 }));
    await renderAndSelectDocument();
    const progress = await screen.findByRole("progressbar");
    expect(progress).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  test("polling runs every 2s and stops after ready", async () => {
    apiMock.documentGet
      .mockResolvedValueOnce(makeDocDetail({ status: "processing", total_pages: 20, progress_page: 1 }))
      .mockResolvedValueOnce(makeDocDetail({ status: "processing", total_pages: 20, progress_page: 2 }))
      .mockResolvedValue(makeDocDetail({ status: "ready", total_pages: 20, progress_page: 20 }));

    await renderAndSelectDocument();
    vi.useFakeTimers();

    const before = apiMock.documentGet.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(apiMock.documentGet.mock.calls.length).toBeGreaterThan(before);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    const callsAtReady = apiMock.documentGet.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(apiMock.documentGet.mock.calls.length).toBe(callsAtReady);
    vi.useRealTimers();
  }, 15000);
});

describe("generation progress UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  test("polling runs every 2s and stops on completed", async () => {
    window.localStorage.setItem("upsc_test_engine_token", TOKEN);
    apiMock.documentsList.mockResolvedValue({
      items: [
        {
          id: DOC_ID,
          user_id: "u1",
          source_type: "pdf",
          filename: "science.pdf",
          title: "science.pdf",
          status: "ready",
          target_questions: 5,
          created_at: "2026-04-19T00:00:00Z",
        },
      ],
      total: 1,
    });
    apiMock.documentGet.mockResolvedValue(makeDocDetail({ status: "ready", total_pages: 20, progress_page: 20 }));
    apiMock.testsGenerate.mockResolvedValue({
      id: "test-1",
      document_id: DOC_ID,
      title: "science test",
      status: "generating",
      progress_mcq: 0,
      total_mcq: 5,
      progress_message: "0 of 5 questions created",
    });
    apiMock.testGet
      .mockResolvedValueOnce({
        id: "test-1",
        document_id: DOC_ID,
        title: "science test",
        status: "generating",
        progress_mcq: 2,
        total_mcq: 5,
        progress_message: "2 of 5 questions created",
        questions: [],
      })
      .mockResolvedValue({
        id: "test-1",
        document_id: DOC_ID,
        title: "science test",
        status: "completed",
        progress_mcq: 5,
        total_mcq: 5,
        progress_message: "5 of 5 questions created",
        questions: [],
      });

    render(<Home />);
    const docButton = await screen.findByRole("button", { name: /science\.pdf/i });
    fireEvent.click(docButton);
    const generateButton = await screen.findByRole("button", { name: /generate test/i });
    fireEvent.click(generateButton);

    vi.useFakeTimers();
    const before = apiMock.testGet.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(apiMock.testGet.mock.calls.length).toBeGreaterThan(before);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    const callsAtCompleted = apiMock.testGet.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(apiMock.testGet.mock.calls.length).toBe(callsAtCompleted);

    const progress = screen.getByRole("progressbar", { name: /generation progress/i });
    expect(progress).toHaveAttribute("aria-valuenow", "100");
    vi.useRealTimers();
  }, 15000);

  test("95% cap while generating even if progress equals total", async () => {
    window.localStorage.setItem("upsc_test_engine_token", TOKEN);
    apiMock.documentsList.mockResolvedValue({
      items: [
        {
          id: DOC_ID,
          user_id: "u1",
          source_type: "pdf",
          filename: "science.pdf",
          title: "science.pdf",
          status: "ready",
          target_questions: 5,
          created_at: "2026-04-19T00:00:00Z",
        },
      ],
      total: 1,
    });
    apiMock.documentGet.mockResolvedValue(makeDocDetail({ status: "ready", total_pages: 20, progress_page: 20 }));
    apiMock.testsGenerate.mockResolvedValue({
      id: "test-2",
      document_id: DOC_ID,
      title: "science test",
      status: "generating",
      progress_mcq: 5,
      total_mcq: 5,
      progress_message: "5 of 5 questions created",
    });
    apiMock.testGet.mockResolvedValue({
      id: "test-2",
      document_id: DOC_ID,
      title: "science test",
      status: "generating",
      progress_mcq: 5,
      total_mcq: 5,
      progress_message: "5 of 5 questions created",
      questions: [],
    });

    render(<Home />);
    const docButton = await screen.findByRole("button", { name: /science\.pdf/i });
    fireEvent.click(docButton);
    const generateButton = await screen.findByRole("button", { name: /generate test/i });
    fireEvent.click(generateButton);

    const progress = await screen.findByRole("progressbar", { name: /generation progress/i });
    expect(progress).toHaveAttribute("aria-valuenow", "95");
  });

  test("completed status shows 100%", async () => {
    window.localStorage.setItem("upsc_test_engine_token", TOKEN);
    apiMock.documentsList.mockResolvedValue({
      items: [
        {
          id: DOC_ID,
          user_id: "u1",
          source_type: "pdf",
          filename: "science.pdf",
          title: "science.pdf",
          status: "ready",
          target_questions: 5,
          created_at: "2026-04-19T00:00:00Z",
        },
      ],
      total: 1,
    });
    apiMock.documentGet.mockResolvedValue(makeDocDetail({ status: "ready", total_pages: 20, progress_page: 20 }));
    apiMock.testsGenerate.mockResolvedValue({
      id: "test-3",
      document_id: DOC_ID,
      title: "science test",
      status: "completed",
      progress_mcq: 5,
      total_mcq: 5,
      progress_message: "5 of 5 questions created",
    });

    render(<Home />);
    const docButton = await screen.findByRole("button", { name: /science\.pdf/i });
    fireEvent.click(docButton);
    const generateButton = await screen.findByRole("button", { name: /generate test/i });
    fireEvent.click(generateButton);

    const progress = await screen.findByRole("progressbar", { name: /generation progress/i });
    expect(progress).toHaveAttribute("aria-valuenow", "100");
  });

  test("zero-division guard for generation progress", async () => {
    window.localStorage.setItem("upsc_test_engine_token", TOKEN);
    apiMock.documentsList.mockResolvedValue({
      items: [
        {
          id: DOC_ID,
          user_id: "u1",
          source_type: "pdf",
          filename: "science.pdf",
          title: "science.pdf",
          status: "ready",
          target_questions: 5,
          created_at: "2026-04-19T00:00:00Z",
        },
      ],
      total: 1,
    });
    apiMock.documentGet.mockResolvedValue(makeDocDetail({ status: "ready", total_pages: 20, progress_page: 20 }));
    apiMock.testsGenerate.mockResolvedValue({
      id: "test-4",
      document_id: DOC_ID,
      title: "science test",
      status: "generating",
      progress_mcq: 0,
      total_mcq: 0,
      progress_message: "starting",
    });
    apiMock.testGet.mockResolvedValue({
      id: "test-4",
      document_id: DOC_ID,
      title: "science test",
      status: "generating",
      progress_mcq: 0,
      total_mcq: 0,
      progress_message: "starting",
      questions: [],
    });

    render(<Home />);
    const docButton = await screen.findByRole("button", { name: /science\.pdf/i });
    fireEvent.click(docButton);
    const generateButton = await screen.findByRole("button", { name: /generate test/i });
    fireEvent.click(generateButton);

    const progress = await screen.findByRole("progressbar", { name: /generation progress/i });
    expect(progress).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByText(/estimating/i)).toBeInTheDocument();
  });

  test("failed state stops polling and shows error state", async () => {
    window.localStorage.setItem("upsc_test_engine_token", TOKEN);
    apiMock.documentsList.mockResolvedValue({
      items: [
        {
          id: DOC_ID,
          user_id: "u1",
          source_type: "pdf",
          filename: "science.pdf",
          title: "science.pdf",
          status: "ready",
          target_questions: 5,
          created_at: "2026-04-19T00:00:00Z",
        },
      ],
      total: 1,
    });
    apiMock.documentGet.mockResolvedValue(makeDocDetail({ status: "ready", total_pages: 20, progress_page: 20 }));
    apiMock.testsGenerate.mockResolvedValue({
      id: "test-5",
      document_id: DOC_ID,
      title: "science test",
      status: "generating",
      progress_mcq: 0,
      total_mcq: 5,
      progress_message: "0 of 5 questions created",
    });
    apiMock.testGet.mockResolvedValue({
      id: "test-5",
      document_id: DOC_ID,
      title: "science test",
      status: "failed",
      progress_mcq: 2,
      total_mcq: 5,
      progress_message: "2 of 5 questions created",
      failure_reason: "Generation failed",
      questions: [],
    });

    render(<Home />);
    const docButton = await screen.findByRole("button", { name: /science\.pdf/i });
    fireEvent.click(docButton);
    const generateButton = await screen.findByRole("button", { name: /generate test/i });
    fireEvent.click(generateButton);

    vi.useFakeTimers();
    const before = apiMock.testGet.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(apiMock.testGet.mock.calls.length).toBeGreaterThan(before);

    const callsAtFailed = apiMock.testGet.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(apiMock.testGet.mock.calls.length).toBe(callsAtFailed);
    expect(screen.getByText(/failure: Generation failed/i)).toBeInTheDocument();
    vi.useRealTimers();
  }, 15000);
});

