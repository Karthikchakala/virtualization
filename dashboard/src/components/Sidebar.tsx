import React from 'react';
import {
  LayoutDashboard,
  Server,
  Cpu,
  Layers,
  Container,
  Zap,
  HardDrive,
  Database,
  Network,
  Clock,
  Terminal,
  ShieldAlert,
  GitCompare,
  FileSearch,
  BookOpen,
  FileCode2,
  ChevronRight
} from 'lucide-react';
import { PageId } from '../types';

interface SidebarProps {
  activePage: PageId;
  onSelectPage: (page: PageId) => void;
  totalRuns: number;
}

interface NavItem {
  id: PageId;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  section: string;
}

export const NAV_ITEMS: NavItem[] = [
  // Laboratory Platforms
  { id: 'overview', label: '1. Overview', icon: LayoutDashboard, section: 'LAB PLATFORMS' },
  { id: 'host', label: '2. Host Baseline', icon: Server, section: 'LAB PLATFORMS' },
  { id: 'kvm', label: '3. KVM / QEMU', icon: Cpu, section: 'LAB PLATFORMS' },
  { id: 'virtualbox', label: '4. VirtualBox', icon: Layers, section: 'LAB PLATFORMS' },
  { id: 'lxc', label: '5. Native LXC', icon: Container, section: 'LAB PLATFORMS' },

  // Workload Benchmarks
  { id: 'cpu', label: '6. CPU Workload', icon: Zap, section: 'BENCHMARK DOMAINS' },
  { id: 'memory', label: '7. Memory & Cache', icon: Database, section: 'BENCHMARK DOMAINS' },
  { id: 'storage', label: '8. Storage (FIO)', icon: HardDrive, section: 'BENCHMARK DOMAINS' },
  { id: 'network', label: '9. Network (Ping/iperf)', icon: Network, section: 'BENCHMARK DOMAINS' },
  { id: 'startup', label: '10. Startup Lifecycle', icon: Clock, section: 'BENCHMARK DOMAINS' },
  { id: 'syscalls', label: '11. Syscalls & strace', icon: Terminal, section: 'BENCHMARK DOMAINS' },

  // Architecture & Evidence
  { id: 'isolation', label: '12. Isolation & Kernel', icon: ShieldAlert, section: 'EMPIRICAL AUDIT' },
  { id: 'comparison', label: '13. Neutral Comparison', icon: GitCompare, section: 'EMPIRICAL AUDIT' },
  { id: 'evidence', label: '14. Traceable Evidence', icon: FileSearch, section: 'EMPIRICAL AUDIT' },
  { id: 'methodology', label: '15. Scientific Method', icon: BookOpen, section: 'EMPIRICAL AUDIT' },
  { id: 'raw_data', label: '16. Raw Datasets', icon: FileCode2, section: 'EMPIRICAL AUDIT' },
];

export const Sidebar: React.FC<SidebarProps> = ({ activePage, onSelectPage, totalRuns }) => {
  const sections = Array.from(new Set(NAV_ITEMS.map(i => i.section)));

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-logo">
          <Layers size={20} color="var(--accent-cyan)" />
          <span className="brand-title">CC2 LAB</span>
        </div>
        <div className="brand-badge">VIRT-BENCH v2.0</div>
      </div>

      <div className="sidebar-nav">
        {sections.map(sec => {
          const items = NAV_ITEMS.filter(i => i.section === sec);
          return (
            <div key={sec} className="nav-group">
              <div className="nav-group-title">{sec}</div>
              {items.map(item => {
                const Icon = item.icon;
                const isActive = activePage === item.id;
                return (
                  <button
                    key={item.id}
                    className={`nav-link ${isActive ? 'nav-link-active' : ''}`}
                    onClick={() => onSelectPage(item.id)}
                    aria-label={`Navigate to ${item.label}`}
                  >
                    <div className="nav-link-content">
                      <Icon size={16} className={isActive ? 'icon-active' : 'icon-muted'} />
                      <span className="nav-label">{item.label}</span>
                    </div>
                    {isActive && <ChevronRight size={14} className="icon-indicator" />}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>

      <div className="sidebar-footer">
        <div className="telemetry-badge">
          <span className="status-dot"></span>
          <span>{totalRuns} Runs Indexed</span>
        </div>
        <div className="telemetry-sub">Zero Mock / Zero Fabricated</div>
      </div>
    </aside>
  );
};
