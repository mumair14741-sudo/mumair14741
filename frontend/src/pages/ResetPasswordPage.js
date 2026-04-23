import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { toast } from "sonner";
import { Lock, Eye, EyeOff, ArrowLeft, Loader2, CheckCircle, XCircle } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(true);
  const [tokenValid, setTokenValid] = useState(false);
  const [userEmail, setUserEmail] = useState("");
  const [resetSuccess, setResetSuccess] = useState(false);

  // Verify token on mount
  useEffect(() => {
    const verifyToken = async () => {
      if (!token) {
        setVerifying(false);
        return;
      }

      try {
        const response = await axios.get(`${API}/auth/verify-reset-token/${token}`);
        setTokenValid(response.data.valid);
        setUserEmail(response.data.email || "");
      } catch (error) {
        setTokenValid(false);
      } finally {
        setVerifying(false);
      }
    };

    verifyToken();
  }, [token]);

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (password.length < 6) {
      toast.error("Password must be at least 6 characters");
      return;
    }

    if (password !== confirmPassword) {
      toast.error("Passwords do not match");
      return;
    }

    setLoading(true);
    try {
      await axios.post(`${API}/auth/reset-password`, {
        token,
        new_password: password
      });
      
      setResetSuccess(true);
      toast.success("Password reset successfully!");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to reset password");
    } finally {
      setLoading(false);
    }
  };

  // Loading state
  if (verifying) {
    return (
      <div className="min-h-screen bg-[#09090B] flex items-center justify-center p-4">
        <Card className="w-full max-w-md bg-[#09090B] border-[#27272A]">
          <CardContent className="p-8 text-center">
            <Loader2 className="mx-auto h-8 w-8 animate-spin text-[#3B82F6]" />
            <p className="mt-4 text-muted-foreground">Verifying reset token...</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Invalid or missing token
  if (!token || !tokenValid) {
    return (
      <div className="min-h-screen bg-[#09090B] flex items-center justify-center p-4">
        <Card className="w-full max-w-md bg-[#09090B] border-[#27272A]">
          <CardHeader className="text-center">
            <div className="mx-auto w-12 h-12 bg-[#EF4444]/20 rounded-full flex items-center justify-center mb-4">
              <XCircle className="w-6 h-6 text-[#EF4444]" />
            </div>
            <CardTitle className="text-2xl">Invalid Reset Link</CardTitle>
            <CardDescription>
              This password reset link is invalid or has expired. Please request a new one.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Button 
              className="w-full"
              onClick={() => navigate("/forgot-password")}
            >
              Request New Reset Link
            </Button>
            <Button 
              variant="ghost" 
              className="w-full"
              onClick={() => navigate("/login")}
            >
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Login
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Success state
  if (resetSuccess) {
    return (
      <div className="min-h-screen bg-[#09090B] flex items-center justify-center p-4">
        <Card className="w-full max-w-md bg-[#09090B] border-[#27272A]">
          <CardHeader className="text-center">
            <div className="mx-auto w-12 h-12 bg-[#22C55E]/20 rounded-full flex items-center justify-center mb-4">
              <CheckCircle className="w-6 h-6 text-[#22C55E]" />
            </div>
            <CardTitle className="text-2xl">Password Reset!</CardTitle>
            <CardDescription>
              Your password has been successfully reset. You can now login with your new password.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button 
              className="w-full"
              onClick={() => navigate("/login")}
            >
              Go to Login
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Reset password form
  return (
    <div className="min-h-screen bg-[#09090B] flex items-center justify-center p-4">
      <Card className="w-full max-w-md bg-[#09090B] border-[#27272A]">
        <CardHeader className="text-center">
          <div className="mx-auto w-12 h-12 bg-[#3B82F6]/20 rounded-full flex items-center justify-center mb-4">
            <Lock className="w-6 h-6 text-[#3B82F6]" />
          </div>
          <CardTitle className="text-2xl">Reset Password</CardTitle>
          <CardDescription>
            {userEmail ? `Enter a new password for ${userEmail}` : "Enter your new password below"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="password">New Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="Enter new password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="bg-[#18181B] border-[#27272A] pr-10"
                  required
                  minLength={6}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-white"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">Confirm Password</Label>
              <Input
                id="confirmPassword"
                type={showPassword ? "text" : "password"}
                placeholder="Confirm new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="bg-[#18181B] border-[#27272A]"
                required
                minLength={6}
              />
            </div>
            {password && confirmPassword && password !== confirmPassword && (
              <p className="text-xs text-[#EF4444]">Passwords do not match</p>
            )}
            <Button 
              type="submit" 
              className="w-full" 
              disabled={loading || password !== confirmPassword}
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Resetting...
                </>
              ) : (
                "Reset Password"
              )}
            </Button>
            <Button 
              type="button" 
              variant="ghost" 
              className="w-full"
              onClick={() => navigate("/login")}
            >
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Login
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
