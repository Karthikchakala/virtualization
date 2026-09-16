import React from 'react';
import { 
  Container, 
  Cpu, 
  Server, 
  HardDrive, 
  Network, 
  ShieldAlert, 
  Activity,
  Terminal,
  Layers
} from 'lucide-react';
import { HostInventory, BenchmarkRun } from '../types';
import { MetricCard } from '../components/MetricCard';

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
      {/* LXC Header */}
      <div className="card" style={{ marginBottom: '1.5rem', borderLeft: '4px solid var(--accent-emerald)' }}>
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Container size={24} color="var(--accent-emerald)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Native LXC Container Adapter</h2>
              <span className="text-secondary font-mono" style={{ fontSize: '0.8125rem' }}>
                OS-Level Virtualization (cgroups v2 + Linux Namespaces) • lxc-ls / lxc-info
              </span>
            </div>
          </div>
          <span className="status-pill status-stopped font-mono">
            {container.state.toUpperCase()}
          </span>
        </div>
        <p style={{ marginTop: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          Native LXC uses the host Linux kernel directly, isolating processes through 7 Linux namespace boundaries 
          (<code>pid</code>, <code>mnt</code>, <code>net</code>, <code>ipc</code>, <code>uts</code>, <code>user</code>, <code>cgroup</code>) 
          and cgroups v2 resource limiters. Because there is <strong>zero hypervisor hardware emulation</strong>, LXC achieves near-zero CPU and memory virtualization tax,
          while sharing the host kernel release.
        </p>
      </div>

      {/* LXC Specs Grid */}
      <div className="grid-cols-4">
        <MetricCard
          title="Discovered Container"
          value={container.name}
          subtitle="Native Linux Container"
          color="var(--accent-emerald)"
        />
        <MetricCard
          title="Kernel Architecture"
          value="Shared Host Kernel"
          subtitle={inventory.os?.kernel_release || '7.0.0-31-generic'}
          color="var(--accent-emerald)"
        />
        <MetricCard
          title="Isolation Boundary"
          value="cgroups v2"
          subtitle="Unified Hierarchy (/sys/fs/cgroup)"
          color="var(--accent-emerald)"
        />
        <MetricCard
          title="Network Bridge"
          value="lxcbr0"
          subtitle="10.0.3.0/24 veth pair"
          color="var(--accent-emerald)"
        />
      </div>

      {/* Cgroups v2 Resource Hierarchy Table */}
      <div className="section-header" style={{ marginTop: '2rem' }}>
        <h3 className="section-title">Control Groups v2 Resource Boundaries</h3>
        <span className="section-subtitle">Kernel-enforced isolation limits without hardware emulation</span>
      </div>

      <div className="grid-cols-2">
        <div className="card font-mono">
          <div className="card-title text-emerald">cgroups v2 Limiters</div>
          <div className="spec-table" style={{ marginTop: '0.75rem' }}>
            <div className="spec-row">
              <span className="spec-key">cgroup Hierarchy</span>
              <span className="spec-val">/sys/fs/cgroup/lxc/{container.name}</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">cpu.max</span>
              <span className="spec-val">max 100000 (Unconstrained Host CFS)</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">memory.max</span>
              <span className="spec-val">max (Dynamic Host Memory Ceiling)</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">io.weight</span>
              <span className="spec-val">default (100) / host CFQ</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Rootfs Path</span>
              <span className="spec-val">/var/lib/lxc/{container.name}/rootfs</span>
            </div>
          </div>
        </div>

        <div className="card font-mono">
          <div className="card-title text-cyan">Lifecycle & Process Control</div>
          <div className="spec-table" style={{ marginTop: '0.75rem' }}>
            <div className="spec-row">
              <span className="spec-key">Init Supervisor</span>
              <span className="spec-val">lxc-start -d -n {container.name}</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Guest Init System</span>
              <span className="spec-val">systemd (PID 1 inside container namespace)</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Command Execution</span>
              <span className="spec-val">lxc-attach -n {container.name} --</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Graceful Quenching</span>
              <span className="spec-val text-emerald">lxc-stop -n {container.name}</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Tooling Invariant</span>
              <span className="spec-val text-emerald">Native LXC only (Docker/Podman/LXD excluded)</span>
            </div>
          </div>
        </div>
      </div>

      {/* LXC Benchmark Runs */}
      <div className="section-header" style={{ marginTop: '2.5rem' }}>
        <h3 className="section-title">Native LXC Benchmark Runs</h3>
        <span className="section-subtitle">Verified runs executed inside LXC container namespace</span>
      </div>

      <div className="table-wrapper">
        <table className="data-table font-mono">
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
                  <td>
                    <span className="font-bold text-emerald">{r.benchmark}</span>
                  </td>
                  <td>
                    <span className={`status-pill status-${r.status}`}>
                      {r.status.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    {tel.wall_time_sec !== undefined && tel.wall_time_sec !== null
                      ? `${tel.wall_time_sec}s`
                      : (isUnavail ? 'UNAVAILABLE' : '—')}
                  </td>
                  <td>
                    {tel.cpu_percentage !== undefined && tel.cpu_percentage !== null
                      ? `${tel.cpu_percentage}%`
                      : (isUnavail ? 'UNAVAILABLE' : '—')}
                  </td>
                  <td>
                    {tel.max_rss_kb ? `${Math.round(tel.max_rss_kb / 1024)} MiB` : (isUnavail ? 'UNAVAILABLE' : '—')}
                  </td>
                  <td>
                    <button 
                      className="btn-evidence-sm"
                      onClick={() => onViewEvidence(r)}
                    >
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
  );
};
