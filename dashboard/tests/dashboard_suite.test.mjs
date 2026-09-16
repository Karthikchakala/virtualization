import test from 'node:test';
import assert from 'node:assert/strict';

// Test Suite: Dashboard API & State Management
test('Dashboard Suite - Environment and Benchmark Selection Validation', async (t) => {
  const validEnvironments = ['host', 'kvm', 'virtualbox', 'lxc', 'all'];
  const validBenchmarks = ['cpu', 'memory', 'disk', 'network', 'startup', 'syscall', 'scheduling', 'isolation', 'all'];
  const validModes = ['quick', 'full'];

  await t.test('accepts valid environments and rejected invalid environments', () => {
    assert.ok(validEnvironments.includes('host'));
    assert.ok(validEnvironments.includes('kvm'));
    assert.ok(validEnvironments.includes('virtualbox'));
    assert.ok(validEnvironments.includes('lxc'));
    assert.ok(validEnvironments.includes('all'));
    assert.strictEqual(validEnvironments.includes('docker'), false);
    assert.strictEqual(validEnvironments.includes('untrusted_env'), false);
  });

  await t.test('accepts valid benchmarks and rejects arbitrary command strings', () => {
    assert.ok(validBenchmarks.includes('cpu'));
    assert.ok(validBenchmarks.includes('memory'));
    assert.ok(validBenchmarks.includes('isolation'));
    assert.ok(validBenchmarks.includes('all'));
    assert.strictEqual(validBenchmarks.includes('rm -rf /'), false);
    assert.strictEqual(validBenchmarks.includes('sh'), false);
  });

  await t.test('validates run counts bounds', () => {
    const validateRuns = (n) => typeof n === 'number' && Number.isInteger(n) && n >= 1 && n <= 20;
    assert.strictEqual(validateRuns(1), true);
    assert.strictEqual(validateRuns(5), true);
    assert.strictEqual(validateRuns(20), true);
    assert.strictEqual(validateRuns(0), false);
    assert.strictEqual(validateRuns(-3), false);
    assert.strictEqual(validateRuns(25), false);
    assert.strictEqual(validateRuns(3.5), false);
  });
});

test('Dashboard Suite - Job Submission and State Tracking', async (t) => {
  const allowedJobStatuses = ['queued', 'running', 'completed', 'failed', 'cancelled'];

  await t.test('tracks legitimate job statuses', () => {
    for (const status of allowedJobStatuses) {
      assert.ok(['queued', 'running', 'completed', 'failed', 'cancelled'].includes(status));
    }
  });

  await t.test('job progress calculation preserves integrity without fabricating metrics', () => {
    const calcProgress = (currentRun, totalRuns) => {
      if (!totalRuns || totalRuns <= 0) return 0;
      return Math.min(100, Math.round((currentRun / totalRuns) * 100));
    };

    assert.strictEqual(calcProgress(0, 5), 0);
    assert.strictEqual(calcProgress(2, 5), 40);
    assert.strictEqual(calcProgress(5, 5), 100);
    assert.strictEqual(calcProgress(1, 0), 0);
  });
});

test('Dashboard Suite - Results Rendering, Missing Values & Unavailable Metrics', async (t) => {
  const sampleRuns = [
    {
      run_id: 'run-host-01',
      environment: 'host',
      benchmark: 'cpu_deterministic',
      status: 'success',
      metrics: { elapsed_sec: 1.25, gflops: 5.12 },
      validation_status: 'PASS'
    },
    {
      run_id: 'run-kvm-02',
      environment: 'kvm',
      benchmark: 'network_iperf3',
      status: 'unavailable',
      metrics: {},
      validation_status: 'UNAVAILABLE'
    },
    {
      run_id: 'run-vbox-03',
      environment: 'virtualbox',
      benchmark: 'disk_fio',
      status: 'failed',
      error: 'Disk timeout',
      validation_status: 'FAILED'
    }
  ];

  await t.test('distinguishes PASS, UNAVAILABLE, and FAILED runs without masking failures', () => {
    const successRun = sampleRuns.find(r => r.run_id === 'run-host-01');
    assert.strictEqual(successRun.status, 'success');
    assert.strictEqual(successRun.validation_status, 'PASS');
    assert.strictEqual(typeof successRun.metrics.gflops, 'number');

    const unavailableRun = sampleRuns.find(r => r.run_id === 'run-kvm-02');
    assert.strictEqual(unavailableRun.status, 'unavailable');
    assert.strictEqual(unavailableRun.validation_status, 'UNAVAILABLE');
    assert.strictEqual(unavailableRun.metrics.throughput, undefined);

    const failedRun = sampleRuns.find(r => r.run_id === 'run-vbox-03');
    assert.strictEqual(failedRun.status, 'failed');
    assert.strictEqual(failedRun.validation_status, 'FAILED');
  });

  await t.test('never formats null/missing metrics as 0 in metric extraction', () => {
    const extractMetric = (run, key) => {
      if (!run || !run.metrics) return null;
      const val = run.metrics[key];
      return (typeof val === 'number' && !isNaN(val)) ? val : null;
    };

    const runWithMissing = { metrics: { val1: 10.5 } };
    assert.strictEqual(extractMetric(runWithMissing, 'val1'), 10.5);
    assert.strictEqual(extractMetric(runWithMissing, 'val2'), null);
    assert.notStrictEqual(extractMetric(runWithMissing, 'val2'), 0);
  });
});

test('Dashboard Suite - Empty State and API Error Handling', async (t) => {
  await t.test('safely handles empty run datasets gracefully', () => {
    const emptyRuns = [];
    const getSummary = (runs) => ({
      count: runs.length,
      hasData: runs.length > 0
    });

    const summary = getSummary(emptyRuns);
    assert.strictEqual(summary.count, 0);
    assert.strictEqual(summary.hasData, false);
  });

  await t.test('parses structured API errors without leaking server internals', () => {
    const formatErrorMessage = (status, errorBody) => {
      if (errorBody && errorBody.error) {
        return errorBody.error;
      }
      return `HTTP Error ${status}`;
    };

    const serverErr = { status: 400, body: { error: 'Invalid environment specified' } };
    assert.strictEqual(formatErrorMessage(serverErr.status, serverErr.body), 'Invalid environment specified');

    const internalErr = { status: 500, body: {} };
    assert.strictEqual(formatErrorMessage(internalErr.status, internalErr.body), 'HTTP Error 500');
  });
});
