# workflows

<!-- docgen:begin id=.github/workflows:overview scope=.github/workflows hash=ee992e42dfaa -->
This module defines a set of GitHub Actions workflows that manage branch validation, automated markdown fixes, and semantic versioning releases. The workflows are configured to run in response to specific events like pull request changes or pushes, and they enforce consistent branch naming, automatically fix markdown formatting, and manage version bumps and releases based on merge patterns.

The `branch-validation.yml` workflow ensures that pull requests follow defined branch naming conventions and provides feedback on the expected version bump impact. The `fix_markdown.yml` workflow automatically detects and fixes markdown formatting issues in changed files, committing any fixes back to the repository. The `semver-release.yml` workflow handles version management by determining the appropriate semantic version bump based on the source and target branches of merged pull requests, creating version files, tagging releases, and publishing GitHub releases.

These workflows integrate through shared repository state and GitHub events, with each workflow operating independently but contributing to a consistent development and release process. The branch validation workflow runs first to enforce conventions, followed by the markdown fixer which operates on changed files, and finally the semantic version release workflow which triggers on merged PRs to main or dev branches to manage versioning and releases.
<!-- docgen:end id=.github/workflows:overview -->

<!-- docgen:begin id=.github/workflows:reference scope=.github/workflows hash=ee992e42dfaa -->
## Reference

### `branch-validation.yml`

- **`Branch Validation`** (workflow)
- **`validate-branch`** (job)

### `fix_markdown.yml`

- **`Fix Markdown Files`** (workflow)
- **`fix-markdown`** (job)

### `semver-release.yml`

- **`Semantic Version Release`** (workflow)
- **`version-bump`** (job)
- **`version-info`** (job)
<!-- docgen:end id=.github/workflows:reference -->
