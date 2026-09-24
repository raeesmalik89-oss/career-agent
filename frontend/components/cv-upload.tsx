"use client";

import { useRef, useState } from "react";
import { Icon } from "./icons";
import { Button, Card, CardHeader, ErrorNote, cx } from "./ui";
import { ApiError, api } from "@/lib/api";

interface UploadResult {
  run_id: string;
  ok: boolean;
  errors: { code: string; message: string }[];
  actions: { type: string }[];
}

const ACCEPT = ".pdf,.docx,.txt,.md";
const MAX_MB = 20;

/** Upload one or more CVs (first file = main CV) plus optional certificates. Facts are extracted for review. */
export function CvUpload({ onDone, compact = false }: { onDone?: () => void; compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);

  function pick(list: FileList | null) {
    if (!list) return;
    const ok = Array.from(list).filter((f) => /\.(pdf|docx|txt|md)$/i.test(f.name) && f.size <= MAX_MB * 1024 * 1024);
    setFiles(ok.slice(0, 20));
    setDone(null);
    setErr(ok.length < list.length ? new ApiError(0, `Only PDF, DOCX, TXT or MD files up to ${MAX_MB} MB are accepted.`) : null);
  }

  async function upload() {
    setBusy(true);
    setErr(null);
    try {
      const form = new FormData();
      files.forEach((f) => form.append("files", f, f.name));
      const r = await api.upload<UploadResult>("/api/v1/resume/upload", form);
      const facts = r.actions.filter((a) => a.type.includes("fact")).length;
      setDone(r.ok ? `Read ${files.length} file${files.length > 1 ? "s" : ""}${facts ? `; ${facts} facts found` : ""}. Review them below.` : r.errors.map((e) => e.message).join(" "));
      setFiles([]);
      onDone?.();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      {!compact && <CardHeader title="Upload your CV" sub="PDF, DOCX or TXT. The first file is your main CV; add older versions or certificates too." />}
      <div className="space-y-3 p-5">
        <button
          type="button"
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            pick(e.dataTransfer.files);
          }}
          className={cx(
            "flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition",
            drag ? "border-accent bg-accent-soft" : "border-border-strong hover:border-accent hover:bg-surface-2",
          )}
        >
          <span className="grid h-10 w-10 place-items-center rounded-full bg-accent-soft text-accent">
            <Icon name="upload" className="h-5 w-5" />
          </span>
          <span className="text-sm font-medium">Drop files here or click to choose</span>
          <span className="text-xs text-muted">Up to {MAX_MB} MB each · parsed on this server, never sent anywhere else</span>
        </button>
        <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => pick(e.target.files)} />
        {files.length > 0 && (
          <ul className="space-y-1 text-sm">
            {files.map((f, i) => (
              <li key={f.name} className="flex items-center justify-between gap-2 rounded-lg bg-surface-2 px-3 py-1.5">
                <span className="truncate">
                  {f.name} {i === 0 && <span className="text-xs text-accent">(main CV)</span>}
                </span>
                <span className="shrink-0 text-xs text-muted tabular">{(f.size / 1024).toFixed(0)} KB</span>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-center gap-3">
          <Button variant="primary" disabled={!files.length || busy} onClick={upload}>
            {busy ? "Reading your CV…" : "Upload and analyse"}
          </Button>
          {done && <span className="text-sm text-good">{done}</span>}
        </div>
        <ErrorNote error={err} />
      </div>
    </Card>
  );
}
