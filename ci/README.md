# ci

<!-- docgen:begin id=ci:overview scope=ci hash=0c4481ae9e07 -->
The `ci` module provides infrastructure and scripts for running continuous integration workflows with dev-lab, focusing on executing tests and deployments in a containerized environment that mimics GitLab's Kubernetes-executor setup. It includes configurations and helper scripts to bootstrap a dev-lab cluster within CI jobs or local execution environments, ensuring consistent behavior across different execution contexts.

At its core, the module defines how CI jobs are structured through reusable templates and setup procedures. The `devlab-ci-setup.sh` script is sourced in CI environments to configure the necessary environment variables, install dependencies, and bootstrap the dev-lab cluster using the specified profile. It also handles certificate management for environments using TLS inspection, ensuring that the Docker daemon and other tools trust the required root CA certificates.

The `run-local.sh` script enables local reproduction of the CI environment by spinning up a privileged Docker-in-Docker (dind) container and a job container that share a network namespace and a volume, closely replicating how GitLab runners execute jobs. This allows developers to test CI workflows locally without needing a GitLab instance. The module's components work together to support both automated CI pipelines and local development workflows, with shared logic encapsulated in `devlab-ci-setup.sh` and execution orchestrated by `run-local.sh`.
<!-- docgen:end id=ci:overview -->

<!-- docgen:begin id=ci:reference scope=ci hash=0c4481ae9e07 -->
## Reference

### `devlab-ci-setup.sh`

- **`devlab-ci-setup.sh`** (script): Source this in a CI job (POSIX sh) to set up and bootstrap dev-lab. Used by ci/devlab.gitlab-ci.yml and ci/run-local.sh.

### `run-local.sh`

- **`run-local.sh`** (script): Run the CI profile locally the way a GitLab Kubernetes-executor job runs it: a privileged docker:dind "service" container and a job container that share one network namespace (like containers in a pod) and a /builds volume.
- **`cleanup`** (function)
<!-- docgen:end id=ci:reference -->
