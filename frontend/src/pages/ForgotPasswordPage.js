import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { toast } from "sonner";
import { Mail, ArrowLeft, Loader2, CheckCircle, Send } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [emailSent, setEmailSent] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email) {
      toast.error("Please enter your email");
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(`${API}/auth/forgot-password`, { email });
      
      // Check if email was actually sent
      setEmailSent(response.data.email_sent || false);
      setSubmitted(true);
      
      if (response.data.email_sent) {
        toast.success("Password reset email sent! Check your inbox.");
      } else {
        toast.success("If the email exists, reset instructions will be sent.");
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to process request");
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return (
      <div className="min-h-screen bg-[#09090B] flex items-center justify-center p-4">
        <Card className="w-full max-w-md bg-[#09090B] border-[#27272A]">
          <CardHeader className="text-center">
            <div className={`mx-auto w-12 h-12 ${emailSent ? 'bg-[#22C55E]/20' : 'bg-[#F59E0B]/20'} rounded-full flex items-center justify-center mb-4`}>
              {emailSent ? (
                <Send className="w-6 h-6 text-[#22C55E]" />
              ) : (
                <CheckCircle className="w-6 h-6 text-[#F59E0B]" />
              )}
            </div>
            <CardTitle className="text-2xl">
              {emailSent ? "Email Sent!" : "Check Your Email"}
            </CardTitle>
            <CardDescription>
              {emailSent 
                ? `We've sent password reset instructions to ${email}. Check your inbox (and spam folder).`
                : `If an account exists with ${email}, you will receive password reset instructions.`
              }
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {emailSent && (
              <div className="p-4 bg-[#22C55E]/10 rounded-lg border border-[#22C55E]/30">
                <p className="text-sm text-[#22C55E]">
                  ✓ Email sent successfully! The link will expire in 1 hour.
                </p>
              </div>
            )}
            
            {!emailSent && (
              <div className="p-4 bg-[#F59E0B]/10 rounded-lg border border-[#F59E0B]/30">
                <p className="text-sm text-[#F59E0B]">
                  ⚠ Email service not configured. Please contact admin to reset your password.
                </p>
              </div>
            )}
            
            <div className="flex gap-2">
              <Button 
                variant="outline" 
                className="flex-1"
                onClick={() => {
                  setSubmitted(false);
                  setEmail("");
                  setEmailSent(false);
                }}
              >
                Try Another Email
              </Button>
              <Button 
                className="flex-1"
                onClick={() => navigate("/login")}
              >
                Back to Login
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#09090B] flex items-center justify-center p-4">
      <Card className="w-full max-w-md bg-[#09090B] border-[#27272A]">
        <CardHeader className="text-center">
          <div className="mx-auto w-12 h-12 bg-[#3B82F6]/20 rounded-full flex items-center justify-center mb-4">
            <Mail className="w-6 h-6 text-[#3B82F6]" />
          </div>
          <CardTitle className="text-2xl">Forgot Password?</CardTitle>
          <CardDescription>
            Enter your email address and we'll send you instructions to reset your password.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email Address</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="bg-[#18181B] border-[#27272A]"
                required
                data-testid="forgot-email-input"
              />
              <p className="text-xs text-muted-foreground">
                Works for admin, main users, and sub-users
              </p>
            </div>
            <Button type="submit" className="w-full" disabled={loading} data-testid="forgot-submit-btn">
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Sending...
                </>
              ) : (
                "Send Reset Instructions"
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
