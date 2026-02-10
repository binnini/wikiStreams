#!/bin/sh

echo "Starting Docker Stats Collector..."

while true; do
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    docker stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemPerc}}" | while read line; do
        container_name=$(echo $line | awk '{print $1}')
        cpu_percent=$(echo $line | awk '{print $2}' | sed 's/%//')
        mem_percent=$(echo $line | awk '{print $3}' | sed 's/%//')
        
        # Logfmt format
        echo "time=\"$timestamp\" level=info msg=\"DockerStats\" target_container=\"$container_name\" cpu_pct=$cpu_percent mem_pct=$mem_percent"
    done
    
    sleep 10
done