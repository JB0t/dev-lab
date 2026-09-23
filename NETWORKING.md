# Dev Lab Networking

How traffic gets from your machine to a pod in the `dev-lab` KinD cluster, and
how to expose something new.

## Summary

| Need | Use | Cluster recreate |
|------|-----|------------------|
| Permanent HTTP access to a service | An Ingress with host `<name>.localhost` | No |
| Ad hoc access or debugging, any TCP protocol | `devlab kubectl port-forward` | No |
| Push images for the cluster | `devlab build` / `devlab push` to `localhost:5000` | No |

The KinD config maps only three ports, and you should not need to add more.

## The Layers

Each KinD "node" is a Docker container on the `kind` Docker network. Traffic
from `localhost` to a pod crosses these hops:

```text
 host                 Docker publish          control-plane node              Kubernetes
┌──────────────┐     ┌──────────────┐      ┌────────────────────────┐      ┌─────────────────┐
│ localhost:H  │ ──► │ H ─► node:C  │ ───► │ pod with hostPort C    │ ───► │ Service ─► Pod  │
└──────────────┘     └──────────────┘      └────────────────────────┘      └─────────────────┘
```

1. **Host to node (`extraPortMappings`)**. `cluster/kind-config.yaml` publishes
   port `C` of the control-plane node container on host port `H`, like
   `docker run -p H:C`. Only the control-plane node has mappings, and they are
   fixed when the cluster is created.
2. **Node to pod (`hostPort`)**. A pod that declares `hostPort: C` receives
   the node's traffic on port `C`. It must run on the control-plane node, so
   these pods select `node-role.kubernetes.io/control-plane` and tolerate its
   taint.
3. **Service to pod**. The Service selects pods by label and forwards `port`
   to the container's `targetPort`.

| Host port | Node port | Pod on the control plane | Purpose |
|-----------|-----------|--------------------------|---------|
| 80 | 80 | Traefik (`hostPort: 80`) | HTTP ingress |
| 443 | 443 | Traefik (`hostPort: 443`) | HTTPS ingress (self-signed certificate) |
| 5000 | 5000 | Registry (`hostPort: 5000`) | Local image registry |
| 127.0.0.1:6443 | 6443 | kube-apiserver | Kubernetes API (added by KinD) |

If host port 80 or 443 is already in use, `devlab bootstrap` fails when it
creates the cluster. Change `hostPort` in `cluster/kind-config.yaml` (for
example to 8080), and add that port to the URLs.

## Ingress

Traefik is the ingress controller. `devlab bootstrap` installs it with Helm
(`config/ingress/traefik-values.yaml`) as the default IngressClass. An Ingress
routes on the HTTP `Host` header, so one host port serves every service.

```text
curl http://my-app.localhost/
  └─► host :80 ─► control-plane :80 ─► Traefik pod (hostPort 80)
        └─► Ingress rule host=my-app.localhost, path=/
              └─► Service my-app:80 ─► Pod my-app:8080
```

**Hostnames**. Use names under `.localhost`. Browsers and curl resolve
`*.localhost` to loopback by themselves, so you need no `/etc/hosts` entries
and no DNS. On WSL2, a Windows browser also reaches these URLs through WSL's
localhost forwarding. Some tools (for example Python `requests`) use the system
resolver, which may not resolve `*.localhost`. For those, add a hosts entry
such as `127.0.0.1 my-app.localhost`, or use `*.localtest.me`, which public DNS
resolves to loopback.

**Bootstrap services**:

| Service | URL |
|---------|-----|
| Grafana | http://grafana.localhost (admin/admin123) |
| Prometheus | http://prometheus.localhost |
| Alertmanager | http://alertmanager.localhost |
| Registry UI | http://registry.localhost |
| Traefik dashboard | http://traefik.localhost/dashboard/ |

