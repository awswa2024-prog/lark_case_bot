"""
AWS Support Complete Service List

This module contains the complete list of AWS services with their Support API
service codes and display names, organized by category.

Features:
- Complete AWS service catalog for Support case creation
- Service categorization (Compute, Storage, Database, Network, etc.)
- Issue type definitions (technical, customer-service, account-and-billing)
- Cost Explorer service name to Support code mapping
- Helper functions for service filtering and merging

Usage:
    from aws_services_complete import (
        get_all_services_flat,
        get_services_for_issue_type,
        merge_with_cost_explorer_services,
        CE_TO_SUPPORT_MAPPING
    )
    
    # Get all services as flat list
    services = get_all_services_flat()
    
    # Get services for specific issue type
    billing_services = get_services_for_issue_type('account-and-billing')
"""

# Complete AWS service list (grouped by category)
AWS_SERVICES_COMPLETE = {
    "Compute Services": [
        {"code": "amazon-elastic-compute-cloud-linux", "name": "EC2 (Linux)", "category": "general-guidance"},
        {"code": "amazon-elastic-compute-cloud-windows", "name": "EC2 (Windows)", "category": "general-guidance"},
        {"code": "aws-lambda", "name": "Lambda", "category": "general-guidance"},
        {"code": "amazon-elastic-container-service", "name": "ECS", "category": "general-guidance"},
        {"code": "service-eks", "name": "EKS", "category": "kubernetes-guidance"},
        {"code": "aws-batch", "name": "Batch", "category": "general-guidance"},
        {"code": "aws-elastic-beanstalk", "name": "Elastic Beanstalk", "category": "general-guidance"},
        {"code": "amazon-lightsail", "name": "Lightsail", "category": "general-guidance"},
    ],
    
    "Storage Services": [
        {"code": "amazon-simple-storage-service", "name": "S3", "category": "general-guidance"},
        {"code": "amazon-elastic-block-store", "name": "EBS", "category": "general-guidance"},
        {"code": "amazon-elastic-file-system", "name": "EFS", "category": "general-guidance"},
        {"code": "aws-storage-gateway", "name": "Storage Gateway", "category": "general-guidance"},
        {"code": "amazon-fsx", "name": "FSx", "category": "general-guidance"},
        {"code": "aws-backup", "name": "Backup", "category": "general-guidance"},
    ],
    
    "Database Services": [
        {"code": "amazon-dynamodb", "name": "DynamoDB", "category": "general-guidance"},
        {"code": "amazon-relational-database-service", "name": "RDS", "category": "general-guidance"},
        {"code": "amazon-aurora", "name": "Aurora", "category": "general-guidance"},
        {"code": "amazon-elasticache", "name": "ElastiCache", "category": "general-guidance"},
        {"code": "amazon-redshift", "name": "Redshift", "category": "general-guidance"},
        {"code": "amazon-documentdb", "name": "DocumentDB", "category": "general-guidance"},
        {"code": "amazon-neptune", "name": "Neptune", "category": "general-guidance"},
        {"code": "amazon-timestream", "name": "Timestream", "category": "general-guidance"},
        {"code": "amazon-keyspaces", "name": "Keyspaces", "category": "general-guidance"},
    ],
    
    "Network Services": [
        {"code": "amazon-virtual-private-cloud", "name": "VPC", "category": "general-guidance"},
        {"code": "amazon-cloudfront", "name": "CloudFront", "category": "general-guidance"},
        {"code": "amazon-route-53", "name": "Route 53", "category": "general-guidance"},
        {"code": "aws-direct-connect", "name": "Direct Connect", "category": "general-guidance"},
        {"code": "elastic-load-balancing", "name": "ELB/ALB/NLB", "category": "general-guidance"},
        {"code": "amazon-api-gateway", "name": "API Gateway", "category": "general-guidance"},
        {"code": "aws-transit-gateway", "name": "Transit Gateway", "category": "general-guidance"},
        {"code": "aws-global-accelerator", "name": "Global Accelerator", "category": "general-guidance"},
    ],
    
    "Security Services": [
        {"code": "aws-identity-and-access-management", "name": "IAM", "category": "general-guidance"},
        {"code": "aws-key-management-service", "name": "KMS", "category": "general-guidance"},
        {"code": "aws-secrets-manager", "name": "Secrets Manager", "category": "general-guidance"},
        {"code": "aws-certificate-manager", "name": "ACM", "category": "general-guidance"},
        {"code": "amazon-cognito", "name": "Cognito", "category": "general-guidance"},
        {"code": "aws-waf", "name": "WAF", "category": "general-guidance"},
        {"code": "aws-shield", "name": "Shield", "category": "general-guidance"},
        {"code": "amazon-guardduty", "name": "GuardDuty", "category": "general-guidance"},
        {"code": "amazon-inspector", "name": "Inspector", "category": "general-guidance"},
        {"code": "aws-security-hub", "name": "Security Hub", "category": "general-guidance"},
    ],
    
    "Monitoring and Management": [
        {"code": "amazon-cloudwatch", "name": "CloudWatch", "category": "general-guidance"},
        {"code": "aws-cloudtrail", "name": "CloudTrail", "category": "general-guidance"},
        {"code": "aws-config", "name": "Config", "category": "general-guidance"},
        {"code": "aws-systems-manager", "name": "Systems Manager", "category": "general-guidance"},
        {"code": "aws-cloudformation", "name": "CloudFormation", "category": "general-guidance"},
        {"code": "aws-service-catalog", "name": "Service Catalog", "category": "general-guidance"},
        {"code": "aws-trusted-advisor", "name": "Trusted Advisor", "category": "general-guidance"},
        {"code": "aws-organizations", "name": "Organizations", "category": "general-guidance"},
    ],
    
    "Analytics Services": [
        {"code": "amazon-athena", "name": "Athena", "category": "general-guidance"},
        {"code": "aws-glue", "name": "Glue", "category": "general-guidance"},
        {"code": "amazon-emr", "name": "EMR", "category": "general-guidance"},
        {"code": "amazon-kinesis", "name": "Kinesis", "category": "general-guidance"},
        {"code": "amazon-quicksight", "name": "QuickSight", "category": "general-guidance"},
        {"code": "amazon-managed-streaming-for-apache-kafka", "name": "MSK", "category": "general-guidance"},
        {"code": "aws-data-pipeline", "name": "Data Pipeline", "category": "general-guidance"},
    ],
    
    "Application Integration": [
        {"code": "amazon-simple-notification-service", "name": "SNS", "category": "general-guidance"},
        {"code": "amazon-simple-queue-service", "name": "SQS", "category": "general-guidance"},
        {"code": "amazon-eventbridge", "name": "EventBridge", "category": "general-guidance"},
        {"code": "aws-step-functions", "name": "Step Functions", "category": "general-guidance"},
        {"code": "amazon-appflow", "name": "AppFlow", "category": "general-guidance"},
    ],
    
    "Developer Tools": [
        {"code": "aws-codecommit", "name": "CodeCommit", "category": "general-guidance"},
        {"code": "aws-codebuild", "name": "CodeBuild", "category": "general-guidance"},
        {"code": "aws-codedeploy", "name": "CodeDeploy", "category": "general-guidance"},
        {"code": "aws-codepipeline", "name": "CodePipeline", "category": "general-guidance"},
        {"code": "aws-cloud9", "name": "Cloud9", "category": "general-guidance"},
        {"code": "aws-x-ray", "name": "X-Ray", "category": "general-guidance"},
    ],
    
    "Machine Learning": [
        {"code": "amazon-sagemaker", "name": "SageMaker", "category": "general-guidance"},
        {"code": "amazon-rekognition", "name": "Rekognition", "category": "general-guidance"},
        {"code": "amazon-comprehend", "name": "Comprehend", "category": "general-guidance"},
        {"code": "amazon-translate", "name": "Translate", "category": "general-guidance"},
        {"code": "amazon-polly", "name": "Polly", "category": "general-guidance"},
        {"code": "amazon-transcribe", "name": "Transcribe", "category": "general-guidance"},
        {"code": "amazon-lex", "name": "Lex", "category": "general-guidance"},
    ],
    
    "Other Services": [
        {"code": "general-info", "name": "General Info", "category": "using-aws"},
        {"code": "billing", "name": "Billing", "category": "general-guidance"},
        {"code": "account", "name": "Account", "category": "general-guidance"},
    ],
}

