import { useState, useRef } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import {
  Upload,
  FileSpreadsheet,
  Download,
  RefreshCw,
  Trash2,
  Filter,
  Table as TableIcon,
  AlertCircle,
  File as FileIcon,
} from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

export default function SeparateDataPage() {
  const fileInputRef = useRef(null);

  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null); // { filename, columns, total_rows, email_column, preview_rows }
  const [previewing, setPreviewing] = useState(false);

  const [emailColumnOverride, setEmailColumnOverride] = useState("");
  const [emailList, setEmailList] = useState("");
  const [filtering, setFiltering] = useState(false);
  const [lastResult, setLastResult] = useState(null); // { matched, notFound, emailColumn }

  const token = () => localStorage.getItem("token");

  const handleFileChange = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;

    const ext = f.name.toLowerCase().substring(f.name.lastIndexOf("."));
    if (![".xlsx", ".xls", ".csv", ".txt"].includes(ext)) {
      toast.error("Please upload .xlsx, .xls, .csv, or .txt");
      return;
    }

    setFile(f);
    setPreview(null);
    setEmailColumnOverride("");
    setLastResult(null);
    setPreviewing(true);

    const fd = new FormData();
    fd.append("file", f);

    try {
      const r = await fetch(`${API_URL}/api/emails/preview-file`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token()}` },
        body: fd,
      });
      const data = await r.json();
      if (!r.ok) {
        toast.error(data.detail || "Failed to preview file");
        return;
      }
      setPreview(data);
      setEmailColumnOverride(data.email_column || "");
      toast.success(
        `Loaded ${data.total_rows} rows · ${data.columns.length} columns` +
          (data.email_column ? ` · email column: ${data.email_column}` : " · email column not auto-detected")
      );
    } catch (err) {
      toast.error("Error: " + err.message);
    } finally {
      setPreviewing(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const pastedEmailCount = emailList
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter((s) => s && s.includes("@")).length;

  const runFilter = async () => {
    if (!file) {
      toast.error("Upload a spreadsheet first");
      return;
    }
    if (pastedEmailCount === 0) {
      toast.error("Paste at least one email to filter by");
      return;
    }

    setFiltering(true);
    setLastResult(null);

    const fd = new FormData();
    fd.append("file", file);
    fd.append("emails", emailList);
    if (emailColumnOverride) fd.append("email_column", emailColumnOverride);

    try {
      const r = await fetch(`${API_URL}/api/emails/filter-rows`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token()}` },
        body: fd,
      });

      if (!r.ok) {
        // Try to read the JSON error
        let msg = "Filter failed";
        try {
          const data = await r.json();
          msg = data.detail || msg;
        } catch {
          // ignore
        }
        toast.error(msg);
        return;
      }

      const matched = parseInt(r.headers.get("X-Matched-Count") || "0", 10);
      const notFound = parseInt(r.headers.get("X-Not-Found-Count") || "0", 10);
      const emailCol = r.headers.get("X-Email-Column") || emailColumnOverride;
      setLastResult({ matched, notFound, emailColumn: emailCol });

      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;

      // Filename from content-disposition or fall back
      const cd = r.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename="?([^"]+)"?/i);
      a.download = m ? m[1] : "filtered.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);

      if (matched === 0) {
        toast.warning("File downloaded, but NO rows matched the pasted emails");
      } else {
        toast.success(
          `Downloaded ${matched} matched row${matched === 1 ? "" : "s"}` +
            (notFound > 0 ? ` · ${notFound} email(s) not found` : "")
        );
      }
    } catch (err) {
      toast.error("Error: " + err.message);
    } finally {
      setFiltering(false);
    }
  };

  const clearAll = () => {
    setFile(null);
    setPreview(null);
    setEmailColumnOverride("");
    setEmailList("");
    setLastResult(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="space-y-6" data-testid="separate-data-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Separate Data</h1>
          <p className="text-zinc-400">
            Upload your bulk data file, paste the email list you want to keep,
            and download an Excel containing only the matching full rows — all
            your original columns preserved.
          </p>
        </div>
        {(file || emailList) && (
          <Button
            variant="outline"
            onClick={clearAll}
            className="border-zinc-700 text-zinc-300"
            data-testid="sd-clear-btn"
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Clear
          </Button>
        )}
      </div>

      {/* Step 1: Upload master file */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2">
            <Upload className="w-5 h-5 text-blue-500" />
            1. Upload your bulk data file
          </CardTitle>
          <CardDescription>
            Any Excel (.xlsx/.xls) or CSV with any columns. We auto-detect the
            email column from its contents.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3 flex-wrap items-center">
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls,.csv,.txt"
              onChange={handleFileChange}
              className="hidden"
            />
            <Button
              onClick={() => fileInputRef.current?.click()}
              disabled={previewing}
              className="bg-purple-600 hover:bg-purple-700"
              data-testid="sd-upload-btn"
            >
              {previewing ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  Reading file…
                </>
              ) : (
                <>
                  <FileSpreadsheet className="w-4 h-4 mr-2" />
                  Choose Excel/CSV File
                </>
              )}
            </Button>

            {file && (
              <Badge className="bg-zinc-700 text-zinc-100 gap-1">
                <FileIcon className="w-3 h-3" />
                {file.name}
              </Badge>
            )}
            {preview && (
              <>
                <Badge className="bg-blue-700">{preview.total_rows} rows</Badge>
                <Badge className="bg-blue-700">
                  {preview.columns.length} columns
                </Badge>
                {preview.email_column ? (
                  <Badge className="bg-green-700">
                    email column: {preview.email_column}
                  </Badge>
                ) : (
                  <Badge className="bg-yellow-700">email column not auto-detected</Badge>
                )}
              </>
            )}
          </div>

          {/* Email column override */}
          {preview && (
            <div className="flex gap-3 flex-wrap items-center">
              <label className="text-zinc-300 text-sm">Email column:</label>
              <select
                value={emailColumnOverride}
                onChange={(e) => setEmailColumnOverride(e.target.value)}
                className="bg-zinc-800 border border-zinc-700 text-white text-sm rounded px-2 py-1"
                data-testid="sd-email-column-select"
              >
                <option value="">(auto-detect)</option>
                {preview.columns.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <span className="text-zinc-500 text-xs">
                Pick the column that contains the email address if auto-detect
                guessed wrong.
              </span>
            </div>
          )}

          {/* Preview table */}
          {preview && preview.preview_rows.length > 0 && (
            <div className="border border-zinc-800 rounded-md overflow-hidden">
              <div className="bg-zinc-800/70 px-3 py-2 text-xs text-zinc-300 flex items-center gap-2">
                <TableIcon className="w-3 h-3" />
                Preview — first {preview.preview_rows.length} rows
              </div>
              <div className="max-h-72 overflow-auto">
                <table className="w-full text-xs text-zinc-200">
                  <thead className="bg-zinc-800/50 sticky top-0">
                    <tr>
                      {preview.columns.map((c) => (
                        <th
                          key={c}
                          className={`text-left px-3 py-2 whitespace-nowrap font-medium ${
                            c === (emailColumnOverride || preview.email_column)
                              ? "text-green-400"
                              : "text-zinc-300"
                          }`}
                        >
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview_rows.map((r, i) => (
                      <tr
                        key={i}
                        className={i % 2 ? "bg-zinc-900" : "bg-zinc-900/60"}
                      >
                        {preview.columns.map((c) => (
                          <td
                            key={c}
                            className="px-3 py-1.5 whitespace-nowrap text-zinc-200"
                          >
                            {String(r[c] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Step 2: Paste email list */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2">
            <Filter className="w-5 h-5 text-blue-500" />
            2. Paste the email list you want to keep
          </CardTitle>
          <CardDescription>
            Paste one email per line (comma/semicolon also OK). We'll find the
            matching rows in your uploaded file.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            value={emailList}
            onChange={(e) => setEmailList(e.target.value)}
            placeholder={"alice@example.com\nbob@example.com\ncarol@example.org"}
            className="bg-zinc-800 border-zinc-700 text-white h-40 font-mono text-sm"
            data-testid="sd-email-list"
          />

          <div className="flex items-center justify-between flex-wrap gap-3">
            <span className="text-zinc-400 text-sm">
              {pastedEmailCount} email{pastedEmailCount === 1 ? "" : "s"} in list
            </span>
            <Button
              onClick={runFilter}
              disabled={filtering || !file || pastedEmailCount === 0}
              className="bg-green-600 hover:bg-green-700"
              data-testid="sd-filter-btn"
            >
              {filtering ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  Filtering…
                </>
              ) : (
                <>
                  <Download className="w-4 h-4 mr-2" />
                  Filter &amp; Download Excel
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Result summary */}
      {lastResult && (
        <Card
          className={`border ${
            lastResult.matched > 0
              ? "bg-green-900/20 border-green-700"
              : "bg-yellow-900/20 border-yellow-700"
          }`}
          data-testid="sd-result-card"
        >
          <CardContent className="py-5">
            <div className="flex items-start gap-3">
              {lastResult.matched > 0 ? (
                <Download className="w-5 h-5 text-green-400 mt-0.5" />
              ) : (
                <AlertCircle className="w-5 h-5 text-yellow-400 mt-0.5" />
              )}
              <div className="text-sm text-zinc-200 space-y-1">
                <p>
                  <strong className="text-white">{lastResult.matched}</strong>{" "}
                  matching row(s) exported.{" "}
                  <strong className="text-white">{lastResult.notFound}</strong>{" "}
                  email(s) from your list were not found in the file.
                </p>
                <p className="text-zinc-400 text-xs">
                  Matched using column{" "}
                  <span className="text-zinc-200 font-mono">
                    {lastResult.emailColumn || "(auto)"}
                  </span>
                  . The downloaded Excel has 3 sheets: Matched Rows, Summary, Not
                  Found.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
