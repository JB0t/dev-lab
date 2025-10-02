#!/bin/bash

# Dev Lab Cycle Script - Full Bootstrap + GitOps Deployment with Timing
# This script runs the complete cycle and provides detailed timing breakdown

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Capture overall start time
CYCLE_START_TIME=$(date +%s)
CYCLE_START_FORMATTED=$(date '+%Y-%m-%d %H:%M:%S')

echo -e "${BOLD}${PURPLE}=================================================${NC}"
echo -e "${BOLD}${PURPLE}🔄 Full Dev Lab Cycle Started${NC}"
echo -e "${BOLD}${PURPLE}   Start Time: $CYCLE_START_FORMATTED${NC}"
echo -e "${BOLD}${PURPLE}=================================================${NC}"
echo ""

# Phase 1: Bootstrap
echo -e "${BOLD}${BLUE}Phase 1: Bootstrap${NC}"
echo -e "${BLUE}Running: $SCRIPT_DIR/bootstrap.sh${NC}"
echo ""

BOOTSTRAP_PHASE_START=$(date +%s)
"$SCRIPT_DIR/bootstrap.sh"
BOOTSTRAP_PHASE_END=$(date +%s)
BOOTSTRAP_PHASE_DURATION=$((BOOTSTRAP_PHASE_END - BOOTSTRAP_PHASE_START))

echo ""
echo -e "${BOLD}${BLUE}Phase 2: GitOps Deployment${NC}"
echo -e "${BLUE}Running: $SCRIPT_DIR/deploy-gitops.sh${NC}"
echo ""

# Phase 2: GitOps Deployment
GITOPS_PHASE_START=$(date +%s)
"$SCRIPT_DIR/deploy-gitops.sh"
GITOPS_PHASE_END=$(date +%s)
GITOPS_PHASE_DURATION=$((GITOPS_PHASE_END - GITOPS_PHASE_START))

# Calculate overall timing
CYCLE_END_TIME=$(date +%s)
CYCLE_DURATION=$((CYCLE_END_TIME - CYCLE_START_TIME))
CYCLE_END_FORMATTED=$(date '+%Y-%m-%d %H:%M:%S')

# Function to format duration
format_duration() {
    local duration=$1
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))
    
    if [ $minutes -gt 0 ]; then
        echo "${minutes}m ${seconds}s"
    else
        echo "${seconds}s"
    fi
}

# Display comprehensive timing report
echo ""
echo ""
echo -e "${BOLD}${PURPLE}=================================================${NC}"
echo -e "${BOLD}${GREEN}🎉 Full Dev Lab Cycle Completed!${NC}"
echo -e "${BOLD}${PURPLE}=================================================${NC}"
echo ""
echo -e "${BOLD}${CYAN}📊 Timing Report:${NC}"
echo ""
echo -e "${BOLD}Overall Cycle:${NC}"
echo -e "  Start Time:    $CYCLE_START_FORMATTED"
echo -e "  End Time:      $CYCLE_END_FORMATTED"
echo -e "  ${BOLD}Total Duration: $(format_duration $CYCLE_DURATION) (${CYCLE_DURATION}s)${NC}"
echo ""
echo -e "${BOLD}Phase Breakdown:${NC}"
echo -e "  ${BLUE}Bootstrap:${NC}       $(format_duration $BOOTSTRAP_PHASE_DURATION) (${BOOTSTRAP_PHASE_DURATION}s)"
echo -e "  ${GREEN}GitOps Deploy:${NC}   $(format_duration $GITOPS_PHASE_DURATION) (${GITOPS_PHASE_DURATION}s)"
echo ""
echo -e "${BOLD}Percentage Breakdown:${NC}"
BOOTSTRAP_PERCENT=$((BOOTSTRAP_PHASE_DURATION * 100 / CYCLE_DURATION))
GITOPS_PERCENT=$((GITOPS_PHASE_DURATION * 100 / CYCLE_DURATION))
echo -e "  ${BLUE}Bootstrap:${NC}       ${BOOTSTRAP_PERCENT}%"
echo -e "  ${GREEN}GitOps Deploy:${NC}   ${GITOPS_PERCENT}%"
echo ""
echo -e "${BOLD}${CYAN}Performance Analysis:${NC}"
if [ $CYCLE_DURATION -lt 300 ]; then
    echo -e "  ${GREEN}🚀 Excellent! Total time under 5 minutes${NC}"
elif [ $CYCLE_DURATION -lt 600 ]; then
    echo -e "  ${YELLOW}⚡ Good! Total time under 10 minutes${NC}"
else
    echo -e "  ${RED}⏰ Slow - Consider optimizing reconciliation intervals${NC}"
fi

if [ $BOOTSTRAP_PHASE_DURATION -lt 120 ]; then
    echo -e "  ${GREEN}🏗️  Fast bootstrap (under 2 minutes)${NC}"
elif [ $BOOTSTRAP_PHASE_DURATION -lt 300 ]; then
    echo -e "  ${YELLOW}🏗️  Moderate bootstrap (2-5 minutes)${NC}"
else
    echo -e "  ${RED}🏗️  Slow bootstrap (over 5 minutes)${NC}"
fi

if [ $GITOPS_PHASE_DURATION -lt 180 ]; then
    echo -e "  ${GREEN}⚙️  Fast GitOps deployment (under 3 minutes)${NC}"
elif [ $GITOPS_PHASE_DURATION -lt 600 ]; then
    echo -e "  ${YELLOW}⚙️  Moderate GitOps deployment (3-10 minutes)${NC}"
else
    echo -e "  ${RED}⚙️  Slow GitOps deployment (over 10 minutes)${NC}"
fi

echo ""
echo -e "${BOLD}${PURPLE}=================================================${NC}"
echo -e "${BOLD}${GREEN}Ready for development! 🎯${NC}"
echo -e "${BOLD}${PURPLE}=================================================${NC}"

# Save timing data for comparison
TIMING_FILE="$SCRIPT_DIR/../.timing-history.log"
echo "$(date '+%Y-%m-%d %H:%M:%S'),${CYCLE_DURATION},${BOOTSTRAP_PHASE_DURATION},${GITOPS_PHASE_DURATION}" >> "$TIMING_FILE"

echo ""
echo -e "${CYAN}💾 Timing data saved to: $TIMING_FILE${NC}"
echo -e "${CYAN}📈 Use 'tail $TIMING_FILE' to see timing history${NC}"