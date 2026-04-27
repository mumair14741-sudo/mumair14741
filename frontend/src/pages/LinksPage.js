import { useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import { Plus, Copy, Pencil, Trash2, TrendingUp, Globe, Shield, Monitor, Smartphone, ExternalLink } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Host for user-facing tracking links. If REACT_APP_BACKEND_URL is empty
// (nginx-same-origin deployments like local Docker), fall back to the
// current window origin so copied links include the full URL.
const PUBLIC_HOST =
  (typeof window !== "undefined" && (BACKEND_URL || window.location.origin)) || "";

// Fallback copy function that works over HTTP (not just HTTPS)
const copyToClipboard = async (text) => {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.log("Clipboard API failed, trying fallback");
    }
  }
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.position = "fixed";
  textArea.style.left = "-999999px";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    document.execCommand('copy');
    textArea.remove();
    return true;
  } catch (err) {
    textArea.remove();
    return false;
  }
};

// Available OS options
const OS_OPTIONS = [
  { value: "iOS", label: "iOS", icon: "📱" },
  { value: "Android", label: "Android", icon: "🤖" },
  { value: "Windows", label: "Windows", icon: "🪟" },
  { value: "macOS", label: "macOS", icon: "🍎" },
  { value: "Linux", label: "Linux", icon: "🐧" },
  { value: "ChromeOS", label: "ChromeOS", icon: "💻" },
];

// Traffic source options
const TRAFFIC_SOURCE_OPTIONS = [
  { value: "", label: "Auto Detect (from referrer)", icon: "🔄" },
  { value: "facebook", label: "Facebook", icon: "📘" },
  { value: "instagram", label: "Instagram", icon: "📷" },
  { value: "twitter", label: "Twitter/X", icon: "🐦" },
  { value: "pinterest", label: "Pinterest", icon: "📌" },
  { value: "linkedin", label: "LinkedIn", icon: "💼" },
  { value: "youtube", label: "YouTube", icon: "🎬" },
  { value: "tiktok", label: "TikTok", icon: "🎵" },
  { value: "whatsapp", label: "WhatsApp", icon: "💬" },
  { value: "telegram", label: "Telegram", icon: "✈️" },
  { value: "discord", label: "Discord", icon: "🎮" },
  { value: "google", label: "Google Search", icon: "🔍" },
  { value: "bing", label: "Bing Search", icon: "🔎" },
  { value: "gmail", label: "Gmail", icon: "📧" },
  { value: "outlook", label: "Outlook/Hotmail", icon: "📨" },
  { value: "reddit", label: "Reddit", icon: "🔴" },
  { value: "direct", label: "Direct (QR Code/Offline)", icon: "🔗" },
  { value: "sms", label: "SMS", icon: "📱" },
  { value: "email", label: "Email Campaign", icon: "📬" },
  { value: "ads", label: "Paid Ads", icon: "💰" },
  { value: "other", label: "Other", icon: "🌐" },
];

// Referrer mode options
const REFERRER_MODE_OPTIONS = [
  { value: "normal", label: "Normal (RealFlow as referrer)", description: "Destination sees your tracking domain" },
  { value: "no_referrer", label: "No Referrer (Blank/Direct)", description: "Destination sees direct traffic" },
  { value: "with_params", label: "Add Source Parameters", description: "Add utm_source, fbclid, etc. to URL" },
];

