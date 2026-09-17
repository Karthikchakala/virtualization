import React, { useState } from 'react';
import { FileSearch, Search, ExternalLink } from 'lucide-react';
import { BenchmarkRun } from '../types';

interface EvidencePageProps {
  runs: BenchmarkRun[];
  onViewEvidence: (run: BenchmarkRun) => void;
}

export const EvidencePage: React.FC<EvidencePageProps> = ({
  runs,
  onViewEvidence
}) => {
  const [search, setSearch] = useState('');
  const [filterEnv, setFilterEnv] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');

  const filtered = runs.filter(r => {
    const matchesEnv = filterEnv === 'all' || r.environment === filterEnv;
    const matchesStatus = filterStatus === 'all' || r.status === filterStatus;
    const q = search.toLowerCase();
    const matchesSearch = !q ||
      r.run_id.toLowerCase().includes(q) ||
      r.benchmark.toLowerCase().includes(q) ||
      r.command.toLowerCase().includes(q) ||
      (r.stdout && r.stdout.toLowerCase().includes(q));

    return matchesEnv && matchesStatus && matchesSearch;
  });

  return (
    <div className="page-container">
      {/* Page Header */}
      <div className="card">
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <FileSearch size={22} color="var(--accent-primary)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Forensic Evidence & Run Traceability</h2>
              <div className="card-subtitle">
                Auditable Record of Benchmark Invocations, Terminal Outputs, and Exit Codes
              </div>
            </div>
          </div>
        </div>
        <p style={{ marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          Every metric in this benchmark suite links directly to a persistent, verifiable execution artifact.
          Inspect the exact command line invocation, standard output, standard error, and exit codes for any run.
        </p>
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ padding: '0.75rem 1rem' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <div className="search-box" style={{ width: '260px' }}>
              <Search size={14} className="search-icon" />
              <input
                type="text"
                placeholder="Search run ID, command, output..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="search-input"
                style={{ width: '100%' }}
              />
            </div>

            <select
              value={filterEnv}
              onChange={e => setFilterEnv(e.target.value)}
              className="filter-select"
            >
              <option value="all">All Environments</option>
              <option value="host">Host</option>
              <option value="kvm">KVM</option>
              <option value="virtualbox">VirtualBox</option>
              <option value="lxc">LXC</option>
            </select>

            <select
              value={filterStatus}
              onChange={e => setFilterStatus(e.target.value)}
              className="filter-select"
            >
              <option value="all">All Statuses</option>
              <option value="success">Success</option>
              <option value="unavailable">Unavailable</option>
              <option value="failed">Failed</option>
            </select>
          </div>

          <span className="text-secondary" style={{ fontSize: '0.75rem' }}>
            Showing {filtered.length} of {runs.length} runs
          </span>
        </div>
      </div>

      {/* Runs Table */}
      <div className="card">
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Environment</th>
                <th>Benchmark</th>
                <th>Run ID</th>
                <th>Status</th>
                <th>Exit Code</th>
                <th>Command</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 100).map((r, idx) => (
                <tr key={idx}>
                  <td className="font-semibold uppercase">{r.environment}</td>
                  <td className="font-mono text-xs">{r.benchmark}</td>
                  <td className="font-mono text-xs text-secondary">{r.run_id}</td>
                  <td>
                    <span className={`status-pill status-${r.status}`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="font-mono">{r.exit_code}</td>
                  <td className="font-mono text-xs text-secondary" style={{ maxWidth: '320px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.command}
                  </td>
                  <td>
                    <button
                      className="btn-evidence-sm"
                      onClick={() => onViewEvidence(r)}
                    >
                      <ExternalLink size={12} />
                      <span>Inspect</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length > 100 && (
          <div style={{ marginTop: '0.75rem', textAlign: 'center', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Showing first 100 matching runs. Use search filters above to narrow results.
          </div>
        )}
      </div>
    </div>
  );
};
