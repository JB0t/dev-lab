# Contributing to Dev Lab

Thank you for your interest in contributing to the Dev Lab project! This guide will help you understand our development workflow and semantic versioning process.

## 🔄 Semantic Versioning Workflow

This project uses **automated semantic versioning** based on branch naming conventions and merge patterns.

### Version Bump Rules

| Branch Pattern | Target Branch | Version Bump | Example |
|---------------|---------------|--------------|---------|
| `feature/*` | `dev` | **Minor** | v1.2.0 → v1.3.0 |
| `patch/*` | `dev` | **Patch** | v1.2.0 → v1.2.1 |
| `dev` | `main` | **Major** | v1.2.0 → v2.0.0 |
| `docs/*`, `ci/*`, `hotfix/*` | any | **None** | No version change |

### 🚀 Development Workflow

#### 1. Feature Development

```bash
# Create feature branch from dev
git checkout dev
git pull origin dev
git checkout -b feature/describe-your-feature

# Make changes and commit
git add .
git commit -m "feat: add new feature"
git push origin feature/describe-your-feature

# Create PR: feature/describe-your-feature → dev
# ✅ Will trigger MINOR version bump when merged
```

#### 2. Bug Fixes

```bash
# Create patch branch from dev
git checkout dev
git pull origin dev
git checkout -b patch/fix-specific-issue

# Make changes and commit
git add .
git commit -m "fix: resolve specific issue"
git push origin patch/fix-specific-issue

# Create PR: patch/fix-specific-issue → dev
# ✅ Will trigger PATCH version bump when merged
```

#### 3. Release to Production

```bash
# Create PR: dev → main
# ✅ Will trigger MAJOR version bump when merged
# 🎉 Creates GitHub release automatically
```

#### 4. Documentation & CI Changes

```bash
# These branches don't trigger version bumps
git checkout -b docs/update-readme
git checkout -b ci/improve-workflows
git checkout -b hotfix/emergency-fix

# Can target any branch without version changes
```

## 📋 Branch Naming Conventions

### Required Patterns

- **Features**: `feature/description-of-feature`
  - Example: `feature/oauth-integration`
  - Target: `dev` branch
  - Triggers: Minor version bump

- **Patches**: `patch/description-of-fix`
  - Example: `patch/memory-leak-fix`
  - Target: `dev` branch
  - Triggers: Patch version bump

### Optional Patterns (No Version Bump)

- **Documentation**: `docs/description`
  - Example: `docs/api-documentation`
  - Target: Any branch

- **CI/CD**: `ci/description`
  - Example: `ci/github-actions-improvement`
  - Target: Any branch

- **Hotfixes**: `hotfix/description`
  - Example: `hotfix/security-vulnerability`
  - Target: Any branch

## 🛠️ Version Management Tools

### Check Current Version

```bash
# Show version information
./scripts/version-info.sh

# Show versioning rules
./scripts/version-info.sh rules

# Show recent releases
./scripts/version-info.sh releases

# Simulate version bump
./scripts/version-info.sh simulate feature/my-feature dev
```

### Manual Version Tracking

The current version is stored in:

- `VERSION` file in project root
- Version badge in `README.md`
- Git tags (automatically created)

## 🤖 Automated Processes

### On Pull Request

- **Branch validation**: Ensures proper naming conventions
- **Version impact comment**: Shows what version bump will occur
- **CI checks**: Runs tests and validation

### On Merge/Push

- **Version calculation**: Determines new version based on branch patterns
- **Tag creation**: Creates and pushes git tag
- **Release creation**: Creates GitHub release with changelog
- **Version file update**: Updates VERSION file and README.md

## 📝 Commit Message Guidelines

While not strictly enforced, we recommend following conventional commits:

```bash
feat: add new feature
fix: resolve bug
docs: update documentation
ci: improve workflows
refactor: code restructuring
test: add tests
chore: maintenance tasks
```

## 🔍 Examples

### Adding a New Feature

```bash
# 1. Create feature branch
git checkout dev
git checkout -b feature/linkerd-dashboard

# 2. Implement feature
echo "Add Linkerd dashboard integration"

# 3. Commit and push
git add .
git commit -m "feat: add Linkerd dashboard integration"
git push origin feature/linkerd-dashboard

# 4. Create PR to dev branch
# → When merged: v1.2.0 becomes v1.3.0
```

### Fixing a Bug

```bash
# 1. Create patch branch
git checkout dev
git checkout -b patch/prometheus-config

# 2. Fix issue
echo "Fix Prometheus configuration"

# 3. Commit and push
git add .
git commit -m "fix: correct Prometheus scrape interval"
git push origin patch/prometheus-config

# 4. Create PR to dev branch
# → When merged: v1.3.0 becomes v1.3.1
```

### Creating a Release

```bash
# 1. Create PR: dev → main
# 2. When merged: v1.3.1 becomes v2.0.0
# 3. GitHub release created automatically
```

## ⚠️ Important Notes

1. **Always target the correct branch**:
   - Features and patches must target `dev`
   - Only `dev` should merge to `main`

1. **Version bumps are automatic**:
   - No manual version editing required
   - Tags and releases are created automatically

1. **Branch validation**:
   - PRs with invalid branch names will fail CI
   - Follow the naming conventions strictly

1. **Testing**:
   - All PRs should include appropriate tests
   - CI must pass before merging

## 🆘 Getting Help

- Check version status: `./scripts/version-info.sh`
- View versioning rules: `./scripts/version-info.sh rules`
- Open an issue for questions
- Ask in PR comments for guidance

## 🏗️ Dev Lab Specific Guidelines

### Infrastructure Changes

- Use `feature/` for new infrastructure components
- Use `patch/` for configuration fixes
- Test in local KinD cluster before submitting

### Application Changes

- Update container tags appropriately
- Test service mesh integration
- Verify GitOps deployment works

### Documentation

- Use `docs/` branches for documentation-only changes
- Update README.md version badges when needed
- Include examples in documentation

---

Thank you for contributing to Dev Lab! 🚀
