import { useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Switch } from "../components/ui/switch";
import { Badge } from "../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { toast } from "sonner";
import { format } from "date-fns";
import { 
  User, Lock, Users, Plus, Trash2, Edit2, 
  Eye, EyeOff, Shield, CheckCircle, XCircle,
  Clock, Save, BarChart3, Link2, MousePointerClick, Server
} from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function SettingsPage() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [subUsers, setSubUsers] = useState([]);
  const [subUserStats, setSubUserStats] = useState([]);
  
  // Profile form
  const [name, setName] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  
  // Sub-user form
  const [subUserDialogOpen, setSubUserDialogOpen] = useState(false);
  const [editingSubUser, setEditingSubUser] = useState(null);
  const [subUserForm, setSubUserForm] = useState({
    email: "",
    name: "",
    password: "",
    permissions: {
      view_clicks: true,
      view_links: true,
      view_proxies: false,
      edit: false
    }
  });

  useEffect(() => {
    fetchUserData();
    fetchSubUsers();
    fetchSubUserStats();
  }, []);

  const getToken = () => localStorage.getItem("token");

  const fetchUserData = async () => {
    try {
      const response = await axios.get(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setUser(response.data);
      setName(response.data.name);
    } catch (error) {
      toast.error("Failed to fetch user data");
    } finally {
      setLoading(false);
    }
  };

  const fetchSubUsers = async () => {
    try {
      const response = await axios.get(`${API}/sub-users`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setSubUsers(response.data);
    } catch (error) {
      // Sub-users feature might not be available
      console.error("Failed to fetch sub-users");
    }
  };

  const fetchSubUserStats = async () => {
    try {
      const response = await axios.get(`${API}/sub-users/stats`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setSubUserStats(response.data.sub_users || []);
    } catch (error) {
      // Sub-user stats might not be available
      console.error("Failed to fetch sub-user stats");
    }
  };

  const handleUpdateProfile = async (e) => {
    e.preventDefault();
    
    if (newPassword && newPassword !== confirmPassword) {
      toast.error("New passwords do not match");
      return;
    }
    
    if (newPassword && newPassword.length < 6) {
      toast.error("Password must be at least 6 characters");
      return;
    }
    
    setSaving(true);
    try {
      const updateData = { name };
      if (newPassword) {
        updateData.current_password = currentPassword;
        updateData.new_password = newPassword;
      }
      
      await axios.put(`${API}/auth/profile`, updateData, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      
      toast.success("Profile updated successfully");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      fetchUserData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to update profile");
    } finally {
      setSaving(false);
    }
  };

  const handleCreateSubUser = async (e) => {
    e.preventDefault();
    
    if (!subUserForm.email || !subUserForm.name) {
      toast.error("Email and name are required");
      return;
    }
    
    if (!editingSubUser && !subUserForm.password) {
      toast.error("Password is required for new sub-user");
      return;
    }
    
    try {
      if (editingSubUser) {
        const updateData = {
          name: subUserForm.name,
          permissions: subUserForm.permissions
        };
        if (subUserForm.password) {
          updateData.password = subUserForm.password;
        }
        
        await axios.put(`${API}/sub-users/${editingSubUser.id}`, updateData, {
          headers: { Authorization: `Bearer ${getToken()}` }
        });
        toast.success("Sub-user updated");
      } else {
        await axios.post(`${API}/sub-users`, subUserForm, {
          headers: { Authorization: `Bearer ${getToken()}` }
        });
        toast.success("Sub-user created");
      }
      
      setSubUserDialogOpen(false);
      setEditingSubUser(null);
      setSubUserForm({
        email: "",
        name: "",
        password: "",
        permissions: { view_clicks: true, view_links: true, view_proxies: false, edit: false }
      });
      fetchSubUsers();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Operation failed");
    }
  };

  const handleDeleteSubUser = async (id, name) => {
    if (!window.confirm(`Delete sub-user "${name}"? This cannot be undone.`)) return;
    
    try {
      await axios.delete(`${API}/sub-users/${id}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      toast.success("Sub-user deleted");
      fetchSubUsers();
    } catch (error) {
      toast.error("Failed to delete sub-user");
    }
  };

  const handleToggleSubUserActive = async (subUser) => {
    try {
      await axios.put(`${API}/sub-users/${subUser.id}`, {
        is_active: !subUser.is_active
      }, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      toast.success(`Sub-user ${subUser.is_active ? 'deactivated' : 'activated'}`);
      fetchSubUsers();
    } catch (error) {
      toast.error("Failed to update sub-user");
    }
  };

  const openEditSubUser = (subUser) => {
    setEditingSubUser(subUser);
    setSubUserForm({
      email: subUser.email,
      name: subUser.name,
      password: "",
      permissions: subUser.permissions || { view_clicks: true, view_links: true, view_proxies: false, edit: false }
    });
    setSubUserDialogOpen(true);
  };

  const openCreateSubUser = () => {
    setEditingSubUser(null);
    setSubUserForm({
      email: "",
      name: "",
      password: "",
      permissions: { view_clicks: true, view_links: true, view_proxies: false, edit: false }
    });
    setSubUserDialogOpen(true);
  };

  if (loading) {
    return <div className="text-muted-foreground">Loading settings...</div>;
  }

  return (
    <div className="space-y-6" data-testid="settings-page">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Settings</h2>
      </div>

      <Tabs defaultValue="profile" className="space-y-6">
        <TabsList className="bg-[#18181B] border border-[#27272A]">
          <TabsTrigger value="profile" className="data-[state=active]:bg-[#27272A]" data-testid="tab-profile">
            <User size={16} className="mr-2" />
            Profile
          </TabsTrigger>
          <TabsTrigger value="subusers" className="data-[state=active]:bg-[#27272A]" data-testid="tab-subusers">
            <Users size={16} className="mr-2" />
            Sub-Users
            {subUsers.length > 0 && (
              <Badge className="ml-2 bg-[#3B82F6]">{subUsers.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="subscription" className="data-[state=active]:bg-[#27272A]" data-testid="tab-subscription">
            <Shield size={16} className="mr-2" />
            Subscription
          </TabsTrigger>
        </TabsList>

        {/* Profile Tab */}
        <TabsContent value="profile" className="space-y-6">
          <Card className="bg-[#09090B] border-[#27272A]">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User size={20} />
                Profile Information
              </CardTitle>
              <CardDescription>Update your profile details and password</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleUpdateProfile} className="space-y-6">
                {/* Account Info */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Email</Label>
                    <Input
                      value={user?.email || ""}
                      disabled
                      className="bg-[#18181B] border-[#27272A] opacity-60"
                    />
                    <p className="text-xs text-muted-foreground">Contact admin to change email</p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="name">Display Name</Label>
                    <Input
                      id="name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="bg-[#18181B] border-[#27272A]"
                      data-testid="profile-name-input"
                    />
                  </div>
                </div>

                {/* Password Change */}
                <div className="border-t border-[#27272A] pt-6">
                  <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                    <Lock size={18} />
                    Change Password
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="current-password">Current Password</Label>
                      <div className="relative">
                        <Input
                          id="current-password"
                          type={showCurrentPassword ? "text" : "password"}
                          value={currentPassword}
                          onChange={(e) => setCurrentPassword(e.target.value)}
                          className="bg-[#18181B] border-[#27272A] pr-10"
                          data-testid="current-password-input"
                        />
                        <button
                          type="button"
                          onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-white"
                        >
                          {showCurrentPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="new-password">New Password</Label>
                      <div className="relative">
                        <Input
                          id="new-password"
                          type={showNewPassword ? "text" : "password"}
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          className="bg-[#18181B] border-[#27272A] pr-10"
                          data-testid="new-password-input"
                        />
                        <button
                          type="button"
                          onClick={() => setShowNewPassword(!showNewPassword)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-white"
                        >
                          {showNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="confirm-password">Confirm Password</Label>
                      <Input
                        id="confirm-password"
                        type="password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        className="bg-[#18181B] border-[#27272A]"
                        data-testid="confirm-password-input"
                      />
                    </div>
                  </div>
                </div>

                <div className="flex justify-end">
                  <Button type="submit" disabled={saving} data-testid="save-profile-button">
                    <Save size={16} className="mr-2" />
                    {saving ? "Saving..." : "Save Changes"}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Sub-Users Tab */}
        <TabsContent value="subusers" className="space-y-6">
          <Card className="bg-[#09090B] border-[#27272A]">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Users size={20} />
                    Sub-User Management
                    {user?.max_sub_users > 0 && (
                      <Badge variant="outline" className="ml-2 text-xs">
                        {subUsers.length}/{user.max_sub_users} used
                      </Badge>
                    )}
                  </CardTitle>
                  <CardDescription>
                    Create sub-accounts with limited access for team members
                    {user?.max_sub_users > 0 && (
                      <span className="text-[#F59E0B]"> (Limit: {user.max_sub_users})</span>
                    )}
                  </CardDescription>
                </div>
                <Dialog open={subUserDialogOpen} onOpenChange={setSubUserDialogOpen}>
                  <DialogTrigger asChild>
                    <Button 
                      onClick={openCreateSubUser} 
                      data-testid="create-subuser-button"
                      disabled={user?.max_sub_users > 0 && subUsers.length >= user.max_sub_users}
                    >
                      <Plus size={16} className="mr-2" />
                      Add Sub-User
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="bg-[#09090B] border-[#27272A]">
                    <DialogHeader>
                      <DialogTitle>{editingSubUser ? "Edit Sub-User" : "Create Sub-User"}</DialogTitle>
                      <DialogDescription>
                        {editingSubUser ? "Update sub-user details and permissions" : "Create a new sub-user with specific permissions"}
                      </DialogDescription>
                    </DialogHeader>
                    <form onSubmit={handleCreateSubUser} className="space-y-4">
                      <div className="space-y-2">
                        <Label htmlFor="sub-email">Email</Label>
                        <Input
                          id="sub-email"
                          type="email"
                          value={subUserForm.email}
                          onChange={(e) => setSubUserForm({ ...subUserForm, email: e.target.value })}
                          disabled={!!editingSubUser}
                          className="bg-[#18181B] border-[#27272A]"
                          required
                          data-testid="subuser-email-input"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="sub-name">Name</Label>
                        <Input
                          id="sub-name"
                          type="text"
                          value={subUserForm.name}
                          onChange={(e) => setSubUserForm({ ...subUserForm, name: e.target.value })}
                          className="bg-[#18181B] border-[#27272A]"
                          required
                          data-testid="subuser-name-input"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="sub-password">
                          {editingSubUser ? "New Password (leave empty to keep current)" : "Password"}
                        </Label>
                        <Input
                          id="sub-password"
                          type="password"
                          value={subUserForm.password}
                          onChange={(e) => setSubUserForm({ ...subUserForm, password: e.target.value })}
                          className="bg-[#18181B] border-[#27272A]"
                          required={!editingSubUser}
                          data-testid="subuser-password-input"
                        />
                      </div>
                      <div className="space-y-3">
                        <Label>Permissions</Label>
                        <div className="bg-[#18181B] p-4 rounded-lg space-y-3">
                          {[
                            { key: "view_clicks", label: "View Clicks" },
                            { key: "view_links", label: "View Links" },
                            { key: "view_proxies", label: "View Proxies" },
                            { key: "edit", label: "Edit Data" }
                          ].map(({ key, label }) => (
                            <div key={key} className="flex items-center justify-between">
                              <span className="text-sm">{label}</span>
                              <Switch
                                checked={subUserForm.permissions[key] || false}
                                onCheckedChange={(checked) => setSubUserForm({
                                  ...subUserForm,
                                  permissions: { ...subUserForm.permissions, [key]: checked }
                                })}
                                data-testid={`permission-${key}`}
                              />
                            </div>
                          ))}
                        </div>
                      </div>
                      <Button type="submit" className="w-full" data-testid="submit-subuser-button">
                        {editingSubUser ? "Update Sub-User" : "Create Sub-User"}
                      </Button>
                    </form>
                  </DialogContent>
                </Dialog>
              </div>
            </CardHeader>
            <CardContent>
              {user?.status !== "active" ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Shield size={48} className="mx-auto mb-4 opacity-50" />
                  <p>Sub-user management is only available for active accounts.</p>
                  <p className="text-sm mt-2">Contact admin to activate your account.</p>
                </div>
              ) : subUsers.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Users size={48} className="mx-auto mb-4 opacity-50" />
                  <p>No sub-users created yet.</p>
                  <p className="text-sm mt-2">Click &quot;Add Sub-User&quot; to create team accounts with limited access.</p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow className="border-[#27272A] hover:bg-transparent">
                      <TableHead>User</TableHead>
                      <TableHead>Permissions</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last Active</TableHead>
                      <TableHead>Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {subUsers.map((subUser) => (
                      <TableRow key={subUser.id} className="border-[#27272A]" data-testid={`subuser-row-${subUser.id}`}>
                        <TableCell>
                          <div>
                            <p className="font-medium text-white">{subUser.name}</p>
                            <p className="text-sm text-muted-foreground">{subUser.email}</p>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1 flex-wrap">
                            {subUser.permissions?.view_clicks && (
                              <Badge variant="outline" className="text-xs border-[#22C55E] text-[#22C55E]">Clicks</Badge>
                            )}
                            {subUser.permissions?.view_links && (
                              <Badge variant="outline" className="text-xs border-[#3B82F6] text-[#3B82F6]">Links</Badge>
                            )}
                            {subUser.permissions?.view_proxies && (
                              <Badge variant="outline" className="text-xs border-[#8B5CF6] text-[#8B5CF6]">Proxies</Badge>
                            )}
                            {subUser.permissions?.edit && (
                              <Badge variant="outline" className="text-xs border-[#F59E0B] text-[#F59E0B]">Edit</Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          {subUser.is_active ? (
                            <Badge className="bg-[#22C55E]">Active</Badge>
                          ) : (
                            <Badge className="bg-[#EF4444]">Inactive</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {subUser.last_active ? (
                            <div className="flex items-center gap-1">
                              <Clock size={14} />
                              {format(new Date(subUser.last_active), "MMM dd, HH:mm")}
                            </div>
                          ) : (
                            "Never"
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleToggleSubUserActive(subUser)}
                              className={subUser.is_active ? "border-[#EF4444] text-[#EF4444]" : "border-[#22C55E] text-[#22C55E]"}
                              data-testid={`toggle-subuser-${subUser.id}`}
                            >
                              {subUser.is_active ? <XCircle size={14} /> : <CheckCircle size={14} />}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => openEditSubUser(subUser)}
                              className="border-[#27272A]"
                              data-testid={`edit-subuser-${subUser.id}`}
                            >
                              <Edit2 size={14} />
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
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Sub-User Statistics Card */}
          {subUserStats.length > 0 && (
            <Card className="bg-[#09090B] border-[#27272A]">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 size={20} className="text-[#8B5CF6]" />
                  Sub-User Statistics
                </CardTitle>
                <CardDescription>
                  Track usage and activity of your sub-users
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow className="border-[#27272A] hover:bg-transparent">
                      <TableHead>Sub-User</TableHead>
                      <TableHead>Links</TableHead>
                      <TableHead>Clicks</TableHead>
                      <TableHead>Proxies</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last Active</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {subUserStats.map((stat) => (
                      <TableRow key={stat.id} className="border-[#27272A]" data-testid={`stat-row-${stat.id}`}>
                        <TableCell>
                          <div>
                            <p className="font-medium text-white">{stat.name}</p>
                            <p className="text-sm text-muted-foreground">{stat.email}</p>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Link2 size={14} className="text-[#3B82F6]" />
                            <span className="font-medium">{stat.link_count}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <MousePointerClick size={14} className="text-[#22C55E]" />
                            <span className="font-medium">{stat.click_count}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Server size={14} className="text-[#8B5CF6]" />
                            <span className="font-medium">{stat.proxy_count}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          {stat.is_active ? (
                            <Badge className="bg-[#22C55E]">Active</Badge>
                          ) : (
                            <Badge className="bg-[#EF4444]">Inactive</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {stat.last_active ? format(new Date(stat.last_active), "MMM dd, HH:mm") : "Never"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Subscription Tab */}
        <TabsContent value="subscription" className="space-y-6">
          <Card className="bg-[#09090B] border-[#27272A]">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Shield size={20} />
                Subscription Status
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="bg-[#18181B] p-6 rounded-lg border border-[#27272A]">
                  <h4 className="text-sm text-muted-foreground mb-2">Account Status</h4>
                  <div className="flex items-center gap-2">
                    {user?.status === "active" ? (
                      <>
                        <CheckCircle className="text-[#22C55E]" size={24} />
                        <span className="text-xl font-bold text-[#22C55E]">Active</span>
                      </>
                    ) : user?.status === "blocked" ? (
                      <>
                        <XCircle className="text-[#EF4444]" size={24} />
                        <span className="text-xl font-bold text-[#EF4444]">Blocked</span>
                      </>
                    ) : (
                      <>
                        <Clock className="text-[#F59E0B]" size={24} />
                        <span className="text-xl font-bold text-[#F59E0B]">Pending</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="bg-[#18181B] p-6 rounded-lg border border-[#27272A]">
                  <h4 className="text-sm text-muted-foreground mb-2">Subscription Type</h4>
                  <p className="text-xl font-bold capitalize">{user?.subscription_type || "Free"}</p>
                  {user?.subscription_expires && (
                    <p className="text-sm text-muted-foreground mt-1">
                      Expires: {format(new Date(user.subscription_expires), "MMM dd, yyyy")}
                    </p>
                  )}
                </div>
              </div>

              <div className="border-t border-[#27272A] pt-6">
                <h4 className="text-lg font-medium mb-4">Active Features</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {[
                    { key: "links", label: "Links Management", icon: "🔗" },
                    { key: "clicks", label: "Click Tracking", icon: "📊" },
                    { key: "conversions", label: "Conversions", icon: "💰" },
                    { key: "proxies", label: "Proxy Management", icon: "🌐" },
                    { key: "import_data", label: "Data Import", icon: "📥" }
                  ].map(({ key, label, icon }) => (
                    <div
                      key={key}
                      className={`p-4 rounded-lg border ${
                        user?.features?.[key]
                          ? "bg-[#22C55E]/10 border-[#22C55E]/30"
                          : "bg-[#27272A]/30 border-[#27272A]"
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span>{icon}</span>
                        {user?.features?.[key] ? (
                          <CheckCircle size={14} className="text-[#22C55E]" />
                        ) : (
                          <XCircle size={14} className="text-[#71717A]" />
                        )}
                      </div>
                      <p className={`text-sm ${user?.features?.[key] ? "text-white" : "text-muted-foreground"}`}>
                        {label}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="bg-[#18181B] p-4 rounded-lg border border-[#27272A]">
                <p className="text-sm text-muted-foreground">
                  To upgrade your subscription or request additional features, please contact admin at{" "}
                  <a href={`mailto:${user?.admin_contact}`} className="text-[#3B82F6] hover:underline">
                    {user?.admin_contact}
                  </a>
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
