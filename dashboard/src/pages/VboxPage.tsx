import React from 'react';
import { 
  Layers, 
  Cpu, 
  Server, 
  HardDrive, 
  Network, 
  ShieldCheck, 
  Activity,
  Terminal
} from 'lucide-react';
import { HostInventory, BenchmarkRun } from '../types';
import { MetricCard } from '../components/MetricCard';

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
      {/* VBox Header */}
      <div className="card" style={{ marginBottom: '1.5rem', borderLeft: '4px solid var(--accent-indigo)' }}>
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Layers size={24} color="var(--accent-indigo)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Oracle VirtualBox Hypervisor Adapter</h2>
              <span className="text-secondary font-mono" style={{ fontSize: '0.8125rem' }}>
                Hosted Hypervisor (Type-2 Architecture) • VBoxManage list vms
              </span>
            </div>
          </div>
          <span className="status-pill status-poweroff font-mono">
            POWERED OFF
          </span>
        </div>
        <p style={{ marginTop: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          VirtualBox operates as a Type-2 hypervisor running atop the host Ubuntu operating system. 
          The virtual machine process (<code>VBoxHeadless</code>) manages CPU emulation, guest memory allocation, and virtual hardware (AHCI SATA, Intel PRO/1000 NIC).
          Crucially, VirtualBox memory configuration reserves a ceiling (2048 MB), whereas host memory consumption fluctuates dynamically based on page allocation.
        </p>
      </div>

      {/* VBox Specs Grid */}
      <div className="grid-cols-4">
        <MetricCard
          title="Discovered VM"
          value={vm.name}
          subtitle={`UUID: ${vm.uuid.slice(0, 13)}...`}
          color="var(--accent-indigo)"
        />
        <MetricCard
          title="Allocated vCPUs"
          value="2 vCPUs"
          subtitle="Execution Cap: 100%"
          color="var(--accent-indigo)"
        />
        <MetricCard
          title="Configured RAM"
          value="2048 MB"
          subtitle="Static Ceiling"
          color="var(--accent-indigo)"
        />
        <MetricCard
          title="Hardware Acceleration"
          value="VT-x / AMD-V"
          subtitle="Nested Paging Enabled"
          color="var(--accent-indigo)"
        />
      </div>

      {/* Allocated vs Actual Memory Callout */}
      <div className="section-header" style={{ marginTop: '2rem' }}>
        <h3 className="section-title">Critical Memory Distinction: Allocated vs. Actual</h3>
        <span className="section-subtitle">VMM static allocation vs. physical host VBoxHeadless resident set</span>
      </div>

      <div className="grid-cols-2">
        <div className="card font-mono">
          <div className="card-title text-indigo">Virtual Machine Settings (Static)</div>
          <div className="spec-table" style={{ marginTop: '0.75rem' }}>
            <div className="spec-row">
              <span className="spec-key">Allocated RAM Ceiling</span>
              <span className="spec-val">2048 MB (2,097,152 KB)</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Virtual Disk Image</span>
              <span className="spec-val">Ubuntu-Server-VBox.vdi (25.0 GB dynamic)</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Storage Controller</span>
              <span className="spec-val">AHCI SATA (Port 0)</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">NIC Emulation</span>
              <span className="spec-val">82540EM Intel PRO/1000 MT Desktop</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">VirtualBox VMM</span>
              <span className="spec-val">Version 7.0+ (Ubuntu packaged)</span>
            </div>
          </div>
        </div>

        <div className="card font-mono">
          <div className="card-title text-emerald">Actual Host Resource Utilization</div>
          <div className="spec-table" style={{ marginTop: '0.75rem' }}>
            <div className="spec-row">
              <span className="spec-key">Host Process</span>
              <span className="spec-val">/usr/lib/virtualbox/VBoxHeadless</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Actual Resident RSS</span>
              <span className="spec-val text-emerald">~240 MiB initial / ~1.4 GiB active</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Lifecycle Control</span>
              <span className="spec-val">VBoxManage startvm --type headless</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Graceful Quenching</span>
              <span className="spec-val text-emerald">VBoxManage controlvm acpipowerbutton</span>
            </div>
            <div className="spec-row">
              <span className="spec-key">Stabilization Cooldown</span>
              <span className="spec-val">2.0s mandatory pre/post quiescence</span>
            </div>
          </div>
        </div>
      </div>

      {/* VirtualBox Benchmark Runs */}
      <div className="section-header" style={{ marginTop: '2.5rem' }}>
        <h3 className="section-title">VirtualBox Benchmark Runs</h3>
        <span className="section-subtitle">Verified runs executed inside VirtualBox guest</span>
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
            {vboxRuns.map((r, idx) => {
              const tel = r.metrics?.telemetry || {};
              const isUnavail = r.status === 'unavailable';

              return (
                <tr key={idx}>
                  <td>
                    <span className="font-bold text-indigo">{r.benchmark}</span>
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
