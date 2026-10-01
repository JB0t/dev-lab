# Running Dev Lab in CI

The `ci` profile runs the lab inside a pipeline job, so a pipeline can test
against a real cluster: build and push images, deploy, and run end-to-end or
autoscaling tests. It targets GitLab runners that use the Kubernetes executor,
where the job itself is a pod, and it works anywhere a Docker daemon is
available.

## How It Works

A job pod cannot run KinD by itself: KinD needs a Docker daemon, and the
cluster nodes are containers. The job therefore gets a Docker-in-Docker
(`docker:dind`) service, and devlab builds the whole lab inside that daemon:

```text
job pod (GitLab Kubernetes executor)
├── job container (docker:29-cli)     runs devlab, kubectl, tests
│     DOCKER_HOST=tcp://docker:2375
├── service container (docker:29-dind, privileged)
│     └── dev-lab-control-plane, dev-lab-worker  (KinD nodes)
│           └── Traefik, registry, metrics-server, addons, your workloads
└── shared: network namespace (localhost) and the /builds volume
```

Two properties of the pod make this work:

- **Shared network**. Containers in a pod share `localhost`. The ports that
  KinD publishes in the dind daemon (80, 443, 5000, 6443) are therefore
  reachable from the job as `localhost`: `curl http://my-app.localhost/`,
  `docker push localhost:5000/...`, and `devlab kubectl port-forward` all work.
