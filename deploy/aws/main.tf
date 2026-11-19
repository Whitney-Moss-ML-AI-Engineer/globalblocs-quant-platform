# AWS: ECS Fargate API, RDS PostgreSQL (Multi-AZ, encrypted, backups), Secrets Manager, KMS,
# private S3 bucket for the static dashboard, AWS Backup. Fill in VPC/subnets, certificate and image URI.
# Add an ALB + ECS service and CloudFront (with Origin Access Control) + WAF for your network layout.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  default = "us-east-2"
}
variable "vpc_id" {}
variable "private_subnets" {
  type = list(string)
}
variable "api_image" {}

resource "aws_kms_key" "gb" {
  description         = "GlobalBLOCS data encryption"
  enable_key_rotation = true
}

resource "aws_secretsmanager_secret" "app" {
  name       = "globalblocs/app"
  kms_key_id = aws_kms_key.gb.arn
}

resource "aws_db_subnet_group" "gb" {
  name       = "globalblocs"
  subnet_ids = var.private_subnets
}

resource "aws_security_group" "db" {
  name   = "gb-db"
  vpc_id = var.vpc_id
}

resource "aws_db_instance" "gb" {
  identifier                   = "globalblocs"
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = "db.t4g.medium"
  allocated_storage            = 100
  storage_encrypted            = true
  kms_key_id                   = aws_kms_key.gb.arn
  db_subnet_group_name         = aws_db_subnet_group.gb.name
  vpc_security_group_ids       = [aws_security_group.db.id]
  username                     = "gb"
  manage_master_user_password  = true
  multi_az                     = true
  backup_retention_period      = 14
  deletion_protection          = true
  skip_final_snapshot          = false
  final_snapshot_identifier    = "globalblocs-final"
  performance_insights_enabled = true
}

resource "aws_ecs_cluster" "gb" {
  name = "globalblocs"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/globalblocs/api"
  retention_in_days = 90
}

resource "aws_iam_role" "task_exec" {
  name = "gb-task-exec"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ecs-tasks.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "exec" {
  role       = aws_iam_role.task_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "secrets" {
  role = aws_iam_role.task_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "kms:Decrypt"]
      Resource = [aws_secretsmanager_secret.app.arn, aws_kms_key.gb.arn]
    }]
  })
}

locals {
  secret_keys = ["GB_ENCRYPTION_KEY", "JWT_SECRET", "ADMIN_PASSWORD_HASH", "POLYGON_API_KEY", "FRED_API_KEY",
  "ETRADE_CONSUMER_KEY", "ETRADE_CONSUMER_SECRET", "PLAID_CLIENT_ID", "PLAID_SECRET", "ANTHROPIC_API_KEY"]
}

resource "aws_ecs_task_definition" "api" {
  family                   = "gb-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 4096
  execution_role_arn       = aws_iam_role.task_exec.arn
  container_definitions = jsonencode([{
    name         = "api"
    image        = var.api_image
    portMappings = [{ containerPort = 8000 }]
    environment  = [{ name = "LIVE_TRADING_ENABLED", value = "false" }]
    secrets      = [for k in local.secret_keys : { name = k, valueFrom = "${aws_secretsmanager_secret.app.arn}:${k}::" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_s3_bucket" "web" {
  bucket_prefix = "globalblocs-web-"
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_backup_vault" "gb" {
  name        = "globalblocs"
  kms_key_arn = aws_kms_key.gb.arn
}

resource "aws_backup_plan" "gb" {
  name = "globalblocs-daily"
  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.gb.name
    schedule          = "cron(0 7 * * ? *)"
    lifecycle {
      delete_after = 35
    }
  }
}

resource "aws_backup_selection" "db" {
  name         = "rds"
  plan_id      = aws_backup_plan.gb.id
  iam_role_arn = aws_iam_role.task_exec.arn # replace with a dedicated AWS Backup service role
  resources    = [aws_db_instance.gb.arn]
}
