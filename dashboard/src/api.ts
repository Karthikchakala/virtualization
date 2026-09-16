/**
 * dashboard/src/api.ts - Typed API Client for CC2 Benchmark Backend.
 *
 * Communicates with the safe Python HTTP backend (default: http://localhost:8000).
 * Handles timeouts, network failures, and parsing without exposing sensitive data.
 */

export interface EnvironmentStatus {
  name: string;
  display_name: string;
  classification: string;
  status: 'available' | 'running' | 'stopped' | 'unavailable' | 'error' | string;
}

export interface BackendHealthResponse {
  status: 'healthy' | 'degraded' | string;
  timestamp: string;
  service: string;
  version: string;
  environments: Record<string, EnvironmentStatus>;
}

export interface RunBenchmarkRequest {
  environment: string;
  benchmark: string;
  mode: 'quick' | 'full';
  runs: number;
  dry_run?: boolean;
}

export interface JobProgress {
  status: string;
  environment?: string;
  benchmark?: string;
  run: number;
  total_runs: number;
  phase: string;
  percent: number;
}

export interface BenchmarkJob {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  environment: string;
  benchmark: string;
  mode: string;
  runs: number;
  created_at: string;
  started_at?: string;
  ended_at?: string;
  exit_code?: number;
  progress: JobProgress;
  result_files?: string[];
  error?: string;
  is_dry_run?: boolean;
}

export interface JobLogsResponse {
  job_id: string;
  status: string;
  stdout: string;
  stderr: string;
  sanitized: boolean;
}

export interface ResultsResponse {
  count: number;
  environment: string;
  benchmark: string;
  results: Array<Record<string, any>>;
}

export interface SummaryResponse {
  summary: Record<string, any>;
  timestamp?: string;
}

// API Base URL - defaults to backend port 8000
const API_BASE = 
  (typeof window !== 'undefined' && window.location.hostname)
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : 'http://127.0.0.1:8000';

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(options.headers || {})
    };

    const resp = await fetch(url, { ...options, headers });
    if (!resp.ok) {
      let errMsg = `HTTP Error ${resp.status}`;
      try {
        const errJson = await resp.json();
        if (errJson.error) errMsg = errJson.error;
      } catch {
        // use default message
      }
      throw new Error(errMsg);
    }

    return resp.json() as Promise<T>;
  }

  async checkHealth(): Promise<BackendHealthResponse> {
    return this.request<BackendHealthResponse>('/api/benchmarks/health');
  }

  async startBenchmark(req: RunBenchmarkRequest): Promise<BenchmarkJob> {
    return this.request<BenchmarkJob>('/api/benchmarks/run', {
      method: 'POST',
      body: JSON.stringify(req)
    });
  }

  async listJobs(): Promise<{ count: number; jobs: BenchmarkJob[] }> {
    return this.request<{ count: number; jobs: BenchmarkJob[] }>('/api/benchmarks/jobs');
  }

  async getJob(jobId: string): Promise<BenchmarkJob> {
    return this.request<BenchmarkJob>(`/api/benchmarks/jobs/${encodeURIComponent(jobId)}`);
  }

  async getJobLogs(jobId: string): Promise<JobLogsResponse> {
    return this.request<JobLogsResponse>(`/api/benchmarks/jobs/${encodeURIComponent(jobId)}/logs`);
  }

  async cancelJob(jobId: string): Promise<{ job_id: string; status: string }> {
    return this.request<{ job_id: string; status: string }>(`/api/benchmarks/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST'
    });
  }

  async getResults(environment?: string, benchmark?: string): Promise<ResultsResponse> {
    let path = '/api/benchmarks/results';
    if (environment && benchmark) {
      path = `/api/benchmarks/results/${encodeURIComponent(environment)}/${encodeURIComponent(benchmark)}`;
    }
    return this.request<ResultsResponse>(path);
  }

  async getSummary(): Promise<SummaryResponse> {
    return this.request<SummaryResponse>('/api/benchmarks/summary');
  }
}

export const api = new ApiClient();
