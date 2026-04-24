import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Package, Smartphone, Server, FileSpreadsheet, Trash2, Plus, RefreshCw, FileCode } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const OS_OPTIONS = [
  { value: "android", label: "Android" },
  { value: "ios", label: "iOS" },
  { value: "windows", label: "Windows" },
  { value: "macos", label: "macOS" },
  { value: "linux", label: "Linux" },
];

const NETWORK_OPTIONS = [
  { value: "tiktok", label: "TikTok" },
  { value: "instagram", label: "Instagram" },
  { value: "facebook", label: "Facebook" },
  { value: "snapchat", label: "Snapchat" },
  { value: "twitter", label: "Twitter / X" },
  { value: "youtube", label: "YouTube" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "telegram", label: "Telegram" },
  { value: "chrome", label: "Chrome Browser" },
  { value: "safari", label: "Safari Browser" },
  { value: "firefox", label: "Firefox" },
];

const COUNTRY_OPTIONS = [
  { value: "US", label: "United States" },
  { value: "GB", label: "United Kingdom" },
  { value: "CA", label: "Canada" },
  { value: "AU", label: "Australia" },
  { value: "DE", label: "Germany" },
  { value: "FR", label: "France" },
  { value: "IN", label: "India" },
  { value: "PK", label: "Pakistan" },
  { value: "BR", label: "Brazil" },
  { value: "MX", label: "Mexico" },
];

const TABS = [
  { key: "user_agents", label: "User Agents / Networks", icon: Smartphone },
  { key: "proxies", label: "Proxies", icon: Server },
  { key: "data_file", label: "Data Files", icon: FileSpreadsheet },
  { key: "automation_json", label: "Automation JSON", icon: FileCode },
];

function TagBadge({ children, color = "indigo" }) {
  return (
    <span
      className="inline-block px-2 py-0.5 rounded text-xs font-medium"
      style={{
        backgroundColor: color === "indigo" ? "rgba(99, 102, 241, 0.15)" : "rgba(16, 185, 129, 0.15)",
        color: color === "indigo" ? "rgb(165, 180, 252)" : "rgb(110, 231, 183)",
      }}
    >
      {children}
    </span>
  );
}