// Platform simulation options (adds realistic click IDs)
const PLATFORM_SIMULATION_OPTIONS = [
  { value: "", label: "None - Don't simulate", description: "No fake click IDs added" },
  { value: "facebook", label: "Facebook (fbclid)", description: "Adds fbclid=IwAR... parameter" },
  { value: "instagram", label: "Instagram (igshid)", description: "Adds igshid parameter" },
  { value: "tiktok", label: "TikTok (ttclid)", description: "Adds ttclid parameter" },
  { value: "twitter", label: "Twitter/X (twclid)", description: "Adds twclid parameter" },
  { value: "google", label: "Google Ads (gclid)", description: "Adds gclid parameter" },
  { value: "pinterest", label: "Pinterest (epik)", description: "Adds epik parameter" },
  { value: "linkedin", label: "LinkedIn (li_fat_id)", description: "Adds li_fat_id parameter" },
  { value: "snapchat", label: "Snapchat (sccid)", description: "Adds sccid parameter" },
  { value: "whatsapp", label: "WhatsApp", description: "Adds utm_source=whatsapp" },
  { value: "telegram", label: "Telegram", description: "Adds utm_source=telegram" },
  { value: "youtube", label: "YouTube", description: "Adds utm_source=youtube" },
  { value: "email", label: "Email Campaign", description: "Adds utm_source=email" },
  { value: "sms", label: "SMS", description: "Adds utm_source=sms" },
];

// Popular countries list
const COUNTRY_OPTIONS = [
  "United States", "United Kingdom", "Canada", "Australia", "Germany", 
  "France", "Italy", "Spain", "Netherlands", "Belgium", "Switzerland",
  "India", "Pakistan", "Bangladesh", "Brazil", "Mexico", "Argentina",
  "Japan", "China", "South Korea", "Thailand", "Vietnam", "Philippines",
  "Indonesia", "Malaysia", "Singapore", "United Arab Emirates", "Saudi Arabia",
  "South Africa", "Nigeria", "Egypt", "Turkey", "Russia", "Poland"
];

