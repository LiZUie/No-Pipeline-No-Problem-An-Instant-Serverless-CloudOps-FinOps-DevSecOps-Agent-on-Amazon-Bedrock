Hands-On with NextOps AI: Building an Instant Serverless CloudOps and DevSecOps Agent on Amazon Bedrock

Setting up continuous integration pipelines for Infrastructure-as-Code (IaC) governance often requires substantial operational overhead. Standard setups typically involve configuring GitHub Actions runners, managing linting tools like Checkov, provisioning third-party API keys, and maintaining dedicated build servers. While effective in mature enterprise environments, this approach introduces noticeable friction for students, independent builders, and agile teams who need rapid feedback on their Terraform configurations without waiting minutes for a pipeline to run.

During the AWS Builder Community Challenge ("Weekend Challenge: No Pipeline, No Problem"), I explored an alternative pattern: replacing heavy build pipelines with an on-demand, instant serverless agent powered by Amazon Bedrock.

In this post, I will share the design, architecture, and verification of NextOps AI, an autonomous serverless agent running on Amazon Nova Micro that validates regional architectures, calculates transparent FinOps monthly cost estimations, and performs static security audits in under three seconds.

Architecture

To eliminate pipelines entirely, the system relies strictly on managed AWS serverless primitives with zero virtual machines, zero containers, and zero build servers.

The request lifecycle is organized across four distinct tiers:

1. Ingress Tier
The web console and API communicate directly with an AWS Lambda Function URL over HTTPS. This eliminates the need for Amazon API Gateway or CloudFront, while providing built-in cross-origin resource sharing (CORS) and automated TLS termination.

2. Compute & Security Tier
An AWS Lambda function running Python 3.12 acts as the core orchestrator. The function is governed by an IAM execution role following least-privilege principles, with real-time execution logs and latency traces automatically ingested by Amazon CloudWatch.

3. AI Reasoning Tier
The core intelligence engine uses Amazon Bedrock with the Amazon Nova Micro foundation model (apac.amazon.nova-micro-v1:0) in the Singapore region (ap-southeast-1). The model handles architectural synthesis, regional pricing calculations, and static code analysis.

4. Storage & Audit Tier
Generated Terraform configurations are stored in an Amazon S3 bucket, with secure presigned URLs generated for client downloads. Audit logs, session history, and latency metrics are persisted in an Amazon DynamoDB table configured with on-demand capacity (Pay-per-Request).

Implementation & Key Features

The agent provides two primary operational modes accessible through a unified web interface:

CloudOps Architecture & FinOps Estimation

In this mode, developers describe their infrastructure requirements in plain English or Bahasa Indonesia. Before generating code, the agent enforces two essential validation rules:

- Target Region Enforcement: The agent requires an explicit AWS region (such as Singapore ap-southeast-1 or Jakarta ap-southeast-3) to ensure data residency compliance and retrieve accurate regional pricing.
- Subnet Placement Clarification: If a user specifies multiple subnets with compute instances, the agent actively verifies whether the workloads belong in a public subnet for web traffic or a private subnet for database isolation.

Once validated, the agent produces modular Terraform code alongside an itemized FinOps monthly cost estimation table covering compute, storage, databases, and AWS Free Tier limits.

DevSecOps Static Security Scanner

In the audit mode, users paste raw Terraform code into the editor. The agent evaluates the configuration against the CIS AWS Foundations Benchmark and the AWS Well-Architected Security Pillar:

- Network Security: Detects open ingress CIDRs (0.0.0.0/0 on port 22, 3389, or 5432).
- IAM Hygiene: Identifies wildcard administrative permissions (Action: * and Resource: *).
- Data Protection: Enforces S3 server-side encryption and RDS storage encryption.
- Boundary Isolation: Identifies publicly accessible databases and missing S3 public access blocks.
- Compute Hardening: Verifies IMDSv2 enforcement (http_tokens = "required").

The scanner calculates a security health score from 0 to 100, provides educational remediation advice, and compiles a hardened version of the code (main_hardened.tf) available for instant download from Amazon S3.

Verification & Hands-On Testing

