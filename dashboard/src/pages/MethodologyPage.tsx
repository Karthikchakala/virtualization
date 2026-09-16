import React from 'react';
import { 
  BookOpen, 
  ShieldCheck, 
  Cpu, 
  Clock, 
  Database, 
  HardDrive, 
  FileCode2,
  CheckCircle2
} from 'lucide-react';

export const MethodologyPage: React.FC = () => {
  return (
    <div className="page-container">
      {/* Methodology Header */}
      <div className="card" style={{ marginBottom: '1.5rem', borderLeft: '4px solid var(--accent-indigo)' }}>
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <BookOpen size={24} color="var(--accent-indigo)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Scientific Methodology & Rigorous Standards</h2>
              <span className="text-secondary font-mono" style={{ fontSize: '0.8125rem' }}>
                Reproducible Benchmarking Protocol • Multi-Stage Stabilization • Zero Fabrication Guarantee
              </span>
            </div>
          </div>
          <span className="badge-verified font-mono">
            Scientific Standard
          </span>
        </div>
        <p style={{ marginTop: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          This experimental framework eliminates transient host interference, compiler dead-code elimination, and cross-hypervisor contamination. 
          Measurements adhere to reproducible scientific benchmarking standards developed for Linux kernel virtualization research.
        </p>
      </div>

      {/* 4 Pillars of Experimental Rigor */}
      <div className="grid-cols-2">
        <div className="card font-mono">
          <div className="card-title text-cyan">
            <Clock size={16} /> 1. Stabilization & Run Isolation Protocol
          </div>
          <ul className="method-list" style={{ marginTop: '0.75rem' }}>
            <li>
              <strong>Single Environment Exclusivity:</strong> Before running any benchmark, KVM domains, VirtualBox VMs, and LXC containers are verified to be completely shut down.
            </li>
            <li>
              <strong>Process Scavenging:</strong> All lingering workload instances (<code>cpu_workload</code>, <code>fio</code>, <code>iperf3</code>) are terminated via SIGKILL.
            </li>
            <li>
              <strong>Host Quiescence:</strong> A mandatory 2-second stabilization delay is enforced before and after every environment execution.
            </li>
            <li>
              <strong>Pre/Post Telemetry:</strong> Host CPU ticks, load averages, and free memory are recorded to detect background interference.
            </li>
          </ul>
        </div>

        <div className="card font-mono">
          <div className="card-title text-emerald">
            <FileCode2 size={16} /> 2. Reproducible Static Workloads
          </div>
          <ul className="method-list" style={{ marginTop: '0.75rem' }}>
            <li>
              <strong>Identical Binary:</strong> The EXACT same static C99 binary is executed across Host, KVM, VirtualBox, and LXC.
            </li>
            <li>
              <strong>Static Linking:</strong> Compiled with <code>-static -O2 -pthread</code> to eliminate glibc dynamic linker variances.
            </li>
            <li>
              <strong>Cryptographic Manifest:</strong> Workloads are packaged with SHA256 checksums in <code>workloads/MANIFEST.json</code>.
            </li>
            <li>
              <strong>Checksum Verification:</strong> Double-precision floating point computations calculate FNV-1a checksums to prevent compiler dead-code elimination.
            </li>
          </ul>
        </div>

        <div className="card font-mono">
          <div className="card-title text-amber">
            <HardDrive size={16} /> 3. Non-Destructive Storage Safety
          </div>
          <ul className="method-list" style={{ marginTop: '0.75rem' }}>
            <li>
              <strong>Regular File Mandate:</strong> Storage benchmarks strictly reject raw block devices (<code>/dev/sd*</code>, <code>/dev/nvme*</code>).
            </li>
            <li>
              <strong>Capacity Guard:</strong> Minimum 100 MB free disk space is verified prior to creating temporary test files.
            </li>
            <li>
              <strong>Bounded Duration:</strong> FIO tests are capped at 16 MB allocations with 3-second sync runtime limits.
            </li>
            <li>
              <strong>Immediate Cleanup:</strong> Test files are deleted immediately after benchmark completion.
            </li>
          </ul>
        </div>

        <div className="card font-mono">
          <div className="card-title text-rose">
            <ShieldCheck size={16} /> 4. Strict Zero-Fabrication Invariant
          </div>
          <ul className="method-list" style={{ marginTop: '0.75rem' }}>
            <li>
              <strong>No Default Zeroes:</strong> When a tool (fio, iperf3, perf) is missing or restricted, metrics remain <code>None</code>.
            </li>
            <li>
              <strong>Explicit Reasons:</strong> Recorded as <code>status: "unavailable"</code> with explicit reason documented.
            </li>
            <li>
              <strong>Linux Security Transparency:</strong> Kernel counter restrictions (e.g. <code>perf_event_paranoid=4</code>) are faithfully reported.
            </li>
            <li>
              <strong>Neutral Reporting:</strong> No subjective winners, scores, or technology rankings are generated.
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
};
