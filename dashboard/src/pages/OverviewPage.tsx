import React from 'react';
import { 
  ShieldCheck, 
  ExternalLink,
  Layers,
  Cpu,
  Container,
  Server
} from 'lucide-react';
import { HostInventory, BenchmarkRun, PageId } from '../types';
import { EnvironmentStatus, BenchmarkJob } from '../api';
import { EnvironmentStatusBar } from '../components/EnvironmentStatusBar';
import { ExperimentControls } from '../components/ExperimentControls';
import { JobProgressCard } from '../components/JobProgressCard';
import { ResultsComparisonView } from '../components/ResultsComparisonView';

interface OverviewPageProps {
  inventory: HostInventory;
  runs: BenchmarkRun[];
  onNavigate: (page: PageId) => void;
  onViewEvidence: (run: BenchmarkRun) => void;
  environmentsStatus?: Record<string, EnvironmentStatus>;
  activeJob?: BenchmarkJob | null;
  onJobStarted?: (job: BenchmarkJob) => void;
  onRefreshResults?: () => void;
  onViewLogs?: (jobId: string) => void;
  onJobCancelled?: () => void;
  isRefreshing?: boolean;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({
  inventory,
  runs,
  onNavigate,
  onViewEvidence,
  environmentsStatus = {},
  activeJob = null,
  onJobStarted = () => {},
  onRefreshResults = () => {},
  onViewLogs = () => {},
  onJobCancelled = () => {},
  isRefreshing = false
}) => {
  const getRunsForEnv = (env: string) => runs.filter(r => r.environment === env);

  const envStatuses = [
    {
      id: 'kvm',
      name: 'KVM / QEMU',
      type: 'Kernel-based Hypervisor (Type-1-like)',
      domain: inventory.kvm?.domains?.[0]?.name || 'ubuntu24.04',
      state: inventory.kvm?.domains?.[0]?.state || 'SHUT OFF',
      vcpu: '2 vCPU',
      ram: '2048 MB Balloon',
      kernel: '6.8.0-generic (Isolated Guest Kernel)',
      storage: 'virtio-scsi / qcow2',
      network: 'virtio-net / tap',
      pageId: 'kvm' as PageId,
      color: 'var(--accent-cyan)'
    },
    {
      id: 'virtualbox',
      name: 'Oracle VirtualBox',
      type: 'Hosted Hypervisor (Type-2)',
      domain: inventory.virtualbox?.vms?.[0]?.name || 'Ubuntu-Server-VBox',
      state: 'POWERED OFF',
      vcpu: '2 vCPU',
      ram: '2048 MB Static',
      kernel: '6.8.0-generic (Isolated Guest Kernel)',
      storage: 'AHCI SATA / VDI',
      network: 'Intel PRO/1000 MT (Bridged/NAT)',
      pageId: 'virtualbox' as PageId,
      color: 'var(--accent-indigo)'
    },
    {
      id: 'lxc',
      name: 'Native LXC',
      type: 'OS-Level Containerization (cgroups v2 + Namespaces)',
      domain: inventory.lxc?.containers?.[0]?.name || 'lxc-ubuntu',
      state: inventory.lxc?.containers?.[0]?.state || 'STOPPED',
      vcpu: 'Host Cores (cgroups quota)',
      ram: 'Host RAM (cgroups memory.max)',
      kernel: `${inventory.os?.kernel_release || '7.0.0-31-generic'} (Shared Host Kernel)`,
      storage: 'Rootfs Overlay / Host VFS',
      network: 'veth pair / lxcbr0 bridge',
      pageId: 'lxc' as PageId,
      color: 'var(--accent-emerald)'
    }
  ];

  return (
    <div className="page-container">
      {/* Neutral Scientific Protocol Notice */}
      <div className="notice-card">
        <ShieldCheck size={18} color="var(--accent-emerald)" />
        <div className="notice-content">
          <div className="notice-title">SCIENTIFIC OBSERVATION DIRECTIVE</div>
          <div className="notice-body">
            This laboratory dashboard presents direct, empirical measurements across bare-metal Host Baseline, KVM/QEMU, VirtualBox, and Native LXC. 
            <strong> Technologies are deliberately not ranked, and no overall "winner" is declared.</strong> Evaluation depends strictly on application isolation, hardware requirements, and virtualization constraints.
          </div>
        </div>
      </div>

      {/* 1. Live Environment Status Bar */}
      <EnvironmentStatusBar 
        environments={environmentsStatus}
        activeJobEnv={activeJob?.status === 'running' ? activeJob.environment : undefined}
      />

      {/* 2. Automated Experiment Dispatch Controls */}
      <ExperimentControls 
        isJobRunning={activeJob?.status === 'running' || activeJob?.status === 'queued'}
        onJobStarted={onJobStarted}
        onRefreshResults={onRefreshResults}
        isRefreshing={isRefreshing}
      />

      {/* 3. Live Job Progress Card (rendered when active or recent job exists) */}
      {activeJob && (
        <JobProgressCard 
          job={activeJob}
          onViewLogs={onViewLogs}
          onJobCancelled={onJobCancelled}
        />
      )}

      {/* 4. Comparative Visualizations & Statistical Results Table */}
      <ResultsComparisonView 
        runs={runs}
        onViewEvidence={onViewEvidence}
      />

      {/* 5. Virtualization Architecture Details */}
      <div className="section-header">
        <h2 className="section-title">Virtualization Architectures Evaluated</h2>
        <span className="section-subtitle">Discovered & Instrumented on Ubuntu 24.04 Host</span>
      </div>

      <div className="grid-cols-3">
        {envStatuses.map(env => {
          const envRuns = getRunsForEnv(env.id);
          const successRuns = envRuns.filter(r => r.status === 'success').length;
          const totalEnvRuns = envRuns.length;

          return (
            <div key={env.id} className="env-overview-card" style={{ borderTop: `4px solid ${env.color}` }}>
              <div className="env-card-header">
                <div>
                  <h3 className="env-name">{env.name}</h3>
                  <span className="env-type">{env.type}</span>
                </div>
                <span className={`status-pill status-${env.state.toLowerCase().replace(/\s+/g, '_')}`}>
                  {env.state}
                </span>
              </div>

              <div className="env-spec-table font-mono">
                <div className="spec-row">
                  <span className="spec-key">Discovered Target</span>
                  <span className="spec-val font-bold">{env.domain}</span>
                </div>
                <div className="spec-row">
                  <span className="spec-key">vCPU / Cores</span>
                  <span className="spec-val">{env.vcpu}</span>
                </div>
                <div className="spec-row">
                  <span className="spec-key">Memory Ceiling</span>
                  <span className="spec-val">{env.ram}</span>
                </div>
                <div className="spec-row">
                  <span className="spec-key">Kernel Paradigm</span>
                  <span className="spec-val">{env.kernel}</span>
                </div>
                <div className="spec-row">
                  <span className="spec-key">Virtual Storage</span>
                  <span className="spec-val">{env.storage}</span>
                </div>
                <div className="spec-row">
                  <span className="spec-key">Virtual Network</span>
                  <span className="spec-val">{env.network}</span>
                </div>
              </div>

              <div className="env-card-footer">
                <div className="env-runs-count font-mono">
                  <span className="text-secondary">{successRuns}/{totalEnvRuns} valid runs</span>
                </div>
                <button 
                  className="btn-nav font-mono"
                  onClick={() => onNavigate(env.pageId)}
                >
                  Inspect Tier <ExternalLink size={12} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