To verify the agent, I conducted tests across both operational modes.

Test 1: Architecture Synthesis with Regional Cost Estimation

Input prompt:
"Design a 2-Tier VPC in Singapore (ap-southeast-1) with 1 public subnet, 1 EC2 t3.micro web server in the public subnet, and an S3 bucket with monthly cost estimation."

Output summary:
The agent validated the Singapore region, generated complete VPC and EC2 Terraform resources, and returned the following FinOps breakdown:

- EC2 t3.micro: $7.45 / month (Eligible for 750 free hours under AWS Free Tier)
- EBS gp3 Storage (20 GB): $1.60 / month (Eligible under 30 GB Free Tier allowance)
- S3 Standard Storage (5 GB): $0.12 / month (Eligible under 5 GB Free Tier allowance)
- Internet Gateway & Routing: $0.00 / month
- Total Estimated Monthly Cost: $9.17 / month ($0.00 with AWS Free Tier)

Execution latency was recorded at 2,840 ms.

Test 2: Security Audit on Insecure Terraform Code

I then submitted an insecure Terraform configuration containing an unrestricted SSH security group (port 22 open to 0.0.0.0/0) and an unencrypted, publicly accessible PostgreSQL database on Amazon RDS:

Output:
Security Health Score: 20/100 (CRITICAL RISK)

Detected Security Findings:
- [CRITICAL] Ingress rule allows SSH access from 0.0.0.0/0 on port 22.
- [CRITICAL] RDS database has publicly_accessible set to true.
- [CRITICAL] RDS storage encryption is set to false.

DevSecOps Remediation:
The scanner flagged that exposing administrative ports and databases to the public internet creates immediate attack vectors for brute force and exfiltration. It recommended placing the RDS instance into private subnets, restricting security groups to explicit bastion CIDRs, and enabling storage encryption.

The hardened Terraform code was automatically uploaded to Amazon S3, and the session record was written to Amazon DynamoDB in 3,110 ms.

Analysis & Operational Comparison

Comparing this serverless agent approach with a traditional CI/CD pipeline reveals several clear operational advantages:

Setup Overhead:
A traditional CI/CD setup requires between 2 and 6 hours to configure runners, linting dependencies, and repository secrets. The serverless architecture deploys with a single Terraform apply command in under 60 seconds.

Feedback Latency:
Pipeline jobs typically require 45 to 180 seconds to spin up containers and run sequential checks. NextOps AI completes comprehensive architectural synthesis and security scanning in 1.2 to 3.1 seconds.

Cost Profile:
Dedicated build runners or standby instances can cost between $15 and $60 per month even when idle. Because NextOps AI runs entirely on serverless primitives, idle costs are exactly $0.00. The cost per invocation using Amazon Nova Micro is approximately $0.0001.

Conclusion

Based on this hands-on implementation, using Amazon Bedrock with AWS Lambda Function URLs provides a lightweight, highly responsive alternative to traditional CI/CD pipelines for everyday IaC governance.

The combination of AWS Lambda for compute, Amazon Bedrock for reasoning, Amazon S3 for artifact storage, and Amazon DynamoDB for audit trails proves that comprehensive CloudOps, FinOps, and DevSecOps capabilities can be delivered with zero operational overhead and zero build pipelines.

Links & Resources:
- Live Web Application: https://wfd6u7eevc6ywr6ytfuwm4bpue0okzom.lambda-url.ap-southeast-1.on.aws/
- GitHub Source Code: https://github.com/LiZUie/No-Pipeline-No-Problem-An-Instant-Serverless-CloudOps-FinOps-DevSecOps-Agent-on-Amazon-Bedrock
- Jupyter Notebook: https://github.com/LiZUie/No-Pipeline-No-Problem-An-Instant-Serverless-CloudOps-FinOps-DevSecOps-Agent-on-Amazon-Bedrock/blob/main/NextOps_AI_Demonstration.ipynb

About the Author:
Muhammad Arsa Faturrahman Saleh (Arsa) is an Internet Engineering Technology student at Universitas Gadjah Mada (UGM), interested in Cloud Architecture, Serverless Systems, and DevSecOps automation.
