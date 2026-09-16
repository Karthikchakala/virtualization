import React, { useState } from 'react';
import { 
  FileCode2, 
  Download, 
  Database, 
  FileText, 
  Check, 
  Copy, 
  Terminal,
  Layers
} from 'lucide-react';
import { BenchmarkRun } from '../types';

interface RawDataPageProps {
  runs: BenchmarkRun[];
  isQuickMode?: boolean;
}

export const RawDataPage: React.FC<RawDataPageProps> = ({
  runs,
  isQuickMode = true
}) => {
  const [copied, setCopied] = useState(false);
  const [activeFile, setActiveFile] = useState<'runs.json' | 'runs.csv' | 'summary'>('runs.json');

  const datasetList = [
    { name: 'runs.json', size: `${(JSON.stringify(runs).length / 1024).toFixed(1)} KB`, format: 'JSON', desc: 'Complete versioned benchmark runs array' },
    { name: 'runs.csv', size: '~17.5 KB', format: 'CSV', desc: 'Flattened tabular benchmark runs for R/Python analysis' },
    { name: 'cpu_deterministic.csv', size: '~5.5 KB', format: 'CSV', desc: 'CPU matrix multiplication timing and FLOPs' },
    { name: 'memory_deterministic.csv', size: '~4.2 KB', format: 'CSV', desc: 'Memory read/write throughput and RSS' },
    { name: 'startup_lifecycle.csv', size: '~0.9 KB', format: 'CSV', desc: 'Phased hypervisor boot and readiness times' },
    { name: 'network_ping.csv', size: '~0.9 KB', format: 'CSV', desc: 'ICMP round-trip latency and packet loss' },
    { name: 'app_latency.csv', size: '~0.8 KB', format: 'CSV', desc: 'HTTP health endpoint connect, TTFB, and duration' },
    { name: 'syscall_deterministic.csv', size: '~2.2 KB', format: 'CSV', desc: 'Syscall latency and throughput breakdown' }
  ];

  const handleDownload = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(runs, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `cc2_benchmark_runs_${isQuickMode ? 'quick' : 'full'}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(JSON.stringify(runs, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="page-container">
      {/* Raw Data Header */}
      <div className="card" style={{ marginBottom: '1.5rem', borderLeft: '4px solid var(--accent-amber)' }}>
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <FileCode2 size={24} color="var(--accent-amber)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Raw Datasets & Processed Exports</h2>
              <span className="text-secondary font-mono" style={{ fontSize: '0.8125rem' }}>
                Reproducible Open Science Data Pipeline • CSV & JSON Format Exports
              </span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn-secondary-sm font-mono" onClick={handleCopy}>
              {copied ? <Check size={14} color="var(--accent-emerald)" /> : <Copy size={14} />}
              <span>{copied ? 'Copied' : 'Copy JSON'}</span>
            </button>
            <button className="btn-primary-sm font-mono" onClick={handleDownload}>
              <Download size={14} />
              <span>Download Dataset</span>
            </button>
          </div>
        </div>
        <p style={{ marginTop: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          All benchmark outputs are persistently serialized in machine-readable JSON and CSV formats under <code>results/processed/</code>. 
          Datasets support standalone exploratory analysis in Jupyter, R, Pandas, and external statistical tools.
        </p>
      </div>

      {/* Dataset Files Grid */}
      <div className="section-header">
        <h3 className="section-title">Available Data Files (results/processed/)</h3>
        <span className="section-subtitle">Compiled during benchmark runner execution</span>
      </div>

      <div className="grid-cols-4">
        {datasetList.map((file, idx) => (
          <div key={idx} className="dataset-file-card font-mono">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="file-name text-cyan font-bold">{file.name}</span>
              <span className="file-format-badge">{file.format}</span>
            </div>
            <div className="file-size text-secondary" style={{ fontSize: '0.75rem', margin: '0.5rem 0' }}>
              Size: {file.size}
            </div>
            <p className="file-desc text-muted" style={{ fontSize: '0.75rem' }}>
              {file.desc}
            </p>
          </div>
        ))}
      </div>

      {/* Raw JSON Preview */}
      <div className="section-header" style={{ marginTop: '2.5rem' }}>
        <h3 className="section-title">In-Memory Dataset Inspector</h3>
        <span className="section-subtitle">Showing live parsed records ({runs.length} runs indexed)</span>
      </div>

      <div className="card font-mono">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <span className="text-secondary" style={{ fontSize: '0.8125rem' }}>
            Live Schema v2.0 Dataset ({isQuickMode ? 'Quick Mode Active' : 'Full Rigor Active'})
          </span>
          <span className="text-muted" style={{ fontSize: '0.75rem' }}>
            Showing top records
          </span>
        </div>
        <pre className="terminal-view font-mono" style={{ maxHeight: '420px' }}>
          {runs.length > 0 
            ? JSON.stringify(runs.slice(0, 3), null, 2)
            : '[]  // Dataset is empty. Run ./benchmark/runner.sh to populate benchmark runs.'}
        </pre>
      </div>
    </div>
  );
};