# Issue type definitions
ISSUE_TYPES = {
    "technical": {
        "name": "🔧 Technical Support",
        "description": "Technical issues, service failures, configuration help",
        "services": "all"  # Can select all services
    },
    "customer-service": {
        "name": "👤 Customer Service",
        "description": "Account related, service limits, general inquiries",
        "services": ["general-info", "account"]
    },
    "account-and-billing": {
        "name": "💰 Billing Issues",
        "description": "Billing issues, cost inquiries, account management",
        "services": ["billing", "account", "general-info"]
    }
}


def get_all_services_flat():
    """Get all services as a flat list"""
    all_services = []
    for category, services in AWS_SERVICES_COMPLETE.items():
        all_services.extend(services)
    return all_services


def get_services_by_category():
    """Get services by category"""
    return AWS_SERVICES_COMPLETE


def get_services_for_issue_type(issue_type: str):
    """Get available services list based on issue type"""
    issue_config = ISSUE_TYPES.get(issue_type, {})
    allowed_services = issue_config.get("services", "all")
    
    if allowed_services == "all":
        return get_all_services_flat()
    else:
        # Only return allowed services
        all_services = get_all_services_flat()
        return [s for s in all_services if s["code"] in allowed_services]


def merge_with_cost_explorer_services(ce_services, all_services):
    """
    Merge Cost Explorer services with complete service list
    Services discovered from Cost Explorer are placed first, marked as "recently used"
    """
    # Service codes from Cost Explorer
    ce_codes = {s["code"] for s in ce_services}
    
    # Recently used services (placed first)
    recent_services = []
    for service in ce_services:
        service_copy = service.copy()
        service_copy["name"] = f"{service['name']} (Recently Used)"
        service_copy["recent"] = True
        recent_services.append(service_copy)
    
    # Other services (placed after)
    other_services = []
    for service in all_services:
        if service["code"] not in ce_codes:
            service_copy = service.copy()
            service_copy["recent"] = False
            other_services.append(service_copy)
    
    # Merge: recently used + separator + other services
    return recent_services, other_services


