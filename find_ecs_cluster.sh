#!/bin/bash
#
# Find your ECS cluster and service names
#

echo "Finding ECS resources..."
echo ""

# List all ECS clusters
echo "Available ECS Clusters:"
echo "======================"
aws ecs list-clusters --query 'clusterArns[]' --output text | while read cluster_arn; do
    cluster_name=$(echo $cluster_arn | awk -F/ '{print $NF}')
    echo "  - $cluster_name"
done

echo ""
echo "Enter your cluster name (or press Enter to search all clusters):"
read CLUSTER_NAME

if [ -z "$CLUSTER_NAME" ]; then
    echo ""
    echo "Searching all clusters for backend services..."
    echo ""
    
    aws ecs list-clusters --query 'clusterArns[]' --output text | while read cluster_arn; do
        cluster_name=$(echo $cluster_arn | awk -F/ '{print $NF}')
        
        services=$(aws ecs list-services --cluster $cluster_name --query 'serviceArns[]' --output text 2>/dev/null)
        
        if [ -n "$services" ]; then
            echo "Cluster: $cluster_name"
            echo "$services" | while read service_arn; do
                service_name=$(echo $service_arn | awk -F/ '{print $NF}')
                echo "  Service: $service_name"
                
                # Check if this looks like the backend
                if echo "$service_name" | grep -qi "backend\|finops\|api"; then
                    running_count=$(aws ecs describe-services \
                        --cluster $cluster_name \
                        --services $service_name \
                        --query 'services[0].runningCount' \
                        --output text 2>/dev/null)
                    
                    if [ "$running_count" -gt 0 ]; then
                        echo "    ✓ Running tasks: $running_count"
                        echo ""
                        echo "    To connect to this service, run:"
                        echo "    CLUSTER_NAME=$cluster_name"
                        echo "    SERVICE_NAME=$service_name"
                        echo ""
                    fi
                fi
            done
            echo ""
        fi
    done
else
    echo ""
    echo "Services in cluster: $CLUSTER_NAME"
    echo "=================================="
    
    aws ecs list-services --cluster $CLUSTER_NAME --query 'serviceArns[]' --output text | while read service_arn; do
        service_name=$(echo $service_arn | awk -F/ '{print $NF}')
        
        running_count=$(aws ecs describe-services \
            --cluster $CLUSTER_NAME \
            --services $service_name \
            --query 'services[0].runningCount' \
            --output text)
        
        echo "  - $service_name (running: $running_count)"
    done
fi

echo ""
echo "Once you have the cluster and service names, run:"
echo "================================================================"
echo ""
echo "CLUSTER_NAME=<your-cluster>"
echo "SERVICE_NAME=<your-service>"
echo ""
echo "TASK_ARN=\$(aws ecs list-tasks \\"
echo "  --cluster \$CLUSTER_NAME \\"
echo "  --service-name \$SERVICE_NAME \\"
echo "  --query 'taskArns[0]' \\"
echo "  --output text)"
echo ""
echo "aws ecs execute-command \\"
echo "  --cluster \$CLUSTER_NAME \\"
echo "  --task \$TASK_ARN \\"
echo "  --container backend \\"
echo "  --interactive \\"
echo "  --command \"/bin/sh\""
