import React, { useState } from 'react';
import { 
  FileSearch, 
  Terminal, 
  CheckCircle2, 
  AlertTriangle, 
  AlertCircle, 
  Search, 
  Filter,
  ArrowUpDown 
} from 'lucide-react';
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
      {/* Evidence Header */}
      <div className="card" style={{ marginBottom: '1.5rem', borderLeft: '4px solid var(--accent-cyan)' }}>
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <FileSearch size={24} color="var(--accent-cyan)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Forensic Evidence & Run Traceability Engine</h2>
              <span className="text-secondary font-mono" style={{ fontSize: '0.8125rem' }}>
                Auditable Terminal Output • Command Verification • Non-Fabricated Results
              </span>
            </div>
          </div>
          <span className="badge-verified font-mono">
            100% Traceable
          </span>
        </div>
        <p style={{ marginTop: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          Every single metric in this benchmark suite links directly to a persistent, cryptographically verifiable raw execution artifact. 
          Inspect the exact shell command, terminal standard output, standard error, exit code, and parsed JSON payload for any test.
        </p>
      </div>

      {/* Filter Toolbar */}
      <div className="evidence-toolbar">
        <div className="search-box" style={{ flex: 1 }}>
          <Search size={14} className="search-icon" />
          <input
            type="text"
            placeholder="Search runs by ID, benchmark name, command, or output..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="search-input font-mono"
          />
        </div>

        <div className="control-pill-group">
          <span className="control-label">ENV:</span>
          {['all', 'host', 'kvm', 'virtualbox', 'lxc'].map(e => (
            <button
              key={e}
              className={`pill-btn ${filterEnv === e ? 'pill-btn-active' : ''}`}
              onClick={() => setFilterEnv(e)}
            >
              {e.toUpperCase()}
            </button>
          ))}
        </div>

        <div className="control-pill-group">
          <span className="control-label">STATUS:</span>
          {['all', 'success', 'unavailable', 'failed'].map(s => (
            <button
              key={s}
              className={`pill-btn ${filterStatus === s ? 'pill-btn-active' : ''}`}
              onClick={() => setFilterStatus(s)}
            >
              {s.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Evidence Table */}
      <div className="table-wrapper" style={{ marginTop: '1.5rem' }}>
        <table className="data-table font-mono">
          <thead>
            <tr>
              <th>Status</th>
              <th>Environment</th>
              <th>Benchmark Domain</th>
              <th>Run ID</th>
              <th>Timestamp</th>
              <th>Exit Code</th>
              <th>Command Snippet</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                  No benchmark runs matched your filter criteria.
                </td>
              </tr>
            ) : (
              filtered.map((r, idx) => (
                <tr key={idx}>
                  <td>
                    <span className={`status-pill status-${r.status}`}>
                      {r.status.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    <span className={`badge-env env-${r.environment}`}>
                      {r.environment.toUpperCase()}
                    </span>
                  </td>
                  <td className="text-cyan font-bold">{r.benchmark}</td>
                  <td className="text-muted">{r.run_id.slice(0, 18)}...</td>
                  <td style={{ fontSize: '0.75rem' }}>{r.timestamp.replace('T', ' ').slice(0, 19)}</td>
                  <td className={r.exit_code === 0 ? 'text-emerald' : 'text-rose'}>
                    {r.exit_code}
                  </td>
                  <td className="text-muted" style={{ maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.command}
                  </td>
                  <td>
                    <button 
                      className="btn-evidence-sm"
                      onClick={() => onViewEvidence(r)}
                    >
                      <FileSearch size={12} />
                      <span>Inspect</span>
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
