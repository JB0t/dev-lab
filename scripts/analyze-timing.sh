#!/bin/bash

# Dev Lab Timing Analysis Script
# Analyzes timing history and shows performance trends

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMING_FILE="$SCRIPT_DIR/../.timing-history.log"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${BOLD}${PURPLE}📊 Dev Lab Timing Analysis${NC}"
echo -e "${PURPLE}==============================${NC}"
echo ""

if [ ! -f "$TIMING_FILE" ]; then
    echo -e "${YELLOW}No timing data found. Run './scripts/cycle-lab.sh' first!${NC}"
    exit 1
fi

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

# Read timing data
echo -e "${BOLD}${CYAN}Recent Deployment Times:${NC}"
echo ""
echo -e "${BOLD}Date/Time               Total    Bootstrap  GitOps${NC}"
echo "----------------------------------------------------"

# Display last 10 entries with formatted output
tail -10 "$TIMING_FILE" | while IFS=',' read -r timestamp total bootstrap gitops; do
    printf "%-22s  %-7s  %-9s  %-7s\n" \
        "$timestamp" \
        "$(format_duration $total)" \
        "$(format_duration $bootstrap)" \
        "$(format_duration $gitops)"
done

echo ""

# Calculate averages
if [ $(wc -l < "$TIMING_FILE") -gt 0 ]; then
    echo -e "${BOLD}${CYAN}Performance Statistics:${NC}"
    echo ""
    
    # Get last 5 runs for recent average
    RECENT_COUNT=$(tail -5 "$TIMING_FILE" | wc -l)
    
    if [ $RECENT_COUNT -gt 0 ]; then
        RECENT_AVG_TOTAL=$(tail -5 "$TIMING_FILE" | cut -d',' -f2 | awk '{sum+=$1} END {print int(sum/NR)}')
        RECENT_AVG_BOOTSTRAP=$(tail -5 "$TIMING_FILE" | cut -d',' -f3 | awk '{sum+=$1} END {print int(sum/NR)}')
        RECENT_AVG_GITOPS=$(tail -5 "$TIMING_FILE" | cut -d',' -f4 | awk '{sum+=$1} END {print int(sum/NR)}')
        
        echo -e "${BOLD}Recent Average (last $RECENT_COUNT runs):${NC}"
        echo -e "  Total:      $(format_duration $RECENT_AVG_TOTAL)"
        echo -e "  Bootstrap:  $(format_duration $RECENT_AVG_BOOTSTRAP)"
        echo -e "  GitOps:     $(format_duration $RECENT_AVG_GITOPS)"
        echo ""
    fi
    
    # Get fastest times
    FASTEST_TOTAL=$(cut -d',' -f2 "$TIMING_FILE" | sort -n | head -1)
    FASTEST_BOOTSTRAP=$(cut -d',' -f3 "$TIMING_FILE" | sort -n | head -1)
    FASTEST_GITOPS=$(cut -d',' -f4 "$TIMING_FILE" | sort -n | head -1)
    
    echo -e "${BOLD}${GREEN}Best Times:${NC}"
    echo -e "  Total:      $(format_duration $FASTEST_TOTAL)"
    echo -e "  Bootstrap:  $(format_duration $FASTEST_BOOTSTRAP)"
    echo -e "  GitOps:     $(format_duration $FASTEST_GITOPS)"
    echo ""
    
    # Performance recommendations
    echo -e "${BOLD}${CYAN}Recommendations:${NC}"
    if [ $RECENT_AVG_TOTAL -lt 300 ]; then
        echo -e "  ${GREEN}🚀 Excellent performance! Deployment under 5 minutes${NC}"
    elif [ $RECENT_AVG_TOTAL -lt 600 ]; then
        echo -e "  ${YELLOW}⚡ Good performance. Consider optimizing reconciliation intervals${NC}"
    else
        echo -e "  ${YELLOW}🐌 Slow deployments. Check:${NC}"
        echo -e "     - Reconciliation intervals in kustomizations"
        echo -e "     - Health check timeouts"
        echo -e "     - Resource dependencies"
    fi
    
    echo ""
fi

echo -e "${CYAN}📁 Full timing log: $TIMING_FILE${NC}"