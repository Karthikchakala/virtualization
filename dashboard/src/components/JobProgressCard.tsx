import React, { useState, useEffect } from 'react';
import { Activity, Clock, Terminal, AlertTriangle, CheckCircle, XCircle, StopCircle } from 'lucide-react';
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
        return <span className="badge-job-running"><Clock size={12} className="animate-spin" /> RUNNING</span>;
      case 'queued':
        return <span className="badge-job-queued"><Clock size={12} /> QUEUED</span>;
      case 'completed':
        return <span className="badge-job-completed"><CheckCircle size={12} /> COMPLETED</span>;
      case 'failed':
        return <span className="badge-job-failed"><AlertTriangle size={12} /> FAILED</span>;
      case 'cancelled':
        return <span className="badge-job-cancelled"><XCircle size={12} /> CANCELLED</span>;
      default:
        return <span className="badge-job-default">{String(job.status).toUpperCase()}</span>;
    }
  };

  const percent = job.progress?.percent || (job.status === 'completed' ? 100 : 0);
  const phase = job.progress?.phase || 'initializing';

  return (
    <div className="job-progress-card">
      <div className="job-progress-header">
        <div className="job-meta-left">
          <Activity size={16} color="var(--accent-cyan)" />
          <div>
            <span className="job-label">Active Experiment Job:</span>
            <span className="job-id font-mono">{job.job_id}</span>
          </div>
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
            className="btn-secondary-sm font-mono"
            onClick={() => onViewLogs(job.job_id)}
          >
            <Terminal size={13} /> View Logs
          </button>

          {job.status === 'running' && (
            <button
              className="btn-danger-sm font-mono"
              onClick={handleCancel}
              disabled={cancelling}
            >
              <StopCircle size={13} /> {cancelling ? 'Stopping...' : 'Cancel'}
            </button>
          )}
        </div>
      </div>

      <div className="job-progress-body">
        <div className="job-details-grid">
          <div className="job-detail-item">
            <span className="detail-label">ENVIRONMENT</span>
            <span className="detail-val font-mono uppercase">{job.environment}</span>
          </div>
          <div className="job-detail-item">
            <span className="detail-label">BENCHMARK</span>
            <span className="detail-val font-mono">{job.benchmark}</span>
          </div>
          <div className="job-detail-item">
            <span className="detail-label">MODE / RUNS</span>
            <span className="detail-val font-mono uppercase">{job.mode} ({job.runs} runs)</span>
          </div>
          <div className="job-detail-item">
            <span className="detail-label">CURRENT PHASE</span>
            <span className="detail-val font-mono text-cyan">{phase}</span>
          </div>
        </div>

        <div className="progress-bar-container">
          <div className="progress-bar-track">
            <div 
              className={`progress-bar-fill ${job.status === 'running' ? 'progress-animated' : ''}`}
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className="progress-bar-meta font-mono">
            <span>Progress: {percent}%</span>
            {job.progress && job.progress.total_runs > 0 && (
              <span>Iteration: {job.progress.run} / {job.progress.total_runs}</span>
            )}
          </div>
        </div>

        {job.error && (
          <div className="job-error-banner font-mono">
            <AlertTriangle size={14} />
            <span>{job.error}</span>
          </div>
        )}
      </div>
    </div>
  );
};
