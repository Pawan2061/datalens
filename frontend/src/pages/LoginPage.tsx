import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { useAuthStore } from '../store/authStore';
import type { FormEvent } from 'react';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const GITHUB_CLIENT_ID = import.meta.env.VITE_GITHUB_CLIENT_ID || '';

export default function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login, loginWithGoogle, loginWithGitHub, isAuthenticated, user } = useAuthStore();
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);
  const [isGitHubLoading, setIsGitHubLoading] = useState(false);
  const [isEmailLoading, setIsEmailLoading] = useState(false);
  const [emailName, setEmailName] = useState('');
  const [emailAddr, setEmailAddr] = useState('');
  const [error, setError] = useState('');

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated && user) {
      if (user.status === 'pending' || user.status === 'suspended') {
        navigate('/pending', { replace: true });
      } else {
        navigate('/', { replace: true });
      }
    }
  }, [isAuthenticated, user, navigate]);

  // Handle GitHub OAuth callback
  useEffect(() => {
    const code = searchParams.get('code');
    if (code && !isGitHubLoading) {
      setIsGitHubLoading(true);
      setError('');
      window.history.replaceState({}, '', '/login');
      loginWithGitHub(code)
        .catch((err) => {
          setError(err instanceof Error ? err.message : 'GitHub sign-in failed');
        })
        .finally(() => {
          setIsGitHubLoading(false);
        });
    }
  }, [searchParams, loginWithGitHub, isGitHubLoading]);

  // Initialize Google Sign-In
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.onload = () => {
      window.google?.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleGoogleResponse,
      });
    };
    document.head.appendChild(script);
    return () => { document.head.removeChild(script); };
  }, []);

  const handleGoogleResponse = async (response: { credential: string }) => {
    setIsGoogleLoading(true);
    setError('');
    try {
      await loginWithGoogle(response.credential);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Google sign-in failed');
    } finally {
      setIsGoogleLoading(false);
    }
  };

  const handleGoogleClick = () => {
    if (GOOGLE_CLIENT_ID && window.google) {
      window.google.accounts.id.prompt();
    } else {
      setError('Google Sign-In is not configured yet. Contact admin.');
    }
  };

  const handleEmailLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (!emailName.trim() || !emailAddr.trim()) {
      setError('Please enter your name and email.');
      return;
    }
    setIsEmailLoading(true);
    setError('');
    try {
      await login(emailName.trim(), emailAddr.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setIsEmailLoading(false);
    }
  };

  const handleGitHubClick = () => {
    if (!GITHUB_CLIENT_ID) {
      setError('GitHub Sign-In is not configured yet. Contact admin.');
      return;
    }
    const redirectUri = `${window.location.origin}/login`;
    const url = `https://github.com/login/oauth/authorize?client_id=${GITHUB_CLIENT_ID}&scope=user:email&redirect_uri=${encodeURIComponent(redirectUri)}`;
    window.location.href = url;
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
            <path d="M12 26 L17 18 L22 22 L28 14" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
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

        {/* Email login form */}
        <form onSubmit={handleEmailLogin} style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 16 }}>
          <input
            type="text"
            placeholder="Your name"
            value={emailName}
            onChange={e => setEmailName(e.target.value)}
            style={{
              padding: '10px 14px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.15)',
              background: 'rgba(255,255,255,0.07)', color: '#fff', fontSize: 14, outline: 'none',
            }}
          />
          <input
            type="email"
            placeholder="Email address"
            value={emailAddr}
            onChange={e => setEmailAddr(e.target.value)}
            style={{
              padding: '10px 14px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.15)',
              background: 'rgba(255,255,255,0.07)', color: '#fff', fontSize: 14, outline: 'none',
            }}
          />
          <button
            type="submit"
            disabled={isEmailLoading}
            style={{
              padding: '10px 14px', borderRadius: 8, background: '#6366f1', color: '#fff',
              fontWeight: 600, fontSize: 14, border: 'none', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            }}
          >
            {isEmailLoading ? <Loader2 size={16} className="ts-spinner" /> : null}
            Sign in with Email
          </button>
        </form>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '4px 0 12px', color: 'rgba(255,255,255,0.3)', fontSize: 12 }}>
          <div style={{ flex: 1, height: 1, background: 'rgba(255,255,255,0.1)' }} />
          or
          <div style={{ flex: 1, height: 1, background: 'rgba(255,255,255,0.1)' }} />
        </div>

        {/* GitHub loading state (during OAuth callback) */}
        {isGitHubLoading ? (
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <Loader2 size={24} className="ts-spinner" style={{ color: '#fff', margin: '0 auto 12px' }} />
            <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: 14 }}>Signing in with GitHub...</p>
          </div>
        ) : (
          <>
            {/* Google SSO */}
            {GOOGLE_CLIENT_ID && (
              <button
                className="dl-login-google"
                onClick={handleGoogleClick}
                disabled={isGoogleLoading}
              >
                {isGoogleLoading ? (
                  <Loader2 size={18} className="ts-spinner" />
                ) : (
                  <svg width="18" height="18" viewBox="0 0 18 18">
                    <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
                    <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
                    <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
                    <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
                  </svg>
                )}
                Continue with Google
              </button>
            )}

            {/* GitHub SSO */}
            {GITHUB_CLIENT_ID && (
              <button
                className="dl-login-github"
                onClick={handleGitHubClick}
                style={{ marginTop: 12 }}
              >
                <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor">
                  <path fillRule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
                </svg>
                Continue with GitHub
              </button>
            )}
          </>
        )}

        <p className="dl-login-footer">
          By continuing, you agree to our Terms of Service
        </p>
      </div>
    </div>
  );
}

// Type augmentation for Google Sign-In
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: { client_id: string; callback: (response: { credential: string }) => void }) => void;
          prompt: () => void;
        };
      };
    };
  }
}
