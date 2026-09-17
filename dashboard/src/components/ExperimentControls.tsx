import React, { useState } from 'react';
import { Play, RefreshCw, AlertCircle, CheckCircle2, Sliders } from 'lucide-react';
import { api, RunBenchmarkRequest, BenchmarkJob } from '../api';

interface ExperimentControlsProps {
  isJobRunning: boolean;
  onJobStarted: (job: BenchmarkJob) => void;
  onRefreshResults: () => void;
  isRefreshing?: boolean;
}

export const ExperimentControls: React.FC<ExperimentControlsProps> = ({
  isJobRunning,
  onJobStarted,
  onRefreshResults,
  isRefreshing = false
}) => {
  const [environment, setEnvironment] = useState<string>('host');
  const [benchmark, setBenchmark] = useState<string>('cpu');
  const [mode, setMode] = useState<'quick' | 'full'>('quick');
  const [runs, setRuns] = useState<number>(2);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const handleModeChange = (newMode: 'quick' | 'full') => {
    setMode(newMode);
    setRuns(newMode === 'quick' ? 2 : 5);
  };

  const handleStart = async () => {
    setErrorMsg(null);
    setSuccessMsg(null);

    if (runs < 1 || runs > 20) {
      setErrorMsg('Runs must be a valid integer between 1 and 20.');
      return;
    }

    setSubmitting(true);
    try {
      const req: RunBenchmarkRequest = {
        environment,
        benchmark,
        mode,
        runs
      };
      const job = await api.startBenchmark(req);
      setSuccessMsg(`Benchmark job started successfully (Job ID: ${job.job_id})`);
      onJobStarted(job);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to start benchmark job.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="experiment-controls-card">
      <div className="controls-header">
        <div className="controls-title-group">
          <Sliders size={18} color="var(--accent-primary)" />
          <div>
            <div className="controls-title">Benchmark Controls</div>
            <div className="controls-subtitle">Configure and run benchmarks across environments</div>
          </div>
        </div>
      </div>

      <div className="controls-form-grid">
        {/* Environment Selector */}
        <div className="control-group">
          <label className="control-field-label">Target Environment</label>
          <select
            value={environment}
            onChange={e => setEnvironment(e.target.value)}
            disabled={isJobRunning || submitting}
            className="control-input"
          >
            <option value="host">Host Baseline (Bare-Metal)</option>
            <option value="kvm">KVM / QEMU (Type-1)</option>
            <option value="virtualbox">Oracle VirtualBox (Type-2)</option>
            <option value="lxc">Native LXC (OS Containers)</option>
            <option value="all">All Environments (Sequential)</option>
          </select>
        </div>

        {/* Benchmark Selector */}
        <div className="control-group">
          <label className="control-field-label">Benchmark Workload</label>
          <select
            value={benchmark}
            onChange={e => setBenchmark(e.target.value)}
            disabled={isJobRunning || submitting}
            className="control-input"
          >
            <option value="all">All Workloads (Comprehensive)</option>
            <option value="cpu">CPU Deterministic (GEMM)</option>
            <option value="memory">Memory Subsystem (Throughput)</option>
            <option value="disk">Disk FIO (Safe Regular File)</option>
            <option value="network">Network Ping (RTT Latency)</option>
            <option value="startup">Startup Lifecycle (Cold Boot)</option>
            <option value="syscall">Syscall Latency (strace)</option>
            <option value="scheduling">Scheduling Latency (Context Switches)</option>
            <option value="isolation">Isolation Audit (Namespaces)</option>
          </select>
        </div>

        {/* Protocol Mode */}
        <div className="control-group">
          <label className="control-field-label">Protocol Mode</label>
          <div className="mode-toggle-group">
            <button
              type="button"
              className={`mode-toggle-btn ${mode === 'quick' ? 'mode-active-quick' : ''}`}
              onClick={() => handleModeChange('quick')}
              disabled={isJobRunning || submitting}
            >
              Quick (2 runs)
            </button>
            <button
              type="button"
              className={`mode-toggle-btn ${mode === 'full' ? 'mode-active-full' : ''}`}
              onClick={() => handleModeChange('full')}
              disabled={isJobRunning || submitting}
            >
              Full (5 runs)
            </button>
          </div>
        </div>

        {/* Runs Input */}
        <div className="control-group">
          <label className="control-field-label">Measured Runs</label>
          <input
            type="number"
            min={1}
            max={20}
            value={runs}
            onChange={e => setRuns(Math.max(1, Math.min(20, parseInt(e.target.value) || 1)))}
            disabled={isJobRunning || submitting}
            className="control-input"
          />
        </div>
      </div>

      {/* Action Buttons */}
      <div className="controls-actions-row">
        <div className="actions-left">
          <button
            className="btn-primary"
            onClick={handleStart}
            disabled={isJobRunning || submitting}
          >
            {submitting ? (
              <>
                <RefreshCw size={15} className="animate-spin" />
                <span>Starting...</span>
              </>
            ) : isJobRunning ? (
              <>
                <RefreshCw size={15} className="animate-spin" />
                <span>Benchmark in Progress...</span>
              </>
            ) : (
              <>
                <Play size={15} />
                <span>Start Benchmark</span>
              </>
            )}
          </button>

          <button
            className="btn-secondary"
            onClick={onRefreshResults}
            disabled={isRefreshing}
          >
            <RefreshCw size={15} className={isRefreshing ? 'animate-spin' : ''} />
            <span>Refresh Results</span>
          </button>
        </div>
      </div>

      {/* Status Messages */}
      {errorMsg && (
        <div className="control-alert control-alert-error">
          <AlertCircle size={15} />
          <span>{errorMsg}</span>
        </div>
      )}

      {successMsg && (
        <div className="control-alert control-alert-success">
          <CheckCircle2 size={15} />
          <span>{successMsg}</span>
        </div>
      )}
    </div>
  );
};
