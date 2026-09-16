import React from 'react';
import { FileSearch, AlertCircle, HelpCircle } from 'lucide-react';
import { BenchmarkRun } from '../types';

interface MetricCardProps {
  title: string;
  value: string | number | null | undefined;
  unit?: string;
  subtitle?: string;
  status?: 'success' | 'unavailable' | 'failed' | string;
  unavailableReason?: string;
  stats?: {
    mean?: number | null;
    median?: number | null;
    stddev?: number | null;
    p95?: number | null;
  };
  evidenceRun?: BenchmarkRun | null;
  onViewEvidence?: (run: BenchmarkRun) => void;
  color?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  unit = '',
  subtitle,
  status = 'success',
  unavailableReason,
  stats,
  evidenceRun,
  onViewEvidence,
  color = 'var(--accent-cyan)'
}) => {
  const isUnavailable = status === 'unavailable' || value === null || value === undefined;

  return (
    <div className="metric-card">
      <div className="metric-header">
        <span className="metric-title" style={{ borderLeft: `3px solid ${color}` }}>
          {title}
        </span>
        {evidenceRun && onViewEvidence && (
          <button
            className="btn-evidence-sm"
            onClick={() => onViewEvidence(evidenceRun)}
            title="Inspect raw execution command, stdout, and stderr"
          >
            <FileSearch size={12} />
            <span>Evidence</span>
          </button>
        )}
      </div>

      <div className="metric-body">
        {isUnavailable ? (
          <div className="metric-unavailable-box">
            <div className="unavailable-pill">
              <AlertCircle size={12} />
              <span>UNAVAILABLE</span>
            </div>
            <p className="unavailable-text">
              {unavailableReason || 'Measurement not supported or restricted in this environment.'}
            </p>
          </div>
        ) : (
          <div className="metric-val-row">
            <span className="metric-value font-mono">{value}</span>
            {unit && <span className="metric-unit font-mono">{unit}</span>}
          </div>
        )}

        {subtitle && <div className="metric-subtitle">{subtitle}</div>}

        {stats && !isUnavailable && (
          <div className="metric-stats-grid font-mono">
            {stats.mean !== undefined && stats.mean !== null && (
              <div className="stat-item">
                <span className="stat-label">mean</span>
                <span className="stat-val">{stats.mean}</span>
              </div>
            )}
            {stats.median !== undefined && stats.median !== null && (
              <div className="stat-item">
                <span className="stat-label">median</span>
                <span className="stat-val">{stats.median}</span>
              </div>
            )}
            {stats.stddev !== undefined && stats.stddev !== null && (
              <div className="stat-item">
                <span className="stat-label">stddev</span>
                <span className="stat-val">{stats.stddev}</span>
              </div>
            )}
            {stats.p95 !== undefined && stats.p95 !== null && (
              <div className="stat-item">
                <span className="stat-label">p95</span>
                <span className="stat-val">{stats.p95}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
