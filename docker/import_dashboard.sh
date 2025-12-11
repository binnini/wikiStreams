#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

echo "Attempting to import Superset dashboard..."

# The user provided this path, assuming the zip is in the docker/ directory
superset import-dashboards -p /app/docker/media_wiki_streams.zip -u admin

echo "Dashboard import process finished."
