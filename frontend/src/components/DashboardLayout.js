import { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { LayoutDashboard, Link2, MousePointerClick, DollarSign, Server, Menu, LogOut, User, Settings, TrendingUp, Upload, Mail, Filter, Smartphone, Search, ClipboardCheck, Fingerprint } from "lucide-react";
import { Button } from "./ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "./ui/dropdown-menu";
import { useBranding } from "../context/BrandingContext";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function DashboardLayout({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { branding } = useBranding();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [user, setUser] = useState(JSON.parse(localStorage.getItem("user") || "{}"));
  const [loading, setLoading] = useState(true);

  // Fetch fresh user data on mount to get updated features
  useEffect(() => {
    const fetchUserData = async () => {
      const token = localStorage.getItem("token");
      if (!token) {
        navigate("/login");
        return;
      }

      try {
        const response = await axios.get(`${API}/auth/me`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const freshUserData = response.data;
        
        // Update localStorage with fresh data
        const currentUser = JSON.parse(localStorage.getItem("user") || "{}");
        const updatedUser = { ...currentUser, ...freshUserData };
        localStorage.setItem("user", JSON.stringify(updatedUser));
        setUser(updatedUser);
      } catch (error) {
        console.error("Failed to fetch user data:", error);
        // If token is invalid, redirect to login
        if (error.response?.status === 401 || error.response?.status === 403) {
          localStorage.removeItem("token");
          localStorage.removeItem("user");
          navigate("/login");
        }
      } finally {
        setLoading(false);
      }
    };

    fetchUserData();
  }, [navigate]);

  const isSubUser = user.is_sub_user === true;
  const features = user.features || {};

  // Build navigation based on user's enabled features
  const allNavItems = [
    { name: "Dashboard", path: "/", icon: LayoutDashboard, feature: null }, // Always show dashboard
    { name: "Links", path: "/links", icon: Link2, feature: "links" },
    { name: "Clicks", path: "/clicks", icon: MousePointerClick, feature: "clicks" },
    { name: "Traffic Sources", path: "/referrers", icon: TrendingUp, feature: "clicks" },
    { name: "Import Traffic", path: "/import-traffic", icon: Upload, feature: "import_traffic" },
    { name: "Email Checker", path: "/email-checker", icon: Mail, feature: "email_checker" },
    { name: "Separate Data", path: "/separate-data", icon: Filter, feature: "separate_data" },
    { name: "UA Generator", path: "/ua-generator", icon: Smartphone, feature: "ua_generator" },
    { name: "UA Checker", path: "/ua-checker", icon: Search, feature: "ua_generator" },
    { name: "Form Filler", path: "/form-filler", icon: ClipboardCheck, feature: "form_filler" },
    { name: "Real User Traffic", path: "/real-user-traffic", icon: Fingerprint, feature: "real_user_traffic" },
    { name: "Conversions", path: "/conversions", icon: DollarSign, feature: "conversions" },
    { name: "Proxies", path: "/proxies", icon: Server, feature: "proxies" },
  ];

  // Backward compat: new granular features fall back to "import_data" legacy flag
  const LEGACY_IMPORT_GROUP = new Set([
    "email_checker", "separate_data", "import_traffic", "real_traffic", "ua_generator"
  ]);

  // Filter navigation: show only enabled features
  const navigation = allNavItems.filter(item => {
    if (item.feature === null) return true; // Always show Dashboard
    if (features[item.feature] === true) return true;
    // Legacy fallback
    if (
      features[item.feature] === undefined &&
      LEGACY_IMPORT_GROUP.has(item.feature) &&
      features.import_data === true
    ) {
      return true;
    }
    return false;
  });

  // Add Settings - ONLY for main users, and only if settings feature is not explicitly false
  // Sub-users NEVER see Settings
  if (!isSubUser && features.settings !== false) {
    navigation.push({ name: "Settings", path: "/settings", icon: Settings, feature: "settings" });
  }

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    navigate("/login");
  };

  return (
    <div className="flex h-screen" style={{ backgroundColor: 'var(--brand-background)' }}>
      <aside
        className={`${
          sidebarOpen ? "w-64" : "w-20"
        } sidebar-brand transition-all duration-300 flex flex-col`}
        style={{ 
          backgroundColor: 'var(--brand-background)', 
          borderRight: '1px solid var(--brand-border)' 
        }}
        data-testid="sidebar"
      >
        <div className="p-6 flex items-center justify-between" style={{ borderBottom: '1px solid var(--brand-border)' }}>
          {sidebarOpen && (
            branding.logo_url ? (
              <img src={branding.logo_url} alt={branding.app_name} className="h-8 object-contain" data-testid="app-logo" />
            ) : (
              <h1 className="text-xl font-bold" style={{ color: 'var(--brand-text)' }} data-testid="app-logo">{branding.app_name || "TrackMaster"}</h1>
            )
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="hover:opacity-80"
            style={{ backgroundColor: 'transparent' }}
            data-testid="sidebar-toggle"
          >
            <Menu size={20} />
          </Button>
        </div>

        <nav className="flex-1 p-4 space-y-2">
          {navigation.map((item) => {
            const isActive = location.pathname === item.path;
            const Icon = item.icon;
            return (
              <Link key={item.path} to={item.path}>
                <div
                  className={`flex items-center gap-3 px-3 py-2 rounded-md transition-colors`}
                  style={{
                    backgroundColor: isActive ? 'var(--brand-primary)' : 'transparent',
                    color: isActive ? 'white' : 'var(--brand-muted)',
                  }}
                  onMouseEnter={(e) => !isActive && (e.currentTarget.style.backgroundColor = 'var(--brand-card)')}
                  onMouseLeave={(e) => !isActive && (e.currentTarget.style.backgroundColor = 'transparent')}
                  data-testid={`nav-${item.name.toLowerCase()}`}
                >
                  <Icon size={20} />
                  {sidebarOpen && <span className="text-sm font-medium">{item.name}</span>}
                </div>
              </Link>
            );
          })}
        </nav>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden">
        <header 
          className="h-16 flex items-center justify-between px-6"
          style={{ 
            backgroundColor: 'var(--brand-background)', 
            borderBottom: '1px solid var(--brand-border)' 
          }}
        >
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold" style={{ color: 'var(--brand-text)' }} data-testid="page-title">
              {navigation.find((item) => item.path === location.pathname)?.name || "Dashboard"}
            </h2>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="flex items-center gap-2" data-testid="user-menu">
                <div 
                  className="w-8 h-8 rounded-full flex items-center justify-center"
                  style={{ backgroundColor: 'var(--brand-primary)' }}
                >
                  <User size={18} />
                </div>
                <span className="text-sm">{user.name || "User"}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              {!isSubUser && (
                <DropdownMenuItem onClick={() => navigate("/settings")} data-testid="settings-button">
                  <Settings size={16} className="mr-2" />
                  Settings
                </DropdownMenuItem>
              )}
              {!isSubUser && <DropdownMenuSeparator />}
              <DropdownMenuItem onClick={handleLogout} data-testid="logout-button">
                <LogOut size={16} className="mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        <main className="flex-1 overflow-auto p-6" data-testid="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
