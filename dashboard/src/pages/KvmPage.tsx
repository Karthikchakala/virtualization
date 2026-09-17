import React from 'react';
import { Cpu, CheckCircle2, FileSearch } from 'lucide-react';
import { HostInventory, BenchmarkRun } from '../types';

interface KvmPageProps {
  inventory: HostInventory;
  runs: BenchmarkRun[];
  onViewEvidence: (run: BenchmarkRun) => void;
}

export const KvmPage: React.FC<KvmPageProps> = ({
  inventory,
  runs,
  onViewEvidence
}) => {
  const kvmRuns = runs.filter(r => r.environment === 'kvm');
  const domain = inventory.kvm?.domains?.[0] || { name: 'ubuntu24.04', state: 'shut off', id: '-' };

  return (
    <div className="page-container">
      {/* Environment Header */}
      <div className="card">
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Cpu size={22} color="var(--accent-primary)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>KVM / QEMU</h2>
              <div className="card-subtitle">
                Kernel-based Virtual Machine (Type-1 Architecture)
              </div>
            </div>
          </div>
          <span className="badge-status-ready">
            <CheckCircle2 size={12} /> Available
          </span>
        </div>
        <p style={{ marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          KVM operates via loadable Linux kernel modules (<code>kvm.ko</code>, <code>kvm_intel.ko</code>), utilizing Intel VT-x hardware virtualization.
          The virtual machine process (<code>qemu-system-x86_64</code>) utilizes VirtIO para-virtualized drivers for disk and network I/O.
        </p>
      </div>

      {/* Virtual Machine Configuration */}
      <div className="card">
        <div className="card-header-row">
          <h3 className="card-title">Virtual Machine Configuration</h3>
          <span className="font-mono text-xs text-secondary">Domain: {domain.name}</span>
        </div>

        <div className="spec-table" style={{ fontSize: '0.8125rem' }}>
          <div className="spec-row">
            <span className="spec-key">Hypervisor</span>
            <span className="spec-val">QEMU/KVM 8.2+ (libvirt)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">vCPUs</span>
            <span className="spec-val">2 vCPUs (Host Core Affinity)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Memory</span>
            <span className="spec-val">2048 MB (VirtIO balloon active)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Network</span>
            <span className="spec-val">virtio-net (virbr0 bridge)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Disk</span>
            <span className="spec-val">qcow2 (virtio-scsi)</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Machine Type</span>
            <span className="spec-val">pc-q35-8.2</span>
          </div>
          <div className="spec-row">
            <span className="spec-key">Guest Kernel</span>
            <span className="spec-val">6.8.0-generic (Isolated Guest Kernel Address Space)</span>
          </div>
        </div>
      </div>

      {/* Benchmark Results */}
      <div className="card">
        <div className="card-header-row">
          <div>
            <h3 className="card-title">Benchmark Results</h3>
            <div className="card-subtitle">Verified runs executed inside KVM guest environment</div>
          </div>
          <span className="text-secondary" style={{ fontSize: '0.75rem' }}>
            {kvmRuns.length} recorded runs
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
              {kvmRuns.map((r, idx) => {
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
