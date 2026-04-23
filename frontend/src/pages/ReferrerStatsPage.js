import { useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { toast } from "sonner";
import { 
  RefreshCw, Globe, Facebook, Instagram, Twitter, Youtube, 
  MessageCircle, Search, Mail, Link2, ExternalLink, TrendingUp,
  ChevronDown, ChevronUp
} from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Source icons mapping
const SOURCE_ICONS = {
  facebook: { icon: Facebook, color: "#1877F2", bg: "#1877F2/10" },
  instagram: { icon: Instagram, color: "#E4405F", bg: "#E4405F/10" },
  twitter: { icon: Twitter, color: "#1DA1F2", bg: "#1DA1F2/10" },
  pinterest: { icon: Globe, color: "#E60023", bg: "#E60023/10" },
  youtube: { icon: Youtube, color: "#FF0000", bg: "#FF0000/10" },
  whatsapp: { icon: MessageCircle, color: "#25D366", bg: "#25D366/10" },
  telegram: { icon: MessageCircle, color: "#0088cc", bg: "#0088cc/10" },
  google: { icon: Search, color: "#4285F4", bg: "#4285F4/10" },
  bing: { icon: Search, color: "#008373", bg: "#008373/10" },
  gmail: { icon: Mail, color: "#EA4335", bg: "#EA4335/10" },
  outlook: { icon: Mail, color: "#0078D4", bg: "#0078D4/10" },
  linkedin: { icon: Globe, color: "#0A66C2", bg: "#0A66C2/10" },
  reddit: { icon: Globe, color: "#FF4500", bg: "#FF4500/10" },
  tiktok: { icon: Globe, color: "#000000", bg: "#000000/10" },
  discord: { icon: Globe, color: "#5865F2", bg: "#5865F2/10" },
  direct: { icon: Link2, color: "#22C55E", bg: "#22C55E/10" },
  other: { icon: ExternalLink, color: "#71717A", bg: "#71717A/10" },
};

export default function ReferrerStatsPage() {
  const [referrerStats, setReferrerStats] = useState([]);
  const [links, setLinks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedLink, setSelectedLink] = useState("all");
  const [dateFilter, setDateFilter] = useState("all");
  const [totalClicks, setTotalClicks] = useState(0);
  const [expandedSource, setExpandedSource] = useState(null);
  const [breakdown, setBreakdown] = useState(null);
  const [loadingBreakdown, setLoadingBreakdown] = useState(false);

  const getToken = () => localStorage.getItem("token");

  const fetchLinks = async () => {
    try {
      const response = await axios.get(`${API}/links`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setLinks(response.data);
    } catch (error) {
      console.error("Failed to fetch links:", error);
    }
  };

  const fetchReferrerStats = async () => {
    try {
      setRefreshing(true);
      const params = new URLSearchParams();
      if (selectedLink !== "all") params.append("link_id", selectedLink);
      if (dateFilter !== "all") params.append("filter_type", dateFilter);

      const response = await axios.get(`${API}/clicks/referrer-stats?${params}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      
      setReferrerStats(response.data.referrers || []);
      setTotalClicks(response.data.total || 0);
    } catch (error) {
      toast.error("Failed to fetch referrer stats");
      console.error("Failed to fetch referrer stats:", error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const fetchBreakdown = async (source) => {
    if (expandedSource === source) {
      setExpandedSource(null);
      setBreakdown(null);
      return;
    }

    setLoadingBreakdown(true);
    setExpandedSource(source);

    try {
      const params = new URLSearchParams();
      params.append("source", source);
      if (selectedLink !== "all") params.append("link_id", selectedLink);

      const response = await axios.get(`${API}/clicks/referrer-breakdown?${params}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      
      setBreakdown(response.data.clicks || []);
    } catch (error) {
      toast.error("Failed to fetch breakdown");
      console.error("Failed to fetch breakdown:", error);
    } finally {
      setLoadingBreakdown(false);
    }
  };

  useEffect(() => {
    fetchLinks();
    fetchReferrerStats();
  }, []);

  useEffect(() => {
    fetchReferrerStats();
    setExpandedSource(null);
    setBreakdown(null);
  }, [selectedLink, dateFilter]);

  const getSourceIcon = (source) => {
    const config = SOURCE_ICONS[source] || SOURCE_ICONS.other;
    const Icon = config.icon;
    return <Icon className="w-5 h-5" style={{ color: config.color }} />;
  };

  const getSourceBgColor = (source) => {
    const colors = {
      facebook: "bg-[#1877F2]/10 border-[#1877F2]/30",
      instagram: "bg-gradient-to-r from-[#833AB4]/10 via-[#FD1D1D]/10 to-[#F77737]/10 border-[#E4405F]/30",
      twitter: "bg-[#1DA1F2]/10 border-[#1DA1F2]/30",
      pinterest: "bg-[#E60023]/10 border-[#E60023]/30",
      youtube: "bg-[#FF0000]/10 border-[#FF0000]/30",
      whatsapp: "bg-[#25D366]/10 border-[#25D366]/30",
      telegram: "bg-[#0088cc]/10 border-[#0088cc]/30",
      google: "bg-[#4285F4]/10 border-[#4285F4]/30",
      bing: "bg-[#008373]/10 border-[#008373]/30",
      gmail: "bg-[#EA4335]/10 border-[#EA4335]/30",
      outlook: "bg-[#0078D4]/10 border-[#0078D4]/30",
      linkedin: "bg-[#0A66C2]/10 border-[#0A66C2]/30",
      reddit: "bg-[#FF4500]/10 border-[#FF4500]/30",
      tiktok: "bg-[#000000]/10 border-[#000000]/30",
      discord: "bg-[#5865F2]/10 border-[#5865F2]/30",
      direct: "bg-[#22C55E]/10 border-[#22C55E]/30",
      other: "bg-[#71717A]/10 border-[#71717A]/30",
    };
    return colors[source] || colors.other;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <TrendingUp className="w-6 h-6 text-[#3B82F6]" />
            Traffic Sources
          </h1>
          <p className="text-[#A1A1AA] text-sm mt-1">
            See where your traffic is coming from
          </p>
        </div>
        
        <Button 
          onClick={fetchReferrerStats} 
          disabled={refreshing}
          variant="outline"
          className="border-[#27272A]"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Filters */}
      <Card className="bg-[#09090B] border-[#27272A]">
        <CardContent className="pt-4">
          <div className="flex flex-wrap gap-4">
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs text-[#71717A] mb-1 block">Link</label>
              <Select value={selectedLink} onValueChange={setSelectedLink}>
                <SelectTrigger className="bg-[#18181B] border-[#27272A]">
                  <SelectValue placeholder="All Links" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Links</SelectItem>
                  {links.map(link => (
                    <SelectItem key={link.id} value={link.id}>
                      {link.name || link.short_code}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs text-[#71717A] mb-1 block">Time Period</label>
              <Select value={dateFilter} onValueChange={setDateFilter}>
                <SelectTrigger className="bg-[#18181B] border-[#27272A]">
                  <SelectValue placeholder="All Time" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Time</SelectItem>
                  <SelectItem value="today">Today</SelectItem>
                  <SelectItem value="yesterday">Yesterday</SelectItem>
                  <SelectItem value="week">This Week</SelectItem>
                  <SelectItem value="month">This Month</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Stats Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="bg-[#09090B] border-[#27272A]">
          <CardContent className="pt-4">
            <p className="text-xs text-[#71717A]">Total Clicks</p>
            <p className="text-2xl font-bold text-white">{totalClicks.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card className="bg-[#09090B] border-[#27272A]">
          <CardContent className="pt-4">
            <p className="text-xs text-[#71717A]">Traffic Sources</p>
            <p className="text-2xl font-bold text-white">{referrerStats.length}</p>
          </CardContent>
        </Card>
        <Card className="bg-[#09090B] border-[#27272A]">
          <CardContent className="pt-4">
            <p className="text-xs text-[#71717A]">Top Source</p>
            <p className="text-lg font-bold text-white">
              {referrerStats[0]?.source_name || "-"}
            </p>
          </CardContent>
        </Card>
        <Card className="bg-[#09090B] border-[#27272A]">
          <CardContent className="pt-4">
            <p className="text-xs text-[#71717A]">Direct Traffic</p>
            <p className="text-2xl font-bold text-white">
              {referrerStats.find(r => r.source === "direct")?.percentage || 0}%
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Referrer Cards */}
      {loading ? (
        <div className="flex justify-center py-12">
          <RefreshCw className="w-8 h-8 animate-spin text-[#3B82F6]" />
        </div>
      ) : referrerStats.length === 0 ? (
        <Card className="bg-[#09090B] border-[#27272A]">
          <CardContent className="py-12 text-center">
            <Globe className="w-12 h-12 text-[#52525B] mx-auto mb-4" />
            <h3 className="text-lg font-medium text-white mb-2">No Traffic Data Yet</h3>
            <p className="text-[#A1A1AA]">
              Traffic source data will appear here once you start getting clicks on your links.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {referrerStats.map((ref, index) => (
            <div key={ref.source}>
              <Card 
                className={`bg-[#09090B] border ${getSourceBgColor(ref.source)} cursor-pointer hover:bg-[#18181B] transition-colors`}
                onClick={() => fetchBreakdown(ref.source)}
              >
                <CardContent className="py-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${getSourceBgColor(ref.source)}`}>
                        {getSourceIcon(ref.source)}
                      </div>
                      <div>
                        <h3 className="font-semibold text-white">{ref.source_name}</h3>
                        <p className="text-sm text-[#A1A1AA]">
                          {ref.count.toLocaleString()} clicks
                          {ref.domains?.length > 0 && ref.domains[0] && (
                            <span className="text-[#52525B] ml-2">
                              • {ref.domains.slice(0, 2).filter(d => d).join(", ")}
                              {ref.domains.length > 2 && ` +${ref.domains.length - 2} more`}
                            </span>
                          )}
                        </p>
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <p className="text-2xl font-bold text-white">{ref.percentage}%</p>
                        <div className="w-32 h-2 bg-[#27272A] rounded-full overflow-hidden mt-1">
                          <div 
                            className="h-full bg-[#3B82F6] rounded-full transition-all"
                            style={{ width: `${ref.percentage}%` }}
                          />
                        </div>
                      </div>
                      {expandedSource === ref.source ? (
                        <ChevronUp className="w-5 h-5 text-[#A1A1AA]" />
                      ) : (
                        <ChevronDown className="w-5 h-5 text-[#A1A1AA]" />
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
              
              {/* Breakdown Table */}
              {expandedSource === ref.source && (
                <Card className="bg-[#18181B] border-[#27272A] mt-1 ml-6">
                  <CardContent className="py-4">
                    {loadingBreakdown ? (
                      <div className="flex justify-center py-4">
                        <RefreshCw className="w-6 h-6 animate-spin text-[#3B82F6]" />
                      </div>
                    ) : breakdown && breakdown.length > 0 ? (
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow className="border-[#27272A]">
                              <TableHead className="text-[#A1A1AA]">Time</TableHead>
                              <TableHead className="text-[#A1A1AA]">IP</TableHead>
                              <TableHead className="text-[#A1A1AA]">Country</TableHead>
                              <TableHead className="text-[#A1A1AA]">Device</TableHead>
                              <TableHead className="text-[#A1A1AA]">Link</TableHead>
                              <TableHead className="text-[#A1A1AA]">Referrer URL</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {breakdown.slice(0, 10).map((click, idx) => (
                              <TableRow key={idx} className="border-[#27272A]">
                                <TableCell className="text-[#E4E4E7] text-sm">
                                  {new Date(click.created_at).toLocaleString()}
                                </TableCell>
                                <TableCell className="text-[#E4E4E7] font-mono text-sm">
                                  {click.ip_address}
                                </TableCell>
                                <TableCell className="text-[#E4E4E7]">{click.country || "-"}</TableCell>
                                <TableCell className="text-[#E4E4E7] capitalize">{click.device_type || "-"}</TableCell>
                                <TableCell className="text-[#E4E4E7]">{click.link_name}</TableCell>
                                <TableCell className="text-[#A1A1AA] text-xs max-w-[200px] truncate">
                                  {click.referrer || "-"}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                        {breakdown.length > 10 && (
                          <p className="text-sm text-[#52525B] mt-2 text-center">
                            Showing 10 of {breakdown.length} clicks
                          </p>
                        )}
                      </div>
                    ) : (
                      <p className="text-[#A1A1AA] text-center py-4">No detailed data available</p>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
