import React, { useState, useMemo, useEffect } from 'react';
import { PageId, BenchmarkRun, HostInventory } from './types';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { EvidenceModal } from './components/EvidenceModal';

// Pages
import { OverviewPage } from './pages/OverviewPage';
import { HostPage } from './pages/HostPage';
import { KvmPage } from './pages/KvmPage';
import { VboxPage } from './pages/VboxPage';
import { LxcPage } from './pages/LxcPage';
import { CpuPage } from './pages/CpuPage';
import { MemoryPage } from './pages/MemoryPage';
import { StoragePage } from './pages/StoragePage';
import { NetworkPage } from './pages/NetworkPage';
import { StartupPage } from './pages/StartupPage';
import { SyscallsPage } from './pages/SyscallsPage';
import { IsolationPage } from './pages/IsolationPage';
import { ComparisonPage } from './pages/ComparisonPage';
import { EvidencePage } from './pages/EvidencePage';
import { MethodologyPage } from './pages/MethodologyPage';
import { RawDataPage } from './pages/RawDataPage';

// Static Data
import inventoryData from './data/inventory.json';
import runsData from './data/runs.json';

const PAGE_METADATA: Record<PageId, { title: string; desc: string }> = {
  overview: {
    title: '1. Laboratory Overview & Virtualization Matrix',
    desc: 'Comparative evaluation of KVM/QEMU, Oracle VirtualBox, and Native LXC against Bare-Metal Host Baseline.'
  },
  host: {
    title: '2. Bare-Metal Host Reference Baseline',
    desc: 'Hardware telemetry, Intel Core CPU topology, DDR RAM, and read-only thermal/frequency observability.'
  },
  kvm: {
    title: '3. KVM / QEMU Virtualization Adapter',
    desc: 'Kernel-based Virtual Machine architecture, virsh dynamic domain inspection, VirtIO drivers, and domstats.'
  },
  virtualbox: {
    title: '4. Oracle VirtualBox Hypervisor Adapter',
    desc: 'Hosted Type-2 hypervisor architecture, VBoxHeadless host process RSS vs. allocated 2048 MB memory ceiling.'
  },
  lxc: {
    title: '5. Native Linux Containers (LXC) Adapter',
    desc: 'OS-level container virtualization using Linux cgroups v2 resource controllers and 7 namespace boundaries.'
  },
  cpu: {
    title: '6. Deterministic CPU Compute Benchmark',
    desc: 'Double-precision matrix multiplication, wall/user/system times, CPU utilization, and context switches.'
  },
  memory: {
    title: '7. Deterministic Memory & Cache Subsystem',
    desc: 'Sequential write, read-accumulate, stride benchmark, allocated vs. actual RAM, and page fault accounting.'
  },
  storage: {
    title: '8. Safe Storage I/O Benchmark (FIO)',
    desc: 'Sequential and random 4K I/O operations strictly restricted to regular files; raw block devices prohibited.'
  },
  network: {
    title: '9. Network Latency & Bandwidth Virtualization',
    desc: 'ICMP ping round-trip times and standardized iperf3 TCP throughput under identical test invariants.'
  },
  startup: {
    title: '10. Virtualization Startup Lifecycle Analysis',
    desc: 'Phased breakdown of cold initialization: Hypervisor VMM start, network ready, and HTTP application ready.'
  },
  syscalls: {
    title: '11. System Call Profiling & Latency (strace -c)',
    desc: 'User/kernel mode transition profiling, syscall invocation counts, cumulative seconds, and error traps.'
  },
  isolation: {
    title: '12. Security & Isolation Architecture Analysis',
    desc: 'Visual hypervisor layer diagrams and empirical evidence: systemd-detect-virt, uname, and namespace IDs.'
  },
  comparison: {
    title: '13. Neutral Scientific Comparative Evaluation',
    desc: 'Side-by-side empirical measurements across identical hardware. Objective reporting without scores or winners.'
  },
  evidence: {
    title: '14. Forensic Evidence & Run Traceability Engine',
    desc: 'Auditable record of every execution: exact command, terminal standard output, standard error, and exit codes.'
  },
  methodology: {
    title: '15. Scientific Methodology & Rigorous Standards',
    desc: 'Experimental protocol, multi-stage stabilization, static C99 compilation, and zero-fabrication guarantees.'
  },
  raw_data: {
    title: '16. Raw Datasets & Processed Exports',
    desc: 'Direct access to machine-readable JSON and CSV processed datasets for independent exploratory analysis.'
  }
};

import { api, EnvironmentStatus, BenchmarkJob } from './api';
import { JobLogsModal } from './components/JobLogsModal';

