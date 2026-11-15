import json
import boto3
import os
import re
import uuid
from datetime import datetime

# Initialize AWS clients
bedrock = boto3.client('bedrock-runtime', region_name='ap-southeast-1')
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

TABLE_NAME = os.environ.get('DYNAMODB_TABLE', 'ArchAnalysisResults')
BUCKET_NAME = os.environ.get('S3_BUCKET', 'archlens-uploads-arsa-2026')
table = dynamodb.Table(TABLE_NAME)

# Official Amazon Bedrock APAC Model ID for Nova Micro
MODEL_ID = "apac.amazon.nova-micro-v1:0"

# AWS Region detection patterns (official codes, major cities, and region keywords)
REGION_PATTERNS = [
    r"\b[a-z]{2}-(?:north|south|east|west|central)-\d\b",
    r"\b(?:jakarta|singapore|singapura|tokyo|seoul|sydney|mumbai|frankfurt|ireland|london|paris|virginia|ohio|oregon|california|milan|stockholm|bahrain|cape\s*town|sao\s*paulo|zurich|melbourne|hyderabad|calgary)\b",
    r"\bregion\s+([a-zA-Z0-9-]+)\b"
]

def detect_region(text):
    text_lower = text.lower()
    for p in REGION_PATTERNS:
        m = re.search(p, text_lower)
        if m:
            return m.group(0)
    return None

def check_subnet_ambiguity(text):
    """Detects if user requested multiple subnets with EC2 without specifying subnet placement."""
    text_lower = text.lower()
    has_multi_subnet = bool(re.search(r'\b(?:2|two|3|three|multi|several|dua|tiga)\s+subnets?\b|\bpublic\b.*\bprivate\b|\bprivate\b.*\bpublic\b', text_lower))
    has_instance = bool(re.search(r'\b(?:ec2|instance|server|vm|workload)\b', text_lower))
    has_placement = bool(re.search(r'\b(?:in|on|into|inside|at|di|pada|ke|dalam)\s+(?:the\s+)?(?:subnet\s+)?(?:public|private)\b|\b(?:public|private)\s+subnets?\s+(?:for|with|hosting|untuk)\s+(?:ec2|instance|server)\b|\b(?:web|frontend)\s+(?:in|on|di)\s+public\b', text_lower))
    
    return has_multi_subnet and has_instance and not has_placement

# Mode 1: Cloud Architect & FinOps System Prompt
ARCHITECT_SYSTEM_PROMPT = """You are NextOps AI, an elite Senior CloudOps & FinOps Architect specialized in AWS and Terraform.
Your goal is to help users design scalable cloud infrastructure, provide rigorous monthly cost estimations for the target AWS region, and generate production-ready Terraform code.

You MUST structure your response with:
### 1. 🏗️ Architectural Overview
- Crisp architectural explanation and rationale for chosen AWS services.
- Explicitly state the Target AWS Region and Subnet placement.

### 2. 💰 FinOps Monthly Cost Estimation (Target Region)
Provide a clear, realistic Markdown table estimating monthly costs based strictly on the target region's pricing:
| AWS Resource | Spec / Capacity | Est. Monthly Cost (USD) | Free Tier Eligible? |
|--------------|-----------------|-------------------------|---------------------|
(Itemize each resource: EC2, EBS, RDS, S3, NAT Gateway, Data Transfer, etc.)

- **💵 Total Estimated Cost: ~$XX.XX / month**
- **🎁 Free Tier Eligibility:** Highlight which resources qualify under the AWS Free Tier (e.g. 750 hrs t2/t3.micro, 5GB S3, 25GB DynamoDB).
- **💡 FinOps Optimization Tips:** Practical advice to minimize cloud spend in this region.

### 3. 🛠️ Production-Ready Terraform Code
Provide complete, secure, valid Terraform (HCL) code enclosed strictly in a ```hcl ... ``` code block. The `provider "aws"` block MUST configure the user's requested region:
```hcl
provider "aws" {
  region = "<target-region>"
}
```

### 4. 🛡️ AWS Well-Architected Framework Highlights
Key security, reliability, and cost-efficiency principles applied.
Be concise, accurate, and professional."""

