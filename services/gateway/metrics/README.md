# Gateway Metrics

`/metrics` in gateway remains the single Prometheus export point.

## Update model

- Runtime collectors refresh from gateway on a short interval.
- DB aggregations refresh asynchronously and populate in-memory cache.
- Prometheus scrape reads only the cache through a custom collector.

## Implemented now

- Pipeline runs, success rate, error rate, cancel rate
- Queue wait and execution latency percentiles
- Per-task status and execution duration for recent tasks
- MTTR from `ERROR -> next SUCCESS`
- Queue length and basic incoming/processing rates
- Worker alive count and approximate busy ratio
- Gateway, scheduler and task-worker-pool resource metrics
- Adoption metrics: projects created, active users, runs per active user, node type usage
- Freshness and cache health metrics
- Runtime `gateway_graph_operations_total`

## Currently unavailable from persisted sources

- Full node stability metrics
- Schedule reliability and missed runs
- Worker heartbeat gap / stale workers
- Reliable `graph_version` dimension
- Exact node-level attribution for pipeline errors

These gaps are exported via `gateway_metrics_feature_available{feature=...}`.

## Per-task export

- `gateway_pipeline_task_status{task_id,project_id,status}` exports one gauge with value `1` for each recent task.
- `gateway_pipeline_task_duration_seconds{task_id,project_id,status}` exports the execution duration for the same recent task set.
- To avoid unbounded label cardinality, per-task metrics are limited to tasks updated within the last 24 hours.
