#!/bin/bash
# RentIQ Database Backup Script
# This script creates encrypted backups of PostgreSQL database and uploads to S3
#
# Usage: bash 03_backup_database.sh
#
# Set up as cron job: 0 2 * * * /home/ubuntu/RentIQ/deployment/scripts/03_backup_database.sh

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================
APP_DIR="/home/ubuntu/RentIQ"
BACKUP_DIR="/home/ubuntu/backups"
RETENTION_DAYS=30  # Keep backups for 30 days locally
S3_BUCKET="${BACKUP_S3_BUCKET:-rentiq-backups}"  # Override in .env

# Load environment variables
set -a
source "${APP_DIR}/.env"
set +a

# Create backup directory if it doesn't exist
mkdir -p ${BACKUP_DIR}

# Timestamp for backup filename
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILENAME="rentiq_db_${TIMESTAMP}.sql"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_FILENAME}"
COMPRESSED_BACKUP="${BACKUP_PATH}.gz"
ENCRYPTED_BACKUP="${COMPRESSED_BACKUP}.gpg"

echo "========================================="
echo "RentIQ Database Backup"
echo "========================================="
echo "Timestamp: ${TIMESTAMP}"

# ============================================================================
# 1. Create Database Dump
# ============================================================================
echo "[1/5] Creating database dump..."
PGPASSWORD=${DB_PASSWORD} pg_dump \
    -h ${DB_HOST} \
    -U ${DB_USER} \
    -d ${DB_NAME} \
    -F p \
    --no-owner \
    --no-acl \
    --clean \
    --if-exists \
    -f ${BACKUP_PATH}

if [ ! -f ${BACKUP_PATH} ]; then
    echo "ERROR: Database dump failed"
    exit 1
fi

DUMP_SIZE=$(du -h ${BACKUP_PATH} | cut -f1)
echo "Database dump created: ${DUMP_SIZE}"

# ============================================================================
# 2. Compress Backup
# ============================================================================
echo "[2/5] Compressing backup..."
gzip -9 ${BACKUP_PATH}

if [ ! -f ${COMPRESSED_BACKUP} ]; then
    echo "ERROR: Compression failed"
    exit 1
fi

COMPRESSED_SIZE=$(du -h ${COMPRESSED_BACKUP} | cut -f1)
echo "Backup compressed: ${COMPRESSED_SIZE}"

# ============================================================================
# 3. Encrypt Backup (Optional but Recommended)
# ============================================================================
if command -v gpg &> /dev/null && [ -n "${BACKUP_ENCRYPTION_KEY:-}" ]; then
    echo "[3/5] Encrypting backup..."
    gpg --batch --yes --passphrase "${BACKUP_ENCRYPTION_KEY}" \
        --symmetric --cipher-algo AES256 \
        -o ${ENCRYPTED_BACKUP} ${COMPRESSED_BACKUP}

    if [ -f ${ENCRYPTED_BACKUP} ]; then
        # Remove unencrypted compressed file
        rm ${COMPRESSED_BACKUP}
        UPLOAD_FILE=${ENCRYPTED_BACKUP}
        echo "Backup encrypted with AES256"
    else
        echo "WARNING: Encryption failed, uploading compressed backup"
        UPLOAD_FILE=${COMPRESSED_BACKUP}
    fi
else
    echo "[3/5] Skipping encryption (gpg not available or BACKUP_ENCRYPTION_KEY not set)"
    UPLOAD_FILE=${COMPRESSED_BACKUP}
fi

# ============================================================================
# 4. Upload to S3
# ============================================================================
echo "[4/5] Uploading to S3..."
if command -v aws &> /dev/null; then
    S3_PATH="s3://${S3_BUCKET}/database/$(date +"%Y/%m/%d")/${UPLOAD_FILE##*/}"

    aws s3 cp ${UPLOAD_FILE} ${S3_PATH} \
        --storage-class STANDARD_IA \
        --metadata "backup-date=${TIMESTAMP},database=${DB_NAME}" \
        --region ${AWS_REGION:-us-east-1}

    if [ $? -eq 0 ]; then
        echo "Backup uploaded to: ${S3_PATH}"

        # Set lifecycle policy on first run
        if ! aws s3api get-bucket-lifecycle-configuration --bucket ${S3_BUCKET} &> /dev/null; then
            echo "Setting S3 lifecycle policy (90-day retention)..."
            cat > /tmp/s3_lifecycle.json <<EOF
{
    "Rules": [
        {
            "Id": "DeleteOldBackups",
            "Status": "Enabled",
            "Prefix": "database/",
            "Expiration": {
                "Days": 90
            },
            "Transitions": [
                {
                    "Days": 30,
                    "StorageClass": "GLACIER"
                }
            ]
        }
    ]
}
EOF
            aws s3api put-bucket-lifecycle-configuration \
                --bucket ${S3_BUCKET} \
                --lifecycle-configuration file:///tmp/s3_lifecycle.json
            rm /tmp/s3_lifecycle.json
        fi
    else
        echo "ERROR: S3 upload failed"
    fi
else
    echo "WARNING: AWS CLI not available, skipping S3 upload"
fi

# ============================================================================
# 5. Clean Up Old Local Backups
# ============================================================================
echo "[5/5] Cleaning up old local backups..."
find ${BACKUP_DIR} -name "rentiq_db_*.sql.gz*" -type f -mtime +${RETENTION_DAYS} -delete
REMAINING_BACKUPS=$(find ${BACKUP_DIR} -name "rentiq_db_*.sql.gz*" -type f | wc -l)
echo "Local backups retained: ${REMAINING_BACKUPS}"

# ============================================================================
# Completion
# ============================================================================
echo ""
echo "========================================="
echo "Backup complete!"
echo "========================================="
echo "Local backup: ${UPLOAD_FILE}"
echo "S3 backup: ${S3_PATH:-N/A}"
echo "Backup size: $(du -h ${UPLOAD_FILE} | cut -f1)"
echo ""
echo "To restore from this backup:"
if [ -f ${ENCRYPTED_BACKUP} ]; then
    echo "1. Decrypt: gpg --decrypt ${UPLOAD_FILE} > backup.sql.gz"
    echo "2. Decompress: gunzip backup.sql.gz"
    echo "3. Restore: PGPASSWORD=\$DB_PASSWORD psql -h \$DB_HOST -U \$DB_USER -d \$DB_NAME -f backup.sql"
else
    echo "1. Decompress: gunzip ${UPLOAD_FILE}"
    echo "2. Restore: PGPASSWORD=\$DB_PASSWORD psql -h \$DB_HOST -U \$DB_USER -d \$DB_NAME -f ${BACKUP_PATH}"
fi
echo ""
echo "Backup timestamp: ${TIMESTAMP}"
