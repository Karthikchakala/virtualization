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
      <div className="modal-container log-modal-width" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <Terminal size={18} color="var(--accent-cyan)" />
            <div>
              <div className="modal-title">Sanitized Execution Logs</div>
              <div className="modal-subtitle font-mono">Job ID: {jobId} | Status: {logs?.status || 'loading'}</div>
            </div>
          </div>
          <div className="modal-actions">
            <button className="btn-icon" onClick={fetchLogs} title="Refresh Logs">
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            </button>
            <button className="btn-icon" onClick={handleCopy} title="Copy to Clipboard">
              {copied ? <Check size={15} color="var(--accent-emerald)" /> : <Copy size={15} />}
            </button>
            <button className="btn-icon" onClick={onClose} title="Close">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="modal-body">
          {error && <div className="notice-error">{error}</div>}

          {logs && (
            <div className="terminal-log-viewer font-mono">
              {logs.stdout ? (
                <pre className="terminal-stdout">{logs.stdout}</pre>
              ) : (
                <div className="terminal-empty">No standard output recorded yet.</div>
              )}

              {logs.stderr && (
                <div className="terminal-stderr-container">
                  <div className="stderr-header">=== STANDARD ERROR ===</div>
                  <pre className="terminal-stderr">{logs.stderr}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
