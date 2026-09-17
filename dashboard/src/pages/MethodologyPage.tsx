import React from 'react';
import { BookOpen, Clock, ShieldCheck, CheckCircle2, FileCode2 } from 'lucide-react';

export const MethodologyPage: React.FC = () => {
  return (
    <div className="page-container">
      {/* Page Header */}
      <div className="card">
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <BookOpen size={22} color="var(--accent-primary)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Scientific Methodology & Standards</h2>
              <div className="card-subtitle">
                Reproducible Benchmarking Protocol, Stabilization Invariants, and Non-Fabrication Guarantees
              </div>
            </div>
          </div>
        </div>
        <p style={{ marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          This experimental framework eliminates transient host interference, compiler dead-code elimination, and cross-hypervisor contamination.
          Measurements adhere to reproducible scientific benchmarking standards developed for Linux kernel virtualization research.
        </p>
      </div>

      {/* 4 Pillars of Methodology */}
      <div className="grid-cols-2">
        <div className="card">
          <h3 className="card-title" style={{ marginBottom: '0.75rem' }}>
            <Clock size={16} color="var(--accent-primary)" />
            1. Stabilization & Environment Isolation
          </h3>
          <ul style={{ paddingLeft: '1.25rem', fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '0.5rem', lineHeight: 1.5 }}>
            <li>
              <strong>Single Environment Exclusivity:</strong> Before running any benchmark, inactive KVM domains, VirtualBox VMs, and LXC containers are verified to be stopped.
            </li>
            <li>
              <strong>Process Cleanup:</strong> Lingering workload instances (<code>cpu_workload</code>, <code>fio</code>, <code>iperf3</code>) are terminated prior to test execution.
            </li>
            <li>
              <strong>Host Quiescence:</strong> A mandatory 2-second stabilization delay is observed before and after every environment execution.
            </li>
            <li>
              <strong>Pre/Post Telemetry:</strong> Host CPU ticks, load averages, and free memory are monitored to detect background interference.
            </li>
          </ul>
        </div>

        <div className="card">
          <h3 className="card-title" style={{ marginBottom: '0.75rem' }}>
            <FileCode2 size={16} color="var(--accent-primary)" />
            2. Deterministic Workload Binaries
          </h3>
          <ul style={{ paddingLeft: '1.25rem', fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '0.5rem', lineHeight: 1.5 }}>
            <li>
              <strong>Static C99 Compilation:</strong> Workloads are compiled statically with GCC (<code>-O2 -static</code>) to remove dynamic shared library resolution overhead.
            </li>
            <li>
              <strong>Checksum Verification:</strong> Double-precision matrix multiplications calculate FNV-1a checksums to ensure compiler optimization does not bypass computations.
            </li>
            <li>
              <strong>Identical Binaries:</strong> Exactly identical binary hashes execute on Host, KVM, VirtualBox, and LXC environments.
            </li>
            <li>
              <strong>Multi-Pass Verification:</strong> Tests execute repeated iterations to measure statistical variance, mean, median, and percentiles.
            </li>
          </ul>
        </div>

        <div className="card">
          <h3 className="card-title" style={{ marginBottom: '0.75rem' }}>
            <ShieldCheck size={16} color="var(--accent-primary)" />
            3. Safe Storage Invariants
          </h3>
          <ul style={{ paddingLeft: '1.25rem', fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '0.5rem', lineHeight: 1.5 }}>
            <li>
              <strong>No Raw Block Device Access:</strong> Storage testing strictly rejects raw block partitions (such as <code>/dev/sd*</code>, <code>/dev/nvme*</code>) to prevent data loss.
            </li>
            <li>
              <strong>Temporary Regular Files:</strong> Tests create temporary regular files in designated test directories and clean up upon completion.
            </li>
            <li>
              <strong>Capacity Checks:</strong> Pre-flight disk space verification ensures at least 2x test file size is available before allocating buffers.
            </li>
            <li>
              <strong>Clean Teardown:</strong> Temporary files and scratch volumes are unlinked during test cleanup.
            </li>
          </ul>
        </div>

        <div className="card">
          <h3 className="card-title" style={{ marginBottom: '0.75rem' }}>
            <CheckCircle2 size={16} color="var(--accent-primary)" />
            4. Strict Non-Fabrication Guarantee
          </h3>
          <ul style={{ paddingLeft: '1.25rem', fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '0.5rem', lineHeight: 1.5 }}>
            <li>
              <strong>Zero Mock Data:</strong> When tools (e.g. <code>fio</code>, hardware performance counters) are uninstalled or restricted, they are reported as <code>unavailable</code>.
            </li>
            <li>
              <strong>Explicit Reasons:</strong> Every unavailable metric includes a human-readable explanation and stderr capture.
            </li>
            <li>
              <strong>Neutral Reporting:</strong> No subjective "Winner", "Best", or aggregate scoring is computed. Results are reported purely as physical measurements.
            </li>
            <li>
              <strong>Cryptographic Traceability:</strong> Raw JSON outputs and terminal logs accompany every recorded execution record.
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
};
