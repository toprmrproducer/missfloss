#!/bin/bash
# Start the LiveKit agent worker locally

set -e

cd "$(dirname "$0")"

echo "🚀 Starting LiveKit Agent Worker..."
echo ""
echo "📋 Configuration:"
echo "   LiveKit URL: $(grep LIVEKIT_URL .env | cut -d= -f2)"
echo "   Gemini Model: $(grep GEMINI_MODEL .env | cut -d= -f2)"
echo "   Vobiz Trunk: $(grep OUTBOUND_TRUNK_ID .env | cut -d= -f2)"
echo ""

source venv/bin/activate

# Fix macOS Python SSL certificate verification
CERT_FILE=$(python -m certifi)
export SSL_CERT_FILE="$CERT_FILE"
export REQUESTS_CA_BUNDLE="$CERT_FILE"

python agent.py start