# Mode 2: DevSecOps Auditor & Mentor System Prompt
AUDITOR_SYSTEM_PROMPT = """You are NextOps DevSecOps Auditor, an elite AWS Security & Terraform Compliance Expert.
Your task is to comprehensively analyze user-submitted Terraform (HCL) code against the AWS Well-Architected Security Pillar and CIS AWS Foundations Benchmark.

You MUST inspect the code across ALL 6 Security Pillars:
1. 🌐 Network & Perimeter Security (Open CIDRs 0.0.0.0/0 on port 22/3389/3306/5432, unencrypted HTTP port 80).
2. 🔑 IAM & Credential Hygiene (Wildcard * actions/resources, plaintext hardcoded credentials/secrets).
3. 🔒 Data Protection & Encryption (S3 SSE/KMS encryption, EBS volume encryption, RDS storage encryption).
4. 🚫 Public Exposure & Isolation (S3 public access blocks, RDS publicly_accessible = true).
5. 💻 Compute Hardening & SSRF (IMDSv2 enforcement http_tokens = "required", public IPs on private instances).
6. 📊 Observability & FinOps (Missing access logs, orphaned expensive resources).

Output Structure:
## 🛡️ Security Health Score: [Score 0-100]/100 ([CRITICAL RISK / HIGH RISK / MODERATE / SECURE])
### 🚨 Detected Security Findings (Grouped by 🔴 CRITICAL, 🟠 HIGH, 🟡 MEDIUM, 🟢 BEST PRACTICE)
### 💡 DevSecOps Educational Mentoring (Explain why each flaw is dangerous in AWS production)
### 🛠️ Hardened & Remediated Terraform Code (Complete secured code enclosed strictly in a ```hcl ... ``` code block)
"""