export default function LinksPage() {
  const [links, setLinks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingLink, setEditingLink] = useState(null);
  const [formData, setFormData] = useState({ 
    offer_url: "", 
    status: "active",
    name: "",
    custom_short_code: "",
    allowed_countries: [],
    allowed_os: [],
    block_vpn: false,
    all_countries: true,
    all_os: true,
    duplicate_timer_enabled: false,
    duplicate_timer_seconds: 5,
    forced_source: "",
    forced_source_name: "",
    referrer_mode: "normal",
    simulate_platform: "",
    url_params: {}
  });

  useEffect(() => {
    fetchLinks();
  }, []);

  const fetchLinks = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await axios.get(`${API}/links`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setLinks(response.data);
    } catch (error) {
      toast.error("Failed to fetch links");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const token = localStorage.getItem("token");
      const submitData = {
        ...formData,
        allowed_countries: formData.all_countries ? [] : formData.allowed_countries,
        allowed_os: formData.all_os ? [] : formData.allowed_os,
      };
      // Remove UI-only fields
      delete submitData.all_countries;
      delete submitData.all_os;

      if (editingLink) {
        await axios.put(`${API}/links/${editingLink.id}`, submitData, {
          headers: { Authorization: `Bearer ${token}` },
        });
        toast.success("Link updated successfully");
      } else {
        await axios.post(`${API}/links`, submitData, {
          headers: { Authorization: `Bearer ${token}` },
        });
        toast.success("Link created successfully");
      }
      setDialogOpen(false);
      setEditingLink(null);
      resetForm();
      fetchLinks();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Operation failed");
    }
  };

  const resetForm = () => {
    setFormData({ 
      offer_url: "", 
      status: "active",
      name: "",
      custom_short_code: "",
      allowed_countries: [],
      allowed_os: [],
      block_vpn: false,
      all_countries: true,
      all_os: true,
      duplicate_timer_enabled: false,
      duplicate_timer_seconds: 5,
      forced_source: "",
      forced_source_name: "",
      referrer_mode: "normal",
      simulate_platform: "",
      url_params: {}
    });
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this link?")) return;
    
    try {
      const token = localStorage.getItem("token");
      await axios.delete(`${API}/links/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Link deleted successfully");
      fetchLinks();
    } catch (error) {
      toast.error("Failed to delete link");
    }
  };

  const copyTrackingLink = (shortCode) => {
    const trackingLink = `${PUBLIC_HOST}/api/t/${shortCode}`;
    copyToClipboard(trackingLink);
    toast.success("Tracking link copied to clipboard");
  };

  const openEditDialog = (link) => {
    setEditingLink(link);
    const hasCountryRestriction = link.allowed_countries && link.allowed_countries.length > 0;
    const hasOsRestriction = link.allowed_os && link.allowed_os.length > 0;
    
    setFormData({ 
      offer_url: link.offer_url, 
      status: link.status,
      name: link.name || "",
      custom_short_code: "", // Leave empty to keep existing, or enter new code
      allowed_countries: link.allowed_countries || [],
      allowed_os: link.allowed_os || [],
      block_vpn: link.block_vpn || false,
      all_countries: !hasCountryRestriction,
      all_os: !hasOsRestriction,
      duplicate_timer_enabled: link.duplicate_timer_enabled || false,
      duplicate_timer_seconds: link.duplicate_timer_seconds || 5,
      forced_source: link.forced_source || "",
      forced_source_name: link.forced_source_name || "",
      referrer_mode: link.referrer_mode || "normal",
      simulate_platform: link.simulate_platform || "",
      url_params: link.url_params || {}
    });
    setDialogOpen(true);
  };

  const openCreateDialog = () => {
    setEditingLink(null);
    resetForm();
    setDialogOpen(true);
  };

  const toggleCountry = (country) => {
    setFormData(prev => ({
      ...prev,
      allowed_countries: prev.allowed_countries.includes(country)
        ? prev.allowed_countries.filter(c => c !== country)
        : [...prev.allowed_countries, country]
    }));
  };

  const toggleOS = (os) => {
    setFormData(prev => ({
      ...prev,
      allowed_os: prev.allowed_os.includes(os)
        ? prev.allowed_os.filter(o => o !== os)
        : [...prev.allowed_os, os]
    }));
  };

  if (loading) {
    return <div className="text-muted-foreground">Loading links...</div>;
  }

  return (
    <div className="space-y-6" data-testid="links-page">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Links Management</h2>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={openCreateDialog} data-testid="create-link-button">
              <Plus size={16} className="mr-2" />
              Create Link
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[#09090B] border-[#27272A] max-w-2xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{editingLink ? "Edit Link" : "Create New Link"}</DialogTitle>
              <DialogDescription>
                {editingLink ? "Update your tracking link settings" : "Configure your new tracking link"}
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleSubmit} className="space-y-5">
              {/* Offer Name */}
              <div className="space-y-2">
                <Label htmlFor="name">Offer Name</Label>
                <Input
                  id="name"
                  data-testid="link-name-input"
                  type="text"
                  placeholder="e.g., Christmas Sale Campaign"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="bg-[#18181B] border-[#27272A]"
                />
              </div>

              {/* Custom Tracking Code */}
              <div className="space-y-2">
                <Label htmlFor="custom_short_code">Custom Tracking Code</Label>
                <Input
                  id="custom_short_code"
                  data-testid="custom-short-code-input"
                  type="text"
                  placeholder="e.g., summer-sale or black-friday-2024"
                  value={formData.custom_short_code}
                  onChange={(e) => setFormData({ ...formData, custom_short_code: e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, '') })}
                  className="bg-[#18181B] border-[#27272A]"
                />
                <p className="text-xs text-muted-foreground">
                  {editingLink 
                    ? `Current: ${editingLink.short_code} • Change to use a new code (3-50 chars)`
                    : "Leave empty for auto-generated code. Use letters, numbers, hyphens, underscores (3-50 chars)"
                  }
                </p>
              </div>

              {/* Offer URL */}
              <div className="space-y-2">
                <Label htmlFor="offer_url">Offer URL *</Label>
                <Input
                  id="offer_url"
                  data-testid="offer-url-input"
                  type="url"
                  placeholder="https://example.com/offer"
                  value={formData.offer_url}
                  onChange={(e) => setFormData({ ...formData, offer_url: e.target.value })}
                  required
                  className="bg-[#18181B] border-[#27272A]"
                />
              </div>

              {/* Status */}
              <div className="space-y-2">
                <Label htmlFor="status">Status</Label>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant={formData.status === "active" ? "default" : "outline"}
                    className={formData.status === "active" ? "bg-[#22C55E] hover:bg-[#16A34A]" : "border-[#27272A]"}
                    onClick={() => setFormData({ ...formData, status: "active" })}
                  >
                    Active
                  </Button>
                  <Button
                    type="button"
                    variant={formData.status === "paused" ? "default" : "outline"}
                    className={formData.status === "paused" ? "bg-[#F59E0B] hover:bg-[#D97706]" : "border-[#27272A]"}
                    onClick={() => setFormData({ ...formData, status: "paused" })}
                  >
                    Paused
                  </Button>
                </div>
              </div>

              {/* Country Restriction */}
              <div className="space-y-3 p-4 bg-[#18181B] rounded-lg border border-[#27272A]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Globe size={18} className="text-[#3B82F6]" />
                    <Label className="text-base font-medium">Country Restriction</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">All Countries</span>
                    <button
                      type="button"
                      onClick={() => setFormData({ ...formData, all_countries: !formData.all_countries, allowed_countries: [] })}
                      className={`relative w-11 h-6 rounded-full transition-colors ${formData.all_countries ? 'bg-[#22C55E]' : 'bg-[#27272A]'}`}
                    >
                      <span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${formData.all_countries ? 'left-6' : 'left-1'}`} />
                    </button>
                  </div>
                </div>
                
                {!formData.all_countries && (
                  <div className="space-y-2 mt-3">
                    <p className="text-xs text-muted-foreground">Select allowed countries:</p>
                    <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto p-2 bg-[#09090B] rounded">
                      {COUNTRY_OPTIONS.map((country) => (
                        <button
                          key={country}
                          type="button"
                          onClick={() => toggleCountry(country)}
                          className={`px-2 py-1 text-xs rounded transition-colors ${
                            formData.allowed_countries.includes(country)
                              ? 'bg-[#3B82F6] text-white'
                              : 'bg-[#27272A] text-[#A1A1AA] hover:bg-[#3F3F46]'
                          }`}
                        >
                          {country}
                        </button>
                      ))}
                    </div>
                    {formData.allowed_countries.length > 0 && (
                      <p className="text-xs text-[#3B82F6]">
                        Selected: {formData.allowed_countries.join(", ")}
                      </p>
                    )}
                  </div>
                )}
              </div>

              {/* OS Restriction */}
              <div className="space-y-3 p-4 bg-[#18181B] rounded-lg border border-[#27272A]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Monitor size={18} className="text-[#8B5CF6]" />
                    <Label className="text-base font-medium">Device/OS Restriction</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">All Devices</span>
                    <button
                      type="button"
                      onClick={() => setFormData({ ...formData, all_os: !formData.all_os, allowed_os: [] })}
                      className={`relative w-11 h-6 rounded-full transition-colors ${formData.all_os ? 'bg-[#22C55E]' : 'bg-[#27272A]'}`}
                    >
                      <span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${formData.all_os ? 'left-6' : 'left-1'}`} />
                    </button>
                  </div>
                </div>
                
                {!formData.all_os && (
                  <div className="space-y-2 mt-3">
                    <p className="text-xs text-muted-foreground">Select allowed operating systems:</p>
                    <div className="grid grid-cols-3 gap-2">
                      {OS_OPTIONS.map((os) => (
                        <button
                          key={os.value}
                          type="button"
                          onClick={() => toggleOS(os.value)}
                          className={`flex items-center gap-2 px-3 py-2 rounded transition-colors ${
                            formData.allowed_os.includes(os.value)
                              ? 'bg-[#8B5CF6] text-white'
                              : 'bg-[#27272A] text-[#A1A1AA] hover:bg-[#3F3F46]'
                          }`}
                        >
                          <span>{os.icon}</span>
                          <span className="text-sm">{os.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* VPN/Proxy Block */}
              <div className="p-4 bg-[#18181B] rounded-lg border border-[#27272A]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Shield size={18} className="text-[#EF4444]" />
                    <div>
                      <Label className="text-base font-medium">Block VPN/Proxy</Label>
                      <p className="text-xs text-muted-foreground mt-1">Prevent access from VPN and proxy connections</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, block_vpn: !formData.block_vpn })}
                    className={`relative w-11 h-6 rounded-full transition-colors ${formData.block_vpn ? 'bg-[#EF4444]' : 'bg-[#27272A]'}`}
                  >
                    <span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${formData.block_vpn ? 'left-6' : 'left-1'}`} />
                  </button>
                </div>
              </div>

              {/* Duplicate Timer */}
              <div className="p-4 bg-[#18181B] rounded-lg border border-[#27272A]">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[#F59E0B]"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                    <div>
                      <Label className="text-base font-medium">Duplicate IP Timer</Label>
                      <p className="text-xs text-muted-foreground mt-1">Auto-close duplicate IP page after specified seconds</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, duplicate_timer_enabled: !formData.duplicate_timer_enabled })}
                    className={`relative w-11 h-6 rounded-full transition-colors ${formData.duplicate_timer_enabled ? 'bg-[#F59E0B]' : 'bg-[#27272A]'}`}
                  >
                    <span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${formData.duplicate_timer_enabled ? 'left-6' : 'left-1'}`} />
                  </button>
                </div>
                {formData.duplicate_timer_enabled && (
                  <div className="flex items-center gap-3 mt-3 pl-7">
                    <Label className="text-sm text-muted-foreground">Wait time:</Label>
                    <Input
                      type="number"
                      min="1"
                      max="3600"
                      value={formData.duplicate_timer_seconds}
                      onChange={(e) => setFormData({ ...formData, duplicate_timer_seconds: parseInt(e.target.value) || 5 })}
                      className="w-24 bg-[#09090B] border-[#27272A]"
                    />
                    <span className="text-sm text-muted-foreground">seconds</span>
                  </div>
                )}
              </div>

              {/* Traffic Source */}
              <div className="p-4 bg-[#18181B] rounded-lg border border-[#27272A]">
                <div className="flex items-center gap-2 mb-3">
                  <TrendingUp size={18} className="text-[#3B82F6]" />
                  <div>
                    <Label className="text-base font-medium">Traffic Source</Label>
                    <p className="text-xs text-muted-foreground mt-1">Force all clicks from this link to show as specific source</p>
                  </div>
                </div>
                <select
                  value={formData.forced_source}
                  onChange={(e) => {
                    const selectedOption = TRAFFIC_SOURCE_OPTIONS.find(opt => opt.value === e.target.value);
                    setFormData({ 
                      ...formData, 
                      forced_source: e.target.value,
                      forced_source_name: selectedOption?.label || ""
                    });
                  }}
                  className="w-full p-2 rounded-md bg-[#09090B] border border-[#27272A] text-white"
                >
                  {TRAFFIC_SOURCE_OPTIONS.map(source => (
                    <option key={source.value} value={source.value}>
                      {source.icon} {source.label}
                    </option>
                  ))}
                </select>
                {formData.forced_source && (
                  <p className="text-xs text-[#22C55E] mt-2">
                    All clicks will be recorded as "{TRAFFIC_SOURCE_OPTIONS.find(s => s.value === formData.forced_source)?.label}"
                  </p>
                )}
              </div>

              {/* Referrer Simulation - Make destination see specific referrer */}
              <div className="p-4 bg-[#18181B] rounded-lg border border-[#27272A]">
                <div className="flex items-center gap-2 mb-3">
                  <ExternalLink size={18} className="text-[#8B5CF6]" />
                  <div>
                    <Label className="text-base font-medium">Referrer Simulation</Label>
                    <p className="text-xs text-muted-foreground mt-1">Make destination website see traffic as from specific platform</p>
                  </div>
                </div>
                
                {/* Referrer Mode */}
                <div className="space-y-3">
                  <div>
                    <Label className="text-xs text-[#A1A1AA]">Referrer Mode</Label>
                    <select
                      value={formData.referrer_mode}
                      onChange={(e) => setFormData({ ...formData, referrer_mode: e.target.value })}
                      className="w-full p-2 rounded-md bg-[#09090B] border border-[#27272A] text-white mt-1"
                    >
                      {REFERRER_MODE_OPTIONS.map(mode => (
                        <option key={mode.value} value={mode.value}>
                          {mode.label}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs text-[#52525B] mt-1">
                      {REFERRER_MODE_OPTIONS.find(m => m.value === formData.referrer_mode)?.description}
                    </p>
                  </div>
                  
                  {/* Platform Simulation */}
                  <div>
                    <Label className="text-xs text-[#A1A1AA]">Simulate Platform (Add Click IDs to URL)</Label>
                    <select
                      value={formData.simulate_platform}
                      onChange={(e) => setFormData({ ...formData, simulate_platform: e.target.value })}
                      className="w-full p-2 rounded-md bg-[#09090B] border border-[#27272A] text-white mt-1"
                    >
                      {PLATFORM_SIMULATION_OPTIONS.map(platform => (
                        <option key={platform.value} value={platform.value}>
                          {platform.label}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs text-[#52525B] mt-1">
                      {PLATFORM_SIMULATION_OPTIONS.find(p => p.value === formData.simulate_platform)?.description}
                    </p>
                  </div>
                  
                  {formData.simulate_platform && (
                    <div className="p-3 bg-[#09090B] rounded border border-[#27272A]">
                      <p className="text-xs text-[#22C55E]">
                        <strong>Example URL:</strong><br/>
                        {formData.simulate_platform === "facebook" && "offer.com?fbclid=IwAR3xyz...&utm_source=facebook"}
                        {formData.simulate_platform === "tiktok" && "offer.com?ttclid=abc123...&utm_source=tiktok"}
                        {formData.simulate_platform === "instagram" && "offer.com?igshid=xyz...&utm_source=instagram"}
                        {formData.simulate_platform === "google" && "offer.com?gclid=Cj0KC...&utm_source=google"}
                        {formData.simulate_platform === "twitter" && "offer.com?twclid=abc...&utm_source=twitter"}
                        {formData.simulate_platform === "whatsapp" && "offer.com?utm_source=whatsapp&utm_medium=social"}
                        {formData.simulate_platform === "youtube" && "offer.com?utm_source=youtube&utm_medium=video"}
                        {!["facebook", "tiktok", "instagram", "google", "twitter", "whatsapp", "youtube"].includes(formData.simulate_platform) && 
                          `offer.com?utm_source=${formData.simulate_platform}`}
                      </p>
                    </div>
                  )}
                </div>
              </div>

              <Button type="submit" data-testid="submit-link-button" className="w-full">
                {editingLink ? "Update Link" : "Create Link"}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card className="bg-[#09090B] border-[#27272A]">
        <CardHeader>
          <CardTitle>All Links</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-[#27272A] hover:bg-transparent">
                  <TableHead>Name / Short Code</TableHead>
                  <TableHead>Offer URL</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Restrictions</TableHead>
                  <TableHead className="text-right">Clicks</TableHead>
                  <TableHead className="text-right">Conversions</TableHead>
                  <TableHead className="text-right">Revenue</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {links.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                      No links created yet. Click "Create Link" to get started.
                    </TableCell>
                  </TableRow>
                ) : (
                  links.map((link) => (
                    <TableRow key={link.id} className="border-[#27272A]" data-testid={`link-row-${link.id}`}>
                      <TableCell className="font-mono">
                        <div>
                          {link.name && <div className="font-semibold text-white mb-1">{link.name}</div>}
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <span>{link.short_code}</span>
                            <button
                              onClick={() => copyTrackingLink(link.short_code)}
                              className="text-muted-foreground hover:text-white"
                              data-testid={`copy-link-${link.id}`}
                            >
                              <Copy size={14} />
                            </button>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="max-w-xs truncate" title={link.offer_url}>
                        {link.offer_url}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={link.status === "active" ? "default" : "secondary"}
                          className={link.status === "active" ? "bg-[#22C55E]" : "bg-[#F59E0B]"}
                        >
                          {link.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          {link.forced_source && (
                            <Badge variant="outline" className="text-xs border-[#22C55E] text-[#22C55E]">
                              <TrendingUp size={10} className="mr-1" /> {link.forced_source_name || link.forced_source}
                            </Badge>
                          )}
                          {link.simulate_platform && (
                            <Badge variant="outline" className="text-xs border-[#8B5CF6] text-[#8B5CF6]">
                              <ExternalLink size={10} className="mr-1" /> Simulates {link.simulate_platform}
                            </Badge>
                          )}
                          {link.referrer_mode === "no_referrer" && (
                            <Badge variant="outline" className="text-xs border-[#F59E0B] text-[#F59E0B]">
                              No Referrer
                            </Badge>
                          )}
                          {link.block_vpn && (
                            <Badge variant="outline" className="text-xs border-[#EF4444] text-[#EF4444]">
                              <Shield size={10} className="mr-1" /> No VPN
                            </Badge>
                          )}
                          {link.allowed_countries && link.allowed_countries.length > 0 && (
                            <Badge variant="outline" className="text-xs border-[#3B82F6] text-[#3B82F6]">
                              <Globe size={10} className="mr-1" /> {link.allowed_countries.length} countries
                            </Badge>
                          )}
                          {link.allowed_os && link.allowed_os.length > 0 && (
                            <Badge variant="outline" className="text-xs border-[#8B5CF6] text-[#8B5CF6]">
                              <Smartphone size={10} className="mr-1" /> {link.allowed_os.join(", ")}
                            </Badge>
                          )}
                          {!link.block_vpn && !link.forced_source && !link.simulate_platform && link.referrer_mode !== "no_referrer" && (!link.allowed_countries || link.allowed_countries.length === 0) && (!link.allowed_os || link.allowed_os.length === 0) && (
                            <span className="text-xs text-muted-foreground">No restrictions</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono">{link.clicks}</TableCell>
                      <TableCell className="text-right font-mono">{link.conversions}</TableCell>
                      <TableCell className="text-right font-mono">${link.revenue.toFixed(2)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => openEditDialog(link)}
                            data-testid={`edit-link-${link.id}`}
                          >
                            <Pencil size={16} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDelete(link.id)}
                            data-testid={`delete-link-${link.id}`}
                            className="text-red-400 hover:text-red-300"
                          >
                            <Trash2 size={16} />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {links.length > 0 && (
        <Card className="bg-[#09090B] border-[#27272A]">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp size={20} />
              Tracking URL Format
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <p className="text-sm text-muted-foreground mb-2">Basic tracking link:</p>
              <code className="block bg-[#18181B] p-3 rounded-md text-sm font-mono">
                {PUBLIC_HOST}/api/t/&#123;shortcode&#125;
              </code>
            </div>
            <div>
              <p className="text-sm text-muted-foreground mb-2">With tracking parameters:</p>
              <code className="block bg-[#18181B] p-3 rounded-md text-sm font-mono">
                {PUBLIC_HOST}/api/t/&#123;shortcode&#125;?sub1=&#123;clickid&#125;&amp;sub2=&#123;source&#125;&amp;sub3=&#123;campaign&#125;
              </code>
            </div>
            <div>
              <p className="text-sm text-muted-foreground mb-2">Postback URL (for conversions):</p>
              <code className="block bg-[#18181B] p-3 rounded-md text-sm font-mono">
                {PUBLIC_HOST}/api/postback?clickid=&#123;clickid&#125;&amp;payout=&#123;amount&#125;&amp;status=approved&amp;token=YOUR_TOKEN
              </code>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
