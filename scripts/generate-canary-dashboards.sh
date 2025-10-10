#!/bin/bash

# Multi-Application Canary Dashboard Generator
# This script discovers canary deployments and creates/updates dashboards

set -e

NAMESPACE_FILTER="${1:-.*}"
OUTPUT_DIR="${2:-./generated-dashboards}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_TOKEN="${GRAFANA_TOKEN:-}"

echo "🔍 Discovering canary deployments..."

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Get all canary deployments
CANARIES=$(kubectl get canaries -A -o json | jq -r '.items[] | "\(.metadata.namespace):\(.metadata.name)"')

if [ -z "$CANARIES" ]; then
    echo "❌ No canary deployments found"
    exit 1
fi

echo "📊 Found canary deployments:"
echo "$CANARIES"
echo ""

# Generate individual dashboard for each application
for canary in $CANARIES; do
    namespace=$(echo "$canary" | cut -d: -f1)
    app_name=$(echo "$canary" | cut -d: -f2)
    
    # Skip if namespace doesn't match filter
    if ! echo "$namespace" | grep -q "$NAMESPACE_FILTER"; then
        continue
    fi
    
    echo "🎨 Generating dashboard for $namespace/$app_name..."
    
    # Create application-specific dashboard
    cat > "$OUTPUT_DIR/${namespace}-${app_name}-canary-dashboard.json" << EOF
{
  "id": null,
  "title": "Canary Dashboard - ${namespace}/${app_name}",
  "tags": [
    "linkerd",
    "flagger", 
    "canary",
    "${namespace}",
    "${app_name}"
  ],
  "timezone": "browser",
  "panels": [
    {
      "id": 1,
      "title": "${app_name} Canary Traffic Weight",
      "type": "stat",
      "targets": [
        {
          "expr": "flagger_canary_weight{workload=\"${app_name}\", exported_namespace=\"${namespace}\"}",
          "legendFormat": "Traffic Weight %",
          "refId": "A"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "thresholds"
          },
          "thresholds": {
            "steps": [
              {
                "color": "green",
                "value": 0
              },
              {
                "color": "yellow",
                "value": 50
              },
              {
                "color": "red",
                "value": 80
              }
            ]
          },
          "unit": "percent"
        }
      },
      "gridPos": {
        "h": 6,
        "w": 6,
        "x": 0,
        "y": 0
      }
    },
    {
      "id": 2,
      "title": "${app_name} Success Rate",
      "type": "stat",
      "targets": [
        {
          "expr": "sum(rate(response_total{namespace=\"${namespace}\",direction=\"inbound\",classification!=\"failure\"}[1m]))/sum(rate(response_total{namespace=\"${namespace}\",direction=\"inbound\"}[1m]))*100",
          "legendFormat": "Success Rate %",
          "refId": "A"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "thresholds"
          },
          "thresholds": {
            "steps": [
              {
                "color": "red",
                "value": 0
              },
              {
                "color": "yellow",
                "value": 95
              },
              {
                "color": "green",
                "value": 99
              }
            ]
          },
          "unit": "percent",
          "min": 0,
          "max": 100
        }
      },
      "gridPos": {
        "h": 6,
        "w": 6,
        "x": 6,
        "y": 0
      }
    },
    {
      "id": 3,
      "title": "${app_name} Request Rate",
      "type": "stat",
      "targets": [
        {
          "expr": "sum(rate(response_total{namespace=\"${namespace}\",direction=\"inbound\"}[1m]))",
          "legendFormat": "Requests/sec",
          "refId": "A"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "palette-classic"
          },
          "unit": "reqps"
        }
      },
      "gridPos": {
        "h": 6,
        "w": 6,
        "x": 12,
        "y": 0
      }
    },
    {
      "id": 4,
      "title": "${app_name} Canary Phase",
      "type": "stat",
      "targets": [
        {
          "expr": "flagger_canary_status{name=\"${app_name}\", exported_namespace=\"${namespace}\"}",
          "legendFormat": "Phase",
          "refId": "A"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "thresholds"
          },
          "thresholds": {
            "steps": [
              {
                "color": "blue",
                "value": 0
              },
              {
                "color": "green",
                "value": 1
              },
              {
                "color": "red",
                "value": 2
              }
            ]
          },
          "mappings": [
            {
              "options": {
                "0": {
                  "text": "Progressing",
                  "color": "blue"
                }
              },
              "type": "value"
            },
            {
              "options": {
                "1": {
                  "text": "Succeeded",
                  "color": "green"
                }
              },
              "type": "value"
            },
            {
              "options": {
                "2": {
                  "text": "Failed",
                  "color": "red"
                }
              },
              "type": "value"
            }
          ]
        }
      },
      "gridPos": {
        "h": 6,
        "w": 6,
        "x": 18,
        "y": 0
      }
    },
    {
      "id": 5,
      "title": "${app_name} Traffic Split Over Time",
      "type": "timeseries",
      "targets": [
        {
          "expr": "flagger_canary_weight{workload=\"${app_name}\", exported_namespace=\"${namespace}\"}",
          "legendFormat": "Canary Weight %",
          "refId": "A"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "palette-classic"
          },
          "unit": "percent",
          "min": 0,
          "max": 100
        }
      },
      "gridPos": {
        "h": 8,
        "w": 12,
        "x": 0,
        "y": 6
      }
    },
    {
      "id": 6,
      "title": "${app_name} Success Rate Over Time",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sum(rate(response_total{namespace=\"${namespace}\",direction=\"inbound\",classification!=\"failure\"}[1m]))/sum(rate(response_total{namespace=\"${namespace}\",direction=\"inbound\"}[1m]))*100",
          "legendFormat": "Success Rate %",
          "refId": "A"
        },
        {
          "expr": "95",
          "legendFormat": "SLA Threshold (95%)",
          "refId": "B"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "palette-classic"
          },
          "unit": "percent",
          "min": 90,
          "max": 100
        }
      },
      "gridPos": {
        "h": 8,
        "w": 12,
        "x": 12,
        "y": 6
      }
    },
    {
      "id": 7,
      "title": "${app_name} Response Latency",
      "type": "timeseries",
      "targets": [
        {
          "expr": "histogram_quantile(0.99, sum(rate(response_latency_ms_bucket{namespace=\"${namespace}\",direction=\"inbound\"}[1m])) by (le))",
          "legendFormat": "P99 Latency",
          "refId": "A"
        },
        {
          "expr": "histogram_quantile(0.95, sum(rate(response_latency_ms_bucket{namespace=\"${namespace}\",direction=\"inbound\"}[1m])) by (le))",
          "legendFormat": "P95 Latency",
          "refId": "B"
        },
        {
          "expr": "histogram_quantile(0.50, sum(rate(response_latency_ms_bucket{namespace=\"${namespace}\",direction=\"inbound\"}[1m])) by (le))",
          "legendFormat": "P50 Latency",
          "refId": "C"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "palette-classic"
          },
          "unit": "ms"
        }
      },
      "gridPos": {
        "h": 8,
        "w": 24,
        "x": 0,
        "y": 14
      }
    },
    {
      "id": 8,
      "title": "${app_name} mTLS Security Status",
      "type": "stat",
      "targets": [
        {
          "expr": "sum(rate(response_total{namespace=\"${namespace}\",direction=\"inbound\",tls=\"true\",path!~\"/health.*|/live|/ready|/metrics\",status_code!~\"404\"}[1m])) / sum(rate(response_total{namespace=\"${namespace}\",direction=\"inbound\",path!~\"/health.*|/live|/ready|/metrics\",status_code!~\"404\"}[1m])) * 100",
          "legendFormat": "mTLS Coverage %",
          "refId": "A"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "thresholds"
          },
          "thresholds": {
            "steps": [
              {
                "color": "red",
                "value": 0
              },
              {
                "color": "yellow",
                "value": 50
              },
              {
                "color": "green",
                "value": 90
              }
            ]
          },
          "unit": "percent",
          "min": 0,
          "max": 100
        }
      },
      "gridPos": {
        "h": 6,
        "w": 12,
        "x": 0,
        "y": 22
      }
    },
    {
      "id": 9,
      "title": "${app_name} Primary vs Canary Traffic",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sum(rate(response_total{namespace=\"${namespace}\",direction=\"inbound\",pod=~\".*primary.*\"}[1m]))",
          "legendFormat": "Primary Requests/sec",
          "refId": "A"
        },
        {
          "expr": "sum(rate(response_total{namespace=\"${namespace}\",direction=\"inbound\",pod!~\".*primary.*\",pod!~\".*flagger.*\"}[1m]))",
          "legendFormat": "Canary Requests/sec",
          "refId": "B"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "palette-classic"
          },
          "unit": "reqps"
        }
      },
      "gridPos": {
        "h": 6,
        "w": 12,
        "x": 12,
        "y": 22
      }
    }
  ],
  "time": {
    "from": "now-1h",
    "to": "now"
  },
  "refresh": "5s",
  "schemaVersion": 27,
  "version": 1
}
EOF

    echo "✅ Generated dashboard: $OUTPUT_DIR/${namespace}-${app_name}-canary-dashboard.json"
