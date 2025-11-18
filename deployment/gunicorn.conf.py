# Gunicorn Configuration for RentIQ Django Backend
# Documentation: https://docs.gunicorn.org/en/stable/settings.html

import multiprocessing
import os

# ============================================================================
# Server Socket
# ============================================================================
bind = os.getenv("GUNICORN_BIND", "127.0.0.1:8000")
backlog = 2048

# ============================================================================
# Worker Processes
# ============================================================================
# Formula: (2 x $num_cores) + 1
# For t3.medium (2 vCPUs): 4-5 workers
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"  # Options: sync, gevent, eventlet
threads = int(os.getenv("GUNICORN_THREADS", 2))
worker_connections = 1000
max_requests = 1000  # Restart worker after this many requests (prevents memory leaks)
max_requests_jitter = 50  # Add randomness to prevent all workers restarting simultaneously
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))  # 2 minutes for LLM requests
graceful_timeout = 30
keepalive = 5

# ============================================================================
# Worker Temporary Files
# ============================================================================
# Use /dev/shm for better performance (in-memory filesystem)
worker_tmp_dir = "/dev/shm"

# ============================================================================
# Logging
# ============================================================================
accesslog = "/var/log/rentiq/gunicorn_access.log"
errorlog = "/var/log/rentiq/gunicorn_error.log"
loglevel = os.getenv("LOG_LEVEL", "info")  # debug, info, warning, error, critical
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'
# Log format includes:
# %(h)s - Remote address
# %(l)s - '-' (not used)
# %(u)s - User name
# %(t)s - Date of request
# %(r)s - Request line
# %(s)s - Status code
# %(b)s - Response length
# %(f)s - Referer
# %(a)s - User agent
# %(L)s - Request time in seconds

# ============================================================================
# Process Naming
# ============================================================================
proc_name = "rentiq_gunicorn"

# ============================================================================
# Server Mechanics
# ============================================================================
daemon = False  # Supervisor/systemd manages daemonization
pidfile = "/var/run/rentiq/gunicorn.pid"
user = None  # Run as the user who starts the process (ubuntu)
group = None
umask = 0
tmp_upload_dir = None

# ============================================================================
# Security
# ============================================================================
# Limit request line size (helps prevent certain attacks)
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# ============================================================================
# Server Hooks
# ============================================================================
def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Gunicorn master process starting")

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    server.log.info("Gunicorn workers reloading")

def when_ready(server):
    """Called just after the server is started."""
    server.log.info(f"Gunicorn server is ready. Spawning {workers} workers")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info(f"Worker spawned (pid: {worker.pid})")

def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    pass

def worker_int(worker):
    """Called just after a worker exited on SIGINT or SIGQUIT."""
    worker.log.info(f"Worker received INT or QUIT signal (pid: {worker.pid})")

def worker_abort(worker):
    """Called when a worker received the SIGABRT signal."""
    worker.log.error(f"Worker received SIGABRT signal (pid: {worker.pid})")

def pre_exec(server):
    """Called just before a new master process is forked."""
    server.log.info("Forking new master process")

def pre_request(worker, req):
    """Called just before a worker processes the request."""
    worker.log.debug(f"{req.method} {req.path}")

def post_request(worker, req, environ, resp):
    """Called after a worker processes the request."""
    pass

def child_exit(server, worker):
    """Called just after a worker has been exited."""
    server.log.info(f"Worker exited (pid: {worker.pid})")

def worker_exit(server, worker):
    """Called just after a worker has been exited."""
    pass

def nworkers_changed(server, new_value, old_value):
    """Called just after num_workers has been changed."""
    server.log.info(f"Number of workers changed from {old_value} to {new_value}")

def on_exit(server):
    """Called just before exiting Gunicorn."""
    server.log.info("Gunicorn shutting down")

# ============================================================================
# SSL (if terminating SSL at application level - not recommended, use ALB/Nginx)
# ============================================================================
# keyfile = None
# certfile = None
# ssl_version = 2  # TLS 1.2
# cert_reqs = 0
# ca_certs = None
# suppress_ragged_eofs = True
# do_handshake_on_connect = False
# ciphers = None

# ============================================================================
# Development Settings (override in .env)
# ============================================================================
if os.getenv("DJANGO_DEBUG", "False").lower() == "true":
    reload = True  # Auto-reload on code changes (DEV ONLY)
    reload_extra_files = []
    loglevel = "debug"
else:
    reload = False

# ============================================================================
# Performance Tuning
# ============================================================================
# Preload application code before worker processes are forked
# This can save RAM but may cause issues with certain code
preload_app = False  # Set to True if all code is fork-safe

# Enable sendfile for serving static files (requires proper headers)
sendfile = False  # Nginx handles static files

# Forward ALLOW_IPS for proxy protocol support
forwarded_allow_ips = "127.0.0.1,::1"  # Trust localhost

# ============================================================================
# Instrumentation (Optional - for monitoring)
# ============================================================================
# statsd_host = None
# statsd_prefix = "rentiq"
# dogstatsd_tags = ""

# ============================================================================
# Notes
# ============================================================================
# To test this configuration:
#   gunicorn --config deployment/gunicorn.conf.py backend.wsgi:application
#
# To reload workers gracefully:
#   kill -HUP $(cat /var/run/rentiq/gunicorn.pid)
#
# To check worker status:
#   ps aux | grep gunicorn
#
# To monitor performance:
#   tail -f /var/log/rentiq/gunicorn_access.log
