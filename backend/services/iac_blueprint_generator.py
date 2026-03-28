"""IaC blueprint generation service for greenfield architecture generation workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set


SUPPORTED_SERVICES = {
    "vpc",
    "ec2",
    "s3",
    "rds",
    "lambda",
    "apigateway",
    "dynamodb",
    "ecs",
    "cloudfront",
    "sqs",
    "sns",
}

KEYWORD_TO_SERVICE = {
    "network": "vpc",
    "vpc": "vpc",
    "bucket": "s3",
    "storage": "s3",
    "object storage": "s3",
    "compute": "ec2",
    "vm": "ec2",
    "instance": "ec2",
    "server": "ec2",
    "database": "rds",
    "postgres": "rds",
    "mysql": "rds",
    "nosql": "dynamodb",
    "dynamo": "dynamodb",
    "queue": "sqs",
    "pubsub": "sns",
    "topic": "sns",
    "notification": "sns",
    "api": "apigateway",
    "microservice": "ecs",
    "container": "ecs",
    "fargate": "ecs",
    "function": "lambda",
    "serverless": "lambda",
    "cdn": "cloudfront",
    "edge": "cloudfront",
}


@dataclass
class GenerationResult:
    summary: str
    assumptions: List[str]
    selected_services: List[str]
    generated_template: str
    alternate_template: str
    next_steps: List[str]


class IaCBlueprintGeneratorService:
    """Generate IaC starter templates from text, selected services, or diagram context."""

    def _normalize_output_format(self, output_format: str) -> str:
        normalized = (output_format or "terraform").strip().lower()
        if normalized not in {"terraform", "cloudformation"}:
            raise ValueError("output_format must be 'terraform' or 'cloudformation'")
        return normalized

    def _normalize_services(self, services: List[str]) -> List[str]:
        normalized: List[str] = []
        for service in services:
            key = (service or "").strip().lower().replace("-", "")
            key = key.replace("api gateway", "apigateway")
            if key in SUPPORTED_SERVICES:
                normalized.append(key)
        return sorted(set(normalized))

    def _infer_services_from_text(self, text: str) -> List[str]:
        haystack = (text or "").lower()
        inferred: Set[str] = set()
        for phrase, service in KEYWORD_TO_SERVICE.items():
            if phrase in haystack:
                inferred.add(service)

        if not inferred:
            # Safe baseline when requirements are broad/ambiguous
            inferred.update({"vpc", "ecs", "s3"})

        if "apigateway" in inferred and "lambda" not in inferred and "ecs" not in inferred:
            inferred.add("lambda")

        if "cloudfront" in inferred and "s3" not in inferred:
            inferred.add("s3")

        return sorted(inferred)

    def _render_terraform(self, services: List[str], region: str, environment: str) -> str:
        blocks: List[str] = [
            "terraform {",
            "  required_version = \">= 1.5.0\"",
            "  required_providers {",
            "    aws = {",
            "      source  = \"hashicorp/aws\"",
            "      version = \"~> 5.0\"",
            "    }",
            "  }",
            "}",
            "",
            f"provider \"aws\" {{",
            f"  region = \"{region}\"",
            "}",
            "",
            f"locals {{",
            f"  environment = \"{environment}\"",
            "  common_tags = {",
            "    ManagedBy   = \"aasmaa-generate\"",
            "    Environment = local.environment",
            "  }",
            "}",
            "",
        ]

        if "vpc" in services:
            blocks.extend([
                "resource \"aws_vpc\" \"main\" {",
                "  cidr_block           = \"10.20.0.0/16\"",
                "  enable_dns_support   = true",
                "  enable_dns_hostnames = true",
                "",
                "  tags = merge(local.common_tags, {",
                "    Name = \"${local.environment}-vpc\"",
                "  })",
                "}",
                "",
            ])

        if "s3" in services:
            blocks.extend([
                "resource \"aws_s3_bucket\" \"app_data\" {",
                "  bucket_prefix = \"aasmaa-${local.environment}-data-\"",
                "",
                "  tags = merge(local.common_tags, {",
                "    Name = \"${local.environment}-data\"",
                "  })",
                "}",
                "",
            ])

        if "ec2" in services:
            blocks.extend([
                "resource \"aws_instance\" \"app\" {",
                "  ami           = \"ami-0c02fb55956c7d316\"",
                "  instance_type = \"t3.small\"",
                "",
                "  tags = merge(local.common_tags, {",
                "    Name = \"${local.environment}-app\"",
                "  })",
                "}",
                "",
            ])

        if "rds" in services:
            blocks.extend([
                "resource \"aws_db_instance\" \"app\" {",
                "  identifier             = \"${local.environment}-app-db\"",
                "  engine                 = \"postgres\"",
                "  instance_class         = \"db.t4g.micro\"",
                "  allocated_storage      = 20",
                "  db_name                = \"appdb\"",
                "  username               = \"appadmin\"",
                "  manage_master_user_password = true",
                "  skip_final_snapshot    = true",
                "}",
                "",
            ])

        if "dynamodb" in services:
            blocks.extend([
                "resource \"aws_dynamodb_table\" \"app\" {",
                "  name         = \"${local.environment}-app-table\"",
                "  billing_mode = \"PAY_PER_REQUEST\"",
                "  hash_key     = \"pk\"",
                "",
                "  attribute {",
                "    name = \"pk\"",
                "    type = \"S\"",
                "  }",
                "}",
                "",
            ])

        if "lambda" in services:
            blocks.extend([
                "resource \"aws_lambda_function\" \"api_handler\" {",
                "  function_name = \"${local.environment}-api-handler\"",
                "  role          = aws_iam_role.lambda_exec.arn",
                "  runtime       = \"python3.11\"",
                "  handler       = \"app.handler\"",
                "  filename      = \"build/lambda.zip\"",
                "}",
                "",
            ])

        if "apigateway" in services:
            blocks.extend([
                "resource \"aws_apigatewayv2_api\" \"http_api\" {",
                "  name          = \"${local.environment}-http-api\"",
                "  protocol_type = \"HTTP\"",
                "}",
                "",
            ])

        if "ecs" in services:
            blocks.extend([
                "resource \"aws_ecs_cluster\" \"app\" {",
                "  name = \"${local.environment}-cluster\"",
                "}",
                "",
            ])

        if "cloudfront" in services:
            blocks.extend([
                "resource \"aws_cloudfront_distribution\" \"cdn\" {",
                "  enabled             = true",
                "  default_root_object = \"index.html\"",
                "  # Configure origin(s), cache behavior, and certificate here",
                "}",
                "",
            ])

        if "sqs" in services:
            blocks.extend([
                "resource \"aws_sqs_queue\" \"jobs\" {",
                "  name = \"${local.environment}-jobs\"",
                "}",
                "",
            ])

        if "sns" in services:
            blocks.extend([
                "resource \"aws_sns_topic\" \"alerts\" {",
                "  name = \"${local.environment}-alerts\"",
                "}",
                "",
            ])

        return "\n".join(blocks).strip() + "\n"

    def _render_cloudformation(self, services: List[str], region: str, environment: str) -> str:
        lines: List[str] = [
            "AWSTemplateFormatVersion: '2010-09-09'",
            "Description: aasmaa generated starter architecture",
            "",
            "Parameters:",
            "  Environment:",
            "    Type: String",
            f"    Default: {environment}",
            "  Region:",
            "    Type: String",
            f"    Default: {region}",
            "",
            "Resources:",
        ]

        if "vpc" in services:
            lines.extend([
                "  AppVpc:",
                "    Type: AWS::EC2::VPC",
                "    Properties:",
                "      CidrBlock: 10.20.0.0/16",
                "      EnableDnsSupport: true",
                "      EnableDnsHostnames: true",
                "      Tags:",
                "        - Key: Name",
                "          Value: !Sub '${Environment}-vpc'",
            ])

        if "s3" in services:
            lines.extend([
                "  AppDataBucket:",
                "    Type: AWS::S3::Bucket",
                "    Properties:",
                "      BucketName: !Sub '${AWS::AccountId}-${Environment}-app-data'",
            ])

        if "ec2" in services:
            lines.extend([
                "  AppInstance:",
                "    Type: AWS::EC2::Instance",
                "    Properties:",
                "      InstanceType: t3.small",
                "      ImageId: ami-0c02fb55956c7d316",
                "      Tags:",
                "        - Key: Name",
                "          Value: !Sub '${Environment}-app'",
            ])

        if "rds" in services:
            lines.extend([
                "  AppDatabase:",
                "    Type: AWS::RDS::DBInstance",
                "    Properties:",
                "      Engine: postgres",
                "      DBInstanceClass: db.t4g.micro",
                "      AllocatedStorage: '20'",
                "      DBName: appdb",
                "      ManageMasterUserPassword: true",
                "      DeletionProtection: false",
            ])

        if "dynamodb" in services:
            lines.extend([
                "  AppTable:",
                "    Type: AWS::DynamoDB::Table",
                "    Properties:",
                "      BillingMode: PAY_PER_REQUEST",
                "      AttributeDefinitions:",
                "        - AttributeName: pk",
                "          AttributeType: S",
                "      KeySchema:",
                "        - AttributeName: pk",
                "          KeyType: HASH",
                "      TableName: !Sub '${Environment}-app-table'",
            ])

        if "lambda" in services:
            lines.extend([
                "  ApiHandler:",
                "    Type: AWS::Lambda::Function",
                "    Properties:",
                "      Runtime: python3.11",
                "      Handler: app.handler",
                "      Role: arn:aws:iam::123456789012:role/replace-lambda-role",
                "      Code:",
                "        S3Bucket: replace-artifacts-bucket",
                "        S3Key: lambda.zip",
            ])

        if "apigateway" in services:
            lines.extend([
                "  HttpApi:",
                "    Type: AWS::ApiGatewayV2::Api",
                "    Properties:",
                "      Name: !Sub '${Environment}-http-api'",
                "      ProtocolType: HTTP",
            ])

        if "ecs" in services:
            lines.extend([
                "  AppCluster:",
                "    Type: AWS::ECS::Cluster",
                "    Properties:",
                "      ClusterName: !Sub '${Environment}-cluster'",
            ])

        if "cloudfront" in services:
            lines.extend([
                "  AppDistribution:",
                "    Type: AWS::CloudFront::Distribution",
                "    Properties:",
                "      DistributionConfig:",
                "        Enabled: true",
                "        DefaultRootObject: index.html",
                "        Origins: []",
                "        DefaultCacheBehavior:",
                "          TargetOriginId: replace-origin",
                "          ViewerProtocolPolicy: redirect-to-https",
                "          AllowedMethods: [GET, HEAD]",
                "          CachedMethods: [GET, HEAD]",
                "          ForwardedValues:",
                "            QueryString: false",
            ])

        if "sqs" in services:
            lines.extend([
                "  JobsQueue:",
                "    Type: AWS::SQS::Queue",
                "    Properties:",
                "      QueueName: !Sub '${Environment}-jobs'",
            ])

        if "sns" in services:
            lines.extend([
                "  AlertsTopic:",
                "    Type: AWS::SNS::Topic",
                "    Properties:",
                "      TopicName: !Sub '${Environment}-alerts'",
            ])

        lines.extend([
            "",
            "Outputs:",
            "  SelectedServices:",
            "    Value: \"" + ",".join(services) + "\"",
        ])

        return "\n".join(lines).rstrip() + "\n"

    def _build_result(self, mode: str, services: List[str], output_format: str, region: str, environment: str, summary_hint: str) -> GenerationResult:
        terraform = self._render_terraform(services, region, environment)
        cloudformation = self._render_cloudformation(services, region, environment)

        generated_template = terraform if output_format == "terraform" else cloudformation
        alternate_template = cloudformation if output_format == "terraform" else terraform

        assumptions = [
            f"Target cloud provider is AWS in region {region}",
            f"Environment is {environment}",
            "Security hardening, IAM least privilege, and networking details should be finalized before production",
            "Generated template is a starter blueprint and should be adapted to org standards",
        ]

        next_steps = [
            "Review generated resources with platform/security teams",
            "Add environment-specific secrets and CI/CD integration",
            "Run terraform plan or CloudFormation validation before deployment",
        ]

        return GenerationResult(
            summary=f"{summary_hint} Generated a starter {output_format} template with {len(services)} core services.",
            assumptions=assumptions,
            selected_services=services,
            generated_template=generated_template,
            alternate_template=alternate_template,
            next_steps=next_steps,
        )

    def generate_from_text(self, requirements: str, output_format: str, region: str = "us-east-1", environment: str = "development") -> GenerationResult:
        if not requirements or len(requirements.strip()) < 10:
            raise ValueError("requirements must be at least 10 characters")

        fmt = self._normalize_output_format(output_format)
        services = self._infer_services_from_text(requirements)
        return self._build_result("text", services, fmt, region, environment, "Parsed your requirements.")

    def generate_from_services(self, services: List[str], output_format: str, region: str = "us-east-1", environment: str = "development") -> GenerationResult:
        normalized_services = self._normalize_services(services)
        if not normalized_services:
            raise ValueError("At least one valid service must be selected")

        fmt = self._normalize_output_format(output_format)
        return self._build_result("services", normalized_services, fmt, region, environment, "Used your selected services.")

    def generate_from_diagram(self, filename: str, content_type: str, notes: str, output_format: str, region: str = "us-east-1", environment: str = "development") -> GenerationResult:
        # For now we infer from optional notes + filename hints. This keeps workflow functional
        # without requiring CV/OCR dependencies in runtime environments.
        descriptor = f"{filename or ''} {notes or ''} {content_type or ''}".strip()
        if len(descriptor) < 3:
            raise ValueError("diagram file or notes are required")

        fmt = self._normalize_output_format(output_format)
        services = self._infer_services_from_text(descriptor)
        return self._build_result("diagram", services, fmt, region, environment, "Inferred architecture from diagram context.")


iac_blueprint_generator_service = IaCBlueprintGeneratorService()
