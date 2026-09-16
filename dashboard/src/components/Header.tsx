import React from 'react';
import { 
  ShieldCheck, 
  Filter, 
  Activity, 
  Calendar, 
  Search,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import { EnvironmentType, BenchmarkType } from '../types';

interface HeaderProps {
  activePageTitle: string;
  activePageDesc: string;
  filterEnv: string;
  onFilterEnvChange: (env: string) => void;
  filterBenchmark: string;
  onFilterBenchmarkChange: (bench: string) => void;
  searchQuery: string;
  onSearchQueryChange: (q: string) => void;
  totalFilteredRuns: number;
  experimentId?: string;
  isQuickMode?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  activePageTitle,
  activePageDesc,
  filterEnv,
  onFilterEnvChange,
  filterBenchmark,
  onFilterBenchmarkChange,
  searchQuery,
  onSearchQueryChange,
  totalFilteredRuns,
  experimentId,
  isQuickMode = true
}) => {
  return (
    <header className="main-header">
      <div className="header-top-row">
        <div>
          <div className="title-row">
            <h1 className="page-title">{activePageTitle}</h1>
            <div className="badge-group">
              <span className={`badge-mode ${isQuickMode ? 'badge-quick' : 'badge-full'}`}>
                {isQuickMode ? 'QUICK MODE (2 runs)' : 'FULL RIGOR (5 runs)'}
              </span>
              <span className="badge-verified">
                <ShieldCheck size={13} /> Empirical Traceability
              </span>
              {experimentId && (
                <span className="badge-exp font-mono">
                  EXP: {experimentId}
                </span>
              )}
            </div>
          </div>
          <p className="page-description">{activePageDesc}</p>
        </div>
      </div>

      <div className="header-controls-row">
        {/* Environment Filter Tabs */}
        <div className="control-pill-group">
          <span className="control-label">ENV:</span>
          {['all', 'host', 'kvm', 'virtualbox', 'lxc'].map(env => (
            <button
              key={env}
              className={`pill-btn ${filterEnv === env ? 'pill-btn-active' : ''}`}
              onClick={() => onFilterEnvChange(env)}
            >
              {env.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Benchmark Domain Filter */}
        <div className="control-pill-group">
          <span className="control-label">DOMAIN:</span>
          <select 
            value={filterBenchmark} 
            onChange={e => onFilterBenchmarkChange(e.target.value)}
            className="filter-select font-mono"
            aria-label="Filter by benchmark domain"
          >
            <option value="all">ALL DOMAINS</option>
            <option value="cpu_deterministic">CPU Deterministic</option>
            <option value="memory_deterministic">Memory Subsystem</option>
            <option value="syscall_deterministic">Syscall Latency</option>
            <option value="scheduling_deterministic">Scheduling / Pipe</option>
            <option value="disk_fio">Disk FIO (Safe)</option>
            <option value="network_ping">Network Ping</option>
            <option value="network_iperf3">Network iperf3</option>
            <option value="app_latency">HTTP Health Latency</option>
            <option value="startup_lifecycle">Startup Lifecycle</option>
            <option value="isolation_audit">Isolation Audit</option>
          </select>
        </div>

        {/* Search Input */}
        <div className="search-box">
          <Search size={14} className="search-icon" />
          <input
            type="text"
            placeholder="Search run ID, command, metric..."
            value={searchQuery}
            onChange={e => onSearchQueryChange(e.target.value)}
            className="search-input font-mono"
          />
        </div>

        <div className="filtered-counter font-mono">
          <Activity size={13} color="var(--accent-cyan)" />
          <span>{totalFilteredRuns} RUNS</span>
        </div>
      </div>
    </header>
  );
};
