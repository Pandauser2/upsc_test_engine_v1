"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Progress } from "@/components/ui/Progress";
import {
  uploadDocument,
  getDocument,
  startGeneration,
  type DocumentResponse,
} from "@/lib/api";

const POLL_DOCUMENT_MS = 2000;
const MAX_QUESTIONS = 8;
const MIN_QUESTIONS = 1;

type FormValues = {
  num_questions: number;
  difficulty: "EASY" | "MEDIUM" | "HARD";
};

export function UploadForm({
  onGenerationStarted,
  onError,
}: {
  onGenerationStarted: (testId: string) => void;
  onError: (message: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [doc, setDoc] = useState<DocumentResponse | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [starting, setStarting] = useState(false);

  const { register, handleSubmit } = useForm<FormValues>({
    defaultValues: { num_questions: 8, difficulty: "MEDIUM" },
  });

  const pollDocumentUntilReady = async (documentId: string): Promise<void> => {
    setExtracting(true);
    try {
      for (;;) {
        const d = await getDocument(documentId);
        setDoc(d);
        if (d.status === "ready") {
          setExtracting(false);
          return;
        }
        if (d.status === "extraction_failed" || d.status === "rejected") {
          setExtracting(false);
          throw new Error(d.status === "rejected" ? "Document rejected (e.g. too many pages)." : "Extraction failed.");
        }
        await new Promise((r) => setTimeout(r, POLL_DOCUMENT_MS));
      }
    } catch (e) {
      setExtracting(false);
      throw e;
    }
  };

  const onUpload = async () => {
    if (!file) {
      onError("Select a PDF file.");
      return;
    }
    setUploading(true);
    onError("");
    try {
      const uploaded = await uploadDocument(file);
      setDoc(uploaded);
      await pollDocumentUntilReady(uploaded.id);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const onSubmit = async (values: FormValues) => {
    if (!doc || doc.status !== "ready") {
      onError("Document must be uploaded and ready first.");
      return;
    }
    const n = Math.min(MAX_QUESTIONS, Math.max(MIN_QUESTIONS, Number(values.num_questions)));
    setStarting(true);
    onError("");
    try {
      const test = await startGeneration(doc.id, n, values.difficulty);
      onGenerationStarted(test.id);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Start generation failed.");
    } finally {
      setStarting(false);
    }
  };

  const extractingMessage = doc
    ? doc.status === "processing"
      ? `Extracting pages ${doc.extracted_pages ?? 0}/${doc.total_pages ?? "?"}`
      : doc.status === "ready"
        ? "Ready. Set options and generate."
        : doc.status
    : null;

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>PDF to MCQ</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium">PDF file</label>
          <Input
            type="file"
            accept=".pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={uploading || extracting}
          />
        </div>
        {!doc ? (
          <Button onClick={onUpload} disabled={uploading || !file}>
            {uploading ? "Uploading…" : "Upload"}
          </Button>
        ) : (
          <>
            {extracting && (
              <div className="space-y-2">
                <p className="text-sm text-slate-600">{extractingMessage}</p>
                <Progress value={doc.total_pages ? ((doc.extracted_pages ?? 0) / doc.total_pages) * 100 : 50} />
              </div>
            )}
            {doc.status === "ready" && (
              <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm font-medium">Number of questions (1–8)</label>
                  <Input
                    type="number"
                    min={MIN_QUESTIONS}
                    max={MAX_QUESTIONS}
                    {...register("num_questions", { valueAsNumber: true })}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium">Difficulty</label>
                  <Select {...register("difficulty")}>
                    <option value="EASY">Easy</option>
                    <option value="MEDIUM">Medium</option>
                    <option value="HARD">Hard</option>
                  </Select>
                </div>
                <Button type="submit" disabled={starting}>
                  {starting ? "Starting…" : "Generate MCQs"}
                </Button>
              </form>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
