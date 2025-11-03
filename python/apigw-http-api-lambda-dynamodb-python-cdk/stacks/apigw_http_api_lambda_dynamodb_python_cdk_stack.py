# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb_,
    aws_lambda as lambda_,
    aws_apigateway as apigw_,
    aws_wafv2 as waf_,
    aws_logs as logs_,
    aws_ec2 as ec2,
    aws_iam as iam,
    Duration,
    CfnOutput,
)
from constructs import Construct

TABLE_NAME = "demo_table"


class ApigwHttpApiLambdaDynamodbPythonCdkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC
        vpc = ec2.Vpc(
            self,
            "Ingress",
            cidr="10.1.0.0/16",
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Private-Subnet", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24
                )
            ],
        )
        
        # Create VPC endpoint
        dynamo_db_endpoint = ec2.GatewayVpcEndpoint(
            self,
            "DynamoDBVpce",
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB,
            vpc=vpc,
        )

        # This allows to customize the endpoint policy
        dynamo_db_endpoint.add_to_policy(
            iam.PolicyStatement(  # Restrict to listing and describing tables
                principals=[iam.AnyPrincipal()],
                actions=[                "dynamodb:DescribeStream",
                "dynamodb:DescribeTable",
                "dynamodb:Get*",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:CreateTable",
                "dynamodb:Delete*",
                "dynamodb:Update*",
                "dynamodb:PutItem"],
                resources=["*"],
            )
        )

        # Create DynamoDb Table
        demo_table = dynamodb_.Table(
            self,
            TABLE_NAME,
            partition_key=dynamodb_.Attribute(
                name="id", type=dynamodb_.AttributeType.STRING
            ),
        )

        # Create the Lambda function to receive the request
        api_hanlder = lambda_.Function(
            self,
            "ApiHandler",
            function_name="apigw_handler",
            runtime=lambda_.Runtime.PYTHON_3_9,
            code=lambda_.Code.from_asset("lambda/apigw-handler"),
            handler="index.handler",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            memory_size=1024,
            timeout=Duration.minutes(5),
        )

        # grant permission to lambda to write to demo table
        demo_table.grant_write_data(api_hanlder)
        api_hanlder.add_environment("TABLE_NAME", demo_table.table_name)

        # Create API Gateway
        api = apigw_.LambdaRestApi(
            self,
            "Endpoint",
            handler=api_hanlder,
        )

        # Create CloudWatch Log Group for WAF
        waf_log_group = logs_.LogGroup(
            self,
            "WAFLogGroup",
            log_group_name=f"/aws/wafv2/{construct_id}",
            retention=logs_.RetentionDays.ONE_MONTH
        )

        # Create WAF WebACL with rate limiting (REL05-BP02)
        web_acl = waf_.CfnWebACL(
            self,
            "APIGatewayWAF",
            scope="REGIONAL",  # For API Gateway
            default_action=waf_.CfnWebACL.DefaultActionProperty(allow={}),
            rules=[
                # Rate limiting rule - 100 requests per 5 minutes per IP
                waf_.CfnWebACL.RuleProperty(
                    name="RateLimitRule",
                    priority=1,
                    statement=waf_.CfnWebACL.StatementProperty(
                        rate_based_statement=waf_.CfnWebACL.RateBasedStatementProperty(
                            limit=100,  # 100 requests per 5 minutes
                            aggregate_key_type="IP"
                        )
                    ),
                    action=waf_.CfnWebACL.RuleActionProperty(
                        block={}  # Block requests exceeding rate limit
                    ),
                    visibility_config=waf_.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name="RateLimitRule"
                    )
                )
            ],
            visibility_config=waf_.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloud_watch_metrics_enabled=True,
                metric_name="APIGatewayWAF"
            )
        )

        # Associate WAF with API Gateway
        waf_association = waf_.CfnWebACLAssociation(
            self,
            "WAFAssociation",
            resource_arn=f"arn:aws:apigateway:{self.region}::/restapis/{api.rest_api_id}/stages/{api.deployment_stage.stage_name}",
            web_acl_arn=web_acl.attr_arn
        )

        # Configure WAF logging
        waf_logging = waf_.CfnLoggingConfiguration(
            self,
            "WAFLogging",
            resource_arn=web_acl.attr_arn,
            log_destination_configs=[waf_log_group.log_group_arn]
        )

        # Output important information
        CfnOutput(
            self,
            "APIGatewayURL",
            value=api.url,
            description="API Gateway URL"
        )
        
        CfnOutput(
            self,
            "WAFWebACLArn",
            value=web_acl.attr_arn,
            description="WAF WebACL ARN for monitoring"
        )