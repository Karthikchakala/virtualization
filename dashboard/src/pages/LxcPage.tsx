import React from 'react';
import { Container, CheckCircle2, FileSearch } from 'lucide-react';
import { HostInventory, BenchmarkRun } from '../types';

interface LxcPageProps {
  inventory: HostInventory;
  runs: BenchmarkRun[];
  onViewEvidence: (run: BenchmarkRun) => void;
}

export const LxcPage: React.FC<LxcPageProps> = ({
  inventory,
  runs,
  onViewEvidence
}) => {
  const lxcRuns = runs.filter(r => r.environment === 'lxc');
  const container = inventory.lxc?.containers?.[0] || { name: 'lxc-ubuntu', state: 'STOPPED' };

  return (
    <div className="page-container">
      {/* Environment Header */}
      <div className="card">
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Container size={22} color="var(--accent-primary)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Native LXC</h2>
              <div className="card-subtitle">
                OS-Level Virtualization (Linux cgroups v2 + Namespaces)
              </div>
            </div>
          </div>
          <span className="badge-status-ready">
            <CheckCircle2 size={12} /> Available
          </span>
        </div>
        <p style={{ marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          Native LXC uses the host Linux kernel directly, isolating processes through 7 Linux namespace boundaries
          (<code>pid</code>, <code>mnt</code>, <code>net</code>, <code>ipc</code>, <code>uts</code>, <code>user</code>, <code>cgroup</code>)
          and cgroups v2 resource controllers. With zero hardware emulation, LXC exhibits negligible CPU and memory virtualization overhead.
        </p>
      </div>

      {/* Container Configuration */}
      <div className="card">
        <div className="card-header-row">
          <h3 className="card-title">Container Configuration</h3>
          <span className="font-mono text-xs text-secondary">Container: {container.name}</span>
        </div>

        <div className="spec-table" style={{ fontSize: '0.8125rem' }}>
          <div className="spec-row">
            <span className="spec-key">Virtualization Technology</span>
            <span className="spec-val">Native LXC (lxc-start / lxc-attach)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">CPU Allocation</span>
            <span className="spec-val">Host CFS Scheduler (cgroups v2 cpu.max unconstrained)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Memory Allocation</span>
            <span className="spec-val">Dynamic Host RAM (cgroups v2 memory.max)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Network</span>
            <span className="spec-val">veth pair connected to lxcbr0 bridge (10.0.3.0/24)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Storage</span>
            <span className="spec-val">Rootfs directory (/var/lib/lxc/{container.name}/rootfs)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Isolation Boundaries</span>
            <span className="spec-val">7 Linux Namespaces + cgroups v2 unified hierarchy</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Kernel Release</span>
            <span className="spec-val">{inventory.os?.kernel_release || '7.0.0-31-generic'} (Shared Host Kernel)</span>
          </div>
        </div>
      </div>

      {/* Benchmark Results */}
      <div className="card">
        <div className="card-header-row">
          <div>
            <h3 className="card-title">Benchmark Results</h3>
            <div className="card-subtitle">Verified runs executed inside Native LXC container</div>
          </div>
          <span className="text-secondary" style={{ fontSize: '0.75rem' }}>
            {lxcRuns.length} recorded runs
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
              {lxcRuns.map((r, idx) => {
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
