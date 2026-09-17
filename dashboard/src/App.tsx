import React, { useState, useMemo, useEffect } from 'react';
import { PageId, BenchmarkRun, HostInventory } from './types';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { EvidenceModal } from './components/EvidenceModal';
import { JobLogsModal } from './components/JobLogsModal';
import { api, EnvironmentStatus, BenchmarkJob } from './api';

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
import { SchedulingPage } from './pages/SchedulingPage';
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
    title: 'Laboratory Overview & Virtualization Matrix',
    desc: 'Comparative evaluation of KVM/QEMU, Oracle VirtualBox, and Native LXC against Bare-Metal Host Baseline.'
  },
  host: {
    title: 'Bare-Metal Host Reference Baseline',
    desc: 'Hardware topology, logical cores, DDR RAM, and host reference measurements.'
  },
  kvm: {
    title: 'KVM / QEMU Virtualization Adapter',
    desc: 'Kernel-based Virtual Machine architecture, libvirt domain configuration, and guest execution.'
  },
  virtualbox: {
    title: 'Oracle VirtualBox Hypervisor Adapter',
    desc: 'Hosted Type-2 hypervisor architecture, VBoxHeadless process execution, and memory allocation.'
  },
  lxc: {
    title: 'Native Linux Containers (LXC) Adapter',
    desc: 'OS-level container virtualization using Linux cgroups v2 resource controllers and 7 namespace boundaries.'
  },
  cpu: {
    title: 'Deterministic CPU Compute Benchmark',
    desc: 'Double-precision matrix multiplication, wall/user/system times, CPU utilization, and context switches.'
  },
  memory: {
    title: 'Deterministic Memory & Cache Subsystem',
    desc: 'Sequential write, read-accumulate, stride benchmark, allocated vs. actual RAM, and page fault accounting.'
  },
  storage: {
    title: 'Safe Storage I/O Benchmark (FIO)',
    desc: 'Sequential and random 4K I/O operations strictly restricted to temporary regular files.'
  },
  network: {
    title: 'Network Latency & Bandwidth Virtualization',
    desc: 'ICMP ping round-trip times and standardized iperf3 TCP throughput under identical test invariants.'
  },
  startup: {
    title: 'Virtualization Startup Lifecycle Analysis',
    desc: 'Phased breakdown of cold initialization: Hypervisor VMM start, network ready, and HTTP application ready.'
  },
  syscalls: {
    title: 'System Call Profiling & Latency (strace -c)',
    desc: 'User/kernel mode transition profiling, syscall invocation counts, cumulative seconds, and error traps.'
  },
  scheduling: {
    title: 'Scheduling Latency & Context Switches',
    desc: 'Two-way pipe inter-process communication latency, voluntary and involuntary scheduler switches.'
  },
  isolation: {
    title: 'Security & Isolation Architecture Analysis',
    desc: 'Hypervisor boundary models, systemd-detect-virt, kernel isolation, and namespace verification.'
  },
  comparison: {
    title: 'Results & Comparative Evaluation',
    desc: 'Side-by-side empirical measurements across identical hardware without subjective scores or winner declarations.'
  },
  evidence: {
    title: 'Forensic Evidence & Run Traceability Engine',
    desc: 'Auditable record of every execution: exact command, standard output, standard error, and exit codes.'
  },
  methodology: {
    title: 'Scientific Methodology & Rigorous Standards',
    desc: 'Experimental protocol, multi-stage stabilization, static C99 compilation, and zero-fabrication guarantees.'
  },
  raw_data: {
    title: 'Raw Datasets & Processed Exports',
    desc: 'Direct access to machine-readable JSON datasets for independent exploratory analysis.'
  }
};

export function App() {
  const getInitialPage = (): PageId => {
    if (typeof window !== 'undefined' && window.location.hash) {
      const hash = window.location.hash.replace('#', '') as PageId;
      if (PAGE_METADATA[hash]) return hash;
    }
    return 'overview';
  };

  const [activePage, setActivePage] = useState<PageId>(getInitialPage);
  const [selectedRun, setSelectedRun] = useState<BenchmarkRun | null>(null);
  const [activeLogJobId, setActiveLogJobId] = useState<string | null>(null);

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace('#', '') as PageId;
      if (PAGE_METADATA[hash]) {
        setActivePage(hash);
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleSelectPage = (page: PageId) => {
    setActivePage(page);
    if (typeof window !== 'undefined') {
      window.location.hash = page;
    }
  };

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
      case 'scheduling':
        return (
          <SchedulingPage
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
      {/* Full-width Top Header */}
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
        experimentId={rawRuns[0]?.experiment_id || 'exp-20260916-105528-ba33df'}
        isQuickMode={true}
        activeJob={activeJob}
      />

      {/* Main Layout Body: Sidebar + Main Content */}
      <div className="layout-body">
        <Sidebar
          activePage={activePage}
          onSelectPage={handleSelectPage}
          totalRuns={rawRuns.length}
        />

        <div className="main-content-area">
          <main className="content-viewport">
            {renderActivePage()}
          </main>
        </div>
      </div>

      {/* Forensic Evidence Modal */}
      <EvidenceModal
        run={selectedRun}
        onClose={() => setSelectedRun(null)}
      />

      {/* Execution Logs Modal */}
      <JobLogsModal
        jobId={activeLogJobId}
        onClose={() => setActiveLogJobId(null)}
      />
    </div>
  );
}

export default App;
