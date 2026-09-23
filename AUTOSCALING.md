# Autoscaling in Dev Lab

Dev Lab can autoscale pods and nodes, so you can test autoscaling tools such
as KEDA and cluster-autoscaler, and test apps that depend on them. Both are
optional addons:

```bash
devlab addon enable keda node-autoscaler
devlab addon list
devlab addon disable node-autoscaler
```

`enable` is safe to re-run: it upgrades the addon in place and re-applies its
configuration. `disable node-autoscaler` removes the KWOK nodes, and their
pods go back to Pending. `disable keda` deletes every `ScaledObject` and
`ScaledJob` in the cluster first, because they cannot be removed once the
KEDA operator is gone.

| Layer | Component | Real or simulated |
|-------|-----------|-------------------|
| Pods, resource based | HorizontalPodAutoscaler + metrics-server (installed by bootstrap) | Real |
| Pods, event based | KEDA (`keda` addon) | Real |
| Nodes | cluster-autoscaler + KWOK (`node-autoscaler` addon) | Simulated nodes, real autoscaler |

## Pod Autoscaling

**HPA** works out of the box on CPU and memory, because bootstrap installs
metrics-server. See "Resource Load Testing" in the [README](./README.md).

**KEDA** scales Deployments, StatefulSets, and Jobs on external events, such
as queue length, Prometheus queries, cron schedules, or HTTP traffic. It can
scale to zero, which an HPA alone cannot. KEDA creates and drives an HPA for
each `ScaledObject`.

KEDA's operator and metrics server are scraped by the bootstrap Prometheus
(ServiceMonitors labelled `release: kube-prometheus-stack`), so metrics such as
`keda_scaler_metrics_value` are available in Grafana.

## Node Autoscaling

KinD cannot add nodes to a running cluster. The `node-autoscaler` addon runs
the real cluster-autoscaler with its `kwok` cloud provider instead:

```text
Pending pod ─► cluster-autoscaler (kwok provider)
                 │ picks a node group from the templates in
                 │ config/addons/node-autoscaler/kwok-provider.yaml
                 ▼
               creates a Node object (annotation kwok.x-k8s.io/node=fake)
                 ▼
               KWOK controller simulates its kubelet: the node becomes
               Ready, and pods bound to it report Running
                 ▼
               scheduler binds the Pending pod to the new node

Node idle for scale-down-unneeded-time ─► cluster-autoscaler deletes the node
```

The scale-up and scale-down decisions, node group limits, expanders,
PodDisruptionBudget checks, and events are the real cluster-autoscaler.
Only the nodes are fake.

**What KWOK nodes cannot do**: they run no containers. Pods on them report
`Running` and `Ready`, but have no processes, logs, `exec`, or real CPU usage.
As a result:

- Run workloads that must really execute (consumers, servers) on the real KinD
  workers.
- Use KWOK nodes for capacity, scheduling, and scaling behaviour: "does my app
  scale out, and does the cluster grow to fit it?"
- CPU-based HPA cannot drive pods on KWOK nodes, because they report no usage.
  Use KEDA triggers that measure something outside the pod (queue length,
  Prometheus, cron) instead.

**Isolation**. Nodes created by the addon have the label
`devlab.io/node-pool=kwok` and the taint `kwok-provider=true:NoSchedule`.
Only pods that tolerate the taint and select the label land on them:

```yaml
nodeSelector:
  devlab.io/node-pool: kwok
tolerations:
- key: kwok-provider
  operator: Exists
  effect: NoSchedule
```

cluster-autoscaler ignores the real KinD nodes; it never removes them.

### Configuration

| File | What it controls |
|------|------------------|
| `config/addons/node-autoscaler/kwok-provider.yaml` | Node pools: one template Node per pool, with capacity, labels, taints, and min/max size (annotations `cluster-autoscaler.kwok.nodegroup/min-count` and `max-count`) |
| `config/addons/node-autoscaler/cluster-autoscaler-values.yaml` | Autoscaler flags. Timings are shortened for the lab: a 10s scan interval, scale-down after 1 minute idle, and a 1 minute recheck of nodes that were busy (the defaults are 10 minutes and 5 minutes). Idle nodes go about 1-2 minutes after their pods |
| `config/addons/keda/values.yaml` | KEDA Helm values |

The default pool is `kwok-small`: 4 CPU, 16 GiB, 0 to 5 nodes. To add a pool,
add another Node item to the template list (with its own `kwok-nodegroup`
label value) and run `devlab addon enable node-autoscaler` again. The
cluster-autoscaler image version follows the cluster's Kubernetes minor
version (`CLUSTER_AUTOSCALER_IMAGE_TAGS` in `python/devlab.py`).

