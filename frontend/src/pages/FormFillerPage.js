import { useState, useEffect, useRef } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import {
  ClipboardCheck,
  Upload,
  Link2,
  Sheet,
  Clock,
  Play,
  RefreshCw,
  Download,
  Trash2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileSpreadsheet,
  ShieldAlert,
} from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

function StatusBadge({ status }) {
  if (status === "completed")
    return <Badge className="bg-emerald-900/50 text-emerald-200 border border-emerald-800">{status}</Badge>;
  if (status === "running" || status === "queued")
    return <Badge className="bg-blue-900/50 text-blue-200 border border-blue-800">{status}</Badge>;
  if (status === "failed")
    return <Badge className="bg-red-900/50 text-red-200 border border-red-800">{status}</Badge>;
  return <Badge className="bg-zinc-800 text-zinc-300">{status}</Badge>;
}

export default function FormFillerPage() {
  const [links, setLinks] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [loadingJobs, setLoadingJobs] = useState(false);

  // Form state
  const [mode, setMode] = useState("link");              // "link" or "url"
  const [targetLinkId, setTargetLinkId] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [dataSource, setDataSource] = useState("excel"); // "excel" or "gsheet"
  const [file, setFile] = useState(null);
  const [gsheetUrl, setGsheetUrl] = useState("");
  const [count, setCount] = useState(10);
  const [duration, setDuration] = useState(5);
  const [skipCaptcha, setSkipCaptcha] = useState(true);
  const [useUAs, setUseUAs] = useState(true);
  const [useProxies, setUseProxies] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef(null);

  // Load user's links + jobs
  const fetchLinks = async () => {
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`${API_URL}/api/links`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.ok) {
        const data = await r.json();
        const arr = Array.isArray(data) ? data : data.links || [];
        setLinks(arr);
      }
    } catch (e) { /* ignore */ }
  };

  const fetchJobs = async () => {
    setLoadingJobs(true);
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`${API_URL}/api/form-filler/jobs`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.ok) {
        const data = await r.json();
        setJobs(data.jobs || []);
      }
    } catch (e) { /* ignore */ }
    finally { setLoadingJobs(false); }
  };

  useEffect(() => {
    fetchLinks();
    fetchJobs();
  }, []);

  // Poll active jobs
  useEffect(() => {
    const hasActive = jobs.some((j) => ["queued", "running"].includes(j.status));
    if (hasActive && !pollRef.current) {
      pollRef.current = setInterval(fetchJobs, 3000);
    } else if (!hasActive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [jobs]);

  const submitJob = async (e) => {
    e.preventDefault();
    if (mode === "link" && !targetLinkId) { toast.error("Pick a link from your panel"); return; }
    if (mode === "url" && !targetUrl.trim()) { toast.error("Paste a target URL"); return; }
    if (dataSource === "excel" && !file) { toast.error("Upload an Excel / CSV file"); return; }
    if (dataSource === "gsheet" && !gsheetUrl.trim()) { toast.error("Paste a Google Sheet URL"); return; }

    setSubmitting(true);
    try {
      const token = localStorage.getItem("token");
      const fd = new FormData();
      if (mode === "link") fd.append("target_link_id", targetLinkId);
      else fd.append("target_url", targetUrl);
      fd.append("data_source", dataSource);
      if (dataSource === "gsheet") fd.append("gsheet_url", gsheetUrl);
      if (dataSource === "excel" && file) fd.append("file", file);
      fd.append("count", String(count));
      fd.append("duration_minutes", String(duration));
      fd.append("skip_captcha", skipCaptcha ? "true" : "false");
      fd.append("use_user_agents", useUAs ? "true" : "false");
      fd.append("use_proxies", useProxies ? "true" : "false");

      const r = await fetch(`${API_URL}/api/form-filler/jobs`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const data = await r.json();
      if (!r.ok) {
        toast.error(data.detail || "Failed to start job");
        return;
      }
      toast.success(`Job started — ${data.total} submissions queued`);
      fetchJobs();
    } catch (err) {
      toast.error("Network error: " + err.message);
    } finally { setSubmitting(false); }
  };

  const downloadJob = async (jid) => {
    const token = localStorage.getItem("token");
    const r = await fetch(`${API_URL}/api/form-filler/jobs/${jid}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) { toast.error("Download failed"); return; }
    const blob = await r.blob();
    const u = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = u; a.download = `form-filler-${jid.slice(0,8)}.zip`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(u);
    toast.success("Downloaded");
  };

  const deleteJob = async (jid) => {
    if (!window.confirm("Delete this job and its screenshots?")) return;
    const token = localStorage.getItem("token");
    const r = await fetch(`${API_URL}/api/form-filler/jobs/${jid}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (r.ok) { toast.success("Deleted"); fetchJobs(); }
    else toast.error("Delete failed");
  };

  return (
    <div className="space-y-6" data-testid="form-filler-page">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <ClipboardCheck className="w-6 h-6 text-emerald-500" />
          Form Filler / Survey Bot
        </h1>
        <p className="text-zinc-400">
          Pick a link from your panel (or paste a URL) → upload Excel/CSV or paste a Google Sheet → we open the form in a headless browser, match columns to form fields by name, submit, and screenshot the result page.
        </p>
      </div>

      <form onSubmit={submitJob}>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader>
            <CardTitle className="text-white">New Job</CardTitle>
            <CardDescription>Build a submission batch</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* Target */}
            <div>
              <Label className="text-zinc-300 mb-2 block">Target</Label>
              <div className="flex gap-2 mb-2">
                <button type="button" onClick={() => setMode("link")}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border ${mode === "link" ? "bg-emerald-600 border-emerald-500 text-white" : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"}`}
                  data-testid="mode-link">
                  <Link2 className="w-4 h-4 inline mr-1" /> From my Links panel
                </button>
                <button type="button" onClick={() => setMode("url")}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border ${mode === "url" ? "bg-emerald-600 border-emerald-500 text-white" : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"}`}
                  data-testid="mode-url">
                  Paste URL
                </button>
              </div>
              {mode === "link" ? (
                <select value={targetLinkId} onChange={(e) => setTargetLinkId(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2"
                  data-testid="link-select">
                  <option value="">— pick a link —</option>
                  {links.map((l) => (
                    <option key={l.id} value={l.id}>
                      {(l.name || l.title || "(no name)")} · {(l.destination_url || l.target_url || l.url || "").slice(0,70)}
                    </option>
                  ))}
                </select>
              ) : (
                <Input value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)}
                  placeholder="https://example.com/survey"
                  className="bg-zinc-800 border-zinc-700 text-white"
                  data-testid="target-url" />
              )}
            </div>

            {/* Data source */}
            <div>
              <Label className="text-zinc-300 mb-2 block">Data source</Label>
              <div className="flex gap-2 mb-2">
                <button type="button" onClick={() => setDataSource("excel")}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border ${dataSource === "excel" ? "bg-emerald-600 border-emerald-500 text-white" : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"}`}
                  data-testid="data-excel">
                  <FileSpreadsheet className="w-4 h-4 inline mr-1" /> Excel / CSV upload
                </button>
                <button type="button" onClick={() => setDataSource("gsheet")}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border ${dataSource === "gsheet" ? "bg-emerald-600 border-emerald-500 text-white" : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"}`}
                  data-testid="data-gsheet">
                  <Sheet className="w-4 h-4 inline mr-1" /> Google Sheet
                </button>
              </div>
              {dataSource === "excel" ? (
                <div>
                  <input type="file" accept=".xlsx,.xls,.csv"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                    className="w-full text-sm text-zinc-300 file:mr-3 file:py-2 file:px-4 file:rounded file:border-0 file:bg-emerald-600 file:text-white hover:file:bg-emerald-700"
                    data-testid="data-file" />
                  <p className="text-xs text-zinc-500 mt-1">
                    Columns must be named like the form fields — e.g. <code>first_name, last_name, email, phone, address</code>. Auto-matches by <code>name</code>, <code>id</code>, <code>placeholder</code>, and <code>aria-label</code>.
                  </p>
                </div>
              ) : (
                <div>
                  <Input value={gsheetUrl} onChange={(e) => setGsheetUrl(e.target.value)}
                    placeholder="https://docs.google.com/spreadsheets/d/.../edit …"
                    className="bg-zinc-800 border-zinc-700 text-white"
                    data-testid="data-gurl" />
                  <p className="text-xs text-zinc-500 mt-1">
                    In Google Sheets: <b>File → Share → Publish to web → CSV</b>, or use a shared-view link (we'll auto-convert to CSV export).
                  </p>
                </div>
              )}
            </div>

            {/* Count + Duration */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label className="text-zinc-300 mb-2 block">How many submissions</Label>
                <Input type="number" min="1" max="5000" value={count}
                  onChange={(e) => setCount(parseInt(e.target.value) || 1)}
                  className="bg-zinc-800 border-zinc-700 text-white"
                  data-testid="ff-count" />
              </div>
              <div>
                <Label className="text-zinc-300 mb-2 block">Complete over how many minutes</Label>
                <Input type="number" min="0" max="1440" step="0.5" value={duration}
                  onChange={(e) => setDuration(parseFloat(e.target.value) || 0)}
                  className="bg-zinc-800 border-zinc-700 text-white"
                  data-testid="ff-duration" />
                <p className="text-xs text-zinc-500 mt-1">
                  Pace: ~{count > 0 ? Math.max(1, (duration * 60 / count)).toFixed(1) : "?"} s between submissions
                </p>
              </div>
            </div>

            {/* Toggles */}
            <div className="flex flex-wrap gap-4 pt-2">
              <label className="flex items-center gap-2 text-sm text-zinc-300">
                <input type="checkbox" checked={skipCaptcha} onChange={(e) => setSkipCaptcha(e.target.checked)}
                  data-testid="skip-captcha" />
                <ShieldAlert className="w-4 h-4 text-amber-400" /> Skip if captcha detected
              </label>
              <label className="flex items-center gap-2 text-sm text-zinc-300">
                <input type="checkbox" checked={useUAs} onChange={(e) => setUseUAs(e.target.checked)}
                  data-testid="use-uas" />
                Rotate realistic user agents
              </label>
              <label className="flex items-center gap-2 text-sm text-zinc-300">
                <input type="checkbox" checked={useProxies} onChange={(e) => setUseProxies(e.target.checked)}
                  data-testid="use-proxies" />
                Use my stored proxies (if any)
              </label>
            </div>

            <div className="pt-2">
              <Button type="submit" disabled={submitting}
                className="bg-emerald-600 hover:bg-emerald-700"
                data-testid="start-job-btn">
                {submitting ? (<><RefreshCw className="w-4 h-4 mr-2 animate-spin" /> Starting…</>) : (<><Play className="w-4 h-4 mr-2" /> Start batch</>)}
              </Button>
            </div>
          </CardContent>
        </Card>
      </form>

      {/* Jobs list */}
      <Card className="bg-zinc-900 border-zinc-800" data-testid="ff-jobs-card">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-white">Jobs</CardTitle>
            <CardDescription>Latest batches — auto-refreshes while running</CardDescription>
          </div>
          <Button variant="outline" onClick={fetchJobs} disabled={loadingJobs}
            className="border-zinc-700 text-zinc-300 h-8"
            data-testid="refresh-jobs-btn">
            <RefreshCw className={`w-4 h-4 ${loadingJobs ? "animate-spin" : ""}`} />
          </Button>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            <div className="text-zinc-500 text-center py-8">No jobs yet — start one above 👆</div>
          ) : (
            <div className="space-y-2">
              {jobs.map((j) => {
                const pct = j.total ? Math.round((j.processed || 0) * 100 / j.total) : 0;
                return (
                  <div key={j.job_id} className="border border-zinc-800 rounded-lg p-3 bg-zinc-950"
                    data-testid={`job-row-${j.job_id.slice(0,8)}`}>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <StatusBadge status={j.status} />
                          <span className="text-xs text-zinc-500">{new Date(j.created_at).toLocaleString()}</span>
                        </div>
                        <div className="text-sm text-white truncate font-mono">{j.target_url}</div>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        {j.status === "completed" && (
                          <Button size="sm" onClick={() => downloadJob(j.job_id)}
                            className="bg-emerald-600 hover:bg-emerald-700 h-8"
                            data-testid={`dl-${j.job_id.slice(0,8)}`}>
                            <Download className="w-3.5 h-3.5 mr-1" /> ZIP
                          </Button>
                        )}
                        <Button size="sm" variant="outline" onClick={() => deleteJob(j.job_id)}
                          className="border-red-800 text-red-300 hover:bg-red-900/30 h-8"
                          data-testid={`del-${j.job_id.slice(0,8)}`}>
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </div>
                    {/* Progress bar */}
                    <div className="h-2 bg-zinc-800 rounded overflow-hidden">
                      <div className="h-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
                    </div>
                    <div className="flex flex-wrap gap-3 mt-2 text-xs text-zinc-400">
                      <span><b className="text-white">{j.processed || 0}/{j.total || 0}</b> processed</span>
                      <span className="text-emerald-400">
                        <CheckCircle2 className="w-3 h-3 inline" /> {j.succeeded || 0} ok
                      </span>
                      <span className="text-amber-400">
                        <AlertTriangle className="w-3 h-3 inline" /> {j.skipped_captcha || 0} captcha-skipped
                      </span>
                      <span className="text-red-400">
                        <XCircle className="w-3 h-3 inline" /> {j.failed || 0} failed
                      </span>
                      {j.delay_seconds && <span className="text-zinc-500">
                        <Clock className="w-3 h-3 inline" /> ~{j.delay_seconds}s pace
                      </span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
