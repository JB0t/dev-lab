# scripts

Build and release scripts. The lab itself is run by `bin/devlab` (Go, `cmd/devlab`); these scripts only produce it.

| Script | Purpose |
|--------|---------|
| `build-distribution.sh [--arch all\|x86_64\|aarch64] [VERSION]` | Builds `build/dev-lab_<branch>_v<version>_<arch>.tar.gz`: the static `devlab` binary, the bundled CLIs, runtime config (`cluster/`, `config/`, `clusters/`, `apps/`), guides and licenses. Copies only tracked files and fails if Go source would ship. |
| `fetch-tools.sh <arch> <dir>` | Downloads kubectl, helm, linkerd and flux for one architecture and verifies each against a pinned SHA-256. Also used in a checkout: `scripts/fetch-tools.sh x86_64 bin`. |
| `ci/build-version.sh` | Prints `BUILD_VERSION` and `BUILD_BRANCH` for CI: `X.Y.Z` on a `vX.Y.Z` tag, otherwise `X.Y.(Z+1).ci.<run number>`. |
| `dist/THIRD_PARTY_NOTICES.md` | Copied into each tarball's `licenses/`. |

## Build Locally

```bash
scripts/build-distribution.sh --arch x86_64 0.1.0
tar -tzf build/dev-lab_*_v0.1.0_x86_64.tar.gz | head
```

Needs Go (version from `go.mod`), git, curl and sha256sum. Only files tracked by git are packaged, so commit (or `git add -N`) new config files before building.

## Bump a Bundled Tool

1. Change the version in `fetch-tools.sh`.
2. Run `scripts/fetch-tools.sh x86_64 /tmp/tools`; it fails with the new file's checksum. Check that checksum against the upstream checksum file, then pin it. Repeat for `aarch64`.
3. Update the versions table in the top-level README and add a CHANGELOG entry.