export function App() {
  const [activePage, setActivePage] = useState<PageId>('overview');
  const [selectedRun, setSelectedRun] = useState<BenchmarkRun | null>(null);
  const [activeLogJobId, setActiveLogJobId] = useState<string | null>(null);

  // Global Filters
  const [filterEnv, setFilterEnv] = useState<string>('all');
  const [filterBenchmark, setFilterBenchmark] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Live Backend & Job States
  const [environmentsStatus, setEnvironmentsStatus] = useState<Record<string, EnvironmentStatus>>({});
  const [activeJob, setActiveJob] = useState<BenchmarkJob | null>(null);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  const inventory: HostInventory = inventoryData as unknown as HostInventory;
  const [rawRuns, setRawRuns] = useState<BenchmarkRun[]>((runsData as unknown as BenchmarkRun[]) || []);

  // Fetch live results from backend API
  const refreshResults = async () => {
    setIsRefreshing(true);
    try {
      const resp = await api.getResults();
      if (resp && resp.results && resp.results.length > 0) {
        setRawRuns(resp.results as unknown as BenchmarkRun[]);
      }
    } catch {
      // Backend offline or no results yet; keep static dataset
    } finally {
      setIsRefreshing(false);
    }
  };

  // Poll backend health and active jobs
  useEffect(() => {
    let mounted = true;

    const pollBackend = async () => {
      try {
        const health = await api.checkHealth();
        if (mounted && health?.environments) {
          setEnvironmentsStatus(health.environments);
        }
      } catch {
        // Backend not running
      }

      try {
        const jobsResp = await api.listJobs();
        if (mounted && jobsResp?.jobs?.length) {
          const latest = jobsResp.jobs[0];
          setActiveJob(prev => {
            // If previous was running and latest completed, refresh results
            if (prev && prev.status === 'running' && latest.status === 'completed') {
              refreshResults();
            }
            return latest;
          });
        }
      } catch {
        // Backend not running
      }
    };

    pollBackend();
    const interval = setInterval(pollBackend, 3000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  // Filtered dataset
  const filteredRuns = useMemo(() => {
    return rawRuns.filter(r => {
      const matchEnv = filterEnv === 'all' || r.environment === filterEnv;
      const matchBench = filterBenchmark === 'all' || r.benchmark === filterBenchmark;
      const q = searchQuery.toLowerCase();
      const matchSearch = !q ||
        r.run_id.toLowerCase().includes(q) ||
        r.benchmark.toLowerCase().includes(q) ||
        r.command.toLowerCase().includes(q) ||
        (r.stdout && r.stdout.toLowerCase().includes(q));

      return matchEnv && matchBench && matchSearch;
    });
  }, [rawRuns, filterEnv, filterBenchmark, searchQuery]);

  const activeMeta = PAGE_METADATA[activePage] || PAGE_METADATA.overview;

  const handleViewEvidence = (run: BenchmarkRun) => {
    setSelectedRun(run);
  };

  const renderActivePage = () => {
    switch (activePage) {
      case 'overview':
        return (
          <OverviewPage
            inventory={inventory}
            runs={filteredRuns}
            onNavigate={page => setActivePage(page)}
            onViewEvidence={handleViewEvidence}
            environmentsStatus={environmentsStatus}
            activeJob={activeJob}
            onJobStarted={job => setActiveJob(job)}
            onRefreshResults={refreshResults}
            onViewLogs={id => setActiveLogJobId(id)}
            onJobCancelled={() => setActiveJob(prev => prev ? { ...prev, status: 'cancelled' } : null)}
            isRefreshing={isRefreshing}
          />
        );
      case 'host':
        return (
          <HostPage
            inventory={inventory}
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'kvm':
        return (
          <KvmPage
            inventory={inventory}
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'virtualbox':
        return (
          <VboxPage
            inventory={inventory}
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'lxc':
        return (
          <LxcPage
            inventory={inventory}
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'cpu':
        return (
          <CpuPage
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'memory':
        return (
          <MemoryPage
            inventory={inventory}
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'storage':
        return (
          <StoragePage
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'network':
        return (
          <NetworkPage
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'startup':
        return (
          <StartupPage
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'syscalls':
        return (
          <SyscallsPage
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'isolation':
        return (
          <IsolationPage
            inventory={inventory}
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'comparison':
        return (
          <ComparisonPage
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'evidence':
        return (
          <EvidencePage
            runs={filteredRuns}
            onViewEvidence={handleViewEvidence}
          />
        );
      case 'methodology':
        return <MethodologyPage />;
      case 'raw_data':
        return (
          <RawDataPage
            runs={filteredRuns}
            isQuickMode={true}
          />
        );
      default:
        return (
          <OverviewPage
            inventory={inventory}
            runs={filteredRuns}
            onNavigate={page => setActivePage(page)}
            onViewEvidence={handleViewEvidence}
          />
        );
    }
  };

  return (
    <div className="app-layout">
      {/* 16-Page Navigation Sidebar */}
      <Sidebar
        activePage={activePage}
        onSelectPage={page => setActivePage(page)}
        totalRuns={rawRuns.length}
      />

      {/* Main Laboratory Dashboard Area */}
      <div className="main-content-area">
        <Header
          activePageTitle={activeMeta.title}
          activePageDesc={activeMeta.desc}
          filterEnv={filterEnv}
          onFilterEnvChange={setFilterEnv}
          filterBenchmark={filterBenchmark}
          onFilterBenchmarkChange={setFilterBenchmark}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          totalFilteredRuns={filteredRuns.length}
          experimentId={rawRuns[0]?.experiment_id || 'exp-cc2-host'}
          isQuickMode={true}
        />

        <main className="content-viewport">
          {renderActivePage()}
        </main>
      </div>

      {/* Forensic Evidence Modal */}
      <EvidenceModal
        run={selectedRun}
        onClose={() => setSelectedRun(null)}
      />

      {/* Sanitized Job Execution Logs Modal */}
      <JobLogsModal
        jobId={activeLogJobId}
        onClose={() => setActiveLogJobId(null)}
      />
    </div>
  );
}

export default App;

