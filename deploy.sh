#!/bin/bash

# Rotato Deployment Script
# This script helps deploy Rotato to a server with basic configuration

# Exit on any error
set -e

echo "🌀 Starting Rotato deployment..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️ No .env file found. Creating from example..."
    cp .env.example .env
    echo "⚠️ Please edit .env with your actual configuration values before proceeding!"
    exit 1
fi

# Set up virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "🔧 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Install or upgrade dependencies
echo "📦 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create database directory if it doesn't exist
mkdir -p instance

# Check if running in production mode
if [ "$1" == "prod" ]; then
    echo "🚀 Setting up for production deployment..."
    
    # Generate secret key if not in .env
    if ! grep -q "FLASK_SECRET_KEY" .env || grep -q "your_random_secret_key_here" .env; then
        echo "🔑 Generating new secret key..."
        SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(24))")
        sed -i.bak "s/FLASK_SECRET_KEY=.*/FLASK_SECRET_KEY=$SECRET_KEY/" .env
        rm .env.bak
    fi
    
    # Set up Gunicorn systemd service
    echo "🔧 Creating systemd service file..."
    cat > rotato.service << EOF
[Unit]
Description=Rotato Gunicorn Daemon
After=network.target

[Service]
User=$(whoami)
Group=$(id -gn)
WorkingDirectory=$(pwd)
Environment="PATH=$(pwd)/.venv/bin"
ExecStart=$(pwd)/.venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 app:app

[Install]
WantedBy=multi-user.target
EOF
    
    echo "🔧 Moving service file to systemd directory..."
    sudo mv rotato.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable rotato
    
    # Set up Nginx config if available
    if command -v nginx &> /dev/null; then
        echo "🔧 Creating Nginx configuration..."
        cat > rotato.nginx << EOF
server {
    listen 80;
    server_name _;  # Replace with your domain name
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF
        echo "🔧 Moving Nginx config to sites-available..."
        sudo mv rotato.nginx /etc/nginx/sites-available/rotato
        sudo ln -sf /etc/nginx/sites-available/rotato /etc/nginx/sites-enabled/
        sudo nginx -t && sudo systemctl restart nginx
    else
        echo "⚠️ Nginx not found. Skipping Nginx configuration."
    fi
    
    echo "🚀 Starting Rotato service..."
    sudo systemctl start rotato
    
    echo "✅ Deployment complete! Rotato is now running in production mode."
    echo "   Check status with: sudo systemctl status rotato"
else
    # Development mode
    echo "🔧 Running in development mode..."
    python app.py
fi