- **Shared files**. devlab runs its tools as containers with bind mounts of
  the project directory and the current directory. With a remote daemon, bind
  mount paths are resolved on the daemon's filesystem, so the dind container
  must see the checkout at the same path. The runner shares the builds
  directory with services when it is a configured volume (see
  [Runner Requirements](#runner-requirements)). devlab checks this before it
  runs a tool and stops with an error that names the missing path.

## The `ci` Profile

Select it with `DEVLAB_PROFILE=ci` or `devlab --profile ci ...`.

| Setting | `local` | `ci` |
|---------|---------|------|
| KinD config | `cluster/kind-config.yaml` (1 control plane + 2 workers) | `cluster/kind-config.ci.yaml` (1 control plane + 1 worker) |
| Monitoring stack | Installed | Skipped (`devlab bootstrap --monitoring` to add it) |
| krew plugins | Installed | Skipped (`--krew` to add them) |
| Prompts | Asks for the Kubernetes version and before recreating a cluster | Never asks: uses the configured node image and reuses an existing cluster |

Other settings:

- **`DEVLAB_KIND_NODE_IMAGE`** pins the node image, for example
  `kindest/node:v1.34.5`, in any profile. The cluster-autoscaler addon follows
  the version.
- Prompts are also skipped in the `local` profile when stdin is not a
  terminal.
- Without the monitoring stack, the addons install without ServiceMonitors.

## GitLab Setup

### Runner Requirements

In the runner's `config.toml`:

```toml
[[runners]]
  executor = "kubernetes"
  builds_dir = "/builds"
  [runners.kubernetes]
    # docker:dind must run privileged
    privileged = true
    # A configured builds volume is also mounted into service containers,
    # which gives the dind daemon the job's files at the same path
    [[runners.kubernetes.volumes.empty_dir]]
      name = "repo"
      mount_path = "/builds"
    # Let jobs request enough resources for the dind service (see the template)
    service_cpu_request_overwrite_max_allowed = "4"
    service_memory_request_overwrite_max_allowed = "8Gi"
    service_memory_limit_overwrite_max_allowed = "16Gi"
```

Privileged pods can reach the node's kernel. Run these jobs on dedicated CI
nodes (`node_selector` and taints in the runner config).

### Pipeline

`ci/devlab.gitlab-ci.yml` defines a hidden `.devlab` job to extend. Its
`before_script` starts from a fresh job, sets up devlab, and runs
`devlab bootstrap`. After that, `devlab` is on `PATH`.

In this repository (see `ci/gitlab-ci.example.yml`):

```yaml
include:
  - local: ci/devlab.gitlab-ci.yml

autoscaling-e2e:
  extends: .devlab
  timeout: 45m
  script:
    - devlab addon enable keda node-autoscaler
    - apps/autoscaling-demo/scripts/test-autoscaling.sh all
```

In an application project, include the template remotely. The job clones
dev-lab into `$CI_PROJECT_DIR/.devlab`, inside the shared builds directory:

```yaml
include:
  - remote: https://raw.githubusercontent.com/JB0t/dev-lab/dev/ci/devlab.gitlab-ci.yml

e2e:
  extends: .devlab
  variables:
    DEVLAB_REF: dev                      # branch or tag of dev-lab
  script:
    - devlab build -t my-app:$CI_COMMIT_SHORT_SHA --push .
    - devlab kubectl apply -f k8s/       # manifests use image: localhost:5000/my-app:...
    - devlab kubectl rollout status deployment/my-app --timeout=180s
    - curl --fail http://my-app.localhost/healthz
```

`include: remote` needs a URL that the GitLab instance can fetch without
authentication. For a private copy, mirror dev-lab into GitLab and use
`include: project`, and set `DEVLAB_REPO` to the mirror.

Template variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEVLAB_REPO`, `DEVLAB_REF` | GitHub repository, `dev` | What to clone in other projects |
| `DEVLAB_BOOTSTRAP_ARGS` | empty | Extra bootstrap flags, such as `--monitoring` |
| `DEVLAB_DIND_IMAGE` | `docker:29-dind` | The dind service image |
| `DEVLAB_CA_CERT` | unset | File-type variable with root CAs for TLS inspection |
| `DEVLAB_KIND_NODE_IMAGE` | `kindest/node:v1.35.8` | Kubernetes version of the cluster |
| `KUBERNETES_SERVICE_*` | 2 CPU, 4-8 GiB | Resources for the dind service, which holds the cluster |

On failure, `after_script` prints nodes, pods, and events, and saves
`kind export logs` output as the `devlab-logs/` artifact.

### TLS Inspection

Behind a TLS-inspecting proxy, three parts need the root CA:

1. **Job container** (apk, git, pip): set the file-type variable
   `DEVLAB_CA_CERT`. The template trusts it first.
2. **Tool images and KinD nodes**: `ci/devlab-ci-setup.sh` copies
   `DEVLAB_CA_CERT` into `python/certs/`, which devlab already uses.
3. **The dind daemon** (image pulls): the daemon reads its trust store only at
   startup, so it needs an image with the CA built in. Put the `.crt` files in
   `ci/certs/`, build `ci/Dockerfile.dind`, push it to a registry the runner
   can pull from, and set `DEVLAB_DIND_IMAGE` to it.

## Try It Without a Runner

`ci/run-local.sh` reproduces the job pod with plain Docker: a privileged dind
container, and a job container that shares its network namespace and a
`/builds` volume. It copies your working tree (with `python/certs`, but
without local state) and runs the same `ci/devlab-ci-setup.sh`:

```bash
ci/run-local.sh                                   # bootstrap, then devlab status
ci/run-local.sh 'devlab addon enable keda node-autoscaler && apps/autoscaling-demo/scripts/test-autoscaling.sh'

# Behind TLS inspection, first build the dind image with your CAs
cp -r python/certs/. ci/certs/
docker build -f ci/Dockerfile.dind -t devlab-dind-ci ci/
DEVLAB_DIND_IMAGE=devlab-dind-ci ci/run-local.sh
```

It needs about 2-3 GB of free memory, and it does not touch your local
`dev-lab` cluster. Set `KEEP=1` to keep the dind container for inspection.

## Other CI Systems

- **GitHub Actions and other VM runners**: the runner has a Docker daemon, so
  no dind is needed. Run `python3 python/setup.py`, then
  `DEVLAB_PROFILE=ci python/devlab bootstrap`.
- **GitLab Docker executor**: use the same template. Services there are
  separate containers, not a shared network namespace, so `localhost` does
  not reach the lab. Use the `docker` hostname instead (for example
  `http://docker:5000`), or map the builds volume and use the host's socket.
- **No privileged pods allowed**: KinD cannot run. Consider vcluster (a
  virtual cluster in the host cluster), envtest (API server only, for
  controller tests), or kwokctl (simulated nodes, for scheduling tests).
