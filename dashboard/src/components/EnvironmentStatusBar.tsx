import React from 'react';
import { Server, Cpu, Layers, Container, CheckCircle2, AlertCircle, Clock, XCircle } from 'lucide-react';
import { EnvironmentStatus } from '../api';

interface EnvironmentStatusBarProps {
  environments: Record<string, EnvironmentStatus>;
  activeJobEnv?: string;
}

export const EnvironmentStatusBar: React.FC<EnvironmentStatusBarProps> = ({
  environments,
  activeJobEnv
}) => {
  const envKeys = ['host', 'kvm', 'virtualbox', 'lxc'];

  const getIcon = (env: string) => {
    switch (env) {
      case 'host': return <Server size={18} color="var(--accent-amber)" />;
      case 'kvm': return <Cpu size={18} color="var(--accent-cyan)" />;
      case 'virtualbox': return <Layers size={18} color="var(--accent-indigo)" />;
      case 'lxc': return <Container size={18} color="var(--accent-emerald)" />;
      default: return <Server size={18} />;
    }
  };

  const getStatusBadge = (env: string, statusInfo?: EnvironmentStatus) => {
    if (activeJobEnv === env) {
      return (
        <span className="badge-status-running">
          <Clock size={12} className="animate-spin" /> RUNNING
        </span>
      );
    }

    const state = statusInfo?.status?.toLowerCase() || 'available';
    if (state === 'available') {
      return (
        <span className="badge-status-ready">
          <CheckCircle2 size={12} /> AVAILABLE
        </span>
      );
    }
    if (state === 'unavailable') {
      return (
        <span className="badge-status-unavail">
          <XCircle size={12} /> UNAVAILABLE
        </span>
      );
    }
    return (
      <span className="badge-status-stopped">
        <AlertCircle size={12} /> {state.toUpperCase()}
      </span>
    );
  };

  return (
    <div className="env-status-grid">
      {envKeys.map(key => {
        const info = environments[key] || {
          name: key,
          display_name: key.toUpperCase(),
          classification: key === 'host' ? 'Bare-Metal Reference' : 'Virtualization Tier',
          status: 'available'
        };

        return (
          <div key={key} className={`env-status-card ${activeJobEnv === key ? 'env-card-active' : ''}`}>
            <div className="env-status-header">
              <div className="env-title-group">
                {getIcon(key)}
                <div>
                  <div className="env-name">{info.display_name}</div>
                  <div className="env-classification">{info.classification}</div>
                </div>
              </div>
              {getStatusBadge(key, info)}
            </div>
          </div>
        );
      })}
    </div>
  );
};
