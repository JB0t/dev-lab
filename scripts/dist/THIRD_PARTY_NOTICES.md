# Third-Party Notices

dev-lab release tarballs bundle the following unmodified binaries. Their versions are in `tool-versions.txt`.

| Binary | Project | License |
|--------|---------|---------|
| `bin/kubectl` | [Kubernetes](https://github.com/kubernetes/kubernetes) | Apache-2.0 |
| `bin/helm` | [Helm](https://github.com/helm/helm) | Apache-2.0 |
| `bin/linkerd` | [Linkerd](https://github.com/linkerd/linkerd2) | Apache-2.0 |
| `bin/flux` | [Flux](https://github.com/fluxcd/flux2) | Apache-2.0 |

The full Apache License 2.0 text is in `Apache-2.0.txt`.

`bin/devlab` is built from the [dev-lab](https://github.com/jbotstevens/dev-lab) source. The license of every Go module compiled into it is in `go-modules/<module path>/`.

The GPU node setup in `bin/devlab` is adapted from [nvkind](https://github.com/NVIDIA/nvkind) (Apache-2.0, Copyright NVIDIA CORPORATION).
