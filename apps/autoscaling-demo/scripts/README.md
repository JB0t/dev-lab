# scripts

<!-- docgen:begin id=apps/autoscaling-demo/scripts:overview scope=apps/autoscaling-demo/scripts hash=3b1452f789c0 -->
This module provides a script for testing autoscaling scenarios in a Kubernetes cluster configured with the dev-lab environment. It automates the execution of predefined test cases that validate the behavior of KEDA and cluster-autoscaler components under different load conditions. The script supports running individual scenarios or all scenarios sequentially, ensuring that autoscaling functionality works as expected in various situations.

The script defines helper functions for interacting with Kubernetes resources, such as checking deployment readiness, counting pods, and managing Redis queues. It also includes predicates and utility functions for waiting on specific conditions, like replica counts or pod phases, which are used to assert expected states during test execution. These utilities make it easier to write reliable and readable tests for complex autoscaling behaviors.

The main test scenarios cover queue-based scaling using KEDA, burst scaling that triggers node addition via cluster-autoscaler, and limit-based scaling that tests the maximum capacity of a node pool. Each scenario is designed to validate a specific aspect of the autoscaling system, from scaling out on demand to handling resource constraints and scaling back in when idle. The script ensures prerequisites are met before running tests and provides clear pass/fail feedback for each step.
<!-- docgen:end id=apps/autoscaling-demo/scripts:overview -->

<!-- docgen:begin id=apps/autoscaling-demo/scripts:reference scope=apps/autoscaling-demo/scripts hash=3b1452f789c0 -->
## Reference

### `test-autoscaling.sh`

- **`test-autoscaling.sh`** (script): Autoscaling scenario tests for the dev-lab cluster.
- **`kubectl`** (function)
- **`redis`** (function)
- **`log`** (function)
- **`pass`** (function)
- **`fail`** (function)
- **`wait_for`** (function): wait_for &lt;description> &lt;timeout seconds> &lt;command...>
- **`ready_replicas`** (function)
- **`pod_count`** (function)
- **`kwok_nodes`** (function)
- **`list_length`** (function)
- **`replicas_at_least`** (function): Predicates for wait_for
- **`running_at_least`** (function)
- **`no_pods`** (function)
- **`list_empty`** (function)
- **`no_kwok_nodes`** (function)
- **`check_prerequisites`** (function)
- **`scenario_queue`** (function)
- **`scenario_burst`** (function)
- **`scenario_limits`** (function)
<!-- docgen:end id=apps/autoscaling-demo/scripts:reference -->
