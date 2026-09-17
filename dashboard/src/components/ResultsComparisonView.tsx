import React, { useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend
} from 'recharts';
import {
  Table, BarChart2, CheckCircle2, AlertTriangle, XCircle, Info, ExternalLink
} from 'lucide-react';
import { BenchmarkRun } from '../types';

interface ResultsComparisonViewProps {
  runs: BenchmarkRun[];
  onViewEvidence: (run: BenchmarkRun) => void;
}

interface TableRowData {
  environment: string;
  benchmark: string;
  metric: string;
  unit: string;
  mean: number | null;
  median: number | null;
  min: number | null;
  max: number | null;
  stdDev: number | null;
  p50: number | null;
  p95: number | null;
  p99: number | null;
  runsCount: number;
  status: string;
  quality: 'PASS' | 'WARNING' | 'FAILED' | 'UNAVAILABLE';
  rawRun?: BenchmarkRun;
}

export const ResultsComparisonView: React.FC<ResultsComparisonViewProps> = ({
  runs,
  onViewEvidence
}) => {
  const [activeTab, setActiveTab] = useState<'charts' | 'table'>('charts');
  const [selectedDomain, setSelectedDomain] = useState<string>('all');

  // Palette: professional, consistent across charts
  const envColors = {
    Host: '#4b5563',
    KVM: '#2563eb',
    VirtualBox: '#0284c7',
    LXC: '#16a34a'
  };

  // Helper to extract numeric metrics
  const getMetricValue = (run: BenchmarkRun, key: string): number | null => {
    if (!run || !run.metrics) return null;
    const val = run.metrics[key];
    if (typeof val === 'number' && !isNaN(val)) return val;
    if (run.parsed_metrics && typeof run.parsed_metrics[key] === 'number') {
      return run.parsed_metrics[key];
    }
    return null;
  };

  const environments = ['host', 'kvm', 'virtualbox', 'lxc'];

  const getEnvStats = (env: string, bench: string, metricKey: string) => {
    const envRuns = runs.filter(r => r.environment === env && r.benchmark === bench && r.status === 'success');
    const values = envRuns
      .map(r => getMetricValue(r, metricKey))
      .filter((v): v is number => v !== null);

    if (values.length === 0) return null;
    const sum = values.reduce((a, b) => a + b, 0);
    const mean = sum / values.length;
    return parseFloat(mean.toFixed(2));
  };

  // Chart 1: CPU Deterministic
  const cpuChartData = [
    {
      metric: 'Elapsed Time',
      unit: 's',
      Host: getEnvStats('host', 'cpu_deterministic', 'elapsed_sec') || getEnvStats('host', 'cpu_deterministic', 'wall_time_sec'),
      KVM: getEnvStats('kvm', 'cpu_deterministic', 'elapsed_sec') || getEnvStats('kvm', 'cpu_deterministic', 'wall_time_sec'),
      VirtualBox: getEnvStats('virtualbox', 'cpu_deterministic', 'elapsed_sec') || getEnvStats('virtualbox', 'cpu_deterministic', 'wall_time_sec'),
      LXC: getEnvStats('lxc', 'cpu_deterministic', 'elapsed_sec') || getEnvStats('lxc', 'cpu_deterministic', 'wall_time_sec')
    },
    {
      metric: 'GFLOPS',
      unit: 'GFLOPS',
      Host: getEnvStats('host', 'cpu_deterministic', 'gflops'),
      KVM: getEnvStats('kvm', 'cpu_deterministic', 'gflops'),
      VirtualBox: getEnvStats('virtualbox', 'cpu_deterministic', 'gflops'),
      LXC: getEnvStats('lxc', 'cpu_deterministic', 'gflops')
    }
  ];

  // Chart 2: Memory Subsystem
  const memoryChartData = [
    {
      metric: 'Sequential Write',
      unit: 'MB/s',
      Host: getEnvStats('host', 'memory_deterministic', 'write_mb_s') || getEnvStats('host', 'memory_deterministic', 'throughput_mb_s'),
      KVM: getEnvStats('kvm', 'memory_deterministic', 'write_mb_s') || getEnvStats('kvm', 'memory_deterministic', 'throughput_mb_s'),
      VirtualBox: getEnvStats('virtualbox', 'memory_deterministic', 'write_mb_s') || getEnvStats('virtualbox', 'memory_deterministic', 'throughput_mb_s'),
      LXC: getEnvStats('lxc', 'memory_deterministic', 'write_mb_s') || getEnvStats('lxc', 'memory_deterministic', 'throughput_mb_s')
    }
  ];

  // Chart 3: Kernel Latency & Context Switching
  const latencyChartData = [
    {
      metric: 'Syscall Latency',
      unit: 'ns',
      Host: getEnvStats('host', 'syscall_deterministic', 'latency_ns'),
      KVM: getEnvStats('kvm', 'syscall_deterministic', 'latency_ns'),
      VirtualBox: getEnvStats('virtualbox', 'syscall_deterministic', 'latency_ns'),
      LXC: getEnvStats('lxc', 'syscall_deterministic', 'latency_ns')
    },
    {
      metric: 'Context Switch Latency',
      unit: 'μs',
      Host: getEnvStats('host', 'scheduling_deterministic', 'latency_us'),
      KVM: getEnvStats('kvm', 'scheduling_deterministic', 'latency_us'),
      VirtualBox: getEnvStats('virtualbox', 'scheduling_deterministic', 'latency_us'),
      LXC: getEnvStats('lxc', 'scheduling_deterministic', 'latency_us')
    }
  ];

  // Chart 4: Cold Startup Duration
  const startupChartData = [
    {
      metric: 'Cold Startup Duration',
      unit: 's',
      Host: getEnvStats('host', 'startup_lifecycle', 'total_startup_sec'),
      KVM: getEnvStats('kvm', 'startup_lifecycle', 'total_startup_sec'),
      VirtualBox: getEnvStats('virtualbox', 'startup_lifecycle', 'total_startup_sec'),
      LXC: getEnvStats('lxc', 'startup_lifecycle', 'total_startup_sec')
    }
  ];

  // Build Tabular Rows with statistical summaries
  const buildTableData = (): TableRowData[] => {
    const rows: TableRowData[] = [];
    const metricDefs: Array<{ bench: string; key: string; label: string; unit: string }> = [
      { bench: 'cpu_deterministic', key: 'gflops', label: 'GFLOPS', unit: 'GFLOPS' },
      { bench: 'cpu_deterministic', key: 'elapsed_sec', label: 'Elapsed Time', unit: 's' },
      { bench: 'memory_deterministic', key: 'throughput_mb_s', label: 'Throughput', unit: 'MB/s' },
      { bench: 'syscall_deterministic', key: 'latency_ns', label: 'Syscall Latency', unit: 'ns' },
      { bench: 'scheduling_deterministic', key: 'latency_us', label: 'Context Switch Latency', unit: 'μs' },
      { bench: 'scheduling_deterministic', key: 'switches_per_sec', label: 'Switches/Sec', unit: 'switches/s' },
      { bench: 'network_ping', key: 'rtt_avg_ms', label: 'Average RTT', unit: 'ms' },
      { bench: 'disk_fio', key: 'read_iops', label: 'Read IOPS', unit: 'IOPS' },
      { bench: 'disk_fio', key: 'write_iops', label: 'Write IOPS', unit: 'IOPS' },
      { bench: 'network_iperf3', key: 'sender_bandwidth_mbps', label: 'Bandwidth', unit: 'Mbps' },
      { bench: 'startup_lifecycle', key: 'total_startup_sec', label: 'Startup Duration', unit: 's' }
    ];

    environments.forEach(env => {
      metricDefs.forEach(def => {
        if (selectedDomain !== 'all' && def.bench !== selectedDomain) return;

        const matchingRuns = runs.filter(r => r.environment === env && r.benchmark === def.bench);
        const validValues = matchingRuns
          .filter(r => r.status === 'success')
          .map(r => getMetricValue(r, def.key))
          .filter((v): v is number => v !== null);

        let quality: 'PASS' | 'WARNING' | 'FAILED' | 'UNAVAILABLE' = 'PASS';
        let statusStr = 'success';

        if (matchingRuns.length === 0) {
          quality = 'UNAVAILABLE';
          statusStr = 'unavailable';
        } else if (validValues.length === 0) {
          const hasUnavailable = matchingRuns.some(r => r.status === 'unavailable');
          quality = hasUnavailable ? 'UNAVAILABLE' : 'FAILED';
          statusStr = hasUnavailable ? 'unavailable' : 'failed';
        }

        let mean: number | null = null;
        let median: number | null = null;
        let min: number | null = null;
        let max: number | null = null;
        let stdDev: number | null = null;
        let p50: number | null = null;
        let p95: number | null = null;
        let p99: number | null = null;

        if (validValues.length > 0) {
          const sorted = [...validValues].sort((a, b) => a - b);
          min = sorted[0];
          max = sorted[sorted.length - 1];
          const sum = sorted.reduce((a, b) => a + b, 0);
          mean = parseFloat((sum / sorted.length).toFixed(4));
          const mid = Math.floor(sorted.length / 2);
          median = sorted.length % 2 !== 0 ? sorted[mid] : parseFloat(((sorted[mid - 1] + sorted[mid]) / 2).toFixed(4));
          p50 = median;
          const idx95 = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
          p95 = sorted[idx95];
          const idx99 = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.99));
          p99 = sorted[idx99];

          if (sorted.length > 1) {
            const variance = sorted.reduce((acc, val) => acc + Math.pow(val - (mean as number), 2), 0) / (sorted.length - 1);
            stdDev = parseFloat(Math.sqrt(variance).toFixed(4));
            const cv = (stdDev / (mean as number)) * 100;
            if (cv > 25) quality = 'WARNING';
          }
        }

        rows.push({
          environment: env,
          benchmark: def.bench,
          metric: def.label,
          unit: def.unit,
          mean,
          median,
          min,
          max,
          stdDev,
          p50,
          p95,
          p99,
          runsCount: matchingRuns.length,
          status: statusStr,
          quality,
          rawRun: matchingRuns[0]
        });
      });
    });

    return rows;
  };

  const tableData = buildTableData();

  const renderQualityBadge = (quality: string) => {
    switch (quality) {
      case 'PASS':
        return <span className="status-pill status-pass"><CheckCircle2 size={12} /> Pass</span>;
      case 'WARNING':
        return <span className="status-pill" style={{ background: 'var(--status-warning-bg)', color: 'var(--status-warning-text)', borderColor: 'var(--status-warning-border)' }}><AlertTriangle size={12} /> Warning</span>;
      case 'FAILED':
        return <span className="status-pill status-failed"><XCircle size={12} /> Failed</span>;
      case 'UNAVAILABLE':
      default:
        return <span className="status-pill status-unavailable"><Info size={12} /> Unavailable</span>;
    }
  };

  const formatCell = (val: number | null, unit: string) => {
    if (val === null || val === undefined) {
      return <span className="text-muted font-mono">—</span>;
    }
    return <span className="font-mono">{val.toLocaleString()} <span className="text-muted text-xs">{unit}</span></span>;
  };

  return (
    <div className="results-comparison-card">
      <div className="results-header-row">
        <div>
          <h2 className="section-title">Benchmark Results & Statistical Validation</h2>
          <span className="section-subtitle">
            Empirical measurements across virtualization adapters without subjective rankings or overall scores.
          </span>
        </div>

        <div className="view-toggle-group">
          <button
            className={`view-toggle-btn ${activeTab === 'charts' ? 'view-active' : ''}`}
            onClick={() => setActiveTab('charts')}
          >
            <BarChart2 size={14} /> Charts
          </button>
          <button
            className={`view-toggle-btn ${activeTab === 'table' ? 'view-active' : ''}`}
            onClick={() => setActiveTab('table')}
          >
            <Table size={14} /> Statistical Table
          </button>
        </div>
      </div>

      {activeTab === 'charts' ? (
        <div className="charts-view-container">
          <div className="grid-cols-2">
            {/* Chart 1: CPU Deterministic */}
            <div className="chart-box">
              <div className="chart-title-bar">
                <span className="chart-title">CPU Performance (Matrix GEMM)</span>
                <span className="chart-badge">400x400 Float64</span>
              </div>
              <div style={{ height: 240 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={cpuChartData} margin={{ top: 15, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                    <XAxis dataKey="metric" stroke="#6b7280" fontSize={12} tickLine={false} />
                    <YAxis stroke="#6b7280" fontSize={12} tickLine={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#ffffff', borderColor: '#e5e7eb', borderRadius: '6px', fontSize: '12px' }}
                      formatter={(val: any, name: any, item: any) => [`${val} ${item.payload.unit}`, name]}
                    />
                    <Legend />
                    <Bar isAnimationActive={false} dataKey="Host" fill={envColors.Host} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="KVM" fill={envColors.KVM} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="VirtualBox" fill={envColors.VirtualBox} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="LXC" fill={envColors.LXC} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Chart 2: Memory Subsystem */}
            <div className="chart-box">
              <div className="chart-title-bar">
                <span className="chart-title">Memory Bandwidth</span>
                <span className="chart-badge">128 MB Buffer</span>
              </div>
              <div style={{ height: 240 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={memoryChartData} margin={{ top: 15, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                    <XAxis dataKey="metric" stroke="#6b7280" fontSize={12} tickLine={false} />
                    <YAxis stroke="#6b7280" fontSize={12} tickLine={false} unit=" MB/s" />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#ffffff', borderColor: '#e5e7eb', borderRadius: '6px', fontSize: '12px' }}
                      formatter={(val: any, name: any, item: any) => [`${val} ${item.payload.unit}`, name]}
                    />
                    <Legend />
                    <Bar isAnimationActive={false} dataKey="Host" fill={envColors.Host} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="KVM" fill={envColors.KVM} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="VirtualBox" fill={envColors.VirtualBox} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="LXC" fill={envColors.LXC} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Chart 3: Kernel Latency & Context Switching */}
            <div className="chart-box">
              <div className="chart-title-bar">
                <span className="chart-title">Syscall & Scheduling Overhead</span>
                <span className="chart-badge">strace & Pipe Switch</span>
              </div>
              <div style={{ height: 240 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={latencyChartData} margin={{ top: 15, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                    <XAxis dataKey="metric" stroke="#6b7280" fontSize={12} tickLine={false} />
                    <YAxis stroke="#6b7280" fontSize={12} tickLine={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#ffffff', borderColor: '#e5e7eb', borderRadius: '6px', fontSize: '12px' }}
                      formatter={(val: any, name: any, item: any) => [`${val} ${item.payload.unit}`, name]}
                    />
                    <Legend />
                    <Bar isAnimationActive={false} dataKey="Host" fill={envColors.Host} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="KVM" fill={envColors.KVM} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="VirtualBox" fill={envColors.VirtualBox} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="LXC" fill={envColors.LXC} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Chart 4: Cold Startup Duration */}
            <div className="chart-box">
              <div className="chart-title-bar">
                <span className="chart-title">Cold Startup Duration</span>
                <span className="chart-badge">Boot to App Ready</span>
              </div>
              <div style={{ height: 240 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={startupChartData} margin={{ top: 15, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                    <XAxis dataKey="metric" stroke="#6b7280" fontSize={12} tickLine={false} />
                    <YAxis stroke="#6b7280" fontSize={12} tickLine={false} unit=" s" />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#ffffff', borderColor: '#e5e7eb', borderRadius: '6px', fontSize: '12px' }}
                      formatter={(val: any, name: any, item: any) => [`${val} ${item.payload.unit}`, name]}
                    />
                    <Legend />
                    <Bar isAnimationActive={false} dataKey="Host" fill={envColors.Host} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="KVM" fill={envColors.KVM} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="VirtualBox" fill={envColors.VirtualBox} radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="LXC" fill={envColors.LXC} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* Statistical Table View */
        <div className="results-table-container">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
            <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>Filter Workload:</span>
            <select
              value={selectedDomain}
              onChange={e => setSelectedDomain(e.target.value)}
              className="filter-select"
            >
              <option value="all">All Domains</option>
              <option value="cpu_deterministic">CPU Deterministic</option>
              <option value="memory_deterministic">Memory Subsystem</option>
              <option value="syscall_deterministic">Syscall Latency</option>
              <option value="scheduling_deterministic">Scheduling Latency</option>
              <option value="network_ping">Network Ping</option>
              <option value="disk_fio">Disk FIO</option>
              <option value="startup_lifecycle">Startup Lifecycle</option>
            </select>
          </div>

          <div className="table-scroll-wrapper">
            <table className="results-data-table">
              <thead>
                <tr>
                  <th>Environment</th>
                  <th>Benchmark</th>
                  <th>Metric</th>
                  <th>Mean</th>
                  <th>Median</th>
                  <th>Min</th>
                  <th>Max</th>
                  <th>Std Dev</th>
                  <th>p95</th>
                  <th>p99</th>
                  <th>Runs</th>
                  <th>Status</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {tableData.map((row, idx) => (
                  <tr key={`${row.environment}-${row.benchmark}-${row.metric}-${idx}`}>
                    <td className="font-semibold uppercase">{row.environment}</td>
                    <td className="font-mono text-xs">{row.benchmark}</td>
                    <td>{row.metric}</td>
                    <td>{formatCell(row.mean, row.unit)}</td>
                    <td>{formatCell(row.median, row.unit)}</td>
                    <td>{formatCell(row.min, row.unit)}</td>
                    <td>{formatCell(row.max, row.unit)}</td>
                    <td>{formatCell(row.stdDev, row.unit)}</td>
                    <td>{formatCell(row.p95, row.unit)}</td>
                    <td>{formatCell(row.p99, row.unit)}</td>
                    <td className="font-mono">{row.runsCount}</td>
                    <td>{renderQualityBadge(row.quality)}</td>
                    <td>
                      {row.rawRun && (
                        <button
                          className="btn-evidence-link"
                          onClick={() => onViewEvidence(row.rawRun!)}
                          title="View raw evidence"
                        >
                          <ExternalLink size={12} />
                          <span className="font-mono text-xs">{row.rawRun.run_id.slice(-8)}</span>
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