Watch the autoscaler:

```bash
devlab kubectl -n kube-system logs deploy/cluster-autoscaler -f
devlab kubectl get nodes -l devlab.io/node-pool=kwok -w
devlab kubectl get events -A --field-selector source=cluster-autoscaler
```

## Demo and Scenario Tests

`apps/autoscaling-demo/` deploys a Redis instance whose lists are work queues,
plus two KEDA-scaled workloads:

- **`queue-consumer`**: a real consumer on the KinD workers. Scales 0 to 10
  replicas on the length of the `jobs` list (5 jobs per replica).
- **`burst-workers`**: pods that only fit on the KWOK pool (1.5 CPU each, so 2
  per node). Scales 0 to 20 replicas on the length of the `burst` list (1 pod
  per item).

```bash
devlab addon enable keda node-autoscaler
apps/autoscaling-demo/scripts/test-autoscaling.sh          # all scenarios
apps/autoscaling-demo/scripts/test-autoscaling.sh burst    # one scenario
```

| Scenario | What it proves |
|----------|----------------|
| `queue` | KEDA scales a real consumer from 0 on queue length, the queue drains, and the consumer scales back to 0 |
| `burst` | KEDA adds pods, the Pending pods make cluster-autoscaler add KWOK nodes, and emptying the queue removes the pods and then the idle nodes |
| `limits` | Demand beyond the pool's max size: the pool stops at 5 nodes, the extra pods stay Pending, and cluster-autoscaler records `NotTriggerScaleUp` events |

Drive the queues by hand:

```bash
devlab kubectl -n autoscaling-demo exec deploy/redis -- redis-cli RPUSH burst 1 2 3 4
devlab kubectl -n autoscaling-demo get pods,scaledobjects,hpa
```

A full run takes about 8 minutes, most of it waiting for scale-down. Remove
the demo with `devlab kubectl delete namespace autoscaling-demo`.

## More Scenarios

These build on the same addons. None of them are implemented yet.

**Testing the autoscalers**:

1. **Several node pools and expanders**. Add a `kwok-large` pool (16 CPU) and
   compare the `least-waste`, `most-pods`, and `priority` expanders for the
   same burst.
2. **Special hardware**. Add a pool whose template advertises
   `nvidia.com/gpu: 4` in `allocatable`. Pods that request GPUs trigger that
   pool only, which tests GPU scheduling and taints without GPUs.
3. **Zones**. Give pools `topology.kubernetes.io/zone` labels and test
   `topologySpreadConstraints` and `--balance-similar-node-groups`.
4. **Slow nodes**. Add a KWOK `Stage` that delays a node's `Ready` condition
   by 60-90 seconds to mimic cloud VM boot time, and measure how the app's
   backlog grows while nodes provision.
5. **Blocked scale-down**. Check that cluster-autoscaler keeps a node when a
   pod has a PodDisruptionBudget with `maxUnavailable: 0`, the annotation
   `cluster-autoscaler.kubernetes.io/safe-to-evict: "false"`, or the node has
   `cluster-autoscaler.kubernetes.io/scale-down-disabled: "true"`.
6. **Scale at size**. Raise a pool's max to hundreds of nodes and check how
   operators, the scheduler, and Prometheus behave with a large node count.
   KWOK nodes cost almost nothing.

**Testing apps that depend on autoscaling**:

1. **Prometheus-driven scaling**. Scale on application metrics (request rate,
   latency, or a custom `in_flight_jobs` gauge) with KEDA's `prometheus`
   trigger against `http://kube-prometheus-stack-prometheus.monitoring:9090`.
2. **HTTP scale to zero**. Add the KEDA HTTP add-on behind Traefik and measure
   cold-start latency and request buffering for an app that idles at 0.
3. **Batch jobs**. Use a `ScaledJob` that runs one Job per queue message.
   KWOK's `pod-complete` stage finishes Jobs on fake nodes, so the job
   lifecycle and node scale-down can run at high counts.
4. **Scheduled load**. Use the `cron` trigger to scale up before a known peak,
   and check that the app is warm when the load arrives.
5. **Graceful scale-down**. Check that consumers finish or requeue in-flight
   work on SIGTERM (`preStop` hooks, `terminationGracePeriodSeconds`) when KEDA
   scales them in. Include a scenario that kills pods mid-job.
6. **Disruption**. Delete a KWOK node that holds replicas
   (`devlab kubectl delete node <name>`). This tests replica counts, PDBs, and
   rescheduling while cluster-autoscaler replaces the capacity.
7. **Dashboards and alerts**. Build a Grafana dashboard that shows queue
   length, KEDA's target value, replicas, Pending pods, and node count, and
   add alerts for "Pending for too long" and "pool at max size".
