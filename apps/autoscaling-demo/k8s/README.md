# k8s

<!-- docgen:begin id=apps/autoscaling-demo/k8s:overview scope=apps/autoscaling-demo/k8s hash=fb311e5444c4 -->
This module defines Kubernetes manifests for an autoscaling demonstration, using KEDA (Kubernetes Event-Driven Autoscaling) to scale workloads based on Redis queue lengths. It includes configurations for two distinct scaling scenarios: one where pods are scaled based on the length of a Redis list, and another that simulates burst workloads requiring specific node pools.

The manifests are organized into three main components: a Redis instance acting as a work queue, a queue consumer deployment that processes jobs from the Redis list with KEDA-driven scaling, and a burst workers deployment that scales based on another Redis list but requires specific node labels and tolerations to run on simulated KWOK nodes.

The `kustomization.yaml` file ties together all the individual manifests into a single deployable unit, ensuring the Redis instance, queue consumer, and burst workers are all created within the `autoscaling-demo` namespace. The Redis deployment and service provide the queue infrastructure, while the `ScaledObject` resources define the scaling policies for both the queue consumer and burst workers based on Redis list lengths.
<!-- docgen:end id=apps/autoscaling-demo/k8s:overview -->

<!-- docgen:begin id=apps/autoscaling-demo/k8s:reference scope=apps/autoscaling-demo/k8s hash=fb311e5444c4 -->
## Reference

### `burst-workers.yaml`

- **`Deployment/burst-workers`** (manifest)
- **`ScaledObject/burst-workers`** (manifest)

### `kustomization.yaml`

- **`Kustomization/`** (manifest)

### `queue-consumer.yaml`

- **`Deployment/queue-consumer`** (manifest)
- **`ScaledObject/queue-consumer`** (manifest)

### `redis.yaml`

- **`Namespace/autoscaling-demo`** (manifest)
- **`Deployment/redis`** (manifest)
- **`Service/redis`** (manifest)
<!-- docgen:end id=apps/autoscaling-demo/k8s:reference -->
