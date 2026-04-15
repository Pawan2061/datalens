import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, LogOut, RefreshCw, Clock, ShieldX } from 'lucide-react';
import { useAuthStore } from '../store/authStore';

export default function PendingApprovalPage() {
  const navigate = useNavigate();
  const { user, refreshUser, logout } = useAuthStore();
  const [isChecking, setIsChecking] = useState(false);
  const [checkMessage, setCheckMessage] = useState('');

  const isSuspended = user?.status === 'suspended';

  const handleCheckStatus = async () => {
    setIsChecking(true);
    setCheckMessage('');
    try {
      await refreshUser();
      // Re-read user from store after refresh
      const updatedUser = useAuthStore.getState().user;
      if (updatedUser?.status === 'active') {
        navigate('/', { replace: true });
      } else {
        setCheckMessage('Your account is still ' + (updatedUser?.status || 'pending') + '. Please check back later.');
      }
    } catch {
      setCheckMessage('Unable to check status. Please try again.');
    } finally {
      setIsChecking(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="dl-login">
      {/* Animated gradient background */}
      <div className="dl-login-bg">
        <div className="dl-login-orb dl-login-orb--1" />
        <div className="dl-login-orb dl-login-orb--2" />
        <div className="dl-login-orb dl-login-orb--3" />
      </div>

      <div className="dl-login-card" style={{ textAlign: 'center' }}>
        {/* Avatar */}
        {user?.avatar_url ? (
          <img
            src={user.avatar_url}
            alt={user.name}
            style={{
              width: 72,
              height: 72,
              borderRadius: '50%',
              margin: '0 auto 16px',
              border: '3px solid rgba(255,255,255,0.15)',
              display: 'block',
            }}
          />
        ) : (
          <div style={{
            width: 72,
            height: 72,
            borderRadius: '50%',
            margin: '0 auto 16px',
            background: 'linear-gradient(135deg, #6366f1, #4f46e5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 28,
            fontWeight: 700,
            color: '#fff',
          }}>
            {user?.name?.charAt(0)?.toUpperCase() || '?'}
          </div>
        )}

        <h2 style={{ color: '#fff', fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
          {user?.name || 'User'}
        </h2>
        <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: 13, marginBottom: 28 }}>
          {user?.email}
        </p>

        {/* Status icon */}
        <div style={{
          width: 56,
          height: 56,
          borderRadius: '50%',
          background: isSuspended ? 'rgba(239,68,68,0.15)' : 'rgba(234,179,8,0.15)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto 20px',
        }}>
          {isSuspended ? (
            <ShieldX size={28} style={{ color: '#f87171' }} />
          ) : (
            <Clock size={28} style={{ color: '#fbbf24' }} />
          )}
        </div>

        <h1 style={{ color: '#fff', fontSize: 22, fontWeight: 800, marginBottom: 8, letterSpacing: '-0.02em' }}>
          {isSuspended ? 'Account Suspended' : 'Pending Approval'}
        </h1>
        <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: 14, lineHeight: 1.6, marginBottom: 32 }}>
          {isSuspended
            ? 'Your account has been suspended. Please contact an administrator for assistance.'
            : 'An administrator will review your access request shortly. You will be able to use DataLens once approved.'}
        </p>

        {checkMessage && (
          <div style={{
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 10,
            padding: '10px 14px',
            fontSize: 13,
            color: 'rgba(255,255,255,0.6)',
            marginBottom: 16,
          }}>
            {checkMessage}
          </div>
        )}

        <button
          className="dl-login-submit"
          onClick={handleCheckStatus}
          disabled={isChecking}
          style={{ marginBottom: 12 }}
        >
          {isChecking ? (
            <><Loader2 size={16} className="ts-spinner" /> Checking...</>
          ) : (
            <><RefreshCw size={16} /> Check Status</>
          )}
        </button>

        <button
          className="dl-login-email-btn"
          onClick={handleLogout}
        >
          <LogOut size={16} />
          Sign Out
        </button>
      </div>
    </div>
  );
}
