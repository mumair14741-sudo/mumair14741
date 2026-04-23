import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import { Upload, Zap, FileText, Smartphone, Globe, CheckCircle, AlertCircle, Copy, RefreshCw, Radio, Shield, Filter } from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

// Sample User Agents for quick selection
const SAMPLE_USER_AGENTS = {
  "iPhone Instagram": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 302.0.0.34.111",
  "iPhone 15 Instagram": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 310.0.0.38.112",
  "Samsung S24 Instagram": "Mozilla/5.0 (Linux; Android 14; Samsung Galaxy S24) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 302.0.0.34.111",
  "Samsung S23 Instagram": "Mozilla/5.0 (Linux; Android 13; Samsung Galaxy S23 Ultra) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36 Instagram 298.0.0.31.115",
  "Pixel 8 Instagram": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 302.0.0.34.111",
  "OnePlus 12 Instagram": "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 302.0.0.34.111",
  "Xiaomi 14 Instagram": "Mozilla/5.0 (Linux; Android 14; Xiaomi 14 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 302.0.0.34.111",
  "iPad Instagram": "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 302.0.0.34.111",
};

const COUNTRIES = [
  "Pakistan", "India", "United States", "United Kingdom", "Canada", "Australia",
  "Germany", "France", "Italy", "Spain", "Netherlands", "Brazil", "Mexico",
  "United Arab Emirates", "Saudi Arabia", "Turkey", "Indonesia", "Philippines",
  "Thailand", "Vietnam", "Japan", "South Korea", "Nigeria", "South Africa", "Egypt"
];

