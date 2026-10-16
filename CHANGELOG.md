# Changelog

Release notes for each `vX.Y.Z` tag. CI publishes the section for a tag as its GitHub Release notes, so add a section before tagging.

## v0.1.0

First release as a distributable tarball.

- `devlab` is now a single Go binary, replacing the Python CLI (`python/`) and the bash scripts (`scripts/bootstrap.sh`, `deploy-*.sh`, `install-prerequisites.sh`, `test-environment.sh`).
- Release tarballs per architecture (`x86_64`, `aarch64`): `bin/devlab`, bundled `kubectl`, `helm`, `linkerd` and `flux`, the cluster and Kubernetes config, sample apps and guides. Docker is the only host requirement.
- kind is built into `devlab`; `devlab load-image` replaces `kind load docker-image`.
- New commands: `test` (end-to-end environment check, was `scripts/test-environment.sh`), `kubeconfig`, `load-image`.
- GPU-enabled clusters (`bootstrap --gpu`) no longer need nvkind, kind or kubectl on the host.
- The kubeconfig lives in `<home>/.kube/config`; `~/.kube/config` is never changed.
- Pinned versions: kind v0.20.0 (Kubernetes v1.27.3), kubectl v1.28.3, helm v3.13.1, linkerd stable-2.14.10, flux v2.3.0, Gateway API v1.0.0, metrics-server v0.7.2, NGINX ingress v1.8.1, NVIDIA device plugin 0.20.1.
