export type EnvironmentType = 'host' | 'kvm' | 'virtualbox' | 'lxc';

export type BenchmarkType = 
  | 'cpu_deterministic'
  | 'memory_deterministic'
  | 'syscall_deterministic'
  | 'scheduling_deterministic'
  | 'disk_fio'
  | 'network_ping'
  | 'network_iperf3'
  | 'app_latency'
  | 'startup_lifecycle'
  | 'isolation_audit';

export interface BenchmarkRun {
  schema_version?: string;
  experiment_id?: string;
  environment: EnvironmentType | string;
  benchmark: BenchmarkType | string;
  run_id: string;
  timestamp: string;
  command: string;
  exit_code: number;
  stdout: string;
  stderr: string;
  status: 'success' | 'failed' | 'unavailable' | string;
  metrics?: Record<string, any>;
  parsed_metrics?: Record<string, any>;
}

export interface HostInventory {
  timestamp?: string;
  cpu?: {
    model_name?: string;
    architecture?: string;
    logical_cpus?: number;
    hardware_virt_support?: {
      intel_vmx?: boolean;
      amd_svm?: boolean;
    };
    scaling_governor?: string;
    flags?: string[];
  };
  memory?: {
    total_kb?: string;
    available_kb?: string;
    free_kb?: string;
    swap_total_kb?: string;
  };
  os?: {
    kernel_release?: string;
    kernel_version?: string;
    virtualization_detected?: string;
    os_release?: {
      PRETTY_NAME?: string;
      NAME?: string;
      VERSION?: string;
    };
  };
  kvm?: {
    kvm_loaded?: boolean;
    domains?: Array<{
      name: string;
      id: string;
      state: string;
    }>;
  };
  virtualbox?: {
    installed?: boolean;
    vms?: Array<{
      name: string;
      uuid: string;
    }>;
  };
  lxc?: {
    installed?: boolean;
    containers?: Array<{
      name: string;
      state: string;
    }>;
  };
  system_state?: {
    cpu_frequency?: {
      status?: string;
      per_core_khz?: Record<string, number>;
      min_khz?: number;
      max_khz?: number;
      avg_khz?: number;
    };
    cpu_governor?: {
      status?: string;
      governors?: string[];
      dominant_governor?: string;
    };
    load_average?: {
      load_1m?: number;
      load_5m?: number;
      load_15m?: number;
    };
    thermal?: {
      status?: string;
      zones?: Array<{
        zone: string;
        type: string;
        temperature_c: number;
      }>;
      max_temp_c?: number;
      package_temp_c?: number;
    };
  };
}

export type PageId =
  | 'overview'
  | 'host'
  | 'kvm'
  | 'virtualbox'
  | 'lxc'
  | 'cpu'
  | 'memory'
  | 'storage'
  | 'network'
  | 'startup'
  | 'syscalls'
  | 'isolation'
  | 'comparison'
  | 'evidence'
  | 'methodology'
  | 'raw_data';