def lambda_handler(event, context):
    print("Received event:", json.dumps(event))
    
    # 1. Handle HTTP method
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')
    
    # Handle CORS Preflight (OPTIONS)
    if http_method == 'OPTIONS':
        return build_response(200, {'message': 'OK'})

    user_prompt = ""
    mode = "generate"

    if http_method == 'POST':
        try:
            body = json.loads(event.get('body', '{}'))
            user_prompt = body.get('prompt', '') or body.get('code', '')
            mode = body.get('mode', 'generate')
        except Exception as e:
            return build_response(400, {'error': f"Invalid JSON body: {str(e)}"})
    elif http_method == 'GET':
        query_params = event.get('queryStringParameters') or {}
        user_prompt = query_params.get('prompt', '')
        mode = query_params.get('mode', 'generate')

    if not user_prompt:
        return build_response(200, {
            'message': 'NextOps CloudOps, FinOps & DevSecOps Agent is Ready. Please submit an architectural prompt or Terraform code via POST/GET.',
            'supported_modes': ['generate', 'audit']
        })

    # Mode 2: AUDIT MODE (Directly audit submitted .tf code)
    if mode == "audit":
        system_prompt = AUDITOR_SYSTEM_PROMPT
        user_message = f"Please audit and security-scan this Terraform code, identify misconfigurations across all 6 AWS security pillars, provide an objective security score (0-100), educational mentoring, and produce hardened code:\n\n```hcl\n{user_prompt}\n```"
    
    # Mode 1: GENERATE MODE (Validate Region & Subnet Placement Ambiguity)
    else:
        # 1. Validate Target AWS Region
        detected_reg = detect_region(user_prompt)
        if not detected_reg:
            warning_msg = (
                "### ⚠️ Target AWS Region Required!\n\n"
                "To compute accurate monthly cost estimations (**FinOps**) and ensure data residency compliance (*data sovereignty / compliance*), you must specify a **Target AWS Region** for your architecture.\n\n"
                "Please specify an AWS region code or geographic location, for example:\n"
                "- 🇸🇬 **Singapore** (`ap-southeast-1`)\n"
                "- 🇮🇩 **Jakarta** (`ap-southeast-3`)\n"
                "- 🇺🇸 **US East / N. Virginia** (`us-east-1`)\n"
                "- 🇯🇵 **Tokyo** (`ap-northeast-1`)\n"
                "- 🇩🇪 **Frankfurt** (`eu-central-1`)\n"
                "- 🇦🇺 **Sydney** (`ap-southeast-2`)\n\n"
                "**Example Prompt:**\n"
                "> *\"Design a 2-Tier VPC in **Singapore (ap-southeast-1)** with 1 EC2 in the public subnet...\"*"
            )
            return build_response(200, {
                'session_id': 'validation-required-region',
                'mode': 'generate',
                'reply': warning_msg,
                'terraform_code': None,
                'download_url': None,
                'latency_ms': 1,
                'model': 'NextOps Region Policy Validator'
            })

        # 2. Validate Subnet Placement Ambiguity (Interactive Clarification)
        if check_subnet_ambiguity(user_prompt):
            clarification_msg = (
                "### ❓ Subnet Placement Clarification Required\n\n"
                "Your requested architecture includes **multiple subnets (Public and Private Subnets)**, but the placement of your EC2 instance has not been specified.\n\n"
                "To ensure the Terraform architecture precisely aligns with your needs, where would you like to place this EC2 instance?\n\n"
                "**1. 🌐 Public Subnet (Web Server / Ingress):**\n"
                "Select this if the EC2 instance acts as a Web Server, Frontend, or Bastion Host that requires direct internet access.\n\n"
                "**2. 🔒 Private Subnet (Backend / Database):**\n"
                "Select this if the EC2 instance serves as an internal API, backend worker, or database that must be isolated from the internet for security.\n\n"
                "---\n"
                "💡 **Please reply with one of the following prompt options:**\n"
                f"- *\"{user_prompt.strip()} **in the public subnet**\"*\n"
                f"- *\"{user_prompt.strip()} **in the private subnet**\"*"
            )
            return build_response(200, {
                'session_id': 'validation-subnet-clarification',
                'mode': 'generate',
                'reply': clarification_msg,
                'terraform_code': None,
                'download_url': None,
                'latency_ms': 1,
                'model': 'NextOps Subnet Advisory Consultant'
            })

        system_prompt = ARCHITECT_SYSTEM_PROMPT
        user_message = f"{user_prompt}\n\nTarget Region detected: {detected_reg}. Please provide the architecture, FinOps Monthly Cost Estimation table for {detected_reg}, and Terraform HCL code configured for this region."

    try:
        # 2. Invoke Amazon Bedrock (Nova Micro)
        bedrock_response = bedrock.converse(
            modelId=MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_message}]
                }
            ],
            system=[{"text": system_prompt}]
        )
        
        stop_reason = bedrock_response.get('stopReason')
        latency = bedrock_response.get('metrics', {}).get('latencyMs', 0)
        session_id = f"session-{uuid.uuid4().hex[:8]}"

        # Handle Bedrock automated content filter trigger gracefully
        if stop_reason == 'content_filtered':
            ai_reply = (
                "## 🛡️ Security Health Score: 0/100 (CRITICAL - SENSITIVE PATTERN DETECTED)\n\n"
                "### 🚨 Amazon Bedrock Automated Guardrail Alert\n"
                "The submitted Terraform code contains sensitive credential patterns or plaintext passwords that triggered the **AWS Bedrock Automated Security Guardrail**.\n\n"
                "### 💡 DevSecOps Educational Mentoring\n"
                "- **Why is this hazardous?** Storing plaintext passwords or API keys in IaC files creates a severe risk of credential leakage in version control (Git repositories).\n"
                "- **AWS Best Practice:** Always use **AWS Secrets Manager** (`aws_secretsmanager_secret`), AWS SSM Parameter Store, or declare sensitive variables (`sensitive = true`).\n\n"
                "```hcl\n"
                "# Secure pattern using sensitive variable:\n"
                "variable \"db_password\" {\n"
                "  description = \"Database password managed externally\"\n"
                "  type        = string\n"
                "  sensitive   = true\n"
                "}\n"
                "```"
            )
            return build_response(200, {
                'session_id': session_id,
                'mode': mode,
                'reply': ai_reply,
                'terraform_code': None,
                'download_url': None,
                'latency_ms': latency,
                'model': 'Amazon Nova Micro + AWS Guardrail'
            })

        ai_reply = bedrock_response['output']['message']['content'][0]['text']

        # Extract Terraform code block
        terraform_code = extract_terraform_code(ai_reply)
        download_url = None

        # Upload Terraform code to S3 and generate Presigned URL
        if terraform_code:
            file_name = "main_hardened.tf" if mode == "audit" else "main.tf"
            s3_key = f"{mode}/{session_id}/{file_name}"
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=s3_key,
                Body=terraform_code.encode('utf-8'),
                ContentType='text/plain'
            )
            download_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': BUCKET_NAME, 'Key': s3_key},
                ExpiresIn=3600
            )

        # Log session to DynamoDB
        table.put_item(
            Item={
                'file_id': session_id,
                'created_at': datetime.utcnow().isoformat(),
                'mode': mode,
                'user_prompt': user_prompt[:2500],
                'ai_reply': ai_reply[:6000],
                'has_terraform': bool(terraform_code),
                'latency_ms': latency,
                'model': MODEL_ID
            }
        )

        return build_response(200, {
            'session_id': session_id,
            'mode': mode,
            'reply': ai_reply,
            'terraform_code': terraform_code,
            'download_url': download_url,
            'latency_ms': latency,
            'model': 'Amazon Nova Micro'
        })

    except Exception as e:
        print("Error invoking Bedrock:", str(e))
        return build_response(500, {
            'error': f"Failed to execute CloudOps Agent: {str(e)}"
        })

def extract_terraform_code(text):
    """Extracts HCL/Terraform code block from AI completion text."""
    pattern = r"```(?:hcl|terraform)?\s*([\s\S]*?)```"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return None

def build_response(status_code, body):
    """Builds standard JSON response."""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json'
        },
        'body': json.dumps(body)
    }
