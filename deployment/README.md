# RentIQ AWS Deployment Guide

Comprehensive guide for deploying RentIQ to AWS (EC2, RDS, ElastiCache, S3, CloudFront).

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Architecture](#architecture)
- [Deployment Files](#deployment-files)
- [Step-by-Step Deployment](#step-by-step-deployment)
- [Configuration](#configuration)
- [Monitoring & Logging](#monitoring--logging)
- [Maintenance](#maintenance)
- [Troubleshooting](#troubleshooting)
- [Cost Estimates](#cost-estimates)

---

## Overview

This deployment guide covers the complete production deployment of RentIQ to AWS infrastructure. The deployment includes:

- **Django REST API** (Gunicorn + Nginx)
- **Streamlit Chat Interface** (WebSocket support)
- **PostgreSQL Database** (AWS RDS)
- **Redis Cache** (AWS ElastiCache)
- **S3 + CloudFront** (Static assets for React frontend)
- **Application Load Balancer** (SSL termination, routing)
- **CloudWatch** (Logging and monitoring)

**Estimated Deployment Time:** 16-24 hours (first-time deployment)

**Monthly Cost Estimate:** $136-185/month (see [Cost Estimates](#cost-estimates))

---

## Prerequisites

### AWS Account Requirements

- **AWS Account** with administrative access
- **IAM User** with the following permissions:
  - EC2 (full access)
  - RDS (full access)
  - ElastiCache (full access)
  - S3 (full access)
  - CloudFront (full access)
  - Route 53 (full access)
  - ACM (full access)
  - CloudWatch (full access)
  - Secrets Manager (full access)
  - VPC (full access)

### Local Requirements

- **AWS CLI** configured (`aws configure`)
- **SSH Key Pair** for EC2 access
- **Domain Name** (optional but recommended)
- **Git** installed

### API Keys Required

Store these in AWS Secrets Manager (instructions below):

- OpenAI API Key
- Google API Key (for Gemini)
- Pinecone API Key

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Route 53 (DNS)                        │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│             Application Load Balancer (ALB)                 │
│              - SSL Termination (ACM Certificate)            │
│              - Health Checks                                │
└────────┬──────────────────────────────┬─────────────────────┘
         │                              │
         │                              │
┌────────▼──────────┐          ┌────────▼─────────────┐
│  api.domain.com   │          │  chat.domain.com     │
│  (Django/Nginx)   │          │  (Streamlit/Nginx)   │
│                   │          │                      │
│  EC2 t3.medium    │          │  Same EC2 Instance   │
│  - Gunicorn       │          │  - Streamlit         │
│  - Nginx          │          │  - WebSocket         │
│  - Supervisor     │          │                      │
└────────┬──────────┘          └────────┬─────────────┘
         │                              │
         │                              │
┌────────▼──────────────────────────────▼─────────────┐
│              Shared Resources                       │
│                                                      │
│  RDS PostgreSQL (db.t3.micro)                       │
│  ElastiCache Redis (cache.t3.micro)                 │
│  S3 (React Frontend + Backups)                      │
│  CloudWatch (Logs + Metrics)                        │
└─────────────────────────────────────────────────────┘
```

---

## Deployment Files

### Configuration Files

| File | Purpose | Install Location |
|------|---------|------------------|
| `.env.production.template` | Environment variables template | `/home/ubuntu/RentIQ/.env` |
| `nginx.conf` | Nginx reverse proxy configuration | `/etc/nginx/sites-available/rentiq` |
| `supervisor.conf` | Process manager configuration | `/etc/supervisor/conf.d/rentiq.conf` |
| `gunicorn.conf.py` | Gunicorn WSGI server settings | `/home/ubuntu/RentIQ/deployment/gunicorn.conf.py` |
| `cloudwatch-config.json` | CloudWatch agent configuration | `/opt/aws/amazon-cloudwatch-agent/etc/` |

### Systemd Services (Alternative to Supervisor)

| File | Purpose |
|------|---------|
| `systemd/rentiq-gunicorn.service` | Django/Gunicorn systemd service |
| `systemd/rentiq-streamlit.service` | Streamlit systemd service |

### Deployment Scripts

| Script | Purpose |
|--------|---------|
| `scripts/01_initial_setup.sh` | Initial EC2 instance setup |
| `scripts/02_deploy_app.sh` | Deploy/update application code |
| `scripts/03_backup_database.sh` | Automated database backups |

---

## Step-by-Step Deployment

### Phase 1: Prerequisites and AWS Setup

#### 1.1 Create AWS Account and Configure CLI

```bash
# Install AWS CLI (if not already installed)
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Configure AWS credentials
aws configure
# Enter: Access Key ID, Secret Access Key, Region (us-east-1), Output format (json)
```

#### 1.2 Create SSH Key Pair

```bash
# Create SSH key pair in AWS console or via CLI
aws ec2 create-key-pair \
    --key-name rentiq-key \
    --query 'KeyMaterial' \
    --output text > ~/.ssh/rentiq-key.pem

chmod 400 ~/.ssh/rentiq-key.pem
```

---

### Phase 2: VPC and Networking

#### 2.1 Create VPC

```bash
# Create VPC
VPC_ID=$(aws ec2 create-vpc \
    --cidr-block 10.0.0.0/16 \
    --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=rentiq-vpc}]' \
    --query 'Vpc.VpcId' \
    --output text)

# Enable DNS hostnames
aws ec2 modify-vpc-attribute \
    --vpc-id $VPC_ID \
    --enable-dns-hostnames
```

#### 2.2 Create Subnets

```bash
# Public Subnet 1 (us-east-1a)
PUBLIC_SUBNET_1=$(aws ec2 create-subnet \
    --vpc-id $VPC_ID \
    --cidr-block 10.0.1.0/24 \
    --availability-zone us-east-1a \
    --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=rentiq-public-1a}]' \
    --query 'Subnet.SubnetId' \
    --output text)

# Public Subnet 2 (us-east-1b)
PUBLIC_SUBNET_2=$(aws ec2 create-subnet \
    --vpc-id $VPC_ID \
    --cidr-block 10.0.2.0/24 \
    --availability-zone us-east-1b \
    --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=rentiq-public-1b}]' \
    --query 'Subnet.SubnetId' \
    --output text)

# Private Subnet 1 (for RDS)
PRIVATE_SUBNET_1=$(aws ec2 create-subnet \
    --vpc-id $VPC_ID \
    --cidr-block 10.0.11.0/24 \
    --availability-zone us-east-1a \
    --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=rentiq-private-1a}]' \
    --query 'Subnet.SubnetId' \
    --output text)

# Private Subnet 2 (for RDS)
PRIVATE_SUBNET_2=$(aws ec2 create-subnet \
    --vpc-id $VPC_ID \
    --cidr-block 10.0.12.0/24 \
    --availability-zone us-east-1b \
    --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=rentiq-private-1b}]' \
    --query 'Subnet.SubnetId' \
    --output text)
```

#### 2.3 Create Internet Gateway

```bash
# Create Internet Gateway
IGW_ID=$(aws ec2 create-internet-gateway \
    --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=rentiq-igw}]' \
    --query 'InternetGateway.InternetGatewayId' \
    --output text)

# Attach to VPC
aws ec2 attach-internet-gateway \
    --vpc-id $VPC_ID \
    --internet-gateway-id $IGW_ID
```

#### 2.4 Create Route Tables

```bash
# Create public route table
PUBLIC_RT=$(aws ec2 create-route-table \
    --vpc-id $VPC_ID \
    --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=rentiq-public-rt}]' \
    --query 'RouteTable.RouteTableId' \
    --output text)

# Add route to Internet Gateway
aws ec2 create-route \
    --route-table-id $PUBLIC_RT \
    --destination-cidr-block 0.0.0.0/0 \
    --gateway-id $IGW_ID

# Associate with public subnets
aws ec2 associate-route-table \
    --subnet-id $PUBLIC_SUBNET_1 \
    --route-table-id $PUBLIC_RT

aws ec2 associate-route-table \
    --subnet-id $PUBLIC_SUBNET_2 \
    --route-table-id $PUBLIC_RT
```

#### 2.5 Create Security Groups

```bash
# EC2 Security Group
EC2_SG=$(aws ec2 create-security-group \
    --group-name rentiq-ec2-sg \
    --description "Security group for RentIQ EC2 instance" \
    --vpc-id $VPC_ID \
    --query 'GroupId' \
    --output text)

aws ec2 authorize-security-group-ingress \
    --group-id $EC2_SG \
    --ip-permissions \
        IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges='[{CidrIp=0.0.0.0/0,Description="SSH"}]' \
        IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges='[{CidrIp=0.0.0.0/0,Description="HTTP"}]' \
        IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges='[{CidrIp=0.0.0.0/0,Description="HTTPS"}]'

# RDS Security Group
RDS_SG=$(aws ec2 create-security-group \
    --group-name rentiq-rds-sg \
    --description "Security group for RentIQ RDS instance" \
    --vpc-id $VPC_ID \
    --query 'GroupId' \
    --output text)

aws ec2 authorize-security-group-ingress \
    --group-id $RDS_SG \
    --protocol tcp \
    --port 5432 \
    --source-group $EC2_SG

# ElastiCache Security Group
REDIS_SG=$(aws ec2 create-security-group \
    --group-name rentiq-redis-sg \
    --description "Security group for RentIQ ElastiCache" \
    --vpc-id $VPC_ID \
    --query 'GroupId' \
    --output text)

aws ec2 authorize-security-group-ingress \
    --group-id $REDIS_SG \
    --protocol tcp \
    --port 6379 \
    --source-group $EC2_SG
```

---

### Phase 3: RDS PostgreSQL and ElastiCache Redis

#### 3.1 Create RDS Subnet Group

```bash
aws rds create-db-subnet-group \
    --db-subnet-group-name rentiq-db-subnet-group \
    --db-subnet-group-description "Subnet group for RentIQ RDS" \
    --subnet-ids $PRIVATE_SUBNET_1 $PRIVATE_SUBNET_2 \
    --tags Key=Name,Value=rentiq-db-subnet-group
```

#### 3.2 Create RDS PostgreSQL Instance

```bash
aws rds create-db-instance \
    --db-instance-identifier rentiq-db \
    --db-instance-class db.t3.micro \
    --engine postgres \
    --engine-version 15.3 \
    --master-username rentiq_admin \
    --master-user-password 'YOUR_SECURE_PASSWORD_HERE' \
    --allocated-storage 20 \
    --storage-type gp3 \
    --vpc-security-group-ids $RDS_SG \
    --db-subnet-group-name rentiq-db-subnet-group \
    --backup-retention-period 7 \
    --preferred-backup-window "03:00-04:00" \
    --preferred-maintenance-window "mon:04:00-mon:05:00" \
    --no-multi-az \
    --no-publicly-accessible \
    --tags Key=Name,Value=rentiq-db

# Wait for RDS to be available (takes ~10 minutes)
aws rds wait db-instance-available --db-instance-identifier rentiq-db

# Get RDS endpoint
RDS_ENDPOINT=$(aws rds describe-db-instances \
    --db-instance-identifier rentiq-db \
    --query 'DBInstances[0].Endpoint.Address' \
    --output text)

echo "RDS Endpoint: $RDS_ENDPOINT"
```

#### 3.3 Create ElastiCache Redis Subnet Group

```bash
aws elasticache create-cache-subnet-group \
    --cache-subnet-group-name rentiq-redis-subnet-group \
    --cache-subnet-group-description "Subnet group for RentIQ ElastiCache" \
    --subnet-ids $PRIVATE_SUBNET_1 $PRIVATE_SUBNET_2
```

#### 3.4 Create ElastiCache Redis Cluster

```bash
aws elasticache create-cache-cluster \
    --cache-cluster-id rentiq-redis \
    --cache-node-type cache.t3.micro \
    --engine redis \
    --engine-version 7.0 \
    --num-cache-nodes 1 \
    --cache-subnet-group-name rentiq-redis-subnet-group \
    --security-group-ids $REDIS_SG \
    --snapshot-retention-limit 5 \
    --preferred-maintenance-window "mon:05:00-mon:06:00" \
    --tags Key=Name,Value=rentiq-redis

# Wait for Redis to be available (takes ~5 minutes)
aws elasticache wait cache-cluster-available --cache-cluster-id rentiq-redis

# Get Redis endpoint
REDIS_ENDPOINT=$(aws elasticache describe-cache-clusters \
    --cache-cluster-id rentiq-redis \
    --show-cache-node-info \
    --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' \
    --output text)

echo "Redis Endpoint: $REDIS_ENDPOINT"
```

---

### Phase 4: Secrets Manager (Store API Keys)

```bash
# Store OpenAI API Key
aws secretsmanager create-secret \
    --name rentiq/openai-api-key \
    --description "OpenAI API Key for RentIQ" \
    --secret-string "YOUR_OPENAI_API_KEY"

# Store Google API Key
aws secretsmanager create-secret \
    --name rentiq/google-api-key \
    --description "Google API Key for RentIQ" \
    --secret-string "YOUR_GOOGLE_API_KEY"

# Store Pinecone API Key
aws secretsmanager create-secret \
    --name rentiq/pinecone-api-key \
    --description "Pinecone API Key for RentIQ" \
    --secret-string "YOUR_PINECONE_API_KEY"
```

---

### Phase 5: Launch EC2 Instance and Deploy Application

#### 5.1 Launch EC2 Instance

```bash
# Find latest Ubuntu 22.04 AMI
AMI_ID=$(aws ec2 describe-images \
    --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
    --output text)

# Launch EC2 instance
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id $AMI_ID \
    --instance-type t3.medium \
    --key-name rentiq-key \
    --security-group-ids $EC2_SG \
    --subnet-id $PUBLIC_SUBNET_1 \
    --associate-public-ip-address \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
    --iam-instance-profile Name=EC2-CloudWatch-Role \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=rentiq-app-server}]' \
    --query 'Instances[0].InstanceId' \
    --output text)

# Wait for instance to be running
aws ec2 wait instance-running --instance-ids $INSTANCE_ID

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids $INSTANCE_ID \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo "EC2 Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
```

#### 5.2 SSH into EC2 and Run Initial Setup

```bash
# SSH into the instance
ssh -i ~/.ssh/rentiq-key.pem ubuntu@$PUBLIC_IP

# On the EC2 instance, clone the repository
git clone https://github.com/yourusername/RentIQ.git
cd RentIQ

# Run initial setup script
sudo bash deployment/scripts/01_initial_setup.sh
```

#### 5.3 Configure Environment Variables

```bash
# Copy .env template
cp deployment/.env.production.template .env

# Edit .env file with actual values
vim .env
# Update:
# - DB_HOST=<RDS_ENDPOINT>
# - DB_PASSWORD=<YOUR_RDS_PASSWORD>
# - REDIS_URL=redis://<REDIS_ENDPOINT>:6379/0
# - OPENAI_API_KEY=<FROM_SECRETS_MANAGER>
# - GOOGLE_API_KEY=<FROM_SECRETS_MANAGER>
# - PINECONE_API_KEY=<FROM_SECRETS_MANAGER>
```

#### 5.4 Deploy Application

```bash
# Run deployment script (first time)
bash deployment/scripts/02_deploy_app.sh --first-time

# This will:
# - Create virtual environment
# - Install dependencies
# - Run migrations
# - Collect static files
# - Deploy Nginx configuration
# - Deploy Supervisor configuration
# - Start services
```

---

### Phase 6: S3 and CloudFront (React Frontend)

#### 6.1 Create S3 Bucket

```bash
# Create S3 bucket for frontend
aws s3 mb s3://rentiq-frontend-assets --region us-east-1

# Enable static website hosting
aws s3 website s3://rentiq-frontend-assets \
    --index-document index.html \
    --error-document index.html

# Set bucket policy for public read
cat > /tmp/bucket-policy.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::rentiq-frontend-assets/*"
        }
    ]
}
EOF

aws s3api put-bucket-policy \
    --bucket rentiq-frontend-assets \
    --policy file:///tmp/bucket-policy.json
```

#### 6.2 Build and Deploy React Frontend

```bash
# On your local machine (in the React frontend directory)
cd react_frontend
npm run build

# Upload to S3
aws s3 sync build/ s3://rentiq-frontend-assets/ --delete
```

#### 6.3 Create CloudFront Distribution

```bash
# Create CloudFront distribution
cat > /tmp/cloudfront-config.json <<EOF
{
    "CallerReference": "rentiq-frontend-$(date +%s)",
    "Comment": "RentIQ React Frontend",
    "Enabled": true,
    "Origins": {
        "Quantity": 1,
        "Items": [
            {
                "Id": "S3-rentiq-frontend",
                "DomainName": "rentiq-frontend-assets.s3.amazonaws.com",
                "S3OriginConfig": {
                    "OriginAccessIdentity": ""
                }
            }
        ]
    },
    "DefaultRootObject": "index.html",
    "DefaultCacheBehavior": {
        "TargetOriginId": "S3-rentiq-frontend",
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": {
            "Quantity": 2,
            "Items": ["GET", "HEAD"]
        },
        "Compress": true,
        "ForwardedValues": {
            "QueryString": false,
            "Cookies": {
                "Forward": "none"
            }
        },
        "MinTTL": 0,
        "DefaultTTL": 86400,
        "MaxTTL": 31536000
    }
}
EOF

CLOUDFRONT_ID=$(aws cloudfront create-distribution \
    --distribution-config file:///tmp/cloudfront-config.json \
    --query 'Distribution.Id' \
    --output text)

echo "CloudFront Distribution ID: $CLOUDFRONT_ID"
```

---

### Phase 7: Application Load Balancer and SSL

#### 7.1 Request SSL Certificate (ACM)

```bash
# Request certificate for your domain
CERT_ARN=$(aws acm request-certificate \
    --domain-name yourdomain.com \
    --subject-alternative-names *.yourdomain.com \
    --validation-method DNS \
    --region us-east-1 \
    --query 'CertificateArn' \
    --output text)

echo "Certificate ARN: $CERT_ARN"

# Get DNS validation records
aws acm describe-certificate \
    --certificate-arn $CERT_ARN \
    --query 'Certificate.DomainValidationOptions'

# Add CNAME records to Route 53 (or your DNS provider)
# Wait for certificate to be validated
aws acm wait certificate-validated --certificate-arn $CERT_ARN
```

#### 7.2 Create Target Group

```bash
# Create target group for Django API
API_TG=$(aws elbv2 create-target-group \
    --name rentiq-api-tg \
    --protocol HTTP \
    --port 80 \
    --vpc-id $VPC_ID \
    --health-check-enabled \
    --health-check-protocol HTTP \
    --health-check-path /health/ \
    --health-check-interval-seconds 30 \
    --health-check-timeout-seconds 5 \
    --healthy-threshold-count 2 \
    --unhealthy-threshold-count 3 \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text)

# Create target group for Streamlit
CHAT_TG=$(aws elbv2 create-target-group \
    --name rentiq-chat-tg \
    --protocol HTTP \
    --port 80 \
    --vpc-id $VPC_ID \
    --health-check-enabled \
    --health-check-protocol HTTP \
    --health-check-path /healthz \
    --health-check-interval-seconds 30 \
    --health-check-timeout-seconds 5 \
    --healthy-threshold-count 2 \
    --unhealthy-threshold-count 3 \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text)

# Register EC2 instance with target groups
aws elbv2 register-targets \
    --target-group-arn $API_TG \
    --targets Id=$INSTANCE_ID

aws elbv2 register-targets \
    --target-group-arn $CHAT_TG \
    --targets Id=$INSTANCE_ID
```

#### 7.3 Create Application Load Balancer

```bash
# Create ALB
ALB_ARN=$(aws elbv2 create-load-balancer \
    --name rentiq-alb \
    --subnets $PUBLIC_SUBNET_1 $PUBLIC_SUBNET_2 \
    --security-groups $EC2_SG \
    --scheme internet-facing \
    --type application \
    --ip-address-type ipv4 \
    --query 'LoadBalancers[0].LoadBalancerArn' \
    --output text)

# Get ALB DNS name
ALB_DNS=$(aws elbv2 describe-load-balancers \
    --load-balancer-arns $ALB_ARN \
    --query 'LoadBalancers[0].DNSName' \
    --output text)

echo "ALB DNS: $ALB_DNS"

# Create HTTPS listener
aws elbv2 create-listener \
    --load-balancer-arn $ALB_ARN \
    --protocol HTTPS \
    --port 443 \
    --certificates CertificateArn=$CERT_ARN \
    --default-actions Type=forward,TargetGroupArn=$API_TG

# Create HTTP listener (redirect to HTTPS)
aws elbv2 create-listener \
    --load-balancer-arn $ALB_ARN \
    --protocol HTTP \
    --port 80 \
    --default-actions Type=redirect,RedirectConfig='{Protocol=HTTPS,Port=443,StatusCode=HTTP_301}'

# Create host-based routing rules
# (Add rules to route api.yourdomain.com to API_TG and chat.yourdomain.com to CHAT_TG)
```

---

### Phase 8: Route 53 DNS Configuration

```bash
# Create hosted zone (if you don't have one)
ZONE_ID=$(aws route53 create-hosted-zone \
    --name yourdomain.com \
    --caller-reference $(date +%s) \
    --query 'HostedZone.Id' \
    --output text)

# Create A record for ALB
cat > /tmp/route53-changes.json <<EOF
{
    "Changes": [
        {
            "Action": "CREATE",
            "ResourceRecordSet": {
                "Name": "api.yourdomain.com",
                "Type": "A",
                "AliasTarget": {
                    "HostedZoneId": "Z35SXDOTRQ7X7K",
                    "DNSName": "$ALB_DNS",
                    "EvaluateTargetHealth": true
                }
            }
        },
        {
            "Action": "CREATE",
            "ResourceRecordSet": {
                "Name": "chat.yourdomain.com",
                "Type": "A",
                "AliasTarget": {
                    "HostedZoneId": "Z35SXDOTRQ7X7K",
                    "DNSName": "$ALB_DNS",
                    "EvaluateTargetHealth": true
                }
            }
        }
    ]
}
EOF

aws route53 change-resource-record-sets \
    --hosted-zone-id $ZONE_ID \
    --change-batch file:///tmp/route53-changes.json
```

---

### Phase 9: CloudWatch Monitoring

#### 9.1 Configure CloudWatch Agent

```bash
# On EC2 instance
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
    -a fetch-config \
    -m ec2 \
    -s \
    -c file:/home/ubuntu/RentIQ/deployment/cloudwatch-config.json

# Verify CloudWatch agent is running
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
    -m ec2 \
    -a query
```

#### 9.2 Create CloudWatch Alarms

```bash
# High CPU alarm
aws cloudwatch put-metric-alarm \
    --alarm-name rentiq-high-cpu \
    --alarm-description "Alert when CPU exceeds 80%" \
    --metric-name CPUUtilization \
    --namespace AWS/EC2 \
    --statistic Average \
    --period 300 \
    --threshold 80 \
    --comparison-operator GreaterThanThreshold \
    --dimensions Name=InstanceId,Value=$INSTANCE_ID \
    --evaluation-periods 2

# High memory alarm
aws cloudwatch put-metric-alarm \
    --alarm-name rentiq-high-memory \
    --alarm-description "Alert when memory exceeds 85%" \
    --metric-name MEM_USED \
    --namespace RentIQ/EC2 \
    --statistic Average \
    --period 300 \
    --threshold 85 \
    --comparison-operator GreaterThanThreshold \
    --dimensions Name=InstanceId,Value=$INSTANCE_ID \
    --evaluation-periods 2
```

---

### Phase 10: Testing and Validation

#### 10.1 Health Checks

```bash
# Test Django API
curl https://api.yourdomain.com/health/

# Test Streamlit
curl https://chat.yourdomain.com/healthz

# Test database connection
ssh ubuntu@$PUBLIC_IP 'cd RentIQ && source venv/bin/activate && python manage.py dbshell --command "SELECT 1"'

# Test Redis connection
ssh ubuntu@$PUBLIC_IP 'redis-cli -u $REDIS_URL ping'
```

#### 10.2 Load Testing (Optional)

```bash
# Install Apache Bench
sudo apt-get install apache2-utils

# Run load test
ab -n 1000 -c 10 https://api.yourdomain.com/health/
```

---

## Configuration

### Environment Variables

All configuration is managed through the `.env` file. See `.env.production.template` for a complete list of variables.

**Critical Variables:**

- `DB_HOST`, `DB_USER`, `DB_PASSWORD` - RDS connection details
- `REDIS_URL` - ElastiCache endpoint
- `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `PINECONE_API_KEY` - API keys
- `DJANGO_SECRET_KEY` - Django secret (generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- `DJANGO_ALLOWED_HOSTS` - Comma-separated list of allowed domains

### Process Management: Supervisor vs. Systemd

You can choose between Supervisor or Systemd for process management:

**Supervisor (Recommended for simplicity):**
- Configuration: `/etc/supervisor/conf.d/rentiq.conf`
- Control commands:
  ```bash
  sudo supervisorctl status
  sudo supervisorctl restart all
  sudo supervisorctl tail django_gunicorn
  ```

**Systemd (Recommended for production):**
- Enable services:
  ```bash
  sudo systemctl enable rentiq-gunicorn
  sudo systemctl enable rentiq-streamlit
  sudo systemctl start rentiq-gunicorn
  sudo systemctl start rentiq-streamlit
  ```
- Control commands:
  ```bash
  sudo systemctl status rentiq-gunicorn
  sudo systemctl restart rentiq-gunicorn
  sudo journalctl -u rentiq-gunicorn -f
  ```

---

## Monitoring & Logging

### CloudWatch Log Groups

All application logs are streamed to CloudWatch:

- `/aws/ec2/rentiq/gunicorn/access` - Gunicorn access logs
- `/aws/ec2/rentiq/gunicorn/error` - Gunicorn error logs
- `/aws/ec2/rentiq/streamlit/stdout` - Streamlit output
- `/aws/ec2/rentiq/nginx/api_access` - Nginx API access logs
- `/aws/ec2/rentiq/nginx/api_error` - Nginx API error logs
- `/aws/ec2/rentiq/nginx/chat_access` - Nginx chat access logs

### Local Logs

Logs are also stored locally at `/var/log/rentiq/`:

```bash
# View all logs
tail -f /var/log/rentiq/*.log

# View specific service
tail -f /var/log/rentiq/gunicorn_error.log
```

### Metrics

CloudWatch metrics include:

- CPU utilization
- Memory usage
- Disk I/O
- Network traffic
- Process counts
- Custom application metrics

View in AWS Console: CloudWatch → Dashboards → Create custom dashboard

---

## Maintenance

### Database Backups

Automated backups are configured via:

1. **RDS Automated Backups** (7-day retention)
2. **Manual Backup Script** (`scripts/03_backup_database.sh`)

Set up automated backups with cron:

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /home/ubuntu/RentIQ/deployment/scripts/03_backup_database.sh
```

### Application Updates

To deploy code updates:

```bash
# SSH into EC2
ssh -i ~/.ssh/rentiq-key.pem ubuntu@$PUBLIC_IP

# Pull latest code
cd RentIQ
git pull origin main

# Run deployment script
bash deployment/scripts/02_deploy_app.sh

# Restart services
sudo supervisorctl restart all
sudo systemctl reload nginx
```

### Scaling Considerations

**Vertical Scaling (Increase EC2 size):**

```bash
# Stop instance
aws ec2 stop-instances --instance-ids $INSTANCE_ID
aws ec2 wait instance-stopped --instance-ids $INSTANCE_ID

# Change instance type
aws ec2 modify-instance-attribute \
    --instance-id $INSTANCE_ID \
    --instance-type "{\"Value\": \"t3.large\"}"

# Start instance
aws ec2 start-instances --instance-ids $INSTANCE_ID
```

**Horizontal Scaling (Auto Scaling Group):**

1. Create AMI from current instance
2. Create Launch Template
3. Create Auto Scaling Group
4. Update ALB target groups

---

## Troubleshooting

### Common Issues

#### 1. Services Not Starting

```bash
# Check service status
sudo supervisorctl status

# Check logs
tail -f /var/log/rentiq/gunicorn_error.log

# Restart services
sudo supervisorctl restart all
```

#### 2. Database Connection Errors

```bash
# Test connectivity
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT 1"

# Check security group allows EC2 to RDS
aws ec2 describe-security-groups --group-ids $RDS_SG
```

#### 3. Redis Connection Errors

```bash
# Test connectivity
redis-cli -u $REDIS_URL ping

# Check security group
aws ec2 describe-security-groups --group-ids $REDIS_SG
```

#### 4. SSL Certificate Issues

```bash
# Check certificate status
aws acm describe-certificate --certificate-arn $CERT_ARN

# Test SSL
openssl s_client -connect api.yourdomain.com:443 -servername api.yourdomain.com
```

#### 5. High Memory Usage

```bash
# Check memory usage
free -h

# Restart services to free memory
sudo supervisorctl restart all
```

---

## Cost Estimates

### Monthly Cost Breakdown (us-east-1)

| Service | Type | Monthly Cost |
|---------|------|--------------|
| EC2 (t3.medium) | On-Demand | $30.37 |
| RDS (db.t3.micro) | PostgreSQL | $13.14 |
| ElastiCache (cache.t3.micro) | Redis | $11.52 |
| EBS Storage (30 GB gp3) | EC2 Volume | $2.40 |
| RDS Storage (20 GB gp3) | Database | $2.30 |
| Application Load Balancer | - | $16.20 |
| CloudFront | 50 GB transfer | $4.25 |
| S3 Standard | 10 GB | $0.23 |
| Route 53 | Hosted Zone + queries | $0.50 |
| CloudWatch Logs | 10 GB ingestion | $5.00 |
| Data Transfer | 100 GB outbound | $9.00 |
| **Total (Low Usage)** | - | **$94.91/month** |
| **Total (Moderate Usage)** | - | **$136-185/month** |

### Cost Optimization Tips

1. **Use Reserved Instances** - Save 40-60% on EC2 and RDS
2. **Right-size instances** - Start with t3.small, scale up as needed
3. **Enable S3 Lifecycle Policies** - Move old backups to Glacier
4. **CloudWatch Log Retention** - Reduce retention to 7-14 days
5. **CloudFront Caching** - Maximize cache hit ratio
6. **Stop instances during non-business hours** (Dev/Staging only)

---

## Security Best Practices

1. **Enable MFA** on AWS root and IAM users
2. **Use Secrets Manager** for all API keys
3. **Enable CloudTrail** for audit logging
4. **Regular Security Updates**: `sudo apt-get update && sudo apt-get upgrade`
5. **Firewall (UFW)**: Restrict SSH to specific IPs
6. **SSL/TLS Only**: Enforce HTTPS with ACM certificates
7. **Database Encryption**: Enable RDS encryption at rest
8. **Regular Backups**: Test restore procedures monthly
9. **IAM Roles**: Use IAM roles instead of access keys on EC2
10. **Security Groups**: Principle of least privilege

---

## Support and Resources

- **AWS Documentation**: https://docs.aws.amazon.com/
- **Gunicorn Docs**: https://docs.gunicorn.org/
- **Nginx Docs**: https://nginx.org/en/docs/
- **Django Deployment**: https://docs.djangoproject.com/en/stable/howto/deployment/
- **Streamlit Deployment**: https://docs.streamlit.io/streamlit-community-cloud/get-started

---

## Deployment Checklist

Before going live, verify:

- [ ] All environment variables configured in `.env`
- [ ] Database migrations applied
- [ ] Static files collected
- [ ] SSL certificate validated and installed
- [ ] DNS records pointing to ALB
- [ ] Health checks passing on all services
- [ ] CloudWatch alarms configured
- [ ] Backup scripts tested
- [ ] Security groups properly configured
- [ ] Firewall (UFW) enabled
- [ ] Application logging working
- [ ] Redis connection successful
- [ ] Database connection successful
- [ ] All API keys stored in Secrets Manager
- [ ] Django admin accessible
- [ ] React frontend deployed to S3/CloudFront
- [ ] Load testing completed
- [ ] Monitoring dashboard created

---

**Last Updated:** November 2025
**Version:** 1.0
**Maintained by:** RentIQ Team
