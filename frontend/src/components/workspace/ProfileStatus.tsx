import { useState, useEffect, useCallback, useRef } from 'react';
import { Brain, RefreshCw, AlertCircle, Loader2 } from 'lucide-react';
import {
  generateProfile,
  getProfileStatus,
  createProfileEventSource,
  deleteProfile,
} from '../../services/api';
import ProfileViewer from './ProfileViewer';

interface ProfileStatusProps {
  workspaceId: string;
  connectionId: string;
  connectionName: string;
}

type Status = 'none' | 'generating' | 'ready' | 'failed' | 'checking';

export default function ProfileStatus({
  workspaceId,
  connectionId,
  connectionName,
}: ProfileStatusProps) {
  const [status, setStatus] = useState<Status>('checking');
  const [progress, setProgress] = useState('');
  const [error, setError] = useState('');
  const [viewerOpen, setViewerOpen] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const checkedRef = useRef('');

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Stop any active polling
  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  // Start polling when profile is generating (handles Cloud Run multi-instance + page navigation)
  const startPolling = useCallback(() => {
    stopPolling();
    setStatus('generating');
    setProgress('Generating data intelligence profile...');

    pollingRef.current = setInterval(() => {
      getProfileStatus(workspaceId, connectionId)
        .then((res) => {
          if (res.status === 'ready') {
            setStatus('ready');
            setProgress('');
            stopPolling();
          } else if (res.status === 'failed') {
            setStatus('failed');
            setError(res.error_message || 'Profile generation failed');
            stopPolling();
          }
          // else still generating — keep polling
        })
        .catch(() => { /* keep polling */ });
    }, 4000); // Poll every 4 seconds
  }, [workspaceId, connectionId, stopPolling]);

  // Check profile status on mount / connection change
  useEffect(() => {
    if (!workspaceId || !connectionId || connectionId === 'mock') return;
    // Avoid re-checking same connection
    const key = `${workspaceId}:${connectionId}`;
    if (checkedRef.current === key) return;
    checkedRef.current = key;

    setStatus('checking');
    getProfileStatus(workspaceId, connectionId)
      .then((res) => {
        const s = res.status as Status;
        if (s === 'ready' || s === 'failed') {
          setStatus(s);
          if (s === 'failed') setError(res.error_message || 'Unknown error');
        } else if (s === 'generating') {
          // Profile is being generated (likely triggered during workspace creation).
          // Start polling since the SSE queue may be on a different instance.
          startPolling();
        } else {
          setStatus('none');
        }
      })
      .catch(() => {
        setStatus('none');
      });

    return () => {
      stopPolling();
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [workspaceId, connectionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const triggerGenerate = useCallback(async () => {
    if (!workspaceId || !connectionId) return;

    setStatus('generating');
    setProgress('Starting data analysis...');
    setError('');

    try {
      await generateProfile(workspaceId, connectionId);

      // Listen to SSE progress
      if (esRef.current) esRef.current.close();
      const es = createProfileEventSource(workspaceId, connectionId);
      esRef.current = es;

      es.addEventListener('thinking', (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          setProgress(data.content || data.step || '');
        } catch { /* ignore */ }
      });

      es.addEventListener('done', () => {
        setStatus('ready');
        setProgress('');
        stopPolling();
        es.close();
        esRef.current = null;
      });

      es.addEventListener('error', (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          setError(data.message || 'Profile generation failed');
        } catch { /* ignore */ }
        setStatus('failed');
        stopPolling();
        es.close();
        esRef.current = null;
      });

      es.onerror = () => {
        // SSE connection lost — fall back to polling
        es.close();
        esRef.current = null;
        startPolling();
      };
    } catch {
      // POST to generate might have succeeded even if SSE failed.
      // Fall back to polling to check.
      startPolling();
    }
  }, [workspaceId, connectionId, startPolling]);

  const handleRefresh = useCallback(async () => {
    try {
      await deleteProfile(workspaceId, connectionId);
    } catch { /* ignore */ }
    checkedRef.current = ''; // Reset so it re-checks
    triggerGenerate();
  }, [workspaceId, connectionId, triggerGenerate]);

  if (connectionId === 'mock' || status === 'checking') {
    return null;
  }

  return (
    <div className="profile-status" data-status={status}>
      {status === 'none' && (
        <>
          <button
            className="profile-status-view"
            onClick={triggerGenerate}
            title="Generate data intelligence profile"
          >
            <Brain size={14} className="profile-status-icon" />
            <span className="profile-status-text">Generate Profile</span>
          </button>
        </>
      )}

      {status === 'generating' && (
        <>
          <Loader2 size={14} className="profile-status-icon spinning" />
          <span className="profile-status-text">{progress || 'Analyzing data...'}</span>
        </>
      )}

      {status === 'ready' && (
        <>
          <button
            className="profile-status-view"
            onClick={() => setViewerOpen(true)}
            title="View data profile"
          >
            <Brain size={14} className="profile-status-icon" />
            <span className="profile-status-text">Data profiled</span>
          </button>
          <button
            className="profile-status-refresh"
            onClick={handleRefresh}
            title="Re-analyze data"
          >
            <RefreshCw size={12} />
          </button>
        </>
      )}

      {status === 'failed' && (
        <>
          <AlertCircle size={14} className="profile-status-icon" />
          <span className="profile-status-text" title={error}>
            Profile failed
          </span>
          <button
            className="profile-status-refresh"
            onClick={handleRefresh}
            title="Retry"
          >
            <RefreshCw size={12} />
          </button>
        </>
      )}

      <ProfileViewer
        isOpen={viewerOpen}
        onClose={() => setViewerOpen(false)}
        workspaceId={workspaceId}
        connectionId={connectionId}
        connectionName={connectionName}
      />
    </div>
  );
}
