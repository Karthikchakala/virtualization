import React, { useState } from 'react';
import { FileCode2, Download, Copy, Check } from 'lucide-react';
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

  const datasetList = [
    { name: 'runs.json', size: `${(JSON.stringify(runs).length / 1024).toFixed(1)} KB`, format: 'JSON', desc: 'Complete versioned benchmark runs array with metrics and telemetry' },
    { name: 'cpu_deterministic.json', size: '~18.5 KB', format: 'JSON', desc: 'CPU matrix multiplication timing, user/sys split, and checksum validation' },
    { name: 'memory_deterministic.json', size: '~14.2 KB', format: 'JSON', desc: 'Sequential and stride memory access bandwidth and resident memory' },
    { name: 'startup_lifecycle.json', size: '~6.8 KB', format: 'JSON', desc: 'Phased hypervisor boot, network ready, and HTTP application ready timings' },
    { name: 'network_ping.json', size: '~5.9 KB', format: 'JSON', desc: 'ICMP round-trip latency, min/max/stddev, and packet loss metrics' },
    { name: 'syscall_deterministic.json', size: '~12.2 KB', format: 'JSON', desc: 'System call latency and strace kernel profile breakdown' },
    { name: 'scheduling_deterministic.json', size: '~8.4 KB', format: 'JSON', desc: 'Two-way pipe context switch latency and switches per second' },
    { name: 'isolation_audit.json', size: '~4.5 KB', format: 'JSON', desc: 'Virtualization detection and namespace boundary verification records' }
  ];

  const handleDownload = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(runs, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `virtualization_lab_runs_${isQuickMode ? 'quick' : 'full'}.json`);
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
      {/* Page Header */}
      <div className="card">
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <FileCode2 size={22} color="var(--accent-primary)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Raw Datasets & Processed Exports</h2>
              <div className="card-subtitle">
                Machine-Readable JSON Datasets for Independent Verification and Analysis
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <button className="btn-secondary-sm" onClick={handleCopy}>
              {copied ? <Check size={13} color="var(--status-success-text)" /> : <Copy size={13} />}
              <span>{copied ? 'Copied' : 'Copy JSON'}</span>
            </button>
            <button className="btn-primary" style={{ padding: '0.3125rem 0.75rem', fontSize: '0.75rem' }} onClick={handleDownload}>
              <Download size={13} />
              <span>Download JSON</span>
            </button>
          </div>
        </div>
        <p style={{ marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          All recorded benchmark runs are published in standardized JSON schemas.
          These datasets include execution commands, exit codes, terminal output streams, and parsed numeric metrics.
        </p>
      </div>

      {/* Available Datasets Table */}
      <div className="card">
        <div className="card-header-row">
          <h3 className="card-title">Available Datasets</h3>
          <span className="text-secondary" style={{ fontSize: '0.75rem' }}>{runs.length} total records</span>
        </div>

        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Dataset Name</th>
                <th>Format</th>
                <th>Estimated Size</th>
                <th>Description</th>
                <th>Export</th>
              </tr>
            </thead>
            <tbody>
              {datasetList.map(ds => (
                <tr key={ds.name}>
                  <td className="font-mono font-semibold">{ds.name}</td>
                  <td>
                    <span className="status-pill status-pass">{ds.format}</span>
                  </td>
                  <td className="font-mono text-xs">{ds.size}</td>
                  <td className="text-secondary">{ds.desc}</td>
                  <td>
                    <button
                      className="btn-secondary-sm"
                      onClick={handleDownload}
                    >
                      <Download size={12} />
                      <span>Export</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* JSON Viewer */}
      <div className="card">
        <div className="card-header-row">
          <h3 className="card-title">JSON Data Preview</h3>
          <span className="text-secondary font-mono text-xs">First 3 runs shown</span>
        </div>
        <pre className="terminal-view font-mono" style={{ maxHeight: '360px' }}>
          {JSON.stringify(runs.slice(0, 3), null, 2)}
        </pre>
      </div>
    </div>
  );
};
