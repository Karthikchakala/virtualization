import React from 'react';
import { Search, Loader2 } from 'lucide-react';
import { BenchmarkJob } from '../api';

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
  activeJob?: BenchmarkJob | null;
}

export const Header: React.FC<HeaderProps> = ({
  filterEnv,
  onFilterEnvChange,
  filterBenchmark,
  onFilterBenchmarkChange,
  searchQuery,
  onSearchQueryChange,
  totalFilteredRuns,
  experimentId,
  activeJob
}) => {
  const isJobRunning = activeJob?.status === 'running';

  return (
    <>
      {/* Top Application Header */}
      <header className="app-header">
        <div className="header-brand">
          <span className="header-brand-title">Virtualization Lab</span>
          <span className="header-brand-subtitle">Performance and Isolation Analysis</span>
        </div>

        <div className="header-status-area">
          {isJobRunning ? (
            <div className="experiment-status-pill status-running">
              <Loader2 size={13} className="animate-spin" />
              <span>Running: {activeJob?.benchmark} ({activeJob?.environment})</span>
            </div>
          ) : experimentId ? (
            <div className="experiment-status-pill status-ready">
              <span className="font-mono text-xs">Experiment: {experimentId}</span>
            </div>
          ) : (
            <div className="experiment-status-pill">
              <span>Ready</span>
            </div>
          )}
        </div>
      </header>

      {/* Global Filter Toolbar */}
      <div className="toolbar-bar">
        <div className="toolbar-left">
          <span className="toolbar-label">Environment:</span>
          <div className="pill-segmented">
            {[
              { id: 'all', label: 'All' },
              { id: 'host', label: 'Host' },
              { id: 'kvm', label: 'KVM' },
              { id: 'virtualbox', label: 'VirtualBox' },
              { id: 'lxc', label: 'LXC' }
            ].map(env => (
              <button
                key={env.id}
                className={`pill-segment-btn ${filterEnv === env.id ? 'active' : ''}`}
                onClick={() => onFilterEnvChange(env.id)}
              >
                {env.label}
              </button>
            ))}
          </div>

          <select
            value={filterBenchmark}
            onChange={e => onFilterBenchmarkChange(e.target.value)}
            className="filter-select"
            aria-label="Filter by benchmark domain"
          >
            <option value="all">All Domains</option>
            <option value="cpu_deterministic">CPU Deterministic</option>
            <option value="memory_deterministic">Memory Subsystem</option>
            <option value="disk_fio">Disk FIO (Storage)</option>
            <option value="network_ping">Network Ping (RTT)</option>
            <option value="network_iperf3">Network iperf3 (Throughput)</option>
            <option value="app_latency">Application HTTP Latency</option>
            <option value="startup_lifecycle">Startup Lifecycle</option>
            <option value="syscall_deterministic">Syscall Latency</option>
            <option value="scheduling_deterministic">Scheduling Latency</option>
            <option value="isolation_audit">Isolation Audit</option>
          </select>
        </div>

        <div className="toolbar-right">
          <div className="search-box">
            <Search size={14} className="search-icon" />
            <input
              type="text"
              placeholder="Search runs, commands, metrics..."
              value={searchQuery}
              onChange={e => onSearchQueryChange(e.target.value)}
              className="search-input"
            />
          </div>
          <span className="toolbar-counter">
            {totalFilteredRuns} {totalFilteredRuns === 1 ? 'run' : 'runs'}
          </span>
        </div>
      </div>
    </>
  );
};
