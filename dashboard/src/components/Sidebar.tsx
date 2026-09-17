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
  Calendar,
  ShieldAlert,
  BarChart2,
  FileSearch,
  BookOpen,
  FileCode2
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
  group: string;
}

export const NAV_ITEMS: NavItem[] = [
  // Environments
  { id: 'overview', label: 'Overview', icon: LayoutDashboard, group: 'Environments' },
  { id: 'host', label: 'Host Baseline', icon: Server, group: 'Environments' },
  { id: 'kvm', label: 'KVM / QEMU', icon: Cpu, group: 'Environments' },
  { id: 'virtualbox', label: 'VirtualBox', icon: Layers, group: 'Environments' },
  { id: 'lxc', label: 'Native LXC', icon: Container, group: 'Environments' },

  // Benchmarks
  { id: 'cpu', label: 'CPU', icon: Zap, group: 'Benchmarks' },
  { id: 'memory', label: 'Memory', icon: Database, group: 'Benchmarks' },
  { id: 'storage', label: 'Storage', icon: HardDrive, group: 'Benchmarks' },
  { id: 'network', label: 'Network', icon: Network, group: 'Benchmarks' },
  { id: 'startup', label: 'Startup', icon: Clock, group: 'Benchmarks' },
  { id: 'syscalls', label: 'Syscalls', icon: Terminal, group: 'Benchmarks' },
  { id: 'scheduling', label: 'Scheduling', icon: Calendar, group: 'Benchmarks' },
  { id: 'isolation', label: 'Isolation', icon: ShieldAlert, group: 'Benchmarks' },

  // Analysis & Data
  { id: 'comparison', label: 'Results', icon: BarChart2, group: 'Analysis' },
  { id: 'evidence', label: 'Forensic Evidence', icon: FileSearch, group: 'Analysis' },
  { id: 'methodology', label: 'Methodology', icon: BookOpen, group: 'Analysis' },
  { id: 'raw_data', label: 'Raw Data', icon: FileCode2, group: 'Analysis' },
];

export const Sidebar: React.FC<SidebarProps> = ({ activePage, onSelectPage, totalRuns }) => {
  const groups = ['Environments', 'Benchmarks', 'Analysis'];

  return (
    <aside className="sidebar">
      <div className="sidebar-nav">
        {groups.map(grp => {
          const items = NAV_ITEMS.filter(i => i.group === grp);
          return (
            <div key={grp} className="nav-group">
              <div className="nav-group-title">{grp}</div>
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
                    <Icon size={16} />
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>

      <div className="sidebar-footer">
        <div>{totalRuns} total runs recorded</div>
      </div>
    </aside>
  );
};
