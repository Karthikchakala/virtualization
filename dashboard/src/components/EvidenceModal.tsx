import React, { useState } from 'react';
import { X, Terminal, Copy, Check, Info } from 'lucide-react';
import { BenchmarkRun } from '../types';

interface EvidenceModalProps {
  run: BenchmarkRun | null;
  onClose: () => void;
}

export const EvidenceModal: React.FC<EvidenceModalProps> = ({ run, onClose }) => {
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<'stdout' | 'stderr' | 'metrics' | 'meta'>('stdout');

  if (!run) return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(JSON.stringify(run, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const workloadSha = run.metrics?.binary_sha256 || run.metrics?.sha256 || run.metrics?.workload_sha256 || run.metrics?.workload_output?.checksum || 'N/A';

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container" onClick={e => e.stopPropagation()}>
        {/* Modal Header */}
        <div className="modal-header">
          <div>
            <div className="modal-title-row">
              <span className={`status-pill status-${run.status}`}>
                {run.status}
              </span>
              <h2 className="modal-title font-mono">{run.benchmark}</h2>
              <span className="font-mono text-xs uppercase" style={{ color: 'var(--text-secondary)' }}>
                [{run.environment}]
              </span>
            </div>
            <div className="modal-meta font-mono">
              Run ID: {run.run_id} • Exit code: {run.exit_code} • {run.timestamp}
            </div>
          </div>

          <div className="modal-actions">
            <button className="btn-icon" onClick={handleCopy} title="Copy Raw JSON">
              {copied ? <Check size={15} color="var(--status-success-text)" /> : <Copy size={15} />}
            </button>
            <button className="btn-icon" onClick={onClose} title="Close Modal">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Command Executed Bar */}
        <div className="command-box">
          <div className="command-label">
            <Terminal size={12} /> Command
          </div>
          <div className="command-text font-mono">{run.command}</div>
        </div>

        {/* Output Tabs */}
        <div className="modal-tabs">
          <button
            className={`tab-btn ${activeTab === 'stdout' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('stdout')}
          >
            Standard Output ({run.stdout ? `${run.stdout.length} B` : 'empty'})
          </button>
          <button
            className={`tab-btn ${activeTab === 'stderr' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('stderr')}
          >
            Standard Error ({run.stderr ? `${run.stderr.length} B` : 'clean'})
          </button>
          <button
            className={`tab-btn ${activeTab === 'metrics' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('metrics')}
          >
            Metrics
          </button>
          <button
            className={`tab-btn ${activeTab === 'meta' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('meta')}
          >
            Run Metadata
          </button>
        </div>

        {/* Output Content */}
        <div className="modal-body">
          {activeTab === 'stdout' && (
            <pre className="terminal-view font-mono">
              {run.stdout || '(Process returned no standard output)'}
            </pre>
          )}

          {activeTab === 'stderr' && (
            <pre className={`terminal-view font-mono ${run.stderr ? 'terminal-stderr' : ''}`}>
              {run.stderr || '(Standard error was clean)'}
            </pre>
          )}

          {activeTab === 'metrics' && (
            <pre className="terminal-view font-mono">
              {JSON.stringify(run.metrics || {}, null, 2)}
            </pre>
          )}

          {activeTab === 'meta' && (
            <div className="spec-table font-mono" style={{ fontSize: '0.8125rem' }}>
              <div className="spec-row">
                <span className="spec-key">Run ID</span>
                <span className="spec-val">{run.run_id}</span>
              </div>
              <div className="spec-row">
                <span className="spec-key">Experiment ID</span>
                <span className="spec-val">{run.experiment_id || 'exp-cc2-host'}</span>
              </div>
              <div className="spec-row">
                <span className="spec-key">Environment</span>
                <span className="spec-val uppercase">{run.environment}</span>
              </div>
              <div className="spec-row">
                <span className="spec-key">Benchmark</span>
                <span className="spec-val">{run.benchmark}</span>
              </div>
              <div className="spec-row">
                <span className="spec-key">Timestamp</span>
                <span className="spec-val">{run.timestamp}</span>
              </div>
              <div className="spec-row">
                <span className="spec-key">Exit Code</span>
                <span className="spec-val">{run.exit_code}</span>
              </div>
              <div className="spec-row">
                <span className="spec-key">Workload Checksum / SHA256</span>
                <span className="spec-val">{workloadSha}</span>
              </div>
              <div className="spec-row">
                <span className="spec-key">Schema Version</span>
                <span className="spec-val">{run.schema_version || '2.0.0'}</span>
              </div>
            </div>
          )}
        </div>

        {/* Footer info */}
        <div className="modal-footer font-mono">
          <span>Schema: {run.schema_version || '2.0.0'}</span>
          <span>Status: {run.status}</span>
        </div>
      </div>
    </div>
  );
};
