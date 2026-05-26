import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import ReCAPTCHA from "react-google-recaptcha";
import { useAuthStore } from "../store/authStore";
import type { FormEvent } from "react";

const RECAPTCHA_SITE_KEY = import.meta.env.VITE_RECAPTCHA_SITE_KEY || "";

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, isAuthenticated, user } = useAuthStore();
  const [isLoading, setIsLoading] = useState(false);
  const [emailAddr, setEmailAddr] = useState("");
  const [password, setPassword] = useState("");
  const [recaptchaToken, setRecaptchaToken] = useState<string | null>(null);
  const [error, setError] = useState("");
  const recaptchaRef = useRef<ReCAPTCHA>(null);

  useEffect(() => {
    if (isAuthenticated && user) {
      if (user.status === "pending" || user.status === "suspended") {
        navigate("/pending", { replace: true });
      } else if (user.role === "admin" || user.role === "manager") {
        navigate("/admin", { replace: true });
      } else {
        navigate("/", { replace: true });
      }
    }
  }, [isAuthenticated, user, navigate]);

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (!emailAddr.trim() || !password.trim()) {
      setError("Please enter your email and password.");
      return;
    }
    // When no site key is configured (dev/CI), skip CAPTCHA and send a
    // dummy token — the backend also bypasses verification when its secret
    // key is unset, so the round-trip still works.
    const token = RECAPTCHA_SITE_KEY ? recaptchaToken : "dev-bypass";
    if (!token) {
      setError("Please complete the CAPTCHA verification.");
      return;
    }
    setIsLoading(true);
    setError("");
    try {
      await login(emailAddr.trim(), password, token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      recaptchaRef.current?.reset();
      setRecaptchaToken(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="dl-login">
      {/* Animated gradient background */}
      <div className="dl-login-bg">
        <div className="dl-login-orb dl-login-orb--1" />
        <div className="dl-login-orb dl-login-orb--2" />
        <div className="dl-login-orb dl-login-orb--3" />
      </div>

      {/* Centered card */}
      <div className="dl-login-card">
        {/* Logo */}
        <div className="dl-login-logo">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
            <rect width="40" height="40" rx="12" fill="url(#dl-logo-grad)" />
            <path
              d="M12 26 L17 18 L22 22 L28 14"
              stroke="#fff"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx="17" cy="18" r="2" fill="#fdba74" />
            <circle cx="28" cy="14" r="2" fill="#fdba74" />
            <defs>
              <linearGradient id="dl-logo-grad" x1="0" y1="0" x2="40" y2="40">
                <stop offset="0%" stopColor="#6366f1" />
                <stop offset="100%" stopColor="#4f46e5" />
              </linearGradient>
            </defs>
          </svg>
          <span className="dl-login-brand">DataLens</span>
        </div>

        <h1 className="dl-login-title">Welcome to DataLens</h1>
        <p className="dl-login-subtitle">Sign in to your analytics workspace</p>

        {error && <div className="dl-login-error">{error}</div>}

        <form
          onSubmit={handleLogin}
          style={{ display: "flex", flexDirection: "column", gap: 10 }}
        >
          <input
            type="email"
            placeholder="Email address"
            value={emailAddr}
            onChange={(e) => setEmailAddr(e.target.value)}
            autoComplete="email"
            style={{
              padding: "10px 14px",
              borderRadius: 8,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.07)",
              color: "#fff",
              fontSize: 14,
              outline: "none",
            }}
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            style={{
              padding: "10px 14px",
              borderRadius: 8,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.07)",
              color: "#fff",
              fontSize: 14,
              outline: "none",
            }}
          />

          {RECAPTCHA_SITE_KEY ? (
            <div style={{ display: "flex", justifyContent: "center", margin: "4px 0" }}>
              <ReCAPTCHA
                ref={recaptchaRef}
                sitekey={RECAPTCHA_SITE_KEY}
                theme="dark"
                onChange={(token: string | null) => setRecaptchaToken(token)}
                onExpired={() => setRecaptchaToken(null)}
              />
            </div>
          ) : (
            <div style={{ fontSize: 12, color: "rgba(255,255,255,0.4)", textAlign: "center" }}>
              CAPTCHA not configured (dev mode)
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading}
            style={{
              padding: "10px 14px",
              borderRadius: 8,
              background: "#6366f1",
              color: "#fff",
              fontWeight: 600,
              fontSize: 14,
              border: "none",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
            }}
          >
            {isLoading ? <Loader2 size={16} className="ts-spinner" /> : null}
            Sign In
          </button>
        </form>

        <p className="dl-login-footer">
          By continuing, you agree to our Terms of Service
        </p>
      </div>
    </div>
  );
}
