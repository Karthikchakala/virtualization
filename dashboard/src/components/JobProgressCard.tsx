import React, { useState, useEffect } from 'react';
import { Clock, Terminal, AlertTriangle, CheckCircle2, XCircle, StopCircle, Loader2 } from 'lucide-react';
import { BenchmarkJob, api } from '../api';

interface JobProgressCardProps {
  job: BenchmarkJob | null;
  onViewLogs: (jobId: string) => void;
  onJobCancelled?: () => void;
}

export const JobProgressCard: React.FC<JobProgressCardProps> = ({
  job,
  onViewLogs,
  onJobCancelled
}) => {
  const [elapsedSec, setElapsedSec] = useState<number>(0);
  const [cancelling, setCancelling] = useState<boolean>(false);

  useEffect(() => {
    if (!job || job.status !== 'running' || !job.started_at) {
      return;
    }

    const startMs = new Date(job.started_at).getTime();
    const updateTimer = () => {
      const nowMs = Date.now();
      setElapsedSec(Math.max(0, Math.floor((nowMs - startMs) / 1000)));
    };

    updateTimer();
    const interval = setInterval(updateTimer, 1000);
    return () => clearInterval(interval);
  }, [job?.status, job?.started_at]);

  if (!job) return null;

  const handleCancel = async () => {
    if (!job) return;
    setCancelling(true);
    try {
      await api.cancelJob(job.job_id);
      if (onJobCancelled) onJobCancelled();
    } catch {
      // ignore
    } finally {
      setCancelling(false);
    }
  };

  const formatElapsed = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const s = sec % 60;
    return `${mins}m ${s < 10 ? '0' : ''}${s}s`;
  };

  const getStatusBadge = () => {
    switch (job.status) {
      case 'running':
        return (
          <span className="badge-status-running">
            <Loader2 size={12} className="animate-spin" /> Running
          </span>
        );
      case 'queued':
        return <span className="badge-status-unavail"><Clock size={12} /> Queued</span>;
      case 'completed':
        return <span className="badge-status-ready"><CheckCircle2 size={12} /> Completed</span>;
      case 'failed':
        return <span className="status-pill status-failed"><AlertTriangle size={12} /> Failed</span>;
      case 'cancelled':
        return <span className="badge-status-unavail"><XCircle size={12} /> Cancelled</span>;
      default:
        return <span className="badge-status-unavail">{job.status}</span>;
    }
  };

  const percent = job.progress?.percent || (job.status === 'completed' ? 100 : 0);
  const currentRun = job.progress?.run || 0;
  const totalRuns = job.progress?.total_runs || job.runs || 0;

  return (
    <div className="job-progress-card">
      <div className="job-progress-header">
        <div className="job-meta-left">
          <span className="job-label">Active Job:</span>
          <span className="job-id font-mono">{job.job_id}</span>
          {getStatusBadge()}
        </div>

        <div className="job-meta-right">
          {job.status === 'running' && (
            <div className="job-timer font-mono">
              <Clock size={13} />
              <span>Elapsed: {formatElapsed(elapsedSec)}</span>
            </div>
          )}

          <button
            className="btn-secondary-sm"
            onClick={() => onViewLogs(job.job_id)}
          >
            <Terminal size={13} />
            <span>View Logs</span>
          </button>

          {job.status === 'running' && (
            <button
              className="btn-danger-sm"
              onClick={handleCancel}
              disabled={cancelling}
            >
              <StopCircle size={13} />
              <span>{cancelling ? 'Stopping...' : 'Cancel Job'}</span>
            </button>
          )}
        </div>
      </div>

      <div className="job-details-grid">
        <div className="job-detail-item">
          <span className="detail-label">Benchmark</span>
          <span className="detail-val font-mono">{job.benchmark}</span>
        </div>
        <div className="job-detail-item">
          <span className="detail-label">Environment</span>
          <span className="detail-val font-mono uppercase">{job.environment}</span>
        </div>
        <div className="job-detail-item">
          <span className="detail-label">Progress</span>
          <span className="detail-val">
            {totalRuns > 0 ? `Run ${currentRun} of ${totalRuns}` : `${percent}%`}
          </span>
        </div>
        <div className="job-detail-item">
          <span className="detail-label">Status</span>
          <span className="detail-val">{job.progress?.phase || job.status}</span>
        </div>
      </div>

      <div className="progress-bar-container">
        <div className="progress-bar-track">
          <div
            className="progress-bar-fill"
            style={{ width: `${percent}%` }}
          />
        </div>
        <div className="progress-bar-meta">
          <span>{percent}% completed</span>
          {totalRuns > 0 && <span>Run {currentRun} of {totalRuns}</span>}
        </div>
      </div>

      {job.error && (
        <div className="control-alert control-alert-error" style={{ marginTop: '0.75rem' }}>
          <AlertTriangle size={14} />
          <span>{job.error}</span>
        </div>
      )}
    </div>
  );
};
