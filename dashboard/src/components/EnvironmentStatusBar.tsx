import React from 'react';
import { Server, Cpu, Layers, Container, CheckCircle2, Clock, XCircle, AlertCircle } from 'lucide-react';
import { EnvironmentStatus } from '../api';

interface EnvironmentStatusBarProps {
  environments: Record<string, EnvironmentStatus>;
  activeJobEnv?: string;
}

export const EnvironmentStatusBar: React.FC<EnvironmentStatusBarProps> = ({
  environments,
  activeJobEnv
}) => {
  const envDefs = [
    { key: 'host', label: 'Host', type: 'Bare-Metal Reference', icon: Server },
    { key: 'kvm', label: 'KVM / QEMU', type: 'Type-1 Hypervisor (Kernel)', icon: Cpu },
    { key: 'virtualbox', label: 'VirtualBox', type: 'Type-2 Hypervisor (Hosted)', icon: Layers },
    { key: 'lxc', label: 'Native LXC', type: 'OS Container (cgroups v2)', icon: Container }
  ];

  const getStatusBadge = (key: string, info?: EnvironmentStatus) => {
    if (activeJobEnv === key) {
      return (
        <span className="badge-status-running">
          <Clock size={12} className="animate-spin" /> Running
        </span>
      );
    }

    const state = (info?.status || 'available').toLowerCase();
    if (state === 'available' || state === 'ready') {
      return (
        <span className="badge-status-ready">
          <CheckCircle2 size={12} /> Available
        </span>
      );
    }
    if (state === 'unavailable') {
      return (
        <span className="badge-status-unavail">
          <XCircle size={12} /> Unavailable
        </span>
      );
    }
    return (
      <span className="badge-status-stopped">
        <AlertCircle size={12} /> {state}
      </span>
    );
  };

  return (
    <div className="env-status-grid">
      {envDefs.map(def => {
        const info = environments[def.key];
        const Icon = def.icon;
        const isActive = activeJobEnv === def.key;

        return (
          <div key={def.key} className={`env-status-card ${isActive ? 'env-card-active' : ''}`}>
            <div className="env-status-header">
              <div className="env-title-group">
                <Icon size={18} color="var(--accent-primary)" />
                <div>
                  <div className="env-name">{def.label}</div>
                  <div className="env-classification">{def.type}</div>
                </div>
              </div>
              {getStatusBadge(def.key, info)}
            </div>
          </div>
        );
      })}
    </div>
  );
};
