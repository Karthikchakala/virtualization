import React, { useState } from 'react';
import { X, Terminal, CheckCircle2, AlertTriangle, AlertCircle, Copy, Check } from 'lucide-react';
import { BenchmarkRun } from '../types';

interface EvidenceModalProps {
  run: BenchmarkRun | null;
  onClose: () => void;
}

export const EvidenceModal: React.FC<EvidenceModalProps> = ({ run, onClose }) => {
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<'stdout' | 'stderr' | 'metrics'>('stdout');

  if (!run) return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(JSON.stringify(run, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container" onClick={e => e.stopPropagation()}>
        {/* Modal Header */}
        <div className="modal-header">
          <div>
            <div className="modal-title-row">
              <span className={`status-pill status-${run.status}`}>
                {run.status.toUpperCase()}
              </span>
              <h2 className="modal-title font-mono">{run.benchmark}</h2>
              <span className="modal-env font-mono">[{run.environment.toUpperCase()}]</span>
            </div>
            <div className="modal-meta font-mono">
              Run ID: <span className="text-cyan">{run.run_id}</span> | 
              Exit Code: <span className={run.exit_code === 0 ? 'text-emerald' : 'text-rose'}>{run.exit_code}</span> | 
              Timestamp: {run.timestamp}
            </div>
          </div>

          <div className="modal-actions">
            <button className="btn-icon" onClick={handleCopy} title="Copy Raw JSON">
              {copied ? <Check size={16} color="var(--accent-emerald)" /> : <Copy size={16} />}
            </button>
            <button className="btn-icon" onClick={onClose} title="Close Modal">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Command Executed Bar */}
        <div className="command-box">
          <div className="command-label font-mono">
            <Terminal size={13} /> EXECUTED COMMAND:
          </div>
          <code className="command-text font-mono">{run.command}</code>
        </div>

        {/* If Unavailable, Show Reason Banner */}
        {run.status === 'unavailable' && (
          <div className="unavailable-banner">
            <AlertCircle size={18} color="var(--accent-amber)" />
            <div>
              <div className="banner-title">METRIC UNAVAILABLE IN THIS ENVIRONMENT</div>
              <div className="banner-desc">
                {run.metrics?.reason || run.stderr || 'Interface not accessible or permissions restricted. Zero values strictly not fabricated.'}
              </div>
            </div>
          </div>
        )}

        {/* Output Tabs */}
        <div className="modal-tabs">
          <button 
            className={`tab-btn ${activeTab === 'stdout' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('stdout')}
          >
            Terminal Stdout ({run.stdout ? `${run.stdout.length} chars` : 'empty'})
          </button>
          <button 
            className={`tab-btn ${activeTab === 'stderr' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('stderr')}
          >
            Stderr ({run.stderr ? `${run.stderr.length} chars` : 'clean'})
          </button>
          <button 
            className={`tab-btn ${activeTab === 'metrics' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('metrics')}
          >
            Parsed Telemetry JSON
          </button>
        </div>

        {/* Output Content */}
        <div className="modal-body">
          {activeTab === 'stdout' && (
            <pre className="terminal-view font-mono">
              {run.stdout || '<Process returned no standard output>'}
            </pre>
          )}

          {activeTab === 'stderr' && (
            <pre className={`terminal-view font-mono ${run.stderr ? 'terminal-stderr' : ''}`}>
              {run.stderr || '<Standard error was clean - no warnings or runtime faults>'}
            </pre>
          )}

          {activeTab === 'metrics' && (
            <pre className="terminal-view font-mono">
              {JSON.stringify(run.metrics || {}, null, 2)}
            </pre>
          )}
        </div>

        {/* Footer info */}
        <div className="modal-footer font-mono">
          <span>Schema: {run.schema_version || '2.0.0'}</span>
          <span>Rigorous Audit Guarantee: Raw output verifiable on host</span>
        </div>
      </div>
    </div>
  );
};
