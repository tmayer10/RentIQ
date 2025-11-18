#!/bin/bash
# RentIQ Application Deployment Script
# This script deploys/updates the RentIQ application
#
# Usage: bash 02_deploy_app.sh [--first-time]
#
# --first-time: Run initial setup tasks (create venv, install dependencies)

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================
APP_USER="ubuntu"
APP_DIR="/home/ubuntu/RentIQ"
VENV_DIR="${APP_DIR}/venv"
DEPLOYMENT_DIR="${APP_DIR}/deployment"
LOG_DIR="/var/log/rentiq"

FIRST_TIME=false
if [[ "${1:-}" == "--first-time" ]]; then
    FIRST_TIME=true
fi

echo "========================================="
echo "RentIQ Application Deployment"
echo "========================================="

# ============================================================================
# Pre-flight Checks
# ============================================================================
echo "[0/12] Running pre-flight checks..."

# Check if .env exists
if [ ! -f "${APP_DIR}/.env" ]; then
    echo "ERROR: .env file not found at ${APP_DIR}/.env"
    echo "Please copy .env.production.template to .env and configure it"
    exit 1
fi

# Source environment variables
set -a
source "${APP_DIR}/.env"
set +a

# ============================================================================
# 1. Pull Latest Code
# ============================================================================
echo "[1/12] Pulling latest code from git..."
cd ${APP_DIR}
if [ -d ".git" ]; then
    git fetch origin
    git pull origin main
else
    echo "WARNING: Not a git repository. Skipping git pull."
fi

# ============================================================================
# 2. Create/Update Virtual Environment
# ============================================================================
if [ "$FIRST_TIME" = true ] || [ ! -d "${VENV_DIR}" ]; then
    echo "[2/12] Creating Python virtual environment..."
    python3.11 -m venv ${VENV_DIR}
else
    echo "[2/12] Using existing virtual environment..."
fi

# Activate virtual environment
source ${VENV_DIR}/bin/activate

# ============================================================================
# 3. Install/Update Python Dependencies
# ============================================================================
echo "[3/12] Installing Python dependencies..."
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# ============================================================================
# 4. Run Database Migrations
# ============================================================================
echo "[4/12] Running database migrations..."
cd ${APP_DIR}
python manage.py makemigrations --noinput
python manage.py migrate --noinput

# ============================================================================
# 5. Collect Static Files
# ============================================================================
echo "[5/12] Collecting static files..."
python manage.py collectstatic --noinput --clear

# ============================================================================
# 6. Create Superuser (First Time Only)
# ============================================================================
if [ "$FIRST_TIME" = true ]; then
    echo "[6/12] Creating Django superuser..."
    echo "Please enter superuser credentials:"
    python manage.py createsuperuser
else
    echo "[6/12] Skipping superuser creation (not first-time deployment)..."
fi

# ============================================================================
# 7. Deploy Nginx Configuration
# ============================================================================
echo "[7/12] Deploying Nginx configuration..."
sudo cp ${DEPLOYMENT_DIR}/nginx.conf /etc/nginx/sites-available/rentiq

# Update domain names in nginx config
sudo sed -i "s/yourdomain.com/${DOMAIN_NAME:-yourdomain.com}/g" /etc/nginx/sites-available/rentiq

# Enable site
sudo ln -sf /etc/nginx/sites-available/rentiq /etc/nginx/sites-enabled/rentiq

# Test Nginx configuration
sudo nginx -t

# ============================================================================
# 8. Deploy Supervisor Configuration
# ============================================================================
echo "[8/12] Deploying Supervisor configuration..."
sudo cp ${DEPLOYMENT_DIR}/supervisor.conf /etc/supervisor/conf.d/rentiq.conf

# Update paths in supervisor config
sudo sed -i "s|/home/ubuntu/RentIQ|${APP_DIR}|g" /etc/supervisor/conf.d/rentiq.conf

# Reload supervisor configuration
sudo supervisorctl reread
sudo supervisorctl update

# ============================================================================
# 9. Create Log Files (if they don't exist)
# ============================================================================
echo "[9/12] Setting up log files..."
for log_file in \
    gunicorn_access.log gunicorn_error.log \
    django_supervisor_stdout.log django_supervisor_stderr.log \
    streamlit_supervisor_stdout.log streamlit_supervisor_stderr.log; do

    touch ${LOG_DIR}/${log_file}
    chown ${APP_USER}:${APP_USER} ${LOG_DIR}/${log_file}
done

# ============================================================================
# 10. Restart Application Services
# ============================================================================
echo "[10/12] Restarting application services..."
sudo supervisorctl restart all

# Wait for services to start
sleep 5

# Check service status
echo "Service status:"
sudo supervisorctl status

# ============================================================================
# 11. Reload Nginx
# ============================================================================
echo "[11/12] Reloading Nginx..."
sudo systemctl reload nginx

# ============================================================================
# 12. Post-Deployment Health Check
# ============================================================================
echo "[12/12] Running health checks..."

# Check if Django is responding
echo -n "Django health check: "
if curl -f http://localhost:8000/health/ > /dev/null 2>&1; then
    echo "✓ OK"
else
    echo "✗ FAILED"
    echo "Check logs: tail -f ${LOG_DIR}/gunicorn_error.log"
fi

# Check if Streamlit is responding
echo -n "Streamlit health check: "
if curl -f http://localhost:8501/healthz > /dev/null 2>&1; then
    echo "✓ OK"
else
    echo "✗ FAILED (may take a few seconds to start)"
    echo "Check logs: tail -f ${LOG_DIR}/streamlit_supervisor_stdout.log"
fi

# Check database connection
echo -n "Database connection: "
if python manage.py dbshell --command "SELECT 1" > /dev/null 2>&1; then
    echo "✓ OK"
else
    echo "✗ FAILED"
fi

# Check Redis connection
echo -n "Redis connection: "
if redis-cli -u ${REDIS_URL} ping > /dev/null 2>&1; then
    echo "✓ OK"
else
    echo "✗ FAILED"
fi

# ============================================================================
# Completion
# ============================================================================
echo ""
echo "========================================="
echo "Deployment complete!"
echo "========================================="
echo ""
echo "Application endpoints:"
echo "- Django API: http://localhost:8000"
echo "- Streamlit: http://localhost:8501"
echo ""
echo "Next steps:"
if [ "$FIRST_TIME" = true ]; then
    echo "1. Configure SSL certificates: sudo certbot --nginx -d api.yourdomain.com -d chat.yourdomain.com"
    echo "2. Test external access via ALB/domain"
    echo "3. Set up CloudWatch monitoring"
fi
echo ""
echo "Useful commands:"
echo "- View logs: tail -f ${LOG_DIR}/*.log"
echo "- Restart services: sudo supervisorctl restart all"
echo "- Check status: sudo supervisorctl status"
echo "- Django shell: python manage.py shell"
echo ""
echo "Deployment timestamp: $(date)"
