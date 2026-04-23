import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Switch } from "../components/ui/switch";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import SystemCheckPanel from "../components/SystemCheckPanel";
import { toast } from "sonner";
import { format } from "date-fns";
import { 
  Shield, Users, Link2, MousePointer, DollarSign, 
  LogOut, Settings, Trash2, CheckCircle, XCircle, 
  Clock, Search, RefreshCw, Eye, EyeOff, UserPlus,
  Palette, Image, Type, RotateCcw, Save, Server, Key, Plus, TestTube, Globe,
  Activity
} from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedUser, setSelectedUser] = useState(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [selectedUsers, setSelectedUsers] = useState([]);
  const [userFeatures, setUserFeatures] = useState({
    links: false,
    clicks: false,
    conversions: false,
    proxies: false,
    import_data: false,
    max_links: 10,
    max_clicks: 10000
  });
  const [userStatus, setUserStatus] = useState("pending");
  const [subscriptionNote, setSubscriptionNote] = useState("");
  const [subscriptionType, setSubscriptionType] = useState("free");
  const [subscriptionExpires, setSubscriptionExpires] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [userPassword, setUserPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [activeTab, setActiveTab] = useState("users");
  const [branding, setBranding] = useState({
    app_name: "TrackMaster",
    tagline: "Traffic Tracking & Link Management System",
    logo_url: "",
    favicon_url: "",
    primary_color: "#3B82F6",
    secondary_color: "#22C55E",
    accent_color: "#8B5CF6",
    danger_color: "#EF4444",
    warning_color: "#F59E0B",
    success_color: "#22C55E",
    background_color: "#09090B",
    card_color: "#18181B",
    border_color: "#27272A",
    text_color: "#FAFAFA",
    muted_color: "#A1A1AA",
    login_bg_url: "",
    admin_email: "",
    footer_text: "",
    sidebar_style: "dark",
    button_style: "rounded",
    font_family: "Inter"
  });
  const [brandingSaving, setBrandingSaving] = useState(false);
  // Sub-users state
  const [subUsers, setSubUsers] = useState([]);
  const [subUserSearchTerm, setSubUserSearchTerm] = useState("");
  const [selectedSubUser, setSelectedSubUser] = useState(null);
  const [editSubUserDialogOpen, setEditSubUserDialogOpen] = useState(false);
  const [subUserName, setSubUserName] = useState("");
  const [subUserPassword, setSubUserPassword] = useState("");
  const [subUserPermissions, setSubUserPermissions] = useState({});
  const [subUserIsActive, setSubUserIsActive] = useState(true);
  // API Settings state
  const [apiSettings, setApiSettings] = useState({});
  const [apiSettingsLoading, setApiSettingsLoading] = useState(false);
  const [showApiKey, setShowApiKey] = useState({});
  const [testingApi, setTestingApi] = useState(null);
  const [addApiDialogOpen, setAddApiDialogOpen] = useState(false);
  const [apiStatus, setApiStatus] = useState(null);
  const [newApiData, setNewApiData] = useState({
    key: "",
    name: "",
    enabled: true,
    api_key: "",
    endpoint: "",
    priority: 10,
    description: ""
  });
  const navigate = useNavigate();

  useEffect(() => {
    const adminToken = localStorage.getItem("adminToken");
    if (!adminToken) {
      navigate("/admin");
      return;
    }
    fetchData();
  }, [navigate]);

  const getAdminToken = () => localStorage.getItem("adminToken");

  const fetchData = async () => {
    try {
      const headers = { Authorization: `Bearer ${getAdminToken()}` };
      
      // Fetch each endpoint separately with error handling
      const fetchWithFallback = async (url, fallback) => {
        try {
          const res = await axios.get(url, { headers });
          return res.data;
        } catch (err) {
          console.error(`Failed to fetch ${url}:`, err);
          return fallback;
        }
      };
      
      // Fetch all data with individual error handling
      const [statsData, usersData, brandingData, subUsersData, userStatsData, apiSettingsData, apiStatusData] = await Promise.all([
        fetchWithFallback(`${API}/admin/stats`, { total_users: 0, active_users: 0, pending_users: 0, blocked_users: 0, total_links: 0, total_clicks: 0, total_conversions: 0, total_sub_users: 0, users_with_sub_users: 0 }),
        fetchWithFallback(`${API}/admin/users`, []),
        fetchWithFallback(`${API}/admin/branding`, {}),
        fetchWithFallback(`${API}/admin/sub-users`, []),
        fetchWithFallback(`${API}/admin/users/stats/all`, []),
        fetchWithFallback(`${API}/admin/api-settings`, {}),
        fetchWithFallback(`${API}/admin/api-settings/status`, { apis: [], total_enabled: 0, total_rate_limited: 0 })
      ]);
      
      setStats(statsData);
      
      // Merge user stats with user data
      const usersWithStats = usersData.map(user => {
        const userStats = userStatsData.find(s => s.id === user.id) || {};
        return {
          ...user,
          link_count: userStats.link_count || 0,
          click_count: userStats.click_count || 0,
          proxy_count: userStats.proxy_count || 0
        };
      });
      setUsers(usersWithStats);
      
      setBranding(brandingData);
      setSubUsers(subUsersData);
      setApiSettings(apiSettingsData);
      setApiStatus(apiStatusData);
    } catch (error) {
      if (error.response?.status === 401 || error.response?.status === 403) {
        localStorage.removeItem("adminToken");
        navigate("/admin");
      }
      toast.error("Failed to fetch data");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("adminToken");
    localStorage.removeItem("isAdmin");
    navigate("/admin");
  };

  const openEditDialog = (user) => {
    setSelectedUser(user);
    setUserFeatures(user.features || {
      links: false,
      clicks: false,
      conversions: false,
      proxies: false,
      import_data: false,
      max_links: 10,
      max_clicks: 10000
    });
    setUserStatus(user.status || "pending");
    setSubscriptionNote(user.subscription_note || "");
    setSubscriptionType(user.subscription_type || "free");
    setSubscriptionExpires(user.subscription_expires ? user.subscription_expires.split("T")[0] : "");
    setUserEmail(user.email);
    setUserPassword("");
    setEditDialogOpen(true);
  };

  const handleUpdateUser = async () => {
    if (!selectedUser) return;

    try {
      const updateData = {
        status: userStatus,
        features: userFeatures,
        subscription_note: subscriptionNote,
        subscription_type: subscriptionType
      };
      
      if (subscriptionExpires) {
        updateData.subscription_expires = subscriptionExpires + "T00:00:00Z";
      }
      
      if (userEmail !== selectedUser.email) {
        updateData.email = userEmail;
      }
      
      if (userPassword) {
        updateData.password = userPassword;
      }
      
      await axios.put(
        `${API}/admin/users/${selectedUser.id}`,
        updateData,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("User updated successfully");
      setEditDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to update user");
    }
  };

  const handleDeleteUser = async (userId, userName) => {
    if (!window.confirm(`Are you sure you want to delete user "${userName}"? This will delete ALL their data including links, clicks, and conversions.`)) {
      return;
    }

    try {
      await axios.delete(`${API}/admin/users/${userId}`, {
        headers: { Authorization: `Bearer ${getAdminToken()}` }
      });
      toast.success("User deleted successfully");
      fetchData();
    } catch (error) {
      toast.error("Failed to delete user");
    }
  };

  const quickActivate = async (userId) => {
    try {
      await axios.put(
        `${API}/admin/users/${userId}`,
        {
          status: "active",
          features: {
            links: true,
            clicks: true,
            conversions: true,
            proxies: true,
            import_data: true,
            max_links: 100,
            max_clicks: 100000
          }
        },
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("User activated with full access");
      fetchData();
    } catch (error) {
      toast.error("Failed to activate user");
    }
  };

  const quickBlock = async (userId) => {
    try {
      await axios.put(
        `${API}/admin/users/${userId}`,
        { status: "blocked" },
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("User blocked");
      fetchData();
    } catch (error) {
      toast.error("Failed to block user");
    }
  };

  const toggleSelectUser = (userId) => {
    setSelectedUsers((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    );
  };

  const toggleSelectAll = () => {
    if (selectedUsers.length === filteredUsers.length) {
      setSelectedUsers([]);
    } else {
      setSelectedUsers(filteredUsers.map((u) => u.id));
    }
  };

  const handleBulkDeleteUsers = async () => {
    if (selectedUsers.length === 0) {
      toast.error("No users selected");
      return;
    }

    if (!window.confirm(`Are you sure you want to delete ${selectedUsers.length} users? This will delete ALL their data including links, clicks, and conversions. This action cannot be undone.`)) {
      return;
    }

    try {
      // Delete users one by one
      let deleted = 0;
      for (const userId of selectedUsers) {
        await axios.delete(`${API}/admin/users/${userId}`, {
          headers: { Authorization: `Bearer ${getAdminToken()}` }
        });
        deleted++;
      }
      toast.success(`${deleted} users deleted successfully`);
      setSelectedUsers([]);
      fetchData();
    } catch (error) {
      toast.error("Failed to delete some users");
      fetchData();
    }
  };

  const filteredUsers = users.filter(user => 
    user.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
    user.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Sub-user functions
  const filteredSubUsers = subUsers.filter(subUser => 
    subUser.email.toLowerCase().includes(subUserSearchTerm.toLowerCase()) ||
    subUser.name.toLowerCase().includes(subUserSearchTerm.toLowerCase()) ||
    (subUser.parent_email && subUser.parent_email.toLowerCase().includes(subUserSearchTerm.toLowerCase()))
  );

  const openEditSubUserDialog = (subUser) => {
    setSelectedSubUser(subUser);
    setSubUserName(subUser.name);
    setSubUserPassword("");
    setSubUserPermissions(subUser.permissions || {});
    setSubUserIsActive(subUser.is_active !== false);
    setEditSubUserDialogOpen(true);
  };

  const handleUpdateSubUser = async () => {
    if (!selectedSubUser) return;

    try {
      const updateData = {
        name: subUserName,
        permissions: subUserPermissions,
        is_active: subUserIsActive
      };
      
      if (subUserPassword) {
        updateData.password = subUserPassword;
      }
      
      await axios.put(
        `${API}/admin/sub-users/${selectedSubUser.id}`,
        updateData,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("Sub-user updated successfully");
      setEditSubUserDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to update sub-user");
    }
  };

  const handleDeleteSubUser = async (subUserId, subUserName) => {
    if (!window.confirm(`Are you sure you want to delete sub-user "${subUserName}"?`)) {
      return;
    }

    try {
      await axios.delete(`${API}/admin/sub-users/${subUserId}`, {
        headers: { Authorization: `Bearer ${getAdminToken()}` }
      });
      toast.success("Sub-user deleted successfully");
      fetchData();
    } catch (error) {
      toast.error("Failed to delete sub-user");
    }
  };

  const handleBrandingChange = (field, value) => {
    setBranding(prev => ({ ...prev, [field]: value }));
  };

  const handleSaveBranding = async () => {
    setBrandingSaving(true);
    try {
      await axios.put(
        `${API}/admin/branding`,
        branding,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("Branding saved successfully! Refresh the page to see changes.");
    } catch (error) {
      toast.error("Failed to save branding");
    } finally {
      setBrandingSaving(false);
    }
  };

  const handleResetBranding = async () => {
    if (!window.confirm("Are you sure you want to reset branding to default settings?")) return;
    
    try {
      const response = await axios.post(
        `${API}/admin/branding/reset`,
        {},
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setBranding(response.data.branding);
      toast.success("Branding reset to default");
    } catch (error) {
      toast.error("Failed to reset branding");
    }
  };

  // API Settings Functions
  const handleApiSettingChange = async (apiKey, field, value) => {
    try {
      const response = await axios.put(
        `${API}/admin/api-settings/${apiKey}`,
        { [field]: value },
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiSettings(prev => ({
        ...prev,
        [apiKey]: { ...prev[apiKey], [field]: value }
      }));
      toast.success(`${apiSettings[apiKey]?.name || apiKey} updated`);
    } catch (error) {
      toast.error("Failed to update API setting");
    }
  };

  const handleTestApi = async (apiKey) => {
    setTestingApi(apiKey);
    try {
      const response = await axios.post(
        `${API}/admin/api-settings/test/${apiKey}`,
        {},
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      if (response.data.success) {
        toast.success(`${apiSettings[apiKey]?.name || apiKey}: API is working!`);
      } else {
        toast.error(`${apiSettings[apiKey]?.name || apiKey}: ${response.data.message}`);
      }
    } catch (error) {
      toast.error(`Failed to test API: ${error.response?.data?.detail || error.message}`);
    } finally {
      setTestingApi(null);
    }
  };

  const handleAddCustomApi = async () => {
    if (!newApiData.key || !newApiData.name || !newApiData.endpoint) {
      toast.error("Please fill in key, name, and endpoint");
      return;
    }
    
    try {
      const response = await axios.post(
        `${API}/admin/api-settings`,
        newApiData,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiSettings(prev => ({
        ...prev,
        [newApiData.key]: response.data.setting
      }));
      setAddApiDialogOpen(false);
      setNewApiData({
        key: "",
        name: "",
        enabled: true,
        api_key: "",
        endpoint: "",
        priority: 10,
        description: ""
      });
      toast.success("Custom API added successfully");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to add custom API");
    }
  };

  const handleDeleteCustomApi = async (apiKey) => {
    if (!window.confirm(`Are you sure you want to delete ${apiSettings[apiKey]?.name || apiKey}?`)) return;
    
    try {
      await axios.delete(
        `${API}/admin/api-settings/${apiKey}`,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiSettings(prev => {
        const newSettings = { ...prev };
        delete newSettings[apiKey];
        return newSettings;
      });
      toast.success("Custom API deleted");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to delete API");
    }
  };

  const handleResetApiSettings = async () => {
    if (!window.confirm("Are you sure you want to reset API settings to default?")) return;
    
    try {
      const response = await axios.post(
        `${API}/admin/api-settings/reset`,
        {},
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiSettings(response.data.settings);
      toast.success("API settings reset to default");
    } catch (error) {
      toast.error("Failed to reset API settings");
    }
  };

  const handleClearRateLimits = async () => {
    try {
      const response = await axios.post(
        `${API}/admin/api-settings/clear-rate-limits`,
        {},
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      // Refresh API status
      const statusResponse = await axios.get(
        `${API}/admin/api-settings/status`,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiStatus(statusResponse.data);
      toast.success(response.data.message);
    } catch (error) {
      toast.error("Failed to clear rate limits");
    }
  };

  const refreshApiStatus = async () => {
    try {
      const response = await axios.get(
        `${API}/admin/api-settings/status`,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiStatus(response.data);
    } catch (error) {
      console.error("Failed to refresh API status");
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case "active":
        return <Badge className="bg-[#22C55E]">Active</Badge>;
      case "blocked":
        return <Badge className="bg-[#EF4444]">Blocked</Badge>;
      default:
        return <Badge className="bg-[#F59E0B]">Pending</Badge>;
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#09090B] flex items-center justify-center">
        <div className="text-white">Loading admin panel...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#09090B]" data-testid="admin-dashboard">
      {/* Header */}
      <header className="border-b border-[#27272A] bg-[#09090B]/95 backdrop-blur sticky top-0 z-50">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Shield className="w-8 h-8 text-[#EF4444]" />
            <div>
              <h1 className="text-xl font-bold text-white">TrackMaster Admin</h1>
              <p className="text-xs text-[#A1A1AA]">System Administration</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <Button variant="outline" size="sm" onClick={fetchData} className="border-[#27272A]">
              <RefreshCw size={16} className="mr-2" />
              Refresh
            </Button>
            <Button variant="destructive" size="sm" onClick={handleLogout}>
              <LogOut size={16} className="mr-2" />
              Logout
            </Button>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8 space-y-8">
        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          <Card className="bg-[#09090B] border-[#27272A]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Total Users</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_users || 0}</p>
                </div>
                <Users className="w-10 h-10 text-[#3B82F6]" />
              </div>
              <div className="mt-2 flex gap-2 text-xs">
                <span className="text-[#22C55E]">{stats?.active_users || 0} active</span>
                <span className="text-[#F59E0B]">{stats?.pending_users || 0} pending</span>
                <span className="text-[#EF4444]">{stats?.blocked_users || 0} blocked</span>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[#09090B] border-[#27272A]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Sub-Users</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_sub_users || 0}</p>
                </div>
                <UserPlus className="w-10 h-10 text-[#8B5CF6]" />
              </div>
              <div className="mt-2 text-xs text-[#A1A1AA]">
                {stats?.users_with_sub_users || 0} users with sub-accounts
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[#09090B] border-[#27272A]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Total Links</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_links || 0}</p>
                </div>
                <Link2 className="w-10 h-10 text-[#8B5CF6]" />
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[#09090B] border-[#27272A]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Total Clicks</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_clicks?.toLocaleString() || 0}</p>
                </div>
                <MousePointer className="w-10 h-10 text-[#22C55E]" />
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[#09090B] border-[#27272A]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Conversions</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_conversions || 0}</p>
                </div>
                <DollarSign className="w-10 h-10 text-[#F59E0B]" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Tabs for Users, Sub-Users, Branding and API Settings */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="bg-[#18181B] border border-[#27272A] p-1">
            <TabsTrigger 
              value="users" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="users-tab"
            >
              <Users size={16} className="mr-2" />
              User Management
            </TabsTrigger>
            <TabsTrigger 
              value="subusers" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="subusers-tab"
            >
              <UserPlus size={16} className="mr-2" />
              Sub-Users ({stats?.total_sub_users || 0})
            </TabsTrigger>
            <TabsTrigger 
              value="branding" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="branding-tab"
            >
              <Palette size={16} className="mr-2" />
              Branding
            </TabsTrigger>
            <TabsTrigger 
              value="api-settings" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="api-settings-tab"
            >
              <Key size={16} className="mr-2" />
              API Settings
            </TabsTrigger>
            <TabsTrigger 
              value="system" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="system-tab"
            >
              <Activity size={16} className="mr-2" />
              System Check
            </TabsTrigger>
          </TabsList>

          <TabsContent value="users" className="mt-6">
        {/* User Management */}
        <Card className="bg-[#09090B] border-[#27272A]">
          <CardHeader>
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <CardTitle className="text-white">User Management</CardTitle>
                <CardDescription>Manage all registered users, their access and subscriptions</CardDescription>
              </div>
              <div className="flex items-center gap-4">
                {selectedUsers.length > 0 && (
                  <Button 
                    variant="destructive" 
                    size="sm" 
                    onClick={handleBulkDeleteUsers}
                    data-testid="bulk-delete-users-button"
                  >
                    <Trash2 size={16} className="mr-2" />
                    Delete Selected ({selectedUsers.length})
                  </Button>
                )}
                <div className="relative w-64">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A1A1AA]" />
                  <Input
                    placeholder="Search users..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="pl-10 bg-[#18181B] border-[#27272A]"
                    data-testid="search-users-input"
                  />
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-[#27272A] hover:bg-transparent">
                    <TableHead className="w-12">
                      <input
                        type="checkbox"
                        checked={filteredUsers.length > 0 && selectedUsers.length === filteredUsers.length}
                        onChange={toggleSelectAll}
                        className="w-4 h-4 cursor-pointer"
                        data-testid="select-all-users"
                      />
                    </TableHead>
                    <TableHead>User</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Stats</TableHead>
                    <TableHead>Features</TableHead>
                    <TableHead>Sub-Users</TableHead>
                    <TableHead>Registered</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredUsers.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center text-[#A1A1AA] py-8">
                        No users found
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredUsers.map((user) => (
                      <TableRow key={user.id} className="border-[#27272A]" data-testid={`user-row-${user.id}`}>
                        <TableCell>
                          <input
                            type="checkbox"
                            checked={selectedUsers.includes(user.id)}
                            onChange={() => toggleSelectUser(user.id)}
                            className="w-4 h-4 cursor-pointer"
                            data-testid={`select-user-${user.id}`}
                          />
                        </TableCell>
                        <TableCell>
                          <div>
                            <p className="font-medium text-white">{user.name}</p>
                            <p className="text-sm text-[#A1A1AA]">{user.email}</p>
                          </div>
                        </TableCell>
                        <TableCell>{getStatusBadge(user.status)}</TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-1 text-xs">
                            <div className="flex items-center gap-1">
                              <Link2 size={12} className="text-[#3B82F6]" />
                              <span className="text-[#A1A1AA]">{user.link_count || 0} links</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <MousePointer size={12} className="text-[#22C55E]" />
                              <span className="text-[#A1A1AA]">{(user.click_count || 0).toLocaleString()} clicks</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Server size={12} className="text-[#8B5CF6]" />
                              <span className="text-[#A1A1AA]">{user.proxy_count || 0} proxies</span>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1 flex-wrap">
                            {user.features?.links && <Badge variant="outline" className="text-xs border-[#3B82F6] text-[#3B82F6]">Links</Badge>}
                            {user.features?.clicks && <Badge variant="outline" className="text-xs border-[#22C55E] text-[#22C55E]">Clicks</Badge>}
                            {user.features?.proxies && <Badge variant="outline" className="text-xs border-[#8B5CF6] text-[#8B5CF6]">Proxies</Badge>}
                            {user.features?.import_data && <Badge variant="outline" className="text-xs border-[#F59E0B] text-[#F59E0B]">Import</Badge>}
                            {user.features?.settings !== false && <Badge variant="outline" className="text-xs border-[#EC4899] text-[#EC4899]">Settings</Badge>}
                            {!user.features?.links && !user.features?.clicks && !user.features?.proxies && user.features?.settings === false && (
                              <span className="text-xs text-[#71717A]">No access</span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          {user.sub_user_count > 0 ? (
                            <Badge className="bg-[#8B5CF6]">
                              <UserPlus size={12} className="mr-1" />
                              {user.sub_user_count}
                            </Badge>
                          ) : (
                            <span className="text-xs text-[#71717A]">None</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-[#A1A1AA]">
                          {format(new Date(user.created_at), "MMM dd, yyyy")}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            {user.status !== "active" && (
                              <Button 
                                size="sm" 
                                variant="outline"
                                className="border-[#22C55E] text-[#22C55E] hover:bg-[#22C55E]/10"
                                onClick={() => quickActivate(user.id)}
                                data-testid={`activate-user-${user.id}`}
                              >
                                <CheckCircle size={14} className="mr-1" />
                                Activate
                              </Button>
                            )}
                            {user.status !== "blocked" && (
                              <Button 
                                size="sm" 
                                variant="outline"
                                className="border-[#EF4444] text-[#EF4444] hover:bg-[#EF4444]/10"
                                onClick={() => quickBlock(user.id)}
                                data-testid={`block-user-${user.id}`}
                              >
                                <XCircle size={14} className="mr-1" />
                                Block
                              </Button>
                            )}
                            <Button 
                              size="sm" 
                              variant="outline"
                              className="border-[#27272A]"
                              onClick={() => openEditDialog(user)}
                              data-testid={`edit-user-${user.id}`}
                            >
                              <Settings size={14} className="mr-1" />
                              Edit
                            </Button>
                            <Button 
                              size="sm" 
                              variant="destructive"
                              onClick={() => handleDeleteUser(user.id, user.name)}
                              data-testid={`delete-user-${user.id}`}
                            >
                              <Trash2 size={14} />
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
          </TabsContent>

          {/* Sub-Users Tab */}
          <TabsContent value="subusers" className="mt-6">
            <Card className="bg-[#09090B] border-[#27272A]">
              <CardHeader>
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <div>
                    <CardTitle className="text-white flex items-center gap-2">
                      <UserPlus className="w-5 h-5 text-[#8B5CF6]" />
                      Sub-User Management
                    </CardTitle>
                    <CardDescription>View and manage all sub-users across all main users</CardDescription>
                  </div>
                  <div className="relative w-64">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A1A1AA]" />
                    <Input
                      placeholder="Search sub-users..."
                      value={subUserSearchTerm}
                      onChange={(e) => setSubUserSearchTerm(e.target.value)}
                      className="pl-10 bg-[#18181B] border-[#27272A]"
                      data-testid="search-subusers-input"
                    />
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-[#27272A] hover:bg-transparent">
                        <TableHead>Sub-User</TableHead>
                        <TableHead>Parent User</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Permissions</TableHead>
                        <TableHead>Last Active</TableHead>
                        <TableHead>Created</TableHead>
                        <TableHead>Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredSubUsers.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={7} className="text-center text-[#A1A1AA] py-8">
                            No sub-users found
                          </TableCell>
                        </TableRow>
                      ) : (
                        filteredSubUsers.map((subUser) => (
                          <TableRow key={subUser.id} className="border-[#27272A]" data-testid={`subuser-row-${subUser.id}`}>
                            <TableCell>
                              <div>
                                <p className="font-medium text-white">{subUser.name}</p>
                                <p className="text-sm text-[#A1A1AA]">{subUser.email}</p>
                              </div>
                            </TableCell>
                            <TableCell>
                              <div>
                                <p className="font-medium text-white">{subUser.parent_name}</p>
                                <p className="text-sm text-[#A1A1AA]">{subUser.parent_email}</p>
                              </div>
                            </TableCell>
                            <TableCell>
                              {subUser.is_active !== false ? (
                                <Badge className="bg-[#22C55E]">Active</Badge>
                              ) : (
                                <Badge className="bg-[#EF4444]">Inactive</Badge>
                              )}
                            </TableCell>
                            <TableCell>
                              <div className="flex gap-1 flex-wrap">
                                {subUser.permissions?.view_links && <Badge variant="outline" className="text-xs border-[#3B82F6] text-[#3B82F6]">Links</Badge>}
                                {subUser.permissions?.view_clicks && <Badge variant="outline" className="text-xs border-[#22C55E] text-[#22C55E]">Clicks</Badge>}
                                {subUser.permissions?.view_proxies && <Badge variant="outline" className="text-xs border-[#8B5CF6] text-[#8B5CF6]">Proxies</Badge>}
                                {subUser.permissions?.edit && <Badge variant="outline" className="text-xs border-[#F59E0B] text-[#F59E0B]">Edit</Badge>}
                              </div>
                            </TableCell>
                            <TableCell className="text-sm text-[#A1A1AA]">
                              {subUser.last_active ? format(new Date(subUser.last_active), "MMM dd, HH:mm") : "Never"}
                            </TableCell>
                            <TableCell className="text-sm text-[#A1A1AA]">
                              {format(new Date(subUser.created_at), "MMM dd, yyyy")}
                            </TableCell>
                            <TableCell>
                              <div className="flex gap-2">
                                <Button 
                                  size="sm" 
                                  variant="outline"
                                  className="border-[#27272A]"
                                  onClick={() => openEditSubUserDialog(subUser)}
                                  data-testid={`edit-subuser-${subUser.id}`}
                                >
                                  <Settings size={14} className="mr-1" />
                                  Edit
                                </Button>
                                <Button 
                                  size="sm" 
                                  variant="destructive"
                                  onClick={() => handleDeleteSubUser(subUser.id, subUser.name)}
                                  data-testid={`delete-subuser-${subUser.id}`}
                                >
                                  <Trash2 size={14} />
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
          </TabsContent>

          {/* Branding Tab */}
          <TabsContent value="branding" className="mt-6">
            <Card className="bg-[#09090B] border-[#27272A]">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-white flex items-center gap-2">
                      <Palette className="w-5 h-5 text-[#3B82F6]" />
                      Branding Settings
                    </CardTitle>
                    <CardDescription>Customize your application's appearance and branding</CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Button 
                      variant="outline" 
                      onClick={handleResetBranding}
                      className="border-[#27272A]"
                      data-testid="reset-branding-btn"
                    >
                      <RotateCcw size={16} className="mr-2" />
                      Reset to Default
                    </Button>
                    <Button 
                      onClick={handleSaveBranding}
                      disabled={brandingSaving}
                      className="bg-[#3B82F6]"
                      data-testid="save-branding-btn"
                    >
                      <Save size={16} className="mr-2" />
                      {brandingSaving ? "Saving..." : "Save Changes"}
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-8">
                {/* Basic Info */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white flex items-center gap-2">
                    <Type size={18} />
                    Basic Information
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="app_name">App Name</Label>
                      <Input
                        id="app_name"
                        value={branding.app_name}
                        onChange={(e) => handleBrandingChange("app_name", e.target.value)}
                        placeholder="TrackMaster"
                        className="bg-[#18181B] border-[#27272A]"
                        data-testid="branding-app-name"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="tagline">Tagline</Label>
                      <Input
                        id="tagline"
                        value={branding.tagline}
                        onChange={(e) => handleBrandingChange("tagline", e.target.value)}
                        placeholder="Traffic Tracking & Link Management"
                        className="bg-[#18181B] border-[#27272A]"
                        data-testid="branding-tagline"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="admin_email">Admin Contact Email</Label>
                      <Input
                        id="admin_email"
                        type="email"
                        value={branding.admin_email}
                        onChange={(e) => handleBrandingChange("admin_email", e.target.value)}
                        placeholder="admin@example.com"
                        className="bg-[#18181B] border-[#27272A]"
                        data-testid="branding-admin-email"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="footer_text">Footer Text</Label>
                      <Input
                        id="footer_text"
                        value={branding.footer_text}
                        onChange={(e) => handleBrandingChange("footer_text", e.target.value)}
                        placeholder="© 2026 TrackMaster. All rights reserved."
                        className="bg-[#18181B] border-[#27272A]"
                        data-testid="branding-footer-text"
                      />
                    </div>
                  </div>
                </div>

                {/* Images */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white flex items-center gap-2">
                    <Image size={18} />
                    Images & Media
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="logo_url">Logo URL</Label>
                      <Input
                        id="logo_url"
                        value={branding.logo_url}
                        onChange={(e) => handleBrandingChange("logo_url", e.target.value)}
                        placeholder="https://example.com/logo.png"
                        className="bg-[#18181B] border-[#27272A]"
                        data-testid="branding-logo-url"
                      />
                      {branding.logo_url && (
                        <div className="p-4 bg-[#18181B] rounded-lg border border-[#27272A] mt-2">
                          <img 
                            src={branding.logo_url} 
                            alt="Logo Preview" 
                            className="max-h-16 object-contain"
                            onError={(e) => e.target.style.display = 'none'}
                          />
                        </div>
                      )}
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="favicon_url">Favicon URL</Label>
                      <Input
                        id="favicon_url"
                        value={branding.favicon_url}
                        onChange={(e) => handleBrandingChange("favicon_url", e.target.value)}
                        placeholder="https://example.com/favicon.ico"
                        className="bg-[#18181B] border-[#27272A]"
                        data-testid="branding-favicon-url"
                      />
                      {branding.favicon_url && (
                        <div className="p-4 bg-[#18181B] rounded-lg border border-[#27272A] mt-2 flex items-center gap-2">
                          <img 
                            src={branding.favicon_url} 
                            alt="Favicon Preview" 
                            className="w-8 h-8 object-contain"
                            onError={(e) => e.target.style.display = 'none'}
                          />
                          <span className="text-xs text-[#A1A1AA]">32x32 recommended</span>
                        </div>
                      )}
                    </div>
                    <div className="space-y-2 md:col-span-2">
                      <Label htmlFor="login_bg_url">Login Background Image URL</Label>
                      <Input
                        id="login_bg_url"
                        value={branding.login_bg_url}
                        onChange={(e) => handleBrandingChange("login_bg_url", e.target.value)}
                        placeholder="https://example.com/background.jpg"
                        className="bg-[#18181B] border-[#27272A]"
                        data-testid="branding-login-bg"
                      />
                      {branding.login_bg_url && (
                        <div className="mt-2 rounded-lg overflow-hidden border border-[#27272A]">
                          <img 
                            src={branding.login_bg_url} 
                            alt="Background Preview" 
                            className="w-full h-32 object-cover"
                            onError={(e) => e.target.style.display = 'none'}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Colors */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white flex items-center gap-2">
                    <Palette size={18} />
                    Color Scheme
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="primary_color">Primary</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="primary_color"
                          value={branding.primary_color}
                          onChange={(e) => handleBrandingChange("primary_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[#27272A] bg-transparent"
                          data-testid="branding-primary-color"
                        />
                        <Input
                          value={branding.primary_color}
                          onChange={(e) => handleBrandingChange("primary_color", e.target.value)}
                          className="bg-[#18181B] border-[#27272A] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="secondary_color">Secondary</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="secondary_color"
                          value={branding.secondary_color}
                          onChange={(e) => handleBrandingChange("secondary_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[#27272A] bg-transparent"
                          data-testid="branding-secondary-color"
                        />
                        <Input
                          value={branding.secondary_color}
                          onChange={(e) => handleBrandingChange("secondary_color", e.target.value)}
                          className="bg-[#18181B] border-[#27272A] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="accent_color">Accent</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="accent_color"
                          value={branding.accent_color || "#8B5CF6"}
                          onChange={(e) => handleBrandingChange("accent_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[#27272A] bg-transparent"
                        />
                        <Input
                          value={branding.accent_color || "#8B5CF6"}
                          onChange={(e) => handleBrandingChange("accent_color", e.target.value)}
                          className="bg-[#18181B] border-[#27272A] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="danger_color">Danger</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="danger_color"
                          value={branding.danger_color || "#EF4444"}
                          onChange={(e) => handleBrandingChange("danger_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[#27272A] bg-transparent"
                        />
                        <Input
                          value={branding.danger_color || "#EF4444"}
                          onChange={(e) => handleBrandingChange("danger_color", e.target.value)}
                          className="bg-[#18181B] border-[#27272A] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="warning_color">Warning</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="warning_color"
                          value={branding.warning_color || "#F59E0B"}
                          onChange={(e) => handleBrandingChange("warning_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[#27272A] bg-transparent"
                        />
                        <Input
                          value={branding.warning_color || "#F59E0B"}
                          onChange={(e) => handleBrandingChange("warning_color", e.target.value)}
                          className="bg-[#18181B] border-[#27272A] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="success_color">Success</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="success_color"
                          value={branding.success_color || "#22C55E"}
                          onChange={(e) => handleBrandingChange("success_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[#27272A] bg-transparent"
                        />
                        <Input
                          value={branding.success_color || "#22C55E"}
                          onChange={(e) => handleBrandingChange("success_color", e.target.value)}
                          className="bg-[#18181B] border-[#27272A] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="background_color">Background</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="background_color"
                          value={branding.background_color || "#09090B"}
                          onChange={(e) => handleBrandingChange("background_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[#27272A] bg-transparent"
                        />
                        <Input
                          value={branding.background_color || "#09090B"}
                          onChange={(e) => handleBrandingChange("background_color", e.target.value)}
                          className="bg-[#18181B] border-[#27272A] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="card_color">Card</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="card_color"
                          value={branding.card_color || "#18181B"}
                          onChange={(e) => handleBrandingChange("card_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[#27272A] bg-transparent"
                        />
                        <Input
                          value={branding.card_color || "#18181B"}
                          onChange={(e) => handleBrandingChange("card_color", e.target.value)}
                          className="bg-[#18181B] border-[#27272A] flex-1 text-xs"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Interface Settings */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white flex items-center gap-2">
                    <Settings size={18} />
                    Interface Settings
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="sidebar_style">Sidebar Style</Label>
                      <Select
                        value={branding.sidebar_style || "dark"}
                        onValueChange={(value) => handleBrandingChange("sidebar_style", value)}
                      >
                        <SelectTrigger className="bg-[#18181B] border-[#27272A]">
                          <SelectValue placeholder="Select style" />
                        </SelectTrigger>
                        <SelectContent className="bg-[#18181B] border-[#27272A]">
                          <SelectItem value="dark">Dark</SelectItem>
                          <SelectItem value="light">Light</SelectItem>
                          <SelectItem value="gradient">Gradient</SelectItem>
                          <SelectItem value="transparent">Transparent</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="button_style">Button Style</Label>
                      <Select
                        value={branding.button_style || "rounded"}
                        onValueChange={(value) => handleBrandingChange("button_style", value)}
                      >
                        <SelectTrigger className="bg-[#18181B] border-[#27272A]">
                          <SelectValue placeholder="Select style" />
                        </SelectTrigger>
                        <SelectContent className="bg-[#18181B] border-[#27272A]">
                          <SelectItem value="rounded">Rounded</SelectItem>
                          <SelectItem value="square">Square</SelectItem>
                          <SelectItem value="pill">Pill</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="font_family">Font Family</Label>
                      <Select
                        value={branding.font_family || "Inter"}
                        onValueChange={(value) => handleBrandingChange("font_family", value)}
                      >
                        <SelectTrigger className="bg-[#18181B] border-[#27272A]">
                          <SelectValue placeholder="Select font" />
                        </SelectTrigger>
                        <SelectContent className="bg-[#18181B] border-[#27272A]">
                          <SelectItem value="Inter">Inter</SelectItem>
                          <SelectItem value="Roboto">Roboto</SelectItem>
                          <SelectItem value="Poppins">Poppins</SelectItem>
                          <SelectItem value="Open Sans">Open Sans</SelectItem>
                          <SelectItem value="Montserrat">Montserrat</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>

                {/* Preview */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white">Preview</h3>
                  <div className="p-6 rounded-lg border border-[#27272A] bg-[#18181B]">
                    <div className="flex items-center gap-3 mb-4">
                      {branding.logo_url ? (
                        <img src={branding.logo_url} alt="Logo" className="h-10 object-contain" />
                      ) : (
                        <div 
                          className="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold"
                          style={{ backgroundColor: branding.primary_color }}
                        >
                          {branding.app_name?.charAt(0) || "T"}
                        </div>
                      )}
                      <div>
                        <h4 className="font-bold text-white">{branding.app_name || "TrackMaster"}</h4>
                        <p className="text-xs text-[#A1A1AA]">{branding.tagline || "Traffic Tracking"}</p>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button 
                        size="sm" 
                        style={{ backgroundColor: branding.primary_color }}
                        className="text-white"
                      >
                        Primary Button
                      </Button>
                      <Button 
                        size="sm" 
                        variant="outline"
                        style={{ borderColor: branding.secondary_color, color: branding.secondary_color }}
                      >
                        Secondary Button
                      </Button>
                    </div>
                    <p className="text-xs text-[#52525B] mt-4">{branding.footer_text || "© 2026 TrackMaster. All rights reserved."}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* API Settings Tab */}
          <TabsContent value="api-settings" className="mt-6">
            <Card className="bg-[#09090B] border-[#27272A]">
              <CardHeader>
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <div>
                    <CardTitle className="text-white flex items-center gap-2">
                      <Key className="w-5 h-5" />
                      API Settings
                    </CardTitle>
                    <CardDescription>Manage VPN detection and geolocation API services</CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Button 
                      variant="outline" 
                      onClick={refreshApiStatus}
                      className="border-[#27272A]"
                    >
                      <RefreshCw size={16} className="mr-2" />
                      Refresh Status
                    </Button>
                    <Button 
                      variant="outline" 
                      onClick={handleResetApiSettings}
                      className="border-[#27272A]"
                    >
                      <RotateCcw size={16} className="mr-2" />
                      Reset to Default
                    </Button>
                    <Button 
                      onClick={() => setAddApiDialogOpen(true)}
                      className="bg-[#3B82F6] hover:bg-[#2563EB]"
                    >
                      <Plus size={16} className="mr-2" />
                      Add Custom API
                    </Button>
                  </div>
                </div>
                
                {/* API Status Summary */}
                {apiStatus && (
                  <div className="mt-4 p-4 bg-[#18181B] rounded-lg border border-[#27272A]">
                    <div className="flex items-center justify-between flex-wrap gap-4">
                      <div className="flex items-center gap-6 flex-wrap">
                        <div className="text-sm">
                          <span className="text-[#A1A1AA]">Enabled: </span>
                          <span className="text-[#22C55E] font-semibold">{apiStatus.total_enabled}</span>
                        </div>
                        <div className="text-sm">
                          <span className="text-[#A1A1AA]">Rate Limited: </span>
                          <span className={`font-semibold ${apiStatus.total_rate_limited > 0 ? 'text-[#F59E0B]' : 'text-[#22C55E]'}`}>
                            {apiStatus.total_rate_limited}
                          </span>
                        </div>
                        <div className="text-sm">
                          <span className="text-[#A1A1AA]">At Limit: </span>
                          <span className={`font-semibold ${apiStatus.total_limit_reached > 0 ? 'text-[#EF4444]' : 'text-[#22C55E]'}`}>
                            {apiStatus.total_limit_reached || 0}
                          </span>
                        </div>
                        <div className="text-sm">
                          <span className="text-[#A1A1AA]">Today's Usage: </span>
                          <span className="text-white font-semibold">
                            {apiStatus.total_used_today?.toLocaleString() || 0} / {apiStatus.total_limit_today?.toLocaleString() || 0}
                          </span>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        {apiStatus.total_rate_limited > 0 && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleClearRateLimits}
                            className="border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B] hover:text-black"
                          >
                            Clear Rate Limits
                          </Button>
                        )}
                      </div>
                    </div>
                    {/* Total usage progress bar */}
                    {apiStatus.total_limit_today > 0 && (
                      <div className="mt-3">
                        <div className="h-2 bg-[#27272A] rounded-full overflow-hidden">
                          <div 
                            className={`h-full transition-all ${
                              (apiStatus.total_used_today / apiStatus.total_limit_today) > 0.9 ? 'bg-[#EF4444]' :
                              (apiStatus.total_used_today / apiStatus.total_limit_today) > 0.7 ? 'bg-[#F59E0B]' : 'bg-[#22C55E]'
                            }`}
                            style={{ width: `${Math.min(100, (apiStatus.total_used_today / apiStatus.total_limit_today) * 100)}%` }}
                          />
                        </div>
                        <p className="text-xs text-[#52525B] mt-1">
                          {apiStatus.date} • Auto-resets at midnight UTC
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {Object.entries(apiSettings).sort((a, b) => (a[1].priority || 99) - (b[1].priority || 99)).map(([apiKey, config]) => {
                    const statusInfo = apiStatus?.apis?.find(a => a.key === apiKey);
                    const isRateLimited = statusInfo?.rate_limited || false;
                    const isLimitReached = statusInfo?.limit_reached || false;
                    const usagePercent = statusInfo?.usage_percent || 0;
                    
                    return (
                    <div 
                      key={apiKey} 
                      className={`p-4 rounded-lg border ${
                        isLimitReached ? 'bg-[#1a0808] border-[#EF4444]/30' :
                        isRateLimited ? 'bg-[#1a1408] border-[#F59E0B]/30' : 
                        config.enabled ? 'bg-[#18181B] border-[#27272A]' : 'bg-[#0a0a0a] border-[#1a1a1a]'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1">
                          <div className="flex items-center gap-3 mb-2 flex-wrap">
                            <Globe className={`w-5 h-5 ${
                              isLimitReached ? 'text-[#EF4444]' :
                              isRateLimited ? 'text-[#F59E0B]' : 
                              config.enabled ? 'text-[#22C55E]' : 'text-[#52525B]'
                            }`} />
                            <h3 className="font-semibold text-white">{config.name}</h3>
                            {config.is_custom && (
                              <Badge className="bg-[#8B5CF6] text-xs">Custom</Badge>
                            )}
                            {isLimitReached ? (
                              <Badge className="bg-[#EF4444] text-xs">
                                Limit Reached
                              </Badge>
                            ) : isRateLimited ? (
                              <Badge className="bg-[#F59E0B] text-xs">
                                Rate Limited ({Math.ceil(statusInfo.rate_limit_resets_in / 60)}m)
                              </Badge>
                            ) : (
                              <Badge className={config.enabled ? 'bg-[#22C55E]' : 'bg-[#52525B]'}>
                                {config.enabled ? 'Enabled' : 'Disabled'}
                              </Badge>
                            )}
                            <span className="text-xs text-[#52525B]">Priority: {config.priority}</span>
                          </div>
                          
                          {/* Usage Progress Bar */}
                          {config.enabled && statusInfo && (
                            <div className="mb-3">
                              <div className="flex justify-between text-xs mb-1">
                                <span className="text-[#A1A1AA]">
                                  Used: {statusInfo.used_today?.toLocaleString() || 0} / {statusInfo.daily_limit?.toLocaleString() || 0}
                                </span>
                                <span className={`font-medium ${
                                  usagePercent >= 100 ? 'text-[#EF4444]' :
                                  usagePercent >= 80 ? 'text-[#F59E0B]' : 'text-[#22C55E]'
                                }`}>
                                  {usagePercent}%
                                </span>
                              </div>
                              <div className="h-2 bg-[#27272A] rounded-full overflow-hidden">
                                <div 
                                  className={`h-full transition-all ${
                                    usagePercent >= 100 ? 'bg-[#EF4444]' :
                                    usagePercent >= 80 ? 'bg-[#F59E0B]' : 'bg-[#22C55E]'
                                  }`}
                                  style={{ width: `${Math.min(100, usagePercent)}%` }}
                                />
                              </div>
                              <p className="text-xs text-[#52525B] mt-1">
                                Remaining: {statusInfo.remaining?.toLocaleString() || 0} requests today
                              </p>
                            </div>
                          )}
                          
                          <p className="text-sm text-[#A1A1AA] mb-3">{config.description}</p>
                          {isLimitReached && (
                            <p className="text-xs text-[#EF4444] mb-3">
                              🚫 Daily limit reached! System will automatically use the next available API.
                            </p>
                          )}
                          {isRateLimited && !isLimitReached && (
                            <p className="text-xs text-[#F59E0B] mb-3">
                              ⚠️ API returned rate limit error. Will retry in {Math.ceil(statusInfo.rate_limit_resets_in / 60)} minutes.
                            </p>
                          )}
                          
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                              <Label className="text-xs text-[#71717A]">API Endpoint</Label>
                              <Input
                                value={config.endpoint || ""}
                                onChange={(e) => handleApiSettingChange(apiKey, "endpoint", e.target.value)}
                                className="bg-[#09090B] border-[#27272A] text-sm"
                                placeholder="API endpoint URL"
                              />
                            </div>
                            <div className="space-y-2">
                              <Label className="text-xs text-[#71717A]">API Key (if required)</Label>
                              <div className="relative">
                                <Input
                                  type={showApiKey[apiKey] ? "text" : "password"}
                                  value={config.api_key || ""}
                                  onChange={(e) => handleApiSettingChange(apiKey, "api_key", e.target.value)}
                                  className="bg-[#09090B] border-[#27272A] text-sm pr-10"
                                  placeholder="Enter API key"
                                />
                                <button
                                  type="button"
                                  onClick={() => setShowApiKey(prev => ({ ...prev, [apiKey]: !prev[apiKey] }))}
                                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-white"
                                >
                                  {showApiKey[apiKey] ? <EyeOff size={14} /> : <Eye size={14} />}
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                        
                        <div className="flex flex-col gap-2">
                          <Switch
                            checked={config.enabled}
                            onCheckedChange={(checked) => handleApiSettingChange(apiKey, "enabled", checked)}
                          />
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleTestApi(apiKey)}
                            disabled={testingApi === apiKey}
                            className="border-[#27272A]"
                          >
                            {testingApi === apiKey ? (
                              <RefreshCw size={14} className="animate-spin" />
                            ) : (
                              <TestTube size={14} />
                            )}
                          </Button>
                          {config.is_custom && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleDeleteCustomApi(apiKey)}
                              className="border-[#EF4444] text-[#EF4444] hover:bg-[#EF4444] hover:text-white"
                            >
                              <Trash2 size={14} />
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                  })}
                  
                  {Object.keys(apiSettings).length === 0 && (
                    <div className="text-center py-8 text-[#A1A1AA]">
                      No API settings configured. Click "Add Custom API" to add one.
                    </div>
                  )}
                </div>
                
                {/* Info Box */}
                <div className="mt-6 p-4 bg-[#18181B] rounded-lg border border-[#27272A]">
                  <h4 className="font-medium text-white mb-2">How API Priority Works</h4>
                  <p className="text-sm text-[#A1A1AA]">
                    APIs are checked in order of priority (lowest number first). If one API fails or times out, 
                    the next enabled API is used. Disable APIs you don't need to speed up VPN detection.
                  </p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── System Check tab ─────────────────────────── */}
          <TabsContent value="system" className="mt-6">
            <SystemCheckPanel api={API} />
          </TabsContent>
        </Tabs>
      </main>

      {/* Edit User Dialog */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="bg-[#09090B] border-[#27272A] max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit User: {selectedUser?.name}</DialogTitle>
            <DialogDescription>{selectedUser?.email}</DialogDescription>
          </DialogHeader>
          
          <div className="space-y-6 py-4">
            {/* Credentials */}
            <div className="space-y-4">
              <Label className="text-base font-medium">Account Credentials</Label>
              <div className="grid grid-cols-2 gap-4 bg-[#18181B] p-4 rounded-lg">
                <div className="space-y-2">
                  <Label htmlFor="user-email">Email</Label>
                  <Input
                    id="user-email"
                    type="email"
                    value={userEmail}
                    onChange={(e) => setUserEmail(e.target.value)}
                    className="bg-[#09090B] border-[#27272A]"
                    data-testid="edit-user-email"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="user-password">New Password (leave empty to keep)</Label>
                  <div className="relative">
                    <Input
                      id="user-password"
                      type={showPassword ? "text" : "password"}
                      value={userPassword}
                      onChange={(e) => setUserPassword(e.target.value)}
                      placeholder="Enter new password"
                      className="bg-[#09090B] border-[#27272A] pr-10"
                      data-testid="edit-user-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-white"
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Status */}
            <div className="space-y-2">
              <Label>Account Status</Label>
              <div className="flex gap-2">
                {["pending", "active", "blocked"].map((status) => (
                  <Button
                    key={status}
                    variant={userStatus === status ? "default" : "outline"}
                    size="sm"
                    onClick={() => setUserStatus(status)}
                    className={userStatus === status ? 
                      status === "active" ? "bg-[#22C55E]" : 
                      status === "blocked" ? "bg-[#EF4444]" : "bg-[#F59E0B]"
                      : "border-[#27272A]"
                    }
                  >
                    {status.charAt(0).toUpperCase() + status.slice(1)}
                  </Button>
                ))}
              </div>
            </div>

            {/* Subscription */}
            <div className="space-y-4">
              <Label className="text-base font-medium">Subscription Management</Label>
              <div className="grid grid-cols-2 gap-4 bg-[#18181B] p-4 rounded-lg">
                <div className="space-y-2">
                  <Label>Subscription Type</Label>
                  <Select value={subscriptionType} onValueChange={setSubscriptionType}>
                    <SelectTrigger className="bg-[#09090B] border-[#27272A]">
                      <SelectValue placeholder="Select type" />
                    </SelectTrigger>
                    <SelectContent className="bg-[#18181B] border-[#27272A]">
                      <SelectItem value="free">Free</SelectItem>
                      <SelectItem value="monthly">Monthly</SelectItem>
                      <SelectItem value="yearly">Yearly</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Expiration Date</Label>
                  <Input
                    type="date"
                    value={subscriptionExpires}
                    onChange={(e) => setSubscriptionExpires(e.target.value)}
                    className="bg-[#09090B] border-[#27272A]"
                  />
                </div>
              </div>
            </div>

            {/* Features */}
            <div className="space-y-4">
              <Label>Feature Access</Label>
              <div className="space-y-3 bg-[#18181B] p-4 rounded-lg">
                {[
                  { key: "links", label: "Links Management" },
                  { key: "clicks", label: "Click Tracking" },
                  { key: "conversions", label: "Conversion Tracking" },
                  { key: "proxies", label: "Proxy Management" },
                  { key: "import_traffic", label: "Import Traffic (Quick / Manual / Bulk)" },
                  { key: "real_traffic", label: "Real Traffic (residential proxies)" },
                  { key: "ua_generator", label: "User Agent Generator" },
                  { key: "email_checker", label: "Email Profile Checker" },
                  { key: "separate_data", label: "Separate Data (row filter)" },
                  { key: "form_filler", label: "Form Filler / Survey Bot" },
                  { key: "real_user_traffic", label: "Real User Traffic (anti-detect)" },
                  { key: "import_data", label: "Data Import (legacy master toggle)" },
                  { key: "settings", label: "Settings Access" }
                ].map(({ key, label }) => (
                  <div key={key} className="flex items-center justify-between">
                    <span className="text-sm text-[#FAFAFA]">{label}</span>
                    <Switch
                      checked={userFeatures[key] || false}
                      onCheckedChange={(checked) => setUserFeatures(prev => ({ ...prev, [key]: checked }))}
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* Limits */}
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label>Max Links</Label>
                <Input
                  type="number"
                  value={userFeatures.max_links || 0}
                  onChange={(e) => setUserFeatures(prev => ({ ...prev, max_links: parseInt(e.target.value) || 0 }))}
                  className="bg-[#18181B] border-[#27272A]"
                />
              </div>
              <div className="space-y-2">
                <Label>Max Clicks</Label>
                <Input
                  type="number"
                  value={userFeatures.max_clicks || 0}
                  onChange={(e) => setUserFeatures(prev => ({ ...prev, max_clicks: parseInt(e.target.value) || 0 }))}
                  className="bg-[#18181B] border-[#27272A]"
                />
              </div>
              <div className="space-y-2">
                <Label>Max Sub-Users</Label>
                <Input
                  type="number"
                  value={userFeatures.max_sub_users || 0}
                  onChange={(e) => setUserFeatures(prev => ({ ...prev, max_sub_users: parseInt(e.target.value) || 0 }))}
                  className="bg-[#18181B] border-[#27272A]"
                  data-testid="max-sub-users-input"
                />
                <p className="text-xs text-[#A1A1AA]">0 = unlimited</p>
              </div>
            </div>

            {/* Subscription Note */}
            <div className="space-y-2">
              <Label>Subscription Note (Internal)</Label>
              <Textarea
                value={subscriptionNote}
                onChange={(e) => setSubscriptionNote(e.target.value)}
                placeholder="Add notes about payment, subscription tier, etc."
                className="bg-[#18181B] border-[#27272A]"
              />
            </div>

            <Button onClick={handleUpdateUser} className="w-full">
              Save Changes
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Edit Sub-User Dialog */}
      <Dialog open={editSubUserDialogOpen} onOpenChange={setEditSubUserDialogOpen}>
        <DialogContent className="bg-[#09090B] border-[#27272A] max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit Sub-User: {selectedSubUser?.name}</DialogTitle>
            <DialogDescription>
              {selectedSubUser?.email} (Parent: {selectedSubUser?.parent_email})
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-6 py-4">
            {/* Name */}
            <div className="space-y-2">
              <Label htmlFor="subuser-name">Name</Label>
              <Input
                id="subuser-name"
                value={subUserName}
                onChange={(e) => setSubUserName(e.target.value)}
                className="bg-[#18181B] border-[#27272A]"
                data-testid="edit-subuser-name"
              />
            </div>

            {/* Password */}
            <div className="space-y-2">
              <Label htmlFor="subuser-password">New Password (leave empty to keep)</Label>
              <div className="relative">
                <Input
                  id="subuser-password"
                  type={showPassword ? "text" : "password"}
                  value={subUserPassword}
                  onChange={(e) => setSubUserPassword(e.target.value)}
                  placeholder="Enter new password"
                  className="bg-[#18181B] border-[#27272A] pr-10"
                  data-testid="edit-subuser-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-white"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* Status */}
            <div className="flex items-center justify-between bg-[#18181B] p-4 rounded-lg">
              <div>
                <Label>Account Status</Label>
                <p className="text-sm text-[#A1A1AA]">Enable or disable this sub-user account</p>
              </div>
              <Switch
                checked={subUserIsActive}
                onCheckedChange={setSubUserIsActive}
                data-testid="subuser-active-switch"
              />
            </div>

            {/* Permissions */}
            <div className="space-y-4">
              <Label>Permissions</Label>
              <div className="space-y-3 bg-[#18181B] p-4 rounded-lg">
                {[
                  { key: "view_links", label: "View Links" },
                  { key: "view_clicks", label: "View Clicks" },
                  { key: "view_proxies", label: "View Proxies" },
                  { key: "edit", label: "Edit Capabilities" }
                ].map(({ key, label }) => (
                  <div key={key} className="flex items-center justify-between">
                    <span className="text-sm text-[#FAFAFA]">{label}</span>
                    <Switch
                      checked={subUserPermissions[key] || false}
                      onCheckedChange={(checked) => setSubUserPermissions(prev => ({ ...prev, [key]: checked }))}
                      data-testid={`subuser-perm-${key}`}
                    />
                  </div>
                ))}
              </div>
            </div>

            <Button onClick={handleUpdateSubUser} className="w-full">
              Save Changes
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Add Custom API Dialog */}
      <Dialog open={addApiDialogOpen} onOpenChange={setAddApiDialogOpen}>
        <DialogContent className="bg-[#09090B] border-[#27272A] max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Custom API</DialogTitle>
            <DialogDescription>Add a new VPN detection or geolocation API service</DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="api-key-id">API Key ID *</Label>
                <Input
                  id="api-key-id"
                  value={newApiData.key}
                  onChange={(e) => setNewApiData(prev => ({ ...prev, key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') }))}
                  className="bg-[#18181B] border-[#27272A]"
                  placeholder="e.g., my_vpn_api"
                />
                <p className="text-xs text-[#52525B]">Unique identifier (lowercase, no spaces)</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="api-name">Display Name *</Label>
                <Input
                  id="api-name"
                  value={newApiData.name}
                  onChange={(e) => setNewApiData(prev => ({ ...prev, name: e.target.value }))}
                  className="bg-[#18181B] border-[#27272A]"
                  placeholder="e.g., My VPN API"
                />
              </div>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="api-endpoint">API Endpoint *</Label>
              <Input
                id="api-endpoint"
                value={newApiData.endpoint}
                onChange={(e) => setNewApiData(prev => ({ ...prev, endpoint: e.target.value }))}
                className="bg-[#18181B] border-[#27272A]"
                placeholder="https://api.example.com/check/"
              />
              <p className="text-xs text-[#52525B]">Use {"{ip}"} as placeholder for IP address</p>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="api-key-value">API Key (if required)</Label>
              <Input
                id="api-key-value"
                type="password"
                value={newApiData.api_key}
                onChange={(e) => setNewApiData(prev => ({ ...prev, api_key: e.target.value }))}
                className="bg-[#18181B] border-[#27272A]"
                placeholder="Your API key"
              />
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="api-priority">Priority</Label>
                <Input
                  id="api-priority"
                  type="number"
                  min="1"
                  max="99"
                  value={newApiData.priority}
                  onChange={(e) => setNewApiData(prev => ({ ...prev, priority: parseInt(e.target.value) || 10 }))}
                  className="bg-[#18181B] border-[#27272A]"
                />
                <p className="text-xs text-[#52525B]">Lower = checked first</p>
              </div>
              <div className="space-y-2 flex items-end">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={newApiData.enabled}
                    onCheckedChange={(checked) => setNewApiData(prev => ({ ...prev, enabled: checked }))}
                  />
                  <Label>Enabled</Label>
                </div>
              </div>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="api-description">Description</Label>
              <Textarea
                id="api-description"
                value={newApiData.description}
                onChange={(e) => setNewApiData(prev => ({ ...prev, description: e.target.value }))}
                className="bg-[#18181B] border-[#27272A]"
                placeholder="What does this API do?"
                rows={2}
              />
            </div>
            
            <div className="flex gap-2 pt-4">
              <Button 
                variant="outline" 
                onClick={() => setAddApiDialogOpen(false)}
                className="flex-1 border-[#27272A]"
              >
                Cancel
              </Button>
              <Button 
                onClick={handleAddCustomApi}
                className="flex-1 bg-[#3B82F6] hover:bg-[#2563EB]"
              >
                Add API
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