done

echo ""
echo "🎯 Dashboard Generation Summary:"
echo "📁 Output directory: $OUTPUT_DIR"
echo "📊 Generated dashboards:"
ls -la "$OUTPUT_DIR"/*.json 2>/dev/null || echo "  (No dashboards generated)"

echo ""
echo "🚀 Next Steps:"
echo "1. Import the multi-app dashboard: multi-app-canary-dashboard.json"
echo "2. Import individual app dashboards from $OUTPUT_DIR/"
echo "3. Configure Grafana data source pointing to Prometheus"
echo "4. Test canary deployments by updating image tags and APP_VERSION"

# If Grafana token is provided, attempt to upload dashboards
if [ -n "$GRAFANA_TOKEN" ]; then
    echo ""
    echo "📤 Uploading dashboards to Grafana..."
    
    for dashboard_file in "$OUTPUT_DIR"/*.json; do
        if [ -f "$dashboard_file" ]; then
            echo "Uploading $(basename "$dashboard_file")..."
            
            # Create dashboard payload
            payload=$(jq -n --argjson dashboard "$(cat "$dashboard_file")" '{dashboard: $dashboard, overwrite: true}')
            
            # Upload to Grafana
            response=$(curl -s -X POST \
                -H "Authorization: Bearer $GRAFANA_TOKEN" \
                -H "Content-Type: application/json" \
                -d "$payload" \
                "$GRAFANA_URL/api/dashboards/db")
            
            if echo "$response" | jq -e '.status == "success"' > /dev/null; then
                echo "✅ Successfully uploaded $(basename "$dashboard_file")"
            else
                echo "❌ Failed to upload $(basename "$dashboard_file"): $response"
            fi
        fi
    done
fi