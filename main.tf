terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "ap-southeast-1"
}

# 1. Amazon S3 Bucket for Uploads & Generated Terraform Artifacts
resource "aws_s3_bucket" "upload_bucket" {
  bucket        = "archlens-uploads-arsa-2026"
  force_destroy = true

  tags = {
    Project     = "AWS-Serverless-Hackathon-NextOps"
    Environment = "Production"
  }
}

# S3 Bucket CORS Configuration
resource "aws_s3_bucket_cors_configuration" "s3_cors" {
  bucket = aws_s3_bucket.upload_bucket.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT", "POST", "GET"]
    allowed_origins = ["*"]
    max_age_seconds = 3000
  }
}

# 2. Amazon DynamoDB NoSQL Table (Audit Trails, FinOps & Session History)
resource "aws_dynamodb_table" "analysis_table" {
  name         = "ArchAnalysisResults"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "file_id"

  attribute {
    name = "file_id"
    type = "S"
  }

  tags = {
    Project     = "AWS-Serverless-Hackathon-NextOps"
    Environment = "Production"
  }
}

# 3. AWS IAM Execution Role for Lambda
resource "aws_iam_role" "lambda_exec_role" {
  name = "archlens_lambda_execution_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

# IAM Least-Privilege Policy: CloudWatch Logs, S3, DynamoDB, and Amazon Bedrock
resource "aws_iam_role_policy" "lambda_policy" {
  name = "archlens_lambda_permissions"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.upload_bucket.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem"
        ]
        Resource = aws_dynamodb_table.analysis_table.arn
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "*"
      }
    ]
  })
}

# 4. AWS Lambda Function: Serverless Core Engine
resource "aws_lambda_function" "archlens_processor" {
  filename         = "lambda.zip"
  function_name    = "archlens_analysis_engine"
  role             = aws_iam_role.lambda_exec_role.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 256
  source_code_hash = filebase64sha256("lambda.zip")

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.analysis_table.name
      S3_BUCKET      = aws_s3_bucket.upload_bucket.id
    }
  }

  tags = {
    Project     = "AWS-Serverless-Hackathon-NextOps"
    Environment = "Production"
  }
}

# 5. AWS Lambda Function URL (Direct HTTPS Serverless Endpoint - No Pipeline & No API Gateway)
resource "aws_lambda_function_url" "api_endpoint" {
  function_name      = aws_lambda_function.archlens_processor.function_name
  authorization_type = "NONE"

  cors {
    allow_origins = ["*"]
    allow_methods = ["*"]
    allow_headers = ["*"]
  }
}

# 6. Outputs
output "api_endpoint_url" {
  description = "Public HTTPS Lambda Function URL Endpoint"
  value       = aws_lambda_function_url.api_endpoint.function_url
}

output "s3_upload_bucket" {
  description = "S3 Artifacts Bucket Name"
  value       = aws_s3_bucket.upload_bucket.id
}
