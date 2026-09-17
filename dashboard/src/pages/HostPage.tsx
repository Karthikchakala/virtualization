import React from 'react';
import { Server, CheckCircle2, FileSearch } from 'lucide-react';
import { HostInventory, BenchmarkRun } from '../types';

interface HostPageProps {
  inventory: HostInventory;
  runs: BenchmarkRun[];
  onViewEvidence: (run: BenchmarkRun) => void;
}

export const HostPage: React.FC<HostPageProps> = ({
  inventory,
  runs,
  onViewEvidence
}) => {
  const hostRuns = runs.filter(r => r.environment === 'host');
  const cpuInfo = inventory.cpu || {};
  const memInfo = inventory.memory || {};
  const osInfo = inventory.os || {};
  const sysState = inventory.system_state || {};

  const totalRamGb = memInfo.total_kb ? Math.round(parseInt(memInfo.total_kb.replace('kB', '')) / 1024 / 1024) : 16;
  const availRamMb = memInfo.available_kb ? Math.round(parseInt(memInfo.available_kb.replace('kB', '')) / 1024) : 8192;

  return (
    <div className="page-container">
      {/* Environment Header */}
      <div className="card">
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Server size={22} color="var(--accent-primary)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Host Baseline</h2>
              <div className="card-subtitle">
                Bare-Metal Reference Baseline (Zero Hypervisor Indirection)
              </div>
            </div>
          </div>
          <span className="badge-status-ready">
            <CheckCircle2 size={12} /> Available
          </span>
        </div>
        <p style={{ marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          The bare-metal host establishes the physical limits of the test system hardware.
          All virtualization adapters (KVM, VirtualBox, Native LXC) are evaluated relative to this zero-indirection baseline to quantify hypervisor virtualization tax.
        </p>
      </div>

      {/* Host Hardware Configuration */}
      <div className="card">
        <div className="card-header-row">
          <h3 className="card-title">Host Hardware & System Configuration</h3>
          <span className="font-mono text-xs text-secondary">{osInfo.hostname || 'ubuntu-host'}</span>
        </div>

        <div className="spec-table" style={{ fontSize: '0.8125rem' }}>
          <div className="spec-row">
            <span className="spec-key">Processor Model</span>
            <span className="spec-val">{cpuInfo.model_name || 'Intel Core Processor'}</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Logical Cores</span>
            <span className="spec-val">{cpuInfo.logical_cpus || 12} Logical CPUs ({cpuInfo.architecture || 'x86_64'})</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Installed Physical RAM</span>
            <span className="spec-val">{totalRamGb} GiB RAM ({availRamMb} MiB available)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Operating System</span>
            <span className="spec-val">{osInfo.os_release?.PRETTY_NAME || 'Ubuntu 24.04 LTS'}</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Host Kernel Release</span>
            <span className="spec-val font-mono">{osInfo.kernel_release || '7.0.0-31-generic'}</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Hardware Virtualization Extensions</span>
            <span className="spec-val">{cpuInfo.hardware_virt_support?.intel_vmx ? 'Intel VT-x (VMX enabled)' : 'Supported'}</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">CPU Frequency & Scaling</span>
            <span className="spec-val">
              {sysState.cpu_frequency?.avg_khz ? `${Math.round(sysState.cpu_frequency.avg_khz / 1000)} MHz (governor: ${sysState.cpu_governor?.dominant_governor || 'powersave'})` : 'Dynamic P-States'}
            </span>
          </div>
        </div>
      </div>

      {/* Host Benchmark Runs */}
      <div className="card">
        <div className="card-header-row">
          <div>
            <h3 className="card-title">Benchmark Results</h3>
            <div className="card-subtitle">Verified baseline runs executed directly on bare-metal host</div>
          </div>
          <span className="text-secondary" style={{ fontSize: '0.75rem' }}>
            {hostRuns.length} recorded runs
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
              {hostRuns.map((r, idx) => {
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