export default function UploadedThingsPage() {
  const token = localStorage.getItem("token");
  const [activeTab, setActiveTab] = useState("user_agents");
  const [uploads, setUploads] = useState([]);
  const [loading, setLoading] = useState(false);

  // UA form
  const [uaName, setUaName] = useState("");
  const [uaOs, setUaOs] = useState("android");
  const [uaNetwork, setUaNetwork] = useState("tiktok");
  const [uaText, setUaText] = useState("");
  const [uaSaving, setUaSaving] = useState(false);

  // Proxy form
  const [pxName, setPxName] = useState("");
  const [pxCountry, setPxCountry] = useState("US");
  const [pxState, setPxState] = useState("");
  const [pxText, setPxText] = useState("");
  const [pxSaving, setPxSaving] = useState(false);

  // Data file form
  const [dfName, setDfName] = useState("");
  const [dfFile, setDfFile] = useState(null);
  const [dfSaving, setDfSaving] = useState(false);

  // Automation JSON form
  const [ajName, setAjName] = useState("");
  const [ajDesc, setAjDesc] = useState("");
  const [ajJson, setAjJson] = useState("");
  const [ajSaving, setAjSaving] = useState(false);

  const fetchUploads = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/uploads`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setUploads(r.data || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load uploads");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchUploads();
  }, [fetchUploads]);

  const createUA = async () => {
    if (!uaName.trim()) return toast.error("Give this batch a name");
    if (!uaText.trim()) return toast.error("Paste at least one user-agent");
    setUaSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", uaName);
      fd.append("os_tag", uaOs);
      fd.append("network_tag", uaNetwork);
      fd.append("user_agents", uaText);
      await axios.post(`${API}/uploads/user-agents`, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("User-agent batch saved");
      setUaName(""); setUaText("");
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setUaSaving(false);
    }
  };

  const createProxy = async () => {
    if (!pxName.trim()) return toast.error("Give this batch a name");
    if (!pxText.trim()) return toast.error("Paste at least one proxy line");
    setPxSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", pxName);
      fd.append("country_tag", pxCountry);
      if (pxState.trim()) fd.append("state_tag", pxState.trim());
      fd.append("proxies", pxText);
      await axios.post(`${API}/uploads/proxies`, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Proxy batch saved");
      setPxName(""); setPxText(""); setPxState("");
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setPxSaving(false);
    }
  };

  const createDF = async () => {
    if (!dfName.trim()) return toast.error("Give this file a name");
    if (!dfFile) return toast.error("Choose an Excel/CSV file");
    setDfSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", dfName);
      fd.append("file", dfFile);
      await axios.post(`${API}/uploads/data-file`, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Data file saved");
      setDfName(""); setDfFile(null);
      const inp = document.getElementById("df-file-input");
      if (inp) inp.value = "";
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setDfSaving(false);
    }
  };

  const createAJ = async () => {
    if (!ajName.trim()) return toast.error("Give this template a name");
    if (!ajJson.trim()) return toast.error("Paste the automation JSON");
    try { JSON.parse(ajJson); }
    catch (e) { return toast.error("Invalid JSON: " + e.message); }
    setAjSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", ajName);
      if (ajDesc.trim()) fd.append("description", ajDesc);
      fd.append("automation_json", ajJson);
      await axios.post(`${API}/uploads/automation-json`, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Automation template saved");
      setAjName(""); setAjDesc(""); setAjJson("");
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setAjSaving(false);
    }
  };

  const deleteUpload = async (id, name) => {
    if (!window.confirm(`Delete "${name}"? This cannot be undone.`)) return;
    try {
      await axios.delete(`${API}/uploads/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Deleted");
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  const filtered = uploads.filter((u) => u.type === activeTab);

  const inputClass = "bg-zinc-800 border-zinc-700 text-zinc-100";

  return (
    <div className="space-y-6" data-testid="uploaded-things-page">
      <div className="flex items-center gap-3">
        <Package size={28} style={{ color: "var(--brand-primary)" }} />
        <div>
          <h2 className="text-2xl font-bold" style={{ color: "var(--brand-text)" }}>
            Uploaded Things
          </h2>
          <p className="text-sm text-zinc-400 mt-1">
            Save reusable batches of user-agents, proxies, and data files — then pick them in any Real User Traffic
            campaign with one click. Used batches auto-delete after the job completes so the same leads / proxies
            never get reused.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-2 border-b border-zinc-800 pb-2">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = activeTab === t.key;
          const count = uploads.filter((u) => u.type === t.key).length;
          return (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className="px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-colors"
              style={{
                backgroundColor: active ? "var(--brand-primary)" : "transparent",
                color: active ? "white" : "var(--brand-muted)",
                border: `1px solid ${active ? "var(--brand-primary)" : "var(--brand-border)"}`,
              }}
              data-testid={`ut-tab-${t.key}`}
            >
              <Icon size={16} />
              {t.label}
              <span className="ml-1 text-xs opacity-80">({count})</span>
            </button>
          );
        })}
        <div className="ml-auto">
          <Button
            variant="outline"
            size="sm"
            onClick={fetchUploads}
            disabled={loading}
            data-testid="ut-refresh"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            <span className="ml-2">Refresh</span>
          </Button>
        </div>
      </div>

      {/* UA tab */}
      {activeTab === "user_agents" && (
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="bg-zinc-900/40 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2 text-zinc-100">
                <Plus size={16} /> Add user-agent batch
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label className="text-zinc-300">Batch name</Label>
                <Input
                  value={uaName}
                  onChange={(e) => setUaName(e.target.value)}
                  placeholder="e.g. TikTok Android Pixel UAs"
                  className={inputClass}
                  data-testid="ut-ua-name"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-zinc-300">OS</Label>
                  <select
                    value={uaOs}
                    onChange={(e) => setUaOs(e.target.value)}
                    className="w-full h-10 px-3 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 text-sm"
                    data-testid="ut-ua-os"
                  >
                    {OS_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-zinc-300">Network / App</Label>
                  <select
                    value={uaNetwork}
                    onChange={(e) => setUaNetwork(e.target.value)}
                    className="w-full h-10 px-3 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 text-sm"
                    data-testid="ut-ua-network"
                  >
                    {NETWORK_OPTIONS.map((n) => (
                      <option key={n.value} value={n.value}>{n.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <Label className="text-zinc-300">User-agents (one per line)</Label>
                <Textarea
                  value={uaText}
                  onChange={(e) => setUaText(e.target.value)}
                  placeholder={"Mozilla/5.0 (Linux; Android 12; Pixel 8 Pro) ...\nMozilla/5.0 (Linux; Android 14; Pixel 8) ..."}
                  className={`${inputClass} font-mono text-xs min-h-[180px]`}
                  data-testid="ut-ua-text"
                />
              </div>
              <Button
                onClick={createUA}
                disabled={uaSaving}
                className="w-full"
                style={{ backgroundColor: "var(--brand-primary)" }}
                data-testid="ut-ua-save"
              >
                {uaSaving ? "Saving..." : "Save batch"}
              </Button>
            </CardContent>
          </Card>

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide">
              Your saved UA batches ({filtered.length})
            </h3>
            {filtered.length === 0 && (
              <div className="text-sm text-zinc-500 p-8 text-center border border-dashed border-zinc-800 rounded-lg">
                No user-agent batches yet. Add your first one on the left.
              </div>
            )}
            {filtered.map((u) => (
              <Card key={u.id} className="bg-zinc-900/40 border-zinc-800" data-testid={`ut-item-${u.id}`}>
                <CardContent className="p-4 flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-zinc-100 truncate">{u.name}</div>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {u.os_tag && <TagBadge>OS · {u.os_tag}</TagBadge>}
                      {u.network_tag && <TagBadge color="emerald">App · {u.network_tag}</TagBadge>}
                      <TagBadge>{u.item_count} UAs</TagBadge>
                    </div>
                    <div className="text-xs text-zinc-500 mt-1">
                      {new Date(u.created_at).toLocaleString()}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteUpload(u.id, u.name)}
                    className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                    data-testid={`ut-del-${u.id}`}
                  >
                    <Trash2 size={16} />
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Proxy tab */}
      {activeTab === "proxies" && (
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="bg-zinc-900/40 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2 text-zinc-100">
                <Plus size={16} /> Add proxy batch
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label className="text-zinc-300">Batch name</Label>
                <Input
                  value={pxName}
                  onChange={(e) => setPxName(e.target.value)}
                  placeholder="e.g. US Residential Pool 1"
                  className={inputClass}
                  data-testid="ut-px-name"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-zinc-300">Country</Label>
                  <select
                    value={pxCountry}
                    onChange={(e) => setPxCountry(e.target.value)}
                    className="w-full h-10 px-3 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 text-sm"
                    data-testid="ut-px-country"
                  >
                    {COUNTRY_OPTIONS.map((c) => (
                      <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-zinc-300">State (optional)</Label>
                  <Input
                    value={pxState}
                    onChange={(e) => setPxState(e.target.value.toUpperCase())}
                    placeholder="e.g. CA, NY, TX"
                    maxLength={3}
                    className={inputClass}
                    data-testid="ut-px-state"
                  />
                </div>
              </div>
              <div>
                <Label className="text-zinc-300">Proxies (one per line, user:pass@host:port)</Label>
                <Textarea
                  value={pxText}
                  onChange={(e) => setPxText(e.target.value)}
                  placeholder={"user1:pass1@proxy.example.com:1010\nuser2:pass2@proxy.example.com:1010"}
                  className={`${inputClass} font-mono text-xs min-h-[180px]`}
                  data-testid="ut-px-text"
                />
              </div>
              <Button
                onClick={createProxy}
                disabled={pxSaving}
                className="w-full"
                style={{ backgroundColor: "var(--brand-primary)" }}
                data-testid="ut-px-save"
              >
                {pxSaving ? "Saving..." : "Save batch"}
              </Button>
            </CardContent>
          </Card>

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide">
              Your saved proxy batches ({filtered.length})
            </h3>
            {filtered.length === 0 && (
              <div className="text-sm text-zinc-500 p-8 text-center border border-dashed border-zinc-800 rounded-lg">
                No proxy batches yet.
              </div>
            )}
            {filtered.map((u) => (
              <Card key={u.id} className="bg-zinc-900/40 border-zinc-800" data-testid={`ut-item-${u.id}`}>
                <CardContent className="p-4 flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-zinc-100 truncate">{u.name}</div>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {u.country_tag && <TagBadge>{u.country_tag}</TagBadge>}
                      {u.state_tag && <TagBadge color="emerald">State · {u.state_tag}</TagBadge>}
                      <TagBadge>{u.item_count} proxies</TagBadge>
                    </div>
                    <div className="text-xs text-zinc-500 mt-1">
                      {new Date(u.created_at).toLocaleString()}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteUpload(u.id, u.name)}
                    className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                    data-testid={`ut-del-${u.id}`}
                  >
                    <Trash2 size={16} />
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Data file tab */}
      {activeTab === "data_file" && (
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="bg-zinc-900/40 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2 text-zinc-100">
                <Plus size={16} /> Add data file
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label className="text-zinc-300">File name / label</Label>
                <Input
                  value={dfName}
                  onChange={(e) => setDfName(e.target.value)}
                  placeholder="e.g. 504 Mixed Leads – Jan"
                  className={inputClass}
                  data-testid="ut-df-name"
                />
              </div>
              <div>
                <Label className="text-zinc-300">Excel / CSV file</Label>
                <input
                  id="df-file-input"
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  onChange={(e) => setDfFile(e.target.files?.[0] || null)}
                  className="block w-full text-sm text-zinc-300 mt-2 file:mr-3 file:py-2 file:px-3 file:rounded file:border-0 file:bg-zinc-700 file:text-zinc-100 hover:file:bg-zinc-600"
                  data-testid="ut-df-file"
                />
                {dfFile && (
                  <div className="text-xs text-zinc-400 mt-1.5">
                    Selected: <span className="text-zinc-100">{dfFile.name}</span> ({(dfFile.size / 1024).toFixed(1)} KB)
                  </div>
                )}
              </div>
              <Button
                onClick={createDF}
                disabled={dfSaving}
                className="w-full"
                style={{ backgroundColor: "var(--brand-primary)" }}
                data-testid="ut-df-save"
              >
                {dfSaving ? "Saving..." : "Save file"}
              </Button>
            </CardContent>
          </Card>

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide">
              Your saved data files ({filtered.length})
            </h3>
            {filtered.length === 0 && (
              <div className="text-sm text-zinc-500 p-8 text-center border border-dashed border-zinc-800 rounded-lg">
                No data files yet.
              </div>
            )}
            {filtered.map((u) => (
              <Card key={u.id} className="bg-zinc-900/40 border-zinc-800" data-testid={`ut-item-${u.id}`}>
                <CardContent className="p-4 flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-zinc-100 truncate">{u.name}</div>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {u.file_name && <TagBadge>{u.file_name}</TagBadge>}
                      <TagBadge color="emerald">{u.item_count} rows</TagBadge>
                    </div>
                    <div className="text-xs text-zinc-500 mt-1">
                      {new Date(u.created_at).toLocaleString()}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteUpload(u.id, u.name)}
                    className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                    data-testid={`ut-del-${u.id}`}
                  >
                    <Trash2 size={16} />
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
      {/* Automation JSON tab */}
      {activeTab === "automation_json" && (
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="bg-zinc-900/40 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2 text-zinc-100">
                <Plus size={16} /> Save an automation template
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label className="text-zinc-300">Template name</Label>
                <Input
                  value={ajName}
                  onChange={(e) => setAjName(e.target.value)}
                  placeholder="e.g. Stimulus $750 Form Template"
                  className={inputClass}
                  data-testid="ut-aj-name"
                />
              </div>
              <div>
                <Label className="text-zinc-300">Description (optional)</Label>
                <Input
                  value={ajDesc}
                  onChange={(e) => setAjDesc(e.target.value)}
                  placeholder="e.g. apptrk.addtitans.in → stimulusassistforall → thnkspg"
                  className={inputClass}
                  data-testid="ut-aj-desc"
                />
              </div>
              <div>
                <Label className="text-zinc-300">Automation JSON (step-list array)</Label>
                <Textarea
                  value={ajJson}
                  onChange={(e) => setAjJson(e.target.value)}
                  placeholder={`[\n  { "action": "wait_for_load", "timeout": 30000 },\n  { "action": "fill", "selector": "input[name='first']", "value": "{{first}}" },\n  ...\n]`}
                  className={`${inputClass} font-mono text-xs min-h-[260px]`}
                  data-testid="ut-aj-json"
                />
              </div>
              <div className="p-2 rounded bg-emerald-950/30 border border-emerald-900/50 text-xs text-emerald-300">
                <strong>Reusable</strong> — unlike data/proxy/UA batches, automation templates are <em>not</em>
                auto-deleted after use. Save once, pick from the RUT page every time.
              </div>
              <Button
                onClick={createAJ}
                disabled={ajSaving}
                className="w-full"
                style={{ backgroundColor: "var(--brand-primary)" }}
                data-testid="ut-aj-save"
              >
                {ajSaving ? "Saving..." : "Save template"}
              </Button>
            </CardContent>
          </Card>

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide">
              Your saved automation templates ({filtered.length})
            </h3>
            {filtered.length === 0 && (
              <div className="text-sm text-zinc-500 p-8 text-center border border-dashed border-zinc-800 rounded-lg">
                No automation templates yet. Save your first one on the left.
              </div>
            )}
            {filtered.map((u) => (
              <Card key={u.id} className="bg-zinc-900/40 border-zinc-800" data-testid={`ut-item-${u.id}`}>
                <CardContent className="p-4 flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-zinc-100 truncate">{u.name}</div>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      <TagBadge color="emerald">{u.item_count} steps</TagBadge>
                      <TagBadge>Reusable</TagBadge>
                    </div>
                    {u.automation_json && (
                      <details className="mt-2">
                        <summary className="text-xs text-indigo-400 cursor-pointer">Preview JSON</summary>
                        <pre className="text-xs text-zinc-400 bg-zinc-950/70 p-2 rounded mt-1 overflow-x-auto max-h-48">
                          {u.automation_json.slice(0, 600)}{u.automation_json.length > 600 ? "…" : ""}
                        </pre>
                      </details>
                    )}
                    <div className="text-xs text-zinc-500 mt-1">
                      {new Date(u.created_at).toLocaleString()}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteUpload(u.id, u.name)}
                    className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                    data-testid={`ut-del-${u.id}`}
                  >
                    <Trash2 size={16} />
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
