import React from 'react';
import { Zap, Clock, Activity, FileSearch } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend
} from 'recharts';
import { BenchmarkRun } from '../types';

interface CpuPageProps {
  runs: BenchmarkRun[];
  onViewEvidence: (run: BenchmarkRun) => void;
}

export const CpuPage: React.FC<CpuPageProps> = ({
  runs,
  onViewEvidence
}) => {
  const cpuRuns = runs.filter(r => r.benchmark === 'cpu_deterministic');

  const envs = ['host', 'kvm', 'virtualbox', 'lxc'];
  const summaryRows = envs.map(env => {
    const matched = cpuRuns.filter(r => r.environment === env && r.status === 'success');
    const wallTimes = matched
      .map(r => r.metrics?.elapsed_sec ?? r.metrics?.telemetry?.wall_time_sec)
      .filter((v): v is number => typeof v === 'number' && !isNaN(v));
    const cpuPcts = matched
      .map(r => r.metrics?.telemetry?.cpu_percentage)
      .filter((v): v is number => typeof v === 'number' && !isNaN(v));
    const cswchs = matched
      .map(r => r.metrics?.telemetry?.context_switches?.total)
      .filter((v): v is number => typeof v === 'number' && !isNaN(v));

    let meanTime: number | null = null;
    let medianTime: number | null = null;
    let avgCpu: number | null = null;
    let avgCswch: number | null = null;

    if (wallTimes.length > 0) {
      const sorted = [...wallTimes].sort((a, b) => a - b);
      meanTime = parseFloat((sorted.reduce((a, b) => a + b, 0) / sorted.length).toFixed(4));
      const mid = Math.floor(sorted.length / 2);
      medianTime = sorted.length % 2 !== 0 ? sorted[mid] : parseFloat(((sorted[mid - 1] + sorted[mid]) / 2).toFixed(4));
    }

    if (cpuPcts.length > 0) {
      avgCpu = parseFloat((cpuPcts.reduce((a, b) => a + b, 0) / cpuPcts.length).toFixed(1));
    }

    if (cswchs.length > 0) {
      avgCswch = Math.round(cswchs.reduce((a, b) => a + b, 0) / cswchs.length);
    }

    return {
      environment: env === 'host' ? 'Host' : env === 'kvm' ? 'KVM' : env === 'virtualbox' ? 'VirtualBox' : 'LXC',
      rawEnv: env,
      meanTime,
      medianTime,
      avgCpu,
      avgCswch,
      runsCount: matched.length
    };
  });

  const chartData = summaryRows.map(row => ({
    environment: row.environment,
    meanTimeSec: row.meanTime || 0,
    cpuUtilizationPct: row.avgCpu || 0
  }));

  return (
    <div className="page-container">
      {/* Page Header */}
      <div className="card">
        <div className="card-header-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Zap size={22} color="var(--accent-primary)" />
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>CPU Performance</h2>
              <div className="card-subtitle">
                Deterministic Double-Precision Matrix Multiplication (GEMM 400x400)
              </div>
            </div>
          </div>
        </div>
        <p style={{ marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          Identical precompiled static C99 binaries execute floating-point matrix multiplication with checksum validation across all environments.
          Evaluates computation duration, user/system mode splits, and scheduler overhead.
        </p>
      </div>

      {/* Comparison Summary Table */}
      <div className="card">
        <div className="card-header-row">
          <h3 className="card-title">CPU Performance Comparison</h3>
          <span className="text-secondary" style={{ fontSize: '0.75rem' }}>Empirical averages across measured runs</span>
        </div>

        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Environment</th>
                <th>Mean Time (s)</th>
                <th>Median (s)</th>
                <th>CPU Utilization</th>
                <th>Context Switches</th>
                <th>Valid Runs</th>
              </tr>
            </thead>
            <tbody>
              {summaryRows.map(row => (
                <tr key={row.environment}>
                  <td className="font-semibold">{row.environment}</td>
                  <td className="font-mono">{row.meanTime !== null ? `${row.meanTime}s` : '—'}</td>
                  <td className="font-mono">{row.medianTime !== null ? `${row.medianTime}s` : '—'}</td>
                  <td className="font-mono">{row.avgCpu !== null ? `${row.avgCpu}%` : '—'}</td>
                  <td className="font-mono">{row.avgCswch !== null ? row.avgCswch.toLocaleString() : '—'}</td>
                  <td className="font-mono">{row.runsCount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Charts */}
      <div className="grid-cols-2">
        <div className="chart-box">
          <div className="chart-title-bar">
            <span className="chart-title">Mean Execution Time</span>
            <span className="chart-badge">Seconds</span>
          </div>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 15, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                <XAxis dataKey="environment" stroke="#6b7280" fontSize={12} tickLine={false} />
                <YAxis stroke="#6b7280" fontSize={12} tickLine={false} unit="s" />
                <Tooltip
                  contentStyle={{ backgroundColor: '#ffffff', borderColor: '#e5e7eb', borderRadius: '6px', fontSize: '12px' }}
                  formatter={(val: any) => [`${val} s`, 'Mean Time']}
                />
                <Bar isAnimationActive={false} dataKey="meanTimeSec" fill="var(--accent-primary)" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="chart-box">
          <div className="chart-title-bar">
            <span className="chart-title">CPU Utilization</span>
            <span className="chart-badge">Percentage</span>
          </div>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 15, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                <XAxis dataKey="environment" stroke="#6b7280" fontSize={12} tickLine={false} />
                <YAxis stroke="#6b7280" fontSize={12} tickLine={false} unit="%" />
                <Tooltip
                  contentStyle={{ backgroundColor: '#ffffff', borderColor: '#e5e7eb', borderRadius: '6px', fontSize: '12px' }}
                  formatter={(val: any) => [`${val}%`, 'CPU Utilization']}
                />
                <Bar isAnimationActive={false} dataKey="cpuUtilizationPct" fill="#4b5563" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Individual Measured Runs */}
      <div className="card">
        <div className="card-header-row">
          <div>
            <h3 className="card-title">Individual Measured Runs</h3>
            <div className="card-subtitle">Verified runs with checksum and wall clock timing</div>
          </div>
          <span className="text-secondary" style={{ fontSize: '0.75rem' }}>{cpuRuns.length} runs</span>
        </div>

        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Environment</th>
                <th>Run ID</th>
                <th>Wall Clock</th>
                <th>User Time</th>
                <th>System Time</th>
                <th>CPU %</th>
                <th>Max RSS</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {cpuRuns.map((r, idx) => {
                const tel = r.metrics?.telemetry || {};

                return (
                  <tr key={idx}>
                    <td className="font-semibold uppercase">{r.environment}</td>
                    <td className="font-mono text-xs text-secondary">{r.run_id}</td>
                    <td className="font-mono">{tel.wall_time_sec !== undefined && tel.wall_time_sec !== null ? `${tel.wall_time_sec}s` : '—'}</td>
                    <td className="font-mono">{tel.user_time_sec !== undefined && tel.user_time_sec !== null ? `${tel.user_time_sec}s` : '—'}</td>
                    <td className="font-mono">{tel.system_time_sec !== undefined && tel.system_time_sec !== null ? `${tel.system_time_sec}s` : '—'}</td>
                    <td className="font-mono">{tel.cpu_percentage !== undefined && tel.cpu_percentage !== null ? `${tel.cpu_percentage}%` : '—'}</td>
                    <td className="font-mono">{tel.max_rss_kb ? `${Math.round(tel.max_rss_kb / 1024)} MiB` : '—'}</td>
                    <td>
                      <button className="btn-evidence-sm" onClick={() => onViewEvidence(r)}>
                        <FileSearch size={12} />
                        <span>Evidence</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
