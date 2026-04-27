import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { toast } from "sonner";
import { Eye, EyeOff, Shield, Mail } from "lucide-react";
import { useBranding } from "../context/BrandingContext";
import ThemeToggle from "../components/ThemeToggle";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function LoginPage() {
  const navigate = useNavigate();
  const { branding } = useBranding();
  const [showPassword, setShowPassword] = useState(false);
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [registerForm, setRegisterForm] = useState({ email: "", password: "", name: "" });
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const response = await axios.post(`${API}/auth/login`, loginForm);
      localStorage.setItem("token", response.data.access_token);
      localStorage.setItem("user", JSON.stringify(response.data.user));
      
      // Check if user is pending/blocked
      const userStatus = response.data.user.status;
      if (userStatus === "pending") {
        toast.info("Your account is pending activation. Contact admin for access.");
      } else if (userStatus === "blocked") {
        toast.error("Your account has been blocked. Contact admin for support.");
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        return;
      }
      
      toast.success("Login successful!");
      navigate("/");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const response = await axios.post(`${API}/auth/register`, registerForm);
      localStorage.setItem("token", response.data.access_token);
      localStorage.setItem("user", JSON.stringify(response.data.user));
      toast.success("Registration successful! Contact admin for feature access.");
      navigate("/");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{
        backgroundImage: branding.login_bg_url ? `url('${branding.login_bg_url}')` : `url('https://images.unsplash.com/photo-1762279388956-1c098163a2a8?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA3MDR8MHwxfHNlYXJjaHwyfHxhYnN0cmFjdCUyMGRpZ2l0YWwlMjBkYXRhJTIwZmxvdyUyMGRhcmslMjBiYWNrZ3JvdW5kfGVufDB8fHx8MTc3MDE0Nzg2Nnww&ixlib=rb-4.1.0&q=85')`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      <div className="absolute inset-0 bg-black/70"></div>
      <div className="absolute top-4 right-4 z-20">
        <ThemeToggle />
      </div>
      <div className="relative z-10 w-full max-w-md">
        <div className="text-center mb-8">
          {branding.logo_url ? (
            <img src={branding.logo_url} alt={branding.app_name} className="h-16 mx-auto mb-4 object-contain" />
          ) : (
            <h1 className="text-4xl font-bold text-white mb-2" data-testid="app-title">{branding.app_name || "RealFlow"}</h1>
          )}
          <p className="text-muted-foreground">{branding.tagline || "Real Users. Real Results."}</p>
        </div>

        <Card className="backdrop-blur-sm" style={{ backgroundColor: 'color-mix(in srgb, var(--brand-card) 90%, transparent)', borderColor: 'var(--brand-border)' }}>
          <CardHeader>
            <CardTitle style={{ color: 'var(--brand-text)' }}>Welcome</CardTitle>
            <CardDescription>Sign in to your account or create a new one</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="login" className="w-full">
              <TabsList className="grid w-full grid-cols-2 mb-6">
                <TabsTrigger value="login" data-testid="login-tab">Login</TabsTrigger>
                <TabsTrigger value="register" data-testid="register-tab">Register</TabsTrigger>
              </TabsList>

              <TabsContent value="login">
                <form onSubmit={handleLogin} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="login-email">Email</Label>
                    <Input
                      id="login-email"
                      data-testid="login-email-input"
                      type="email"
                      placeholder="you@example.com"
                      value={loginForm.email}
                      onChange={(e) => setLoginForm({ ...loginForm, email: e.target.value })}
                      required
                      style={{ backgroundColor: 'var(--brand-card)', borderColor: 'var(--brand-border)' }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="login-password">Password</Label>
                    <div className="relative">
                      <Input
                        id="login-password"
                        data-testid="login-password-input"
                        type={showPassword ? "text" : "password"}
                        placeholder="••••••••"
                        value={loginForm.password}
                        onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                        required
                        className="pr-10"
                        style={{ backgroundColor: 'var(--brand-card)', borderColor: 'var(--brand-border)' }}
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 hover:opacity-80"
                        style={{ color: 'var(--brand-muted)' }}
                      >
                        {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                  </div>
                  <Button
                    type="submit"
                    data-testid="login-submit-button"
                    className="w-full"
                    disabled={loading}
                    style={{ backgroundColor: 'var(--brand-primary)' }}
                  >
                    {loading ? "Logging in..." : "Login"}
                  </Button>
                  <div className="text-center mt-3">
                    <Link 
                      to="/forgot-password" 
                      className="text-sm hover:underline"
                      style={{ color: 'var(--brand-primary)' }}
                    >
                      Forgot Password?
                    </Link>
                  </div>
                </form>
              </TabsContent>

              <TabsContent value="register">
                <form onSubmit={handleRegister} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="register-name">Name</Label>
                    <Input
                      id="register-name"
                      data-testid="register-name-input"
                      type="text"
                      placeholder="John Doe"
                      value={registerForm.name}
                      onChange={(e) => setRegisterForm({ ...registerForm, name: e.target.value })}
                      required
                      style={{ backgroundColor: 'var(--brand-card)', borderColor: 'var(--brand-border)' }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="register-email">Email</Label>
                    <Input
                      id="register-email"
                      data-testid="register-email-input"
                      type="email"
                      placeholder="you@example.com"
                      value={registerForm.email}
                      onChange={(e) => setRegisterForm({ ...registerForm, email: e.target.value })}
                      required
                      style={{ backgroundColor: 'var(--brand-card)', borderColor: 'var(--brand-border)' }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="register-password">Password</Label>
                    <div className="relative">
                      <Input
                        id="register-password"
                        data-testid="register-password-input"
                        type={showPassword ? "text" : "password"}
                        placeholder="••••••••"
                        value={registerForm.password}
                        onChange={(e) => setRegisterForm({ ...registerForm, password: e.target.value })}
                        required
                        className="pr-10"
                        style={{ backgroundColor: 'var(--brand-card)', borderColor: 'var(--brand-border)' }}
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 hover:opacity-80"
                        style={{ color: 'var(--brand-muted)' }}
                      >
                        {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                  </div>
                  <Button
                    type="submit"
                    data-testid="register-submit-button"
                    className="w-full"
                    disabled={loading}
                    style={{ backgroundColor: 'var(--brand-primary)' }}
                  >
                    {loading ? "Creating account..." : "Create Account"}
                  </Button>
                </form>
                
                {/* Contact Info for Payment */}
                <div className="mt-4 p-3 rounded-lg" style={{ backgroundColor: 'var(--brand-card)', borderColor: 'var(--brand-border)', border: '1px solid var(--brand-border)' }}>
                  <p className="text-xs mb-2" style={{ color: 'var(--brand-muted)' }}>
                    After registration, contact admin for feature access:
                  </p>
                  <a 
                    href={`mailto:${branding.admin_email || "admin@example.com"}`}
                    className="flex items-center gap-2 text-sm hover:opacity-80 transition-colors"
                    style={{ color: 'var(--brand-primary)' }}
                  >
                    <Mail size={14} />
                    {branding.admin_email || "admin@example.com"}
                  </a>
                </div>
              </TabsContent>
            </Tabs>
            
            {/* Admin Login Link */}
            <div className="mt-6 pt-4 text-center" style={{ borderTop: '1px solid var(--brand-border)' }}>
              <a 
                href="/admin" 
                className="inline-flex items-center gap-2 text-sm transition-colors hover:opacity-80"
                style={{ color: 'var(--brand-muted)' }}
              >
                <Shield size={14} />
                Admin Login
              </a>
            </div>
          </CardContent>
        </Card>
        
        {/* Footer */}
        <p className="text-center text-xs text-[#52525B] mt-6">{branding.footer_text || "© 2026 RealFlow. All rights reserved."}</p>
      </div>
    </div>
  );
}
