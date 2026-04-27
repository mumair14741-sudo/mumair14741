import { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { toast } from "sonner";
import { Shield, Eye, EyeOff } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function AdminLoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      const response = await axios.post(`${API}/admin/login`, { email, password });
      localStorage.setItem("adminToken", response.data.access_token);
      localStorage.setItem("isAdmin", "true");
      toast.success("Admin login successful!");
      navigate("/admin/dashboard");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Invalid admin credentials");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div 
      className="min-h-screen flex items-center justify-center p-4"
      style={{
        backgroundColor: 'var(--brand-background)',
        backgroundImage:
          'radial-gradient(circle at 30% 20%, color-mix(in srgb, var(--brand-primary) 12%, transparent), transparent 60%), ' +
          'radial-gradient(circle at 70% 80%, color-mix(in srgb, var(--brand-accent) 10%, transparent), transparent 60%)',
      }}
      data-testid="admin-login-page"
    >
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2 mb-2">
            <Shield className="w-10 h-10" style={{ color: 'var(--brand-danger)' }} />
            <h1 className="text-3xl font-bold" style={{ color: 'var(--brand-text)' }}>Admin Panel</h1>
          </div>
          <p style={{ color: 'var(--brand-muted)' }}>RealFlow Administration</p>
        </div>

        <Card style={{ backgroundColor: 'color-mix(in srgb, var(--brand-card) 90%, transparent)', borderColor: 'var(--brand-border)' }} className="backdrop-blur-lg">
          <CardHeader>
            <CardTitle style={{ color: 'var(--brand-text)' }}>Admin Login</CardTitle>
            <CardDescription>Access the administration dashboard</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Admin Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="admin@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="bg-[#18181B] border-[#27272A]"
                  data-testid="admin-email-input"
                  required
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">Password</Label>
                  <a 
                    href="/forgot-password" 
                    className="text-xs text-[#3B82F6] hover:text-[#60A5FA]"
                  >
                    Forgot Password?
                  </a>
                </div>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="bg-[#18181B] border-[#27272A] pr-10"
                    data-testid="admin-password-input"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-white"
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>
              <Button 
                type="submit" 
                className="w-full bg-[#EF4444] hover:bg-[#DC2626]"
                disabled={loading}
                data-testid="admin-login-button"
              >
                {loading ? "Signing in..." : "Sign In as Admin"}
              </Button>
            </form>
            
            <div className="mt-6 pt-4 border-t border-[#27272A]">
              <a 
                href="/login" 
                className="text-sm text-[#A1A1AA] hover:text-white transition-colors"
              >
                ← Back to User Login
              </a>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