export default function ImportTrafficPage() {
  const [links, setLinks] = useState([]);
  const [selectedLink, setSelectedLink] = useState("");
  const [loading, setLoading] = useState(false);
  const [importResult, setImportResult] = useState(null);
  
  // Quick Generate state
  const [quickCount, setQuickCount] = useState(10);
  const [quickCountries, setQuickCountries] = useState(["Pakistan", "India", "United States"]);
  const [quickIpList, setQuickIpList] = useState("");
  
  // Manual Import state
  const [manualData, setManualData] = useState([
    { ip: "", user_agent: "", country: "Pakistan" }
  ]);
  
  // Bulk Import state
  const [bulkText, setBulkText] = useState("");
  const [bulkFormat, setBulkFormat] = useState("csv"); // csv or json

  // Real Traffic state
  const [realProxies, setRealProxies] = useState("");
  const [realUserAgents, setRealUserAgents] = useState("");
  const [realTotal, setRealTotal] = useState(10);
  const [realConcurrency, setRealConcurrency] = useState(3);
  const [realSkipDup, setRealSkipDup] = useState(true);
  const [realSkipVpn, setRealSkipVpn] = useState(true);
  const [realAllowedCountries, setRealAllowedCountries] = useState([]);
  const [realFollowRedirect, setRealFollowRedirect] = useState(false);
  const [realNoRepeatProxy, setRealNoRepeatProxy] = useState(false);
  const [realTargetUrl, setRealTargetUrl] = useState("");
  const [realResolvedUrl, setRealResolvedUrl] = useState("");
  const [realDurationMin, setRealDurationMin] = useState(0); // 0 = as fast as possible
  const [realRunning, setRealRunning] = useState(false);
  const [realLog, setRealLog] = useState([]);
  const [realStats, setRealStats] = useState(null);
  const [realAbortCtrl, setRealAbortCtrl] = useState(null);

  useEffect(() => {
    fetchLinks();
    // If UA Generator pushed a UA list here, prefill the Real Traffic UA textarea once
    try {
      const stash = localStorage.getItem("ua_generator_payload");
      if (stash && stash.trim()) {
        setRealUserAgents(stash);
        localStorage.removeItem("ua_generator_payload");
        toast.success(`Loaded ${stash.split("\n").filter(Boolean).length} UAs from UA Generator`);
      }
    } catch (e) { /* ignore */ }
  }, []);

  const fetchLinks = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await fetch(`${API_URL}/api/links`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (response.ok) {
        const data = await response.json();
        setLinks(data);
        if (data.length > 0 && !selectedLink) {
          setSelectedLink(data[0].id);
        }
      }
    } catch (error) {
      console.error("Error fetching links:", error);
    }
  };

  // Quick Generate - Random traffic
  const handleQuickGenerate = async () => {
    if (!selectedLink) {
      toast.error("Please select a link first");
      return;
    }
    
    setLoading(true);
    setImportResult(null);
    
    try {
      const token = localStorage.getItem("token");
      const ipList = quickIpList.trim() ? quickIpList.split("\n").map(ip => ip.trim()).filter(ip => ip) : null;
      
      const response = await fetch(`${API_URL}/api/clicks/generate-traffic`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          link_id: selectedLink,
          count: quickCount,
          ip_list: ipList,
          countries: quickCountries
        })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        setImportResult({ success: true, ...data });
        toast.success(`Generated ${data.generated} clicks!`);
      } else {
        setImportResult({ success: false, error: data.detail });
        toast.error(data.detail || "Generation failed");
      }
    } catch (error) {
      toast.error("Network error");
      setImportResult({ success: false, error: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Manual Import - Add row
  const addManualRow = () => {
    setManualData([...manualData, { ip: "", user_agent: "", country: "Pakistan" }]);
  };

  const removeManualRow = (index) => {
    setManualData(manualData.filter((_, i) => i !== index));
  };

  const updateManualRow = (index, field, value) => {
    const newData = [...manualData];
    newData[index][field] = value;
    setManualData(newData);
  };

  const handleManualImport = async () => {
    if (!selectedLink) {
      toast.error("Please select a link first");
      return;
    }
    
    const validClicks = manualData.filter(d => d.ip.trim());
    if (validClicks.length === 0) {
      toast.error("Please add at least one IP address");
      return;
    }
    
    setLoading(true);
    setImportResult(null);
    
    try {
      const token = localStorage.getItem("token");
      
      const response = await fetch(`${API_URL}/api/clicks/import-bulk`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          link_id: selectedLink,
          clicks: validClicks
        })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        setImportResult({ success: true, ...data });
        toast.success(`Imported ${data.imported} clicks!`);
        setManualData([{ ip: "", user_agent: "", country: "Pakistan" }]);
      } else {
        setImportResult({ success: false, error: data.detail });
        toast.error(data.detail || "Import failed");
      }
    } catch (error) {
      toast.error("Network error");
      setImportResult({ success: false, error: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Bulk Import - Parse and import
  const handleBulkImport = async () => {
    if (!selectedLink) {
      toast.error("Please select a link first");
      return;
    }
    
    if (!bulkText.trim()) {
      toast.error("Please paste your data");
      return;
    }
    
    setLoading(true);
    setImportResult(null);
    
    try {
      let clicks = [];
      
      if (bulkFormat === "json") {
        // Parse JSON
        clicks = JSON.parse(bulkText);
      } else {
        // Parse CSV (ip,user_agent,country)
        const lines = bulkText.trim().split("\n");
        for (const line of lines) {
          const parts = line.split(",").map(p => p.trim());
          if (parts[0]) {
            clicks.push({
              ip: parts[0],
              user_agent: parts[1] || SAMPLE_USER_AGENTS["iPhone Instagram"],
              country: parts[2] || "Pakistan"
            });
          }
        }
      }
      
      if (clicks.length === 0) {
        toast.error("No valid data found");
        setLoading(false);
        return;
      }
      
      const token = localStorage.getItem("token");
      
      const response = await fetch(`${API_URL}/api/clicks/import-bulk`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          link_id: selectedLink,
          clicks: clicks
        })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        setImportResult({ success: true, ...data });
        toast.success(`Imported ${data.imported} clicks!`);
        setBulkText("");
      } else {
        setImportResult({ success: false, error: data.detail });
        toast.error(data.detail || "Import failed");
      }
    } catch (error) {
      toast.error("Invalid format: " + error.message);
      setImportResult({ success: false, error: error.message });
    } finally {
      setLoading(false);
    }
  };

  const copyUserAgent = (ua) => {
    navigator.clipboard.writeText(ua);
    toast.success("Copied to clipboard!");
  };

  // Real Traffic handler (streaming NDJSON)
  const handleSendRealTraffic = async () => {
    if (!selectedLink) {
      toast.error("Please select a link first");
      return;
    }
    const proxies = realProxies.split("\n").map(l => l.trim()).filter(Boolean);
    const uas = realUserAgents.split("\n").map(l => l.trim()).filter(Boolean);
    if (proxies.length === 0) {
      toast.error("Paste at least one proxy");
      return;
    }
    if (uas.length === 0) {
      toast.error("Paste at least one user agent");
      return;
    }

    setRealRunning(true);
    setRealLog([]);
    setRealStats(null);
    setRealResolvedUrl("");

    const countries = realAllowedCountries;

    const controller = new AbortController();
    setRealAbortCtrl(controller);

    const token = localStorage.getItem("token");
    try {
      const response = await fetch(`${API_URL}/api/traffic/send-real`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          link_id: selectedLink,
          proxies,
          user_agents: uas,
          total_clicks: realTotal,
          concurrency: realConcurrency,
          skip_duplicate: realSkipDup,
          skip_vpn: realSkipVpn,
          allowed_countries: countries,
          follow_redirect: realFollowRedirect,
          no_repeat_proxy: realNoRepeatProxy,
          target_url: realTargetUrl.trim() || null,
          duration_minutes: realDurationMin > 0 ? realDurationMin : null
        }),
        signal: controller.signal
      });

      if (!response.ok) {
        let msg = "Request failed";
        try { const d = await response.json(); msg = d.detail || msg; } catch (e) { /* ignore */ }
        toast.error(msg);
        setRealRunning(false);
        setRealAbortCtrl(null);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const newLog = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value);
        const lines = text.split("\n").filter(l => l.trim());
        for (const line of lines) {
          try {
            const data = JSON.parse(line);
            if (data.type === "info") {
              setRealResolvedUrl(data.target_url || "");
            } else if (data.type === "result") {
              newLog.push(data);
              setRealLog([...newLog]);
            } else if (data.type === "progress") {
              setRealStats({ ...data });
            } else if (data.type === "complete") {
              setRealStats({ ...data, done: true });
            }
          } catch (e) { /* ignore malformed line */ }
        }
      }
      toast.success("Real traffic run complete");
    } catch (error) {
      if (error.name === "AbortError") {
        toast.info("Real traffic run stopped");
      } else {
        toast.error("Network error: " + error.message);
      }
    } finally {
      setRealRunning(false);
      setRealAbortCtrl(null);
    }
  };

  const handleStopRealTraffic = () => {
    if (realAbortCtrl) {
      realAbortCtrl.abort();
    }
  };

  const downloadRealLog = () => {
    if (realLog.length === 0) return;
    const header = "index,proxy,exit_ip,country,status,reason,http_status,ua\n";
    const rows = realLog.map(r =>
      [
        r.index,
        (r.proxy || "").replace(/,/g, ";"),
        r.exit_ip || "",
        r.country || "",
        r.status,
        (r.reason || "").replace(/,/g, ";"),
        r.http_status || "",
        (r.ua || "").replace(/,/g, ";"),
      ].join(",")
    ).join("\n");
    const blob = new Blob([header + rows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `real_traffic_log_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };



  return (
    <div className="space-y-6" data-testid="import-traffic-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Import Traffic</h1>
          <p className="text-zinc-400">Add clicks with custom IPs, user agents, and countries</p>
        </div>
      </div>

      {/* Link Selection */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader className="pb-3">
          <CardTitle className="text-white flex items-center gap-2">
            <Globe className="w-5 h-5 text-blue-500" />
            Select Link
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Select value={selectedLink} onValueChange={setSelectedLink}>
            <SelectTrigger className="bg-zinc-800 border-zinc-700 text-white" data-testid="link-select">
              <SelectValue placeholder="Select a link..." />
            </SelectTrigger>
            <SelectContent className="bg-zinc-800 border-zinc-700">
              {links.map(link => (
                <SelectItem key={link.id} value={link.id} className="text-white hover:bg-zinc-700">
                  {link.name || link.short_code} - /t/{link.short_code}
                  {link.forced_source && <Badge className="ml-2 bg-pink-600">{link.forced_source}</Badge>}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {/* Import Result */}
      {importResult && (
        <Card className={`border ${importResult.success ? 'bg-green-900/20 border-green-700' : 'bg-red-900/20 border-red-700'}`}>
          <CardContent className="py-4">
            <div className="flex items-center gap-3">
              {importResult.success ? (
                <CheckCircle className="w-6 h-6 text-green-500" />
              ) : (
                <AlertCircle className="w-6 h-6 text-red-500" />
              )}
              <div>
                <p className="text-white font-medium">
                  {importResult.success ? importResult.message : "Import Failed"}
                </p>
                {importResult.sample_devices && (
                  <p className="text-zinc-400 text-sm">
                    Devices: {importResult.sample_devices.join(", ")}
                  </p>
                )}
                {importResult.error && (
                  <p className="text-red-400 text-sm">{importResult.error}</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Import Tabs */}
      <Tabs defaultValue="quick" className="space-y-4">
        <TabsList className="bg-zinc-800 border-zinc-700">
          <TabsTrigger value="quick" className="data-[state=active]:bg-blue-600">
            <Zap className="w-4 h-4 mr-2" />
            Quick Generate
          </TabsTrigger>
          <TabsTrigger value="manual" className="data-[state=active]:bg-blue-600">
            <Smartphone className="w-4 h-4 mr-2" />
            Manual Entry
          </TabsTrigger>
          <TabsTrigger value="bulk" className="data-[state=active]:bg-blue-600">
            <FileText className="w-4 h-4 mr-2" />
            Bulk Import
          </TabsTrigger>
          <TabsTrigger value="real" className="data-[state=active]:bg-blue-600" data-testid="real-traffic-tab">
            <Radio className="w-4 h-4 mr-2" />
            Real Traffic
          </TabsTrigger>
        </TabsList>

        {/* Quick Generate Tab */}
        <TabsContent value="quick">
          <Card className="bg-zinc-900 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-white">Quick Generate Traffic</CardTitle>
              <CardDescription>Generate random Instagram traffic with realistic devices</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-zinc-300">Number of Clicks</Label>
                  <Input
                    type="number"
                    min="1"
                    max="1000"
                    value={quickCount}
                    onChange={(e) => setQuickCount(parseInt(e.target.value) || 10)}
                    className="bg-zinc-800 border-zinc-700 text-white"
                    data-testid="quick-count-input"
                  />
                </div>
                <div>
                  <Label className="text-zinc-300">Countries (comma separated)</Label>
                  <Input
                    value={quickCountries.join(", ")}
                    onChange={(e) => setQuickCountries(e.target.value.split(",").map(c => c.trim()).filter(c => c))}
                    placeholder="Pakistan, India, USA"
                    className="bg-zinc-800 border-zinc-700 text-white"
                  />
                </div>
              </div>
              
              <div>
                <Label className="text-zinc-300">Custom IP List (optional - one per line)</Label>
                <Textarea
                  value={quickIpList}
                  onChange={(e) => setQuickIpList(e.target.value)}
                  placeholder="Leave empty for random IPs, or paste your IPs:&#10;103.45.67.89&#10;92.123.45.67&#10;185.234.56.78"
                  className="bg-zinc-800 border-zinc-700 text-white h-32"
                  data-testid="quick-ip-list"
                />
              </div>
              
              <Button 
                onClick={handleQuickGenerate} 
                disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-700"
                data-testid="quick-generate-btn"
              >
                {loading ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />}
                Generate {quickCount} Clicks
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Manual Entry Tab */}
        <TabsContent value="manual">
          <Card className="bg-zinc-900 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-white">Manual Entry</CardTitle>
              <CardDescription>Add clicks one by one with full control</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Sample User Agents */}
              <div className="p-3 bg-zinc-800 rounded-lg">
                <Label className="text-zinc-300 mb-2 block">Quick Copy User Agents:</Label>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(SAMPLE_USER_AGENTS).slice(0, 4).map(([name, ua]) => (
                    <Badge 
                      key={name}
                      className="bg-zinc-700 hover:bg-zinc-600 cursor-pointer"
                      onClick={() => copyUserAgent(ua)}
                    >
                      <Copy className="w-3 h-3 mr-1" />
                      {name}
                    </Badge>
                  ))}
                </div>
              </div>

              {/* Manual Rows */}
              <div className="space-y-3">
                {manualData.map((row, index) => (
                  <div key={index} className="grid grid-cols-12 gap-2 items-end">
                    <div className="col-span-3">
                      <Label className="text-zinc-400 text-xs">IP Address</Label>
                      <Input
                        value={row.ip}
                        onChange={(e) => updateManualRow(index, "ip", e.target.value)}
                        placeholder="103.45.67.89"
                        className="bg-zinc-800 border-zinc-700 text-white"
                      />
                    </div>
                    <div className="col-span-5">
                      <Label className="text-zinc-400 text-xs">User Agent</Label>
                      <Select 
                        value={row.user_agent || "custom"}
                        onValueChange={(v) => updateManualRow(index, "user_agent", v === "custom" ? "" : v)}
                      >
                        <SelectTrigger className="bg-zinc-800 border-zinc-700 text-white">
                          <SelectValue placeholder="Select or paste..." />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-800 border-zinc-700 max-h-60">
                          <SelectItem value="custom" className="text-zinc-400">Custom (paste below)</SelectItem>
                          {Object.entries(SAMPLE_USER_AGENTS).map(([name, ua]) => (
                            <SelectItem key={name} value={ua} className="text-white hover:bg-zinc-700">
                              {name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="col-span-3">
                      <Label className="text-zinc-400 text-xs">Country</Label>
                      <Select value={row.country} onValueChange={(v) => updateManualRow(index, "country", v)}>
                        <SelectTrigger className="bg-zinc-800 border-zinc-700 text-white">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-800 border-zinc-700 max-h-60">
                          {COUNTRIES.map(country => (
                            <SelectItem key={country} value={country} className="text-white hover:bg-zinc-700">
                              {country}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="col-span-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => removeManualRow(index)}
                        className="text-red-500 hover:text-red-400 hover:bg-red-900/20"
                        disabled={manualData.length === 1}
                      >
                        ×
                      </Button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex gap-2">
                <Button variant="outline" onClick={addManualRow} className="border-zinc-700 text-zinc-300">
                  + Add Row
                </Button>
                <Button 
                  onClick={handleManualImport} 
                  disabled={loading}
                  className="flex-1 bg-green-600 hover:bg-green-700"
                  data-testid="manual-import-btn"
                >
                  {loading ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Upload className="w-4 h-4 mr-2" />}
                  Import {manualData.filter(d => d.ip.trim()).length} Clicks
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Bulk Import Tab */}
        <TabsContent value="bulk">
          <Card className="bg-zinc-900 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-white">Bulk Import</CardTitle>
              <CardDescription>Paste CSV or JSON data to import many clicks at once</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Button
                  variant={bulkFormat === "csv" ? "default" : "outline"}
                  onClick={() => setBulkFormat("csv")}
                  className={bulkFormat === "csv" ? "bg-blue-600" : "border-zinc-700 text-zinc-300"}
                >
                  CSV Format
                </Button>
                <Button
                  variant={bulkFormat === "json" ? "default" : "outline"}
                  onClick={() => setBulkFormat("json")}
                  className={bulkFormat === "json" ? "bg-blue-600" : "border-zinc-700 text-zinc-300"}
                >
                  JSON Format
                </Button>
              </div>

              <div className="p-3 bg-zinc-800 rounded-lg text-sm">
                <p className="text-zinc-400 mb-2">Format Example:</p>
                {bulkFormat === "csv" ? (
                  <pre className="text-green-400 text-xs overflow-x-auto">
{`ip,user_agent,country
103.45.67.89,Mozilla/5.0 (iPhone...) Instagram/302.0,Pakistan
92.123.45.67,Mozilla/5.0 (Samsung...) Instagram/301.0,India
185.234.56.78,,United States`}
                  </pre>
                ) : (
                  <pre className="text-green-400 text-xs overflow-x-auto">
{`[
  {"ip": "103.45.67.89", "user_agent": "Mozilla/5.0...", "country": "Pakistan"},
  {"ip": "92.123.45.67", "user_agent": "Mozilla/5.0...", "country": "India"}
]`}
                  </pre>
                )}
              </div>

              <Textarea
                value={bulkText}
                onChange={(e) => setBulkText(e.target.value)}
                placeholder={bulkFormat === "csv" 
                  ? "Paste CSV data here...\nip,user_agent,country\n103.45.67.89,Mozilla/5.0...,Pakistan"
                  : 'Paste JSON array here...\n[{"ip": "103.45.67.89", "user_agent": "...", "country": "Pakistan"}]'
                }
                className="bg-zinc-800 border-zinc-700 text-white h-48 font-mono text-sm"
                data-testid="bulk-text-input"
              />

              <Button 
                onClick={handleBulkImport} 
                disabled={loading}
                className="w-full bg-purple-600 hover:bg-purple-700"
                data-testid="bulk-import-btn"
              >
                {loading ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Upload className="w-4 h-4 mr-2" />}
                Import Bulk Data
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Real Traffic Tab */}
        <TabsContent value="real">
          <Card className="bg-zinc-900 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-white flex items-center gap-2">
                <Radio className="w-5 h-5 text-red-500" />
                Real HTTP Traffic via Residential Proxies
              </CardTitle>
              <CardDescription>
                Fires <strong>real</strong> HTTP GET requests against your selected short link
                through each proxy you paste. Each exit IP is checked for duplicates, VPN, and
                allowed country BEFORE the click is sent — so only clean traffic reaches your tracker.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-zinc-300">Proxies (one per line)</Label>
                  <Textarea
                    value={realProxies}
                    onChange={(e) => setRealProxies(e.target.value)}
                    placeholder={"user:pass@host:port\nuser:pass@host:port"}
                    className="bg-zinc-800 border-zinc-700 text-white h-48 font-mono text-xs"
                    data-testid="real-proxies-input"
                  />
                  <p className="text-zinc-500 text-xs mt-1">
                    {realProxies.split("\n").map(l => l.trim()).filter(Boolean).length} proxies
                  </p>
                </div>
                <div>
                  <Label className="text-zinc-300">User Agents (one per line)</Label>
                  <Textarea
                    value={realUserAgents}
                    onChange={(e) => setRealUserAgents(e.target.value)}
                    placeholder={"Mozilla/5.0 (Linux; Android 15; ...) ..."}
                    className="bg-zinc-800 border-zinc-700 text-white h-48 font-mono text-xs"
                    data-testid="real-uas-input"
                  />
                  <p className="text-zinc-500 text-xs mt-1">
                    {realUserAgents.split("\n").map(l => l.trim()).filter(Boolean).length} UAs
                  </p>
                </div>
              </div>

              <div>
                <Label className="text-zinc-300">
                  Target URL{" "}
                  <span className="text-zinc-500 text-xs">
                    (optional — paste your PUBLIC short-link URL here if your tracker isn't
                    reachable from the internet, e.g. localhost / Docker / behind NAT)
                  </span>
                </Label>
                <Input
                  value={realTargetUrl}
                  onChange={(e) => setRealTargetUrl(e.target.value)}
                  placeholder="https://yourdomain.com/t/insta  — leave empty to auto-detect"
                  className="bg-zinc-800 border-zinc-700 text-white font-mono text-xs"
                  data-testid="real-target-url"
                />
                {realResolvedUrl && (
                  <p className="text-green-400 text-xs mt-1 font-mono">
                    Firing at: {realResolvedUrl}
                  </p>
                )}
              </div>

              <div className="p-3 bg-zinc-800/50 border border-zinc-700 rounded-lg">
                <Label className="text-zinc-200 font-medium flex items-center gap-2">
                  <RefreshCw className="w-4 h-4 text-blue-400" />
                  Pacing — deliver clicks over time (optional)
                </Label>
                <p className="text-zinc-500 text-xs mt-1 mb-3">
                  Set duration in minutes to spread the run. e.g. Target=1000 + Duration=20 → about one click every ~1.2s.
                  Leave 0 to fire as fast as possible.
                </p>
                <div className="grid grid-cols-3 gap-3 items-end">
                  <div>
                    <Label className="text-zinc-400 text-xs">Duration (minutes)</Label>
                    <Input
                      type="number"
                      min="0"
                      step="0.5"
                      value={realDurationMin}
                      onChange={(e) => setRealDurationMin(parseFloat(e.target.value) || 0)}
                      className="bg-zinc-900 border-zinc-700 text-white"
                      data-testid="real-duration"
                      placeholder="0 = instant"
                    />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {[1, 5, 10, 20, 30, 60].map((m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setRealDurationMin(m)}
                        className={`px-2 py-1 text-[11px] rounded border ${
                          realDurationMin === m
                            ? "bg-blue-600 border-blue-500 text-white"
                            : "bg-zinc-900 border-zinc-700 text-zinc-300 hover:bg-zinc-800"
                        }`}
                      >
                        {m}m
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => setRealDurationMin(0)}
                      className={`px-2 py-1 text-[11px] rounded border ${
                        realDurationMin === 0
                          ? "bg-red-600 border-red-500 text-white"
                          : "bg-zinc-900 border-zinc-700 text-zinc-300 hover:bg-zinc-800"
                      }`}
                    >
                      Instant
                    </button>
                  </div>
                  <div className="text-xs text-zinc-400">
                    {realDurationMin > 0 && realTotal > 0 ? (
                      <>
                        <div>
                          ≈{" "}
                          <span className="text-white font-mono">
                            {((realDurationMin * 60) / realTotal).toFixed(2)}s
                          </span>{" "}
                          between attempts
                        </div>
                        <div className="text-zinc-500">
                          Total run: ~{realDurationMin} minute{realDurationMin === 1 ? "" : "s"}
                        </div>
                      </>
                    ) : (
                      <span className="text-zinc-500">As fast as proxies allow</span>
                    )}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-zinc-300">Total Clicks Target</Label>
                  <Input
                    type="number"
                    min="1"
                    max="100000"
                    value={realTotal}
                    onChange={(e) => setRealTotal(parseInt(e.target.value) || 10)}
                    className="bg-zinc-800 border-zinc-700 text-white"
                    data-testid="real-total-input"
                  />
                </div>
                <div>
                  <Label className="text-zinc-300">Concurrency (1-20)</Label>
                  <Input
                    type="number"
                    min="1"
                    max="20"
                    value={realConcurrency}
                    onChange={(e) => setRealConcurrency(parseInt(e.target.value) || 3)}
                    className="bg-zinc-800 border-zinc-700 text-white"
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <Label className="text-zinc-300">
                    Allowed Countries{" "}
                    <span className="text-zinc-500 text-xs">
                      (click to toggle — leave empty to allow ALL countries)
                    </span>
                  </Label>
                  {realAllowedCountries.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setRealAllowedCountries([])}
                      className="text-xs text-zinc-400 hover:text-red-300 underline"
                      data-testid="real-clear-countries"
                    >
                      Clear all
                    </button>
                  )}
                </div>
                <div className="flex flex-wrap gap-2 p-3 bg-zinc-800/50 border border-zinc-700 rounded-lg max-h-40 overflow-y-auto">
                  {COUNTRIES.map((c) => {
                    const active = realAllowedCountries.includes(c);
                    return (
                      <button
                        key={c}
                        type="button"
                        onClick={() =>
                          setRealAllowedCountries((prev) =>
                            prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]
                          )
                        }
                        className={`px-3 py-1 rounded-full text-xs border transition ${
                          active
                            ? "bg-blue-600 border-blue-500 text-white"
                            : "bg-zinc-900 border-zinc-700 text-zinc-300 hover:bg-zinc-800"
                        }`}
                        data-testid={`real-country-${c.toLowerCase().replace(/\s+/g, "-")}`}
                      >
                        {c}
                      </button>
                    );
                  })}
                </div>
                <p className="text-zinc-500 text-xs mt-1">
                  {realAllowedCountries.length === 0
                    ? "Any country will be accepted"
                    : `Only: ${realAllowedCountries.join(", ")}`}
                </p>
              </div>

              <div className="flex flex-wrap gap-5 p-3 bg-zinc-800/60 rounded-lg border border-zinc-700">
                <label className="flex items-center gap-2 text-zinc-200 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={realSkipDup}
                    onChange={(e) => setRealSkipDup(e.target.checked)}
                    className="w-4 h-4"
                    data-testid="real-skip-dup"
                  />
                  <Filter className="w-4 h-4" /> Skip duplicate exit IP
                </label>
                <label className="flex items-center gap-2 text-zinc-200 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={realSkipVpn}
                    onChange={(e) => setRealSkipVpn(e.target.checked)}
                    className="w-4 h-4"
                    data-testid="real-skip-vpn"
                  />
                  <Shield className="w-4 h-4" /> Skip VPN / datacenter
                </label>
                <label className="flex items-center gap-2 text-zinc-200 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={realFollowRedirect}
                    onChange={(e) => setRealFollowRedirect(e.target.checked)}
                    className="w-4 h-4"
                  />
                  <Globe className="w-4 h-4" /> Follow redirect to offer URL
                </label>
                <label className="flex items-center gap-2 text-zinc-200 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={realNoRepeatProxy}
                    onChange={(e) => setRealNoRepeatProxy(e.target.checked)}
                    className="w-4 h-4"
                    data-testid="real-no-repeat"
                  />
                  <RefreshCw className="w-4 h-4" /> No repeated proxy (one use per line)
                </label>
              </div>

              <div className="flex gap-2">
                <Button
                  onClick={handleSendRealTraffic}
                  disabled={realRunning || !selectedLink}
                  className="flex-1 bg-red-600 hover:bg-red-700"
                  data-testid="send-real-traffic-btn"
                >
                  {realRunning ? (
                    <><RefreshCw className="w-4 h-4 mr-2 animate-spin" /> Firing real traffic...</>
                  ) : (
                    <><Radio className="w-4 h-4 mr-2" /> Send {realTotal} Real Clicks</>
                  )}
                </Button>
                {realRunning && (
                  <Button
                    onClick={handleStopRealTraffic}
                    variant="outline"
                    className="border-red-700 text-red-300 hover:bg-red-900/30"
                    data-testid="stop-real-traffic-btn"
                  >
                    <AlertCircle className="w-4 h-4 mr-2" /> Stop
                  </Button>
                )}
              </div>

              {/* Live Stats */}
              {realStats && (
                <div className="grid grid-cols-6 gap-2">
                  <div className="bg-blue-900/30 border border-blue-700 rounded p-2 text-center">
                    <div className="text-lg font-bold text-blue-300">{realStats.succeeded || 0}</div>
                    <div className="text-[10px] text-blue-400 uppercase">Succeeded</div>
                  </div>
                  <div className="bg-zinc-800 border border-zinc-700 rounded p-2 text-center">
                    <div className="text-lg font-bold text-zinc-200">{realStats.attempted || 0}</div>
                    <div className="text-[10px] text-zinc-400 uppercase">Attempted</div>
                  </div>
                  <div className="bg-yellow-900/30 border border-yellow-700 rounded p-2 text-center">
                    <div className="text-lg font-bold text-yellow-300">{realStats.blocked_dup || 0}</div>
                    <div className="text-[10px] text-yellow-400 uppercase">Dup Skip</div>
                  </div>
                  <div className="bg-purple-900/30 border border-purple-700 rounded p-2 text-center">
                    <div className="text-lg font-bold text-purple-300">{realStats.blocked_vpn || 0}</div>
                    <div className="text-[10px] text-purple-400 uppercase">VPN Skip</div>
                  </div>
                  <div className="bg-orange-900/30 border border-orange-700 rounded p-2 text-center">
                    <div className="text-lg font-bold text-orange-300">{realStats.blocked_geo || 0}</div>
                    <div className="text-[10px] text-orange-400 uppercase">Geo Skip</div>
                  </div>
                  <div className="bg-red-900/30 border border-red-700 rounded p-2 text-center">
                    <div className="text-lg font-bold text-red-300">
                      {(realStats.probe_failed || 0) + (realStats.fire_failed || 0)}
                    </div>
                    <div className="text-[10px] text-red-400 uppercase">Failed</div>
                  </div>
                </div>
              )}

              {/* Live Log */}
              {realLog.length > 0 && (
                <Card className="bg-zinc-950 border-zinc-800">
                  <CardHeader className="pb-2 flex-row items-center justify-between">
                    <CardTitle className="text-white text-sm">Live Log ({realLog.length})</CardTitle>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={downloadRealLog}
                      className="border-zinc-700 text-zinc-300 h-7"
                    >
                      <FileText className="w-3 h-3 mr-1" /> Download CSV
                    </Button>
                  </CardHeader>
                  <CardContent>
                    <div className="max-h-72 overflow-auto font-mono text-xs space-y-1">
                      {realLog.slice().reverse().map((r, i) => {
                        const color = {
                          success: "text-green-400",
                          blocked_duplicate: "text-yellow-400",
                          blocked_vpn: "text-purple-400",
                          blocked_geo: "text-orange-400",
                          probe_failed: "text-red-400",
                          fire_failed: "text-red-400",
                        }[r.status] || "text-zinc-300";
                        return (
                          <div key={i} className={`${color} truncate`}>
                            <span className="text-zinc-500">#{r.index ?? "?"}</span>{" "}
                            [{r.status}]{" "}
                            <span className="text-zinc-200">{r.exit_ip || "-"}</span>{" "}
                            {r.country ? <span className="text-zinc-400">({r.country})</span> : null}{" "}
                            {r.reason ? <span className="text-zinc-500">— {r.reason}</span> : null}{" "}
                            {r.http_status ? <span className="text-zinc-500">HTTP {r.http_status}</span> : null}
                            {r.redirect_to ? (
                              <span className="text-blue-400 block pl-6">
                                → {r.redirect_to}
                                {r.final_status ? ` (offer HTTP ${r.final_status})` : ""}
                              </span>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* User Agent Reference */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-white text-lg">Instagram User Agent Reference</CardTitle>
          <CardDescription>Click to copy any user agent</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2">
            {Object.entries(SAMPLE_USER_AGENTS).map(([name, ua]) => (
              <div 
                key={name}
                className="flex items-center justify-between p-2 bg-zinc-800 rounded hover:bg-zinc-700 cursor-pointer"
                onClick={() => copyUserAgent(ua)}
              >
                <div className="flex items-center gap-2">
                  <Smartphone className="w-4 h-4 text-zinc-500" />
                  <span className="text-white font-medium">{name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-zinc-500 text-xs truncate max-w-md">{ua.substring(0, 50)}...</span>
                  <Copy className="w-4 h-4 text-zinc-500" />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
