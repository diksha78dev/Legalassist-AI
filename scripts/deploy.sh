#!/bin/bash
# Quick deployment helper script
# Usage: ./scripts/deploy.sh staging aws

set -e

ENVIRONMENT=${1:-staging}
PROVIDER=${2:-aws}
IMAGE_TAG=${3:-$(git rev-parse --short HEAD)}

echo "🚀 Deploying Legalassist-AI"
echo "   Environment: $ENVIRONMENT"
echo "   Provider: $PROVIDER"
echo "   Image Tag: $IMAGE_TAG"
echo ""

# Run Python deployment script
python scripts/deploy.py \
    --environment $ENVIRONMENT \
    --provider $PROVIDER \
    --image-tag legalassist-ai:$IMAGE_TAG

echo ""
echo "✨ Deployment complete!"