# Cost Explorer service name to Support code mapping
CE_TO_SUPPORT_MAPPING = {
    'Amazon Elastic Compute Cloud - Compute': ('amazon-elastic-compute-cloud-linux', 'EC2'),
    'Amazon Simple Storage Service': ('amazon-simple-storage-service', 'S3'),
    'AWS Lambda': ('aws-lambda', 'Lambda'),
    'Amazon DynamoDB': ('amazon-dynamodb', 'DynamoDB'),
    'Amazon Relational Database Service': ('amazon-relational-database-service', 'RDS'),
    'Amazon Virtual Private Cloud': ('amazon-virtual-private-cloud', 'VPC'),
    'AWS Glue': ('aws-glue', 'Glue'),
    'Amazon Athena': ('amazon-athena', 'Athena'),
    'AWS Config': ('aws-config', 'Config'),
    'AWS Key Management Service': ('aws-key-management-service', 'KMS'),
    'AWS Secrets Manager': ('aws-secrets-manager', 'Secrets Manager'),
    'Amazon Route 53': ('amazon-route-53', 'Route 53'),
    'Amazon CloudFront': ('amazon-cloudfront', 'CloudFront'),
    'Amazon Elastic Container Service': ('amazon-elastic-container-service', 'ECS'),
    'Amazon Elastic Kubernetes Service': ('service-eks', 'EKS'),
    'Amazon Simple Notification Service': ('amazon-simple-notification-service', 'SNS'),
    'Amazon Simple Queue Service': ('amazon-simple-queue-service', 'SQS'),
    'Amazon ElastiCache': ('amazon-elasticache', 'ElastiCache'),
    'Amazon Redshift': ('amazon-redshift', 'Redshift'),
    'Amazon CloudWatch': ('amazon-cloudwatch', 'CloudWatch'),
    'AWS CloudTrail': ('aws-cloudtrail', 'CloudTrail'),
    'Amazon API Gateway': ('amazon-api-gateway', 'API Gateway'),
    'AWS Step Functions': ('aws-step-functions', 'Step Functions'),
    'Amazon Kinesis': ('amazon-kinesis', 'Kinesis'),
    'Amazon EMR': ('amazon-emr', 'EMR'),
    'Amazon SageMaker': ('amazon-sagemaker', 'SageMaker'),
    'AWS CodeBuild': ('aws-codebuild', 'CodeBuild'),
    'AWS CodePipeline': ('aws-codepipeline', 'CodePipeline'),
    'Amazon Cognito': ('amazon-cognito', 'Cognito'),
    'AWS WAF': ('aws-waf', 'WAF'),
    'Amazon GuardDuty': ('amazon-guardduty', 'GuardDuty'),
    'AWS Systems Manager': ('aws-systems-manager', 'Systems Manager'),
    'AWS CloudFormation': ('aws-cloudformation', 'CloudFormation'),
}