**Example**. Deploy an app from the local registry and route to it:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 2
  selector:
    matchLabels: {app: my-app}
  template:
    metadata:
      labels: {app: my-app}
    spec:
      containers:
      - name: my-app
        image: localhost:5000/my-app:1
        ports:
        - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: my-app
spec:
  selector: {app: my-app}
  ports:
  - port: 80
    targetPort: 8080
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
spec:
  rules:
  - host: my-app.localhost
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-app
            port:
              number: 80
```

```bash
devlab build -t my-app:1 --push .
devlab kubectl apply -f my-app.yaml
curl http://my-app.localhost/
```

`ingressClassName` is optional because Traefik is the default class. Set
`ingressClassName: traefik` explicitly when the Ingress can be created before
Traefik is installed. Traefik ignores `nginx.ingress.kubernetes.io/*`
annotations; use Traefik
[Middlewares](https://doc.traefik.io/traefik/middlewares/overview/) for
rewrites, redirects, and authentication.

**Non-HTTP services** (databases, gRPC without TLS, and so on) cannot be
routed by hostname. Use `port-forward` for these.

**Troubleshooting**:

```bash
devlab kubectl -n traefik get pods -o wide      # must run on dev-lab-control-plane
devlab kubectl get ingress -A                   # hosts and backends
devlab kubectl -n traefik logs deploy/traefik
```

A `404` means no Ingress matched the host or path. A `503` means the Ingress
matched but its Service has no ready endpoints.

## Port-Forward

`devlab kubectl port-forward` exposes a Service or pod on `localhost` for as
long as the command runs. Use it for one-off access and debugging when an
Ingress is not worth it:

```bash
devlab kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
devlab kubectl port-forward pod/my-app-abc123 8080       # localhost:8080 -> 8080
devlab kubectl port-forward svc/postgres :5432           # picks a free local port
devlab kubectl port-forward --address 0.0.0.0 svc/my-app 8080:80   # reachable from the LAN
```

kubectl runs in a container, so `devlab` rewrites the command. kubectl listens
on `0.0.0.0` inside the container, and each local port is published on the host
with `docker run -p`. The host bind address comes from `--address` (default
`127.0.0.1`, like kubectl). kubectl's own "Forwarding from 0.0.0.0:..." line
describes the container side. Press Ctrl+C to stop, which also removes the
container.

## The Local Registry

```text
docker push localhost:5000/app:1
  └─► host :5000 ─► control-plane :5000 ─► registry pod (hostPort 5000)

kubelet pulls image localhost:5000/app:1
  └─► containerd mirror (containerdConfigPatches in kind-config.yaml)
        localhost:5000 ─► http://dev-lab-control-plane:5000 ─► same registry pod
```

Inside a node, `localhost:5000` means the node itself. For that reason,
containerd on every node rewrites it to the control-plane container name,
which Docker DNS resolves on the `kind` network. Manifests use
`image: localhost:5000/<name>:<tag>`.

The registry is one Deployment on the control-plane node. It stores data in
the node's `/var/lib/registry`, which KinD mounts from `/tmp/dev-lab-registry`
on the Docker host. Pushed images survive `devlab cleanup` and a new
bootstrap, until the Docker host clears `/tmp`.

```bash
devlab build -t my-app:1 --push .     # docker build -t localhost:5000/my-app:1 . && docker push
devlab push my-app:1                  # tag an existing local image and push it
curl -s http://localhost:5000/v2/_catalog
```

Images are built for the Docker host's platform, which is also the KinD
nodes' platform, so the same commands work on amd64 and arm64 hosts.

## The API Server and the Tool Containers

KinD writes a kubeconfig that points at `https://127.0.0.1:6443`. That address
works from the host. However, `devlab kubectl`, `helm`, `flux`, and `linkerd`
run in containers, where `127.0.0.1` is the container itself. Bootstrap
rewrites the shared kubeconfig in `.kube/config` to use the control-plane IP
on the `kind` network (for example `https://172.18.0.3:6443`). The tool
containers run with `--network kind`, so they reach that IP directly.
