"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Progress } from "@/components/ui/Progress";
import { getToken, getTestStatus, getTest, patchQuestion, exportDocx } from "@/lib/api";
import type { TestDetailResponse, QuestionResponse } from "@/lib/api";

const POLL_INTERVAL_MS = 5000;

export default function TestPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [test, setTest] = useState<TestDetailResponse | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);

  const fetchTest = useCallback(async () => {
    const t = await getTest(id);
    setTest(t);
    return t;
  }, [id]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/");
      return;
    }
    let cancelled = false;

    const poll = async () => {
      try {
        const status = await getTestStatus(id);
        setProgress(status.progress * 100);
        setStatusMessage(
          status.status === "pending" || status.status === "generating"
            ? `Generating questions ${status.questions_generated}/${status.target_questions}`
            : status.message
        );

        if (status.status === "completed" || status.status === "partial" || status.status === "failed" || status.status === "failed_timeout") {
          await fetchTest();
          return;
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load status");
        return;
      }
      if (!cancelled) setTimeout(poll, POLL_INTERVAL_MS);
    };

    poll();
    return () => {
      cancelled = true;
    };
  }, [id, router, fetchTest]);

  const handleQuestionBlur = async (q: QuestionResponse, field: "question" | "explanation", value: string) => {
    if (!test) return;
    try {
      const updated = await patchQuestion(test.id, q.id, { [field]: value });
      setTest((prev) =>
        prev
          ? {
              ...prev,
              questions: prev.questions.map((x) => (x.id === q.id ? { ...x, [field]: updated[field as keyof QuestionResponse] } : x)),
            }
          : null
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
  };

  const handleDownload = async () => {
    setDownloading(true);
    setError("");
    try {
      const blob = await exportDocx(id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `test-${id}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setDownloading(false);
    }
  };

  if (!test && !error && !statusMessage) {
    return (
      <main className="min-h-screen bg-slate-50 p-8">
        <p className="text-slate-600">Loading…</p>
      </main>
    );
  }

  const terminal = test && (test.status === "completed" || test.status === "partial" || test.status === "failed" || test.status === "failed_timeout");

  return (
    <main className="min-h-screen bg-slate-50 p-8">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-center gap-4">
          <Link href="/" className="text-slate-600 hover:underline">
            ← Back
          </Link>
        </div>
        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}
        {!terminal && (
          <Card>
            <CardHeader>
              <CardTitle>Progress</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <p className="text-sm text-slate-600">{statusMessage}</p>
              <Progress value={progress} />
            </CardContent>
          </Card>
        )}
        {test?.partial_reason && (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            {test.partial_reason}
          </div>
        )}
        {test?.failure_reason && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {test.failure_reason}
          </div>
        )}
        {terminal && test?.questions && test.questions.length > 0 && (
          <>
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold">Questions</h2>
              <Button onClick={handleDownload} disabled={downloading}>
                {downloading ? "Downloading…" : "Download .docx"}
              </Button>
            </div>
            <div className="space-y-6">
              {test.questions.map((q, idx) => (
                <Card key={q.id}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Q{idx + 1}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div>
                      <label className="mb-1 block text-sm font-medium">Question</label>
                      <textarea
                        className="min-h-[80px] w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
                        defaultValue={q.question}
                        onBlur={(e) => handleQuestionBlur(q, "question", e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-sm font-medium">Explanation</label>
                      <textarea
                        className="min-h-[60px] w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
                        defaultValue={q.explanation}
                        onBlur={(e) => handleQuestionBlur(q, "explanation", e.target.value)}
                      />
                    </div>
                    <p className="text-xs text-slate-500">
                      Correct: {q.correct_option} · Difficulty: {q.difficulty}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </>
        )}
        {terminal && test?.questions?.length === 0 && !test.failure_reason && (
          <p className="text-slate-600">No questions generated.</p>
        )}
      </div>
    </main>
  );
}
