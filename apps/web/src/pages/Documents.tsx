import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Doc, type ScanProposal } from "../api";
import CaseReview, { type CaseReviewData } from "./CaseReview";
import ScanReview from "./ScanReview";

const TYPE_LABEL: Record<string, string> = {
  imaging: "Imaging", genomics: "Genomics", pathology: "Pathology", lab: "Lab", prescription: "Prescription", advice: "Doctor's advice", other: "Other",
};

export default function Documents({ version, onUpload, onOpenCase, onOpenProgress, onOpenInbox }: { version: number; onUpload: (f: File[]) => Promise<void>; onOpenCase: () => void; onOpenProgress: () => void; onOpenInbox: () => void }) {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [review, setReview] = useState<CaseReviewData | null>(null);
  const [scanReview, setScanReview] = useState<{ doc: Doc; proposal: ScanProposal } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api.documents().then(setDocs), []);
  useEffect(() => {
    void load();
  }, [load, version]);

  async function fill(doc: Doc) {
    setBusy(doc.id);
    setError("");
    try {
      const { fields, as_of, events, rejected } = await api.extractCase(doc.id);
      setReview({ documentId: doc.id, filename: doc.filename, proposal: { fields, as_of, events, rejected } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function readScan(doc: Doc) {
    setBusy(doc.id);
    setError("");
    try {
      setScanReview({ doc, proposal: await api.extractScan(doc.id) });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function remove(doc: Doc) {
    if (!confirm(`Remove ${doc.filename}? This deletes the stored file.`)) return;
    await api.deleteDocument(doc.id);
    await load();
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Documents</h1>
        <p>Reports, scans, prescriptions and doctor advice. Text is read and indexed on your computer so the assistant can cite it.</p>
      </header>
      <div className="dropzone" onClick={() => input.current?.click()}>
        <strong>Drop any number of files here, or click to choose</strong>
        <span>
          They are queued and processed in the background — keep using the app. Results appear in the{" "}
          <button className="link" onClick={(e) => { e.stopPropagation(); onOpenInbox(); }}>Inbox</button> for your review. Scanned pages and photos are read automatically by the local AI (about 30 seconds a page).
        </span>
        <input ref={input} type="file" multiple hidden accept=".pdf,.txt,.md,.csv,.png,.jpg,.jpeg" onChange={(e) => { if (e.target.files) void onUpload(Array.from(e.target.files)); e.target.value = ""; }} />
      </div>
      <div className="row" style={{ marginBottom: 12 }}>
        <button onClick={() => folder.current?.click()}>Choose a folder…</button>
        <button onClick={() => api.scanInbox().then((r) => setNote(r.queued ? `Queued ${r.queued} file(s) from the uploads folder.` : "No new files in the uploads folder."))}>Check the uploads folder</button>
        {note && <span className="muted small">{note}</span>}
        <input ref={folder} type="file" hidden multiple {...({ webkitdirectory: "" } as object)} onChange={(e) => { if (e.target.files) void onUpload(Array.from(e.target.files)); e.target.value = ""; }} />
      </div>
      {busy !== null && (
        <div className="modal-backdrop">
          <div className="modal center">
            <div className="spinner" />
            <h2>Reading the report…</h2>
            <p className="muted">The local AI is extracting details and each one is then checked against the document text. This takes about a minute. A review screen will open next — nothing is saved until you confirm.</p>
          </div>
        </div>
      )}
      {error && (
        <div className="alert urgent">
          Could not read the report: {error} <button onClick={() => setError("")}>Dismiss</button>
        </div>
      )}
      <ul className="doclist">
        {docs.map((d) => (
          <li key={d.id}>
            <div>
              <a href={`/api/documents/${d.id}/file`} target="_blank" rel="noreferrer">
                <strong>{d.filename}</strong>
              </a>
              <div className="muted">
                D{d.id} · {TYPE_LABEL[d.doc_type] ?? d.doc_type} · {d.doc_date || "date unknown"} · {d.page_count} page{d.page_count === 1 ? "" : "s"}
                {d.status === "needs_ocr" && " · scanned — waiting to be read by the AI"}
                {d.status === "unreadable" && " · no readable text found on the page(s)"}
                {d.text_source === "vision_ocr" && d.status === "indexed" && " · AI-read scan — check the original"}
              </div>
            </div>
            <div className="row">
              <button disabled={d.status !== "indexed" || busy !== null} onClick={() => readScan(d)} title="Extract lesion sizes and findings from an imaging report">
                {busy === d.id ? "Reading…" : "Read scan data"}
              </button>
              <button disabled={d.status !== "indexed" || busy !== null} onClick={() => fill(d)}>
                Fill case file
              </button>
              <button className="danger" onClick={() => remove(d)}>
                Remove
              </button>
            </div>
          </li>
        ))}
        {docs.length === 0 && <li className="muted">No documents yet.</li>}
      </ul>
      {review && <CaseReview review={review} onClose={() => setReview(null)} onApplied={() => { setReview(null); onOpenCase(); }} />}
      {scanReview && (
        <ScanReview doc={scanReview.doc} proposal={scanReview.proposal} onClose={() => setScanReview(null)} onSaved={() => { setScanReview(null); onOpenProgress(); }} />
      )}
    </section>
  );
}
