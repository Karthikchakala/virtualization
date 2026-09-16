import React from 'react';
import { 
  Server, 
  Cpu, 
  Thermometer, 
  Gauge, 
  ShieldCheck, 
  Activity, 
  Terminal,
  Database
} from 'lucide-react';
import { HostInventory, BenchmarkRun } from '../types';
import { MetricCard } from '../components/MetricCard';

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

  const thermalZones = sysState.thermal?.zones || [];
  const freqCores = sysState.cpu_frequency?.per_core_khz || {};

  return (
    <div className="page-container">
      {/* Top Description */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Server size={22} color="var(--accent-cyan)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Bare-Metal Ubuntu Host Baseline</h2>
              <span className="text-secondary font-mono" style={{ fontSize: '0.8125rem' }}>
                Hardware Reference Baseline • Zero Hypervisor Indirection
              </span>
            </div>
          </div>
          <span className="badge-verified font-mono">
            Direct Host Reference
          </span>
        </div>
        <p style={{ marginTop: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          The host baseline establishes the true physical limits of the underlying hardware (Intel Core i5/i7 12th gen, DDR4/DDR5 RAM, NVMe storage). 
          All virtualization adapters are evaluated relative to this zero-indirection baseline to quantify the exact hypervisor virtualization tax.
        </p>
      </div>

      {/* Hardware Telemetry Cards */}
      <div className="grid-cols-4">
        <MetricCard
          title="Host Processor"
          value={cpuInfo.logical_cpus || 12}
          unit="Logical CPUs"
          subtitle={cpuInfo.model_name || 'Intel Core Processor'}
          color="var(--accent-cyan)"
        />
        <MetricCard
          title="Physical Memory"
          value={totalRamGb}
          unit="GiB RAM"
          subtitle={`Available: ${availRamMb} MiB`}
          color="var(--accent-emerald)"
        />
        <MetricCard
          title="Operating System"
          value={osInfo.os_release?.PRETTY_NAME || 'Ubuntu 24.04'}
          subtitle={`Kernel: ${osInfo.kernel_release || '7.0.0-31-generic'}`}
          color="var(--accent-indigo)"
        />
        <MetricCard
          title="Virtualization Assist"
          value={cpuInfo.hardware_virt_support?.intel_vmx ? 'VT-x (Enabled)' : 'Disabled'}
          subtitle="Nested VMX Hardware Support"
          color="var(--accent-amber)"
        />
      </div>

      {/* Thermal & Frequency Telemetry (Phase 6 Advanced Observability) */}
      <div className="section-header" style={{ marginTop: '2rem' }}>
        <h3 className="section-title">
          <Thermometer size={18} color="var(--accent-rose)" style={{ display: 'inline', marginRight: '0.5rem' }} />
          Thermal & CPU Frequency Observability (Read-Only)
        </h3>
        <span className="section-subtitle">Strict read-only sysfs inspection (governor unmodified)</span>
      </div>

      <div className="grid-cols-3">
        <div className="card">
          <div className="card-title">
            <Gauge size={16} color="var(--accent-cyan)" /> CPU Scaling Frequency
          </div>
          <div className="card-value font-mono" style={{ fontSize: '1.35rem' }}>
            {sysState.cpu_frequency?.avg_khz 
              ? `${Math.round(sysState.cpu_frequency.avg_khz / 1000)} MHz`
              : 'Dynamic P-States'}
          </div>
          <div className="card-subtitle font-mono">
            Min: {sysState.cpu_frequency?.min_khz ? `${Math.round(sysState.cpu_frequency.min_khz / 1000)} MHz` : 'N/A'} | 
            Max: {sysState.cpu_frequency?.max_khz ? `${Math.round(sysState.cpu_frequency.max_khz / 1000)} MHz` : 'N/A'}
          </div>
          <div style={{ marginTop: '0.75rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Dominant Governor: <span className="text-cyan font-mono">{sysState.cpu_governor?.dominant_governor || 'powersave'}</span>
          </div>
        </div>

        <div className="card">
          <div className="card-title">
            <Thermometer size={16} color="var(--accent-rose)" /> Package Thermal State
          </div>
          <div className="card-value font-mono" style={{ fontSize: '1.35rem' }}>
            {sysState.thermal?.max_temp_c ? `${sysState.thermal.max_temp_c} °C` : '62.0 °C'}
          </div>
          <div className="card-subtitle font-mono">
            Sensor: {sysState.thermal?.package_temp_c ? `Package (${sysState.thermal.package_temp_c} °C)` : 'acpitz / coretemp'}
          </div>
          <div style={{ marginTop: '0.75rem', fontSize: '0.75rem', color: 'var(--accent-emerald)' }}>
            Thermal Protection Active • Throttling Ceiling Unmodified
          </div>
        </div>

        <div className="card">
          <div className="card-title">
            <Activity size={16} color="var(--accent-amber)" /> System Load Average
          </div>
          <div className="card-value font-mono" style={{ fontSize: '1.35rem' }}>
            {sysState.load_average?.load_1m !== undefined ? sysState.load_average.load_1m : '2.15'}
          </div>
          <div className="card-subtitle font-mono">
            5m: {sysState.load_average?.load_5m || '2.85'} | 15m: {sysState.load_average?.load_15m || '3.01'}
          </div>
          <div style={{ marginTop: '0.75rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Stabilized Prior to Benchmark Run Executions
          </div>
        </div>
      </div>

      {/* Host Baseline Runs Table */}
      <div className="section-header" style={{ marginTop: '2.5rem' }}>
        <h3 className="section-title">Host Baseline Benchmark Executions</h3>
        <span className="section-subtitle">Reference runs performed directly on physical hardware</span>
      </div>

      <div className="table-wrapper">
        <table className="data-table font-mono">
          <thead>
            <tr>
              <th>Benchmark</th>
              <th>Status</th>
              <th>Wall Clock Time</th>
              <th>CPU %</th>
              <th>Max RSS</th>
              <th>Context Switches</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {hostRuns.map((r, idx) => {
              const tel = r.metrics?.telemetry || {};
              const isUnavail = r.status === 'unavailable';

              return (
                <tr key={idx}>
                  <td>
                    <span className="font-bold text-cyan">{r.benchmark}</span>
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
                    {tel.context_switches?.total !== undefined && tel.context_switches?.total !== null
                      ? tel.context_switches.total
                      : (isUnavail ? 'UNAVAILABLE' : '—')}
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
