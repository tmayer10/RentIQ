#!/bin/bash
# RentIQ EC2 Initial Setup Script
# This script sets up a fresh Ubuntu 22.04 EC2 instance for RentIQ deployment
#
# Usage: sudo bash 01_initial_setup.sh
#
# Run this script ONCE on a new EC2 instance

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================
APP_USER="ubuntu"
APP_DIR="/home/ubuntu/RentIQ"
LOG_DIR="/var/log/rentiq"
RUN_DIR="/var/run/rentiq"
PYTHON_VERSION="3.11"

echo "========================================="
echo "RentIQ Initial EC2 Setup"
echo "========================================="

# ============================================================================
# 1. System Updates
# ============================================================================
echo "[1/10] Updating system packages..."
apt-get update -y
apt-get upgrade -y

# ============================================================================
# 2. Install System Dependencies
# ============================================================================
echo "[2/10] Installing system dependencies..."
apt-get install -y \
    python${PYTHON_VERSION} \
    python${PYTHON_VERSION}-venv \
    python${PYTHON_VERSION}-dev \
    python3-pip \
    postgresql-client \
    redis-tools \
    nginx \
    supervisor \
    git \
    curl \
    wget \
    unzip \
    build-essential \
    libssl-dev \
    libffi-dev \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    certbot \
    python3-certbot-nginx \
    htop \
    vim \
    tmux

# ============================================================================
# 3. Configure Firewall (UFW)
# ============================================================================
echo "[3/10] Configuring firewall..."
ufw --force enable
ufw allow ssh
ufw allow 'Nginx Full'
ufw allow 8000/tcp  # Gunicorn (internal)
ufw allow 8501/tcp  # Streamlit (internal)
ufw status

# ============================================================================
# 4. Create Application Directories
# ============================================================================
echo "[4/10] Creating application directories..."
mkdir -p ${LOG_DIR}
mkdir -p ${RUN_DIR}
mkdir -p ${APP_DIR}/staticfiles
mkdir -p ${APP_DIR}/media
mkdir -p /var/www/certbot

# Set ownership
chown -R ${APP_USER}:${APP_USER} ${LOG_DIR}
chown -R ${APP_USER}:${APP_USER} ${RUN_DIR}
chown -R ${APP_USER}:${APP_USER} ${APP_DIR}

# ============================================================================
# 5. Configure Log Rotation
# ============================================================================
echo "[5/10] Configuring log rotation..."
cat > /etc/logrotate.d/rentiq <<EOF
${LOG_DIR}/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 ${APP_USER} ${APP_USER}
    sharedscripts
    postrotate
        supervisorctl restart all > /dev/null 2>&1 || true
    endscript
}
EOF

# ============================================================================
# 6. Install CloudWatch Agent (Optional)
# ============================================================================
echo "[6/10] Installing CloudWatch agent..."
if ! command -v amazon-cloudwatch-agent &> /dev/null; then
    wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
    dpkg -i -E ./amazon-cloudwatch-agent.deb
    rm amazon-cloudwatch-agent.deb
    echo "CloudWatch agent installed. Configure it later with: sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-config-wizard"
else
    echo "CloudWatch agent already installed"
fi

# ============================================================================
# 7. Configure Nginx
# ============================================================================
echo "[7/10] Configuring Nginx..."
# Remove default site
rm -f /etc/nginx/sites-enabled/default

# Optimize Nginx
cat > /etc/nginx/nginx.conf <<EOF
user www-data;
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 2048;
    use epoll;
    multi_accept on;
}

http {
    # Basic Settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    server_tokens off;
    client_max_body_size 10M;

    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # SSL Settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';

    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;

    # Gzip Settings
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml text/javascript application/json application/javascript application/xml+rss application/rss+xml font/truetype font/opentype application/vnd.ms-fontobject image/svg+xml;

    # Virtual Host Configs
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
EOF

# Test configuration
nginx -t

# ============================================================================
# 8. Configure Supervisor
# ============================================================================
echo "[8/10] Configuring Supervisor..."
# Ensure supervisor is enabled
systemctl enable supervisor
systemctl start supervisor

# Create supervisor socket directory
mkdir -p /var/run/supervisor
chown root:root /var/run/supervisor

# ============================================================================
# 9. Set Up Python Environment
# ============================================================================
echo "[9/10] Setting up Python environment..."
# Update pip
sudo -u ${APP_USER} python${PYTHON_VERSION} -m pip install --upgrade pip setuptools wheel

# Note: Virtual environment will be created during app deployment

# ============================================================================
# 10. Create Deployment Helper Scripts
# ============================================================================
echo "[10/10] Creating helper scripts..."

# Health check script
cat > ${APP_DIR}/healthcheck.sh <<'EOF'
#!/bin/bash
# Quick health check for RentIQ services

echo "=== RentIQ Health Check ==="

echo -n "Nginx: "
systemctl is-active nginx

echo -n "Supervisor: "
systemctl is-active supervisor

echo -n "Django (Gunicorn): "
supervisorctl status django_gunicorn | awk '{print $2}'

echo -n "Streamlit: "
supervisorctl status streamlit_app | awk '{print $2}'

echo -n "PostgreSQL connection: "
if PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT 1" > /dev/null 2>&1; then
    echo "OK"
else
    echo "FAILED"
fi

echo -n "Redis connection: "
if redis-cli -u $REDIS_URL ping > /dev/null 2>&1; then
    echo "OK"
else
    echo "FAILED"
fi
EOF

chmod +x ${APP_DIR}/healthcheck.sh
chown ${APP_USER}:${APP_USER} ${APP_DIR}/healthcheck.sh

# Service restart script
cat > ${APP_DIR}/restart_services.sh <<'EOF'
#!/bin/bash
# Restart all RentIQ services

echo "Restarting RentIQ services..."
sudo supervisorctl restart all
sudo systemctl reload nginx
echo "Done!"
EOF

chmod +x ${APP_DIR}/restart_services.sh
chown ${APP_USER}:${APP_USER} ${APP_DIR}/restart_services.sh

# ============================================================================
# Completion
# ============================================================================
echo "========================================="
echo "Initial setup complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Clone the RentIQ repository to ${APP_DIR}"
echo "2. Copy .env.production.template to .env and configure"
echo "3. Run 02_deploy_app.sh to deploy the application"
echo "4. Configure SSL certificates with certbot"
echo ""
echo "Installed services status:"
echo "- Nginx: $(systemctl is-active nginx)"
echo "- Supervisor: $(systemctl is-active supervisor)"
echo ""
echo "Useful commands:"
echo "- Check services: ${APP_DIR}/healthcheck.sh"
echo "- Restart services: ${APP_DIR}/restart_services.sh"
echo "- View logs: tail -f ${LOG_DIR}/*.log"
echo "- Supervisor control: sudo supervisorctl status"
