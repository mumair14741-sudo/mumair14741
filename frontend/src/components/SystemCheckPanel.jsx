import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { CheckCircle2, XCircle, RefreshCw, Activity } from "lucide-react";
import { toast } from "sonner";

/**
 * SystemCheckPanel — live dependency / service health check for admins.
 * Calls GET /api/admin/system-check and renders green/red badges per item.
 */
export default function SystemCheckPanel({ api }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem("adminToken");
      const r = await fetch(`${api}/admin/system-check`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
      setData(await r.json());
    } catch (e) {
      toast.error("System check failed: " + (e.message || e));
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => { load(); }, [load]);

  if (!data && loading) {
    return (
      <Card className="bg-[#09090B] border-[#27272A]">
        <CardContent className="p-10 text-center text-zinc-400">
          <RefreshCw size={22} className="animate-spin inline mr-2" />
          Running system check…
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card className="bg-[#09090B] border-[#27272A]">
        <CardContent className="p-10 text-center text-zinc-400">
          <Button onClick={load} data-testid="system-check-retry">Retry</Button>
        </CardContent>
      </Card>
    );
  }

  const groups = {};
  for (const c of data.checks) {
    if (!groups[c.group]) groups[c.group] = [];
    groups[c.group].push(c);
  }

  const statusColor =
    data.overall === "healthy" ? "bg-emerald-600" :
    data.overall === "degraded" ? "bg-amber-600" : "bg-rose-600";

  return (
    <div className="space-y-4" data-testid="system-check-panel">
      {/* Summary header */}
      <Card className="bg-[#09090B] border-[#27272A]">
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <div>
            <CardTitle className="text-white flex items-center gap-2">
              <Activity size={18} className="text-cyan-400" />
              Overall status
              <Badge className={`${statusColor} text-white capitalize ml-2`} data-testid="system-overall-badge">
                {data.overall}
              </Badge>
            </CardTitle>
            <p className="text-zinc-400 text-xs mt-1">
              {data.passed} / {data.total} checks passing — last run {new Date(data.checked_at).toLocaleString()}
            </p>
          </div>
          <Button
            onClick={load}
            disabled={loading}
            className="bg-cyan-600 hover:bg-cyan-500 text-white"
            data-testid="system-check-refresh"
          >
            <RefreshCw size={14} className={`mr-2 ${loading ? "animate-spin" : ""}`} />
            Re-run
          </Button>
        </CardHeader>
      </Card>

      {/* Groups */}
      {Object.entries(groups).map(([grp, checks]) => (
        <Card key={grp} className="bg-[#09090B] border-[#27272A]">
          <CardHeader className="pb-2">
            <CardTitle className="text-white text-base">{grp}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {checks.map((c, i) => (
              <div
                key={i}
                className="flex items-center justify-between bg-[#18181B] border border-[#27272A] rounded-md px-3 py-2"
                data-testid={`system-check-row-${c.name.replace(/\s+/g, "-").toLowerCase()}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  {c.ok ? (
                    <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />
                  ) : (
                    <XCircle size={16} className="text-rose-500 shrink-0" />
                  )}
                  <span className="text-zinc-200 text-sm font-medium truncate">{c.name}</span>
                </div>
                <span className="text-zinc-400 text-xs font-mono truncate max-w-[60%] text-right">
                  {c.detail}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}

      <p className="text-xs text-zinc-500 text-center pt-2">
        Tip: re-run after any deploy / restart to confirm all dependencies loaded correctly.
      </p>
    </div>
  );
}
