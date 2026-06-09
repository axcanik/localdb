#!/bin/bash

# Start the Flask app using Gunicorn in the foreground
# Render automatically injects the PORT environment variable
# The bots will be spawned dynamically by the Flask app when resellers click "Start"
echo "Starting Flask Web Server for Multi-Tenant System..."
gunicorn app:app --bind 0.0.0.0:${PORT:-10000}
