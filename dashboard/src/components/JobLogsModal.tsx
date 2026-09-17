import React, { useState, useEffect } from 'react';
import { X, Terminal, RefreshCw, Copy, Check } from 'lucide-react';
import { api, JobLogsResponse } from '../api';

interface JobLogsModalProps {
  jobId: string | null;
  onClose: () => void;
}

export const JobLogsModal: React.FC<JobLogsModalProps> = ({ jobId, onClose }) => {
  const [logs, setLogs] = useState<JobLogsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchLogs = async () => {
    if (!jobId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getJobLogs(jobId);
      setLogs(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch logs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (jobId) {
      fetchLogs();
    }
  }, [jobId]);

  if (!jobId) return null;

  const handleCopy = () => {
    if (!logs) return;
    const fullText = `=== STDOUT ===\n${logs.stdout}\n\n=== STDERR ===\n${logs.stderr}`;
    navigator.clipboard.writeText(fullText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div className="modal-title">Execution Logs</div>
            <div className="modal-meta font-mono">Job ID: {jobId} • Status: {logs?.status || 'loading'}</div>
          </div>
          <div className="modal-actions">
            <button className="btn-icon" onClick={fetchLogs} title="Refresh Logs">
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button className="btn-icon" onClick={handleCopy} title="Copy to Clipboard">
              {copied ? <Check size={14} color="var(--status-success-text)" /> : <Copy size={14} />}
            </button>
            <button className="btn-icon" onClick={onClose} title="Close">
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="modal-body">
          {error && (
            <div className="control-alert control-alert-error" style={{ marginBottom: '1rem' }}>
              {error}
            </div>
          )}

          {logs && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <div className="command-label">
                  <Terminal size={12} /> Standard Output
                </div>
                {logs.stdout ? (
                  <pre className="terminal-view font-mono">{logs.stdout}</pre>
                ) : (
                  <div style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>No standard output recorded.</div>
                )}
              </div>

              {logs.stderr && (
                <div>
                  <div className="command-label" style={{ color: 'var(--status-danger-text)' }}>
                    Standard Error
                  </div>
                  <pre className="terminal-view font-mono terminal-stderr">{logs.stderr}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
