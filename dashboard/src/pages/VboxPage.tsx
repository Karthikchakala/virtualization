import React from 'react';
import { Layers, CheckCircle2, FileSearch } from 'lucide-react';
import { HostInventory, BenchmarkRun } from '../types';

interface VboxPageProps {
  inventory: HostInventory;
  runs: BenchmarkRun[];
  onViewEvidence: (run: BenchmarkRun) => void;
}

export const VboxPage: React.FC<VboxPageProps> = ({
  inventory,
  runs,
  onViewEvidence
}) => {
  const vboxRuns = runs.filter(r => r.environment === 'virtualbox');
  const vm = inventory.virtualbox?.vms?.[0] || { name: 'Ubuntu-Server-VBox', uuid: 'fa6b26c2-b5f7-4147-9ea8-2ca2a7b8e515' };

  return (
    <div className="page-container">
      {/* Environment Header */}
      <div className="card">
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Layers size={22} color="var(--accent-primary)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Oracle VirtualBox</h2>
              <div className="card-subtitle">
                Hosted Hypervisor (Type-2 Architecture)
              </div>
            </div>
          </div>
          <span className="badge-status-ready">
            <CheckCircle2 size={12} /> Available
          </span>
        </div>
        <p style={{ marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          Oracle VirtualBox operates as a hosted Type-2 hypervisor atop the host OS. The virtual machine process (<code>VBoxHeadless</code>)
          allocates static memory (2048 MB ceiling) and emulates standard hardware peripherals (AHCI SATA, Intel PRO/1000 MT network adapter).
        </p>
      </div>

      {/* Virtual Machine Configuration */}
      <div className="card">
        <div className="card-header-row">
          <h3 className="card-title">Virtual Machine Configuration</h3>
          <span className="font-mono text-xs text-secondary">VM: {vm.name}</span>
        </div>

        <div className="spec-table" style={{ fontSize: '0.8125rem' }}>
          <div className="spec-row">
            <span className="spec-key">Hypervisor</span>
            <span className="spec-val">Oracle VirtualBox 7.0+ (VBoxManage headless)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">vCPUs</span>
            <span className="spec-val">2 vCPUs (100% execution cap)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Memory</span>
            <span className="spec-val">2048 MB (Static Allocation Ceiling)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Network</span>
            <span className="spec-val">Intel PRO/1000 MT Desktop (82540EM)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Disk</span>
            <span className="spec-val">VDI (AHCI SATA Controller)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Hardware Acceleration</span>
            <span className="spec-val">Intel VT-x with Nested Paging</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Guest Kernel</span>
            <span className="spec-val">6.8.0-generic (Separate Guest Kernel)</span>
          </div>
        </div>
      </div>

      {/* Benchmark Results */}
      <div className="card">
        <div className="card-header-row">
          <div>
            <h3 className="card-title">Benchmark Results</h3>
            <div className="card-subtitle">Verified runs executed inside VirtualBox guest environment</div>
          </div>
          <span className="text-secondary" style={{ fontSize: '0.75rem' }}>
            {vboxRuns.length} recorded runs
          </span>
        </div>

        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Benchmark</th>
                <th>Status</th>
                <th>Execution Time</th>
                <th>CPU Utilization</th>
                <th>Max RSS</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {vboxRuns.map((r, idx) => {
                const tel = r.metrics?.telemetry || {};
                const isUnavail = r.status === 'unavailable';

                return (
                  <tr key={idx}>
                    <td className="font-mono text-xs font-semibold">{r.benchmark}</td>
                    <td>
                      <span className={`status-pill status-${r.status}`}>
                        {r.status}
                      </span>
                    </td>
                    <td className="font-mono">
                      {tel.wall_time_sec !== undefined && tel.wall_time_sec !== null
                        ? `${tel.wall_time_sec}s`
                        : (isUnavail ? 'Unavailable' : '—')}
                    </td>
                    <td className="font-mono">
                      {tel.cpu_percentage !== undefined && tel.cpu_percentage !== null
                        ? `${tel.cpu_percentage}%`
                        : (isUnavail ? 'Unavailable' : '—')}
                    </td>
                    <td className="font-mono">
                      {tel.max_rss_kb ? `${Math.round(tel.max_rss_kb / 1024)} MiB` : (isUnavail ? 'Unavailable' : '—')}
                    </td>
                    <td>
                      <button
                        className="btn-evidence-sm"
                        onClick={() => onViewEvidence(r)}
                      >
                        <FileSearch size={12} />
                        <span>Evidence</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
