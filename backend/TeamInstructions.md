# 🏠 RentIQ - Team Setup Guide

Quick setup guide to get the RentIQ Django + PostgreSQL application running locally using Docker.

---

## 📋 Prerequisites

Before you begin, install these on your machine:

1. **Docker Desktop** - [Download here](https://www.docker.com/products/docker-desktop)
   - macOS: Download and install Docker Desktop for Mac
   - Windows: Download and install Docker Desktop for Windows
   - Linux: Install Docker Engine and Docker Compose

2. **Git** - Should already be installed, verify with:
   ```bash
   git --version
   ```

---

## 🚀 Quick Start (5 minutes)

### Step 1: Clone the Repository

```bash
git clone <YOUR_REPO_URL_HERE>
cd RentIQ
```

### Step 2: Create Environment File

```bash
# Copy the example environment file
cp .env.example .env

# No need to change anything - defaults work for local development!
```

### Step 3: Build and Start Docker Containers

```bash
# Build the Docker images (first time only, takes ~2-3 minutes)
docker-compose build

# Start all containers (PostgreSQL + Django)
docker-compose up
```

**You should see:**

git clone <YOUR_REPO_URL_HERE>
cd RentIQ
---


**Expected output:**

# Copy the example environment file
cp .env.example .env

# No need to change anything - defaults work for local development!ith your superuser credentials
  - Browse Buildings, Listings, Subway Stations

- **API** (once we build it): http://localhost:8000/api/

---

## 🛠️ Daily Development Workflow

### Starting Work (Morning)

```bash
cd RentIQ
docker-compose up
```

### Making Code Changes

- **Edit files** in your IDE as normal (VS Code, PyCharm, etc.)
- **Changes auto-reload!** Django detects file changes automatically
- No need to restart containers for code changes

### Running Django Commands

**Always prefix with `docker-compose exec backend`:**

```bash
# Run migrations after model changes
docker-compose exec backend python manage.py makemigrations
docker-compose exec backend python manage.py migrate

# Access Django shell
docker-compose exec backend python manage.py shell

# Create new app
docker-compose exec backend python manage.py startapp <app_name>

# Run tests
docker-compose exec backend python manage.py test

# Import more data
docker-compose exec backend python manage.py import_manhattan --limit 100
```

### Stopping Work (End of Day)

**In the terminal running docker-compose:**
- Press `Ctrl + C` to stop
- Then run:
  ```bash
  docker-compose down
  ```

---

## 📚 Common Commands Reference

### Docker Commands

```bash
# Start containers
docker-compose up

# Start in background (detached mode)
docker-compose up -d

# Stop containers
docker-compose down

# Stop and remove database (fresh start)
docker-compose down -v

# View logs
docker-compose logs
docker-compose logs -f backend  # Follow backend logs
docker-compose logs -f db       # Follow database logs

# Restart a service
docker-compose restart backend

# Rebuild after requirements.txt changes
docker-compose build --no-cache
docker-compose up
```



---

## 🚀 Quick Command Summary

```bash
# First time setup
git clone <repo-url>
cd RentIQ
cp .env.example .env
docker-compose build
docker-compose up
# (new terminal)
docker-compose exec backend python manage.py createsuperuser
docker-compose exec backend python manage.py import_manhattan --limit 50

# Daily workflow
docker-compose up                    # Start
# ... make code changes ...
docker-compose down                  # Stop

# Common tasks
docker-compose exec backend python manage.py <command>
docker-compose logs -f backend
docker-compose restart backend
```

---

**Last Updated:** October 15, 2025  
**Questions?** Contact the team lead or check our project docs

---

**Happy Coding! 🎉**

rentiq_db       | database system is ready to accept connections
rentiq_backend  | Running migrations...
rentiq_backend  | Starting development server at http://0.0.0.0:8000/
