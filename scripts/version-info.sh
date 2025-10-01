#!/bin/bash

# Dev Lab Version Management Script
# This script helps with manual version management and provides information about the semver process

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Function to get current version
get_current_version() {
    if [[ -f "$PROJECT_ROOT/VERSION" ]]; then
        cat "$PROJECT_ROOT/VERSION"
    else
        git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0"
    fi
}

# Function to show version info
show_version_info() {
    local current_version=$(get_current_version)
    local latest_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
    local current_branch=$(git branch --show-current)
    
    echo -e "${BLUE}=== Dev Lab Version Information ===${NC}"
    echo ""
    echo -e "${CYAN}Current Version:${NC} $current_version"
    echo -e "${CYAN}Latest Git Tag:${NC} $latest_tag"
    echo -e "${CYAN}Current Branch:${NC} $current_branch"
    echo ""
    
    # Show commit count since last tag
    local commit_count=$(git rev-list --count ${latest_tag}..HEAD 2>/dev/null || echo "0")
    if [[ "$commit_count" -gt 0 ]]; then
        echo -e "${YELLOW}Commits since last tag:${NC} $commit_count"
        echo ""
    fi
}

# Function to show versioning rules
show_versioning_rules() {
    echo -e "${PURPLE}=== Semantic Versioning Rules ===${NC}"
    echo ""
    echo -e "${GREEN}Automatic Version Bumps:${NC}"
    echo "  🚀 feature/* → dev    = Minor version bump (v1.2.0 → v1.3.0)"
    echo "  🔧 patch/*   → dev    = Patch version bump (v1.2.0 → v1.2.1)"
    echo "  🎉 dev       → main   = Major version bump (v1.2.0 → v2.0.0)"
    echo ""
    echo -e "${CYAN}No Version Bump:${NC}"
    echo "  📝 docs/*    → any    = Documentation changes"
    echo "  🔧 ci/*      → any    = CI/CD changes"
    echo "  🔥 hotfix/*  → any    = Emergency fixes"
    echo ""
    echo -e "${YELLOW}Branch Naming Examples:${NC}"
    echo "  feature/add-oauth-integration"
    echo "  patch/fix-memory-leak"
    echo "  docs/update-installation-guide"
    echo "  ci/improve-test-coverage"
    echo "  hotfix/critical-security-patch"
    echo ""
}

# Function to simulate version bump
simulate_bump() {
    local branch_name="$1"
    local target_branch="$2"
    local current_version=$(get_current_version)
    
    # Remove 'v' prefix for calculation
    local version=${current_version#v}
    
    # Split version into components
    IFS='.' read -ra VERSION_PARTS <<< "$version"
    local major=${VERSION_PARTS[0]:-0}
    local minor=${VERSION_PARTS[1]:-0}
    local patch=${VERSION_PARTS[2]:-0}
    
    local bump_type="none"
    local new_version=""
    
    # Determine bump type
    if [[ "$branch_name" =~ ^feature/.+ ]] && [[ "$target_branch" == "dev" ]]; then
        bump_type="minor"
        minor=$((minor + 1))
        patch=0
    elif [[ "$branch_name" =~ ^patch/.+ ]] && [[ "$target_branch" == "dev" ]]; then
        bump_type="patch"
        patch=$((patch + 1))
    elif [[ "$branch_name" == "dev" ]] && [[ "$target_branch" == "main" ]]; then
        bump_type="major"
        major=$((major + 1))
        minor=0
        patch=0
    fi
    
    if [[ "$bump_type" != "none" ]]; then
        new_version="v$major.$minor.$patch"
        echo -e "${GREEN}Version Bump Simulation:${NC}"
        echo "  Branch: $branch_name → $target_branch"
        echo "  Bump Type: $bump_type"
        echo "  Current: $current_version"
        echo "  New: $new_version"
    else
        echo -e "${YELLOW}No version bump for:${NC} $branch_name → $target_branch"
    fi
}

# Function to show recent releases
show_recent_releases() {
    echo -e "${BLUE}=== Recent Releases ===${NC}"
    echo ""
    
    # Show last 5 tags with dates
    git tag --sort=-creatordate | head -5 | while read tag; do
        local date=$(git log -1 --format=%ai "$tag" 2>/dev/null || echo "Unknown date")
        local commit_msg=$(git log -1 --format=%s "$tag" 2>/dev/null || echo "No message")
        echo -e "${CYAN}$tag${NC} - $date"
        echo "  $commit_msg"
        echo ""
    done
}

# Function to validate current branch
validate_current_branch() {
    local current_branch=$(git branch --show-current)
    echo -e "${BLUE}=== Branch Validation ===${NC}"
    echo ""
    echo -e "${CYAN}Current Branch:${NC} $current_branch"
    
    if [[ "$current_branch" =~ ^feature/.+ ]]; then
        echo -e "${GREEN}✅ Valid feature branch${NC}"
        echo "  Should target: dev branch"
        echo "  Will trigger: MINOR version bump"
    elif [[ "$current_branch" =~ ^patch/.+ ]]; then
        echo -e "${GREEN}✅ Valid patch branch${NC}"
        echo "  Should target: dev branch"
        echo "  Will trigger: PATCH version bump"
    elif [[ "$current_branch" == "dev" ]]; then
        echo -e "${GREEN}✅ Development branch${NC}"
        echo "  Should target: main branch"
        echo "  Will trigger: MAJOR version bump"
    elif [[ "$current_branch" =~ ^(docs|ci|hotfix)/.+ ]]; then
        echo -e "${CYAN}📝 Utility branch${NC}"
        echo "  Will trigger: No version bump"
    else
        echo -e "${YELLOW}⚠️ Non-standard branch name${NC}"
        echo "  Consider using: feature/, patch/, docs/, ci/, or hotfix/"
    fi
}

# Main function
main() {
    case "${1:-info}" in
        "info"|"")
            show_version_info
            echo ""
            validate_current_branch
            ;;
        "rules")
            show_versioning_rules
            ;;
        "simulate")
            if [[ $# -lt 3 ]]; then
                echo "Usage: $0 simulate <branch-name> <target-branch>"
                echo "Example: $0 simulate feature/new-feature dev"
                exit 1
            fi
            simulate_bump "$2" "$3"
            ;;
        "releases")
            show_recent_releases
            ;;
        "help"|"-h"|"--help")
            echo "Dev Lab Version Management Script"
            echo ""
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  info          Show current version and branch info (default)"
            echo "  rules         Show semantic versioning rules"
            echo "  simulate      Simulate version bump for branch"
            echo "  releases      Show recent releases"
            echo "  help          Show this help"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Show version info"
            echo "  $0 rules                              # Show versioning rules"
            echo "  $0 simulate feature/new-auth dev      # Simulate version bump"
            echo "  $0 releases                           # Show recent releases"
            ;;
        *)
            echo -e "${RED}Unknown command: $1${NC}"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Ensure we're in a git repository
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo -e "${RED}Error: Not in a git repository${NC}"
    exit 1
fi

# Change to project root
cd "$PROJECT_ROOT"

# Run main function
main "$@"