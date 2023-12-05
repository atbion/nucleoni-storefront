# -*- encoding: utf-8 -*-
"""
Copyright (c) 2023 - present Atbion<atbion.com>
Yadisnel Galvez Velazquez <yadisnel@atbion.com>
"""
import os

from aws_cdk import (Duration, RemovalPolicy, Stack, aws_certificatemanager,
                     aws_cloudfront, aws_cloudfront_origins,
                     aws_ec2, aws_ecs, aws_elasticloadbalancingv2, aws_iam,
                     aws_logs, aws_route53, aws_route53_targets,
                     aws_ssm)
from constructs import Construct

from stacks.utils import UtilsService


class StoreFrontStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        storefront_certificate: aws_certificatemanager.Certificate,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.stage = os.environ.get("STAGE", "dev")
        self.is_production = self.stage == "prod"
        self.storefront_certificate = storefront_certificate

        self.vpc = None
        self.hosted_zone = None
        self.storefront_ecs_service = None
        self.storefront_cloud_front_distribution = None

        # Setup common resources
        self.setup_common_resources()
        # Setup ECS Service
        self.setup_storefront_ecs_service()
        # Setup CloudFront Distribution
        self.setup_storefront_cloud_front_distribution()

    def setup_common_resources(self):
        vpc_id = aws_ssm.StringParameter.value_from_lookup(
            self, "/infra/vpc-id/vpc-atbion"
        )
        self.vpc = aws_ec2.Vpc.from_lookup(self, f"vpc-{self.stage}", vpc_id=vpc_id)
        self.hosted_zone = aws_route53.HostedZone.from_lookup(
            self,
            f"hosted-zone-{self.stage}",
            domain_name="nucleoni.com",
        )

    def setup_storefront_ecs_service(self):
        ecs_cluster = aws_ecs.Cluster.from_cluster_attributes(
            self,
            f"common-ecs-cluster",
            cluster_name=f"common-ecs-cluster",
            vpc=self.vpc,
        )

        # Create Task Definition
        task_definition = aws_ecs.FargateTaskDefinition(
            self, f"storefront-ecs-task-{self.stage}",
            cpu=512,
            memory_limit_mib=2048,
        )

        task_definition.add_to_task_role_policy(
            aws_iam.PolicyStatement(
                actions=[
                    "ssm:*",
                    "dynamodb:*",
                    "states:*",
                ],
                resources=[
                    "*",
                ],
                effect=aws_iam.Effect.ALLOW,
            )
        )

        task_definition_log_group = aws_logs.LogGroup(
            self,
            f"storefront-task-group-{self.stage}",
            log_group_name=f"storefront-task-group-{self.stage}",
            removal_policy=RemovalPolicy.RETAIN,
            retention=aws_logs.RetentionDays.THREE_MONTHS,
        )

        container = task_definition.add_container(
            f"storefront-container-{self.stage}",
            image=aws_ecs.ContainerImage.from_asset(
                directory=UtilsService.root_dir(),
                file="Dockerfile",
            ),
            container_name=f"storefront-container-{self.stage}",
            cpu=512,
            memory_limit_mib=2048,
            logging=aws_ecs.LogDriver.aws_logs(
                stream_prefix=f"storefront-{self.stage}",
                log_group=task_definition_log_group,
            ),
            environment=UtilsService.build_storefront_environment(
                stage=self.stage,
                region=self.region,
            ),
        )

        port_mapping = aws_ecs.PortMapping(
            container_port=3000, protocol=aws_ecs.Protocol.TCP
        )

        container.add_port_mappings(port_mapping)

        # Create Service
        self.storefront_ecs_service = aws_ecs.FargateService(
            self,
            f"nucleoni-storefront-service-{self.stage}",
            service_name=f"nucleoni-storefront-service-{self.stage}",
            cluster=ecs_cluster,
            task_definition=task_definition,
            vpc_subnets=aws_ec2.SubnetSelection(
                subnet_type=aws_ec2.SubnetType.PUBLIC,
            ),
            assign_public_ip=True,
            desired_count=1,
            circuit_breaker=aws_ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=100,
            max_healthy_percent=200,
        )

        task_scaling = self.storefront_ecs_service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=2,
        )

        task_scaling.scale_on_cpu_utilization(
            f"nucleoni-storefront-service-cpu-scaling-{self.stage}",
            target_utilization_percent=85,
        )

        listener = aws_elasticloadbalancingv2.ApplicationListener.from_lookup(
            self,
            f"nucleoni-common-alb-listener-{self.stage}",
            listener_arn=aws_ssm.StringParameter.value_from_lookup(
                self,
                "/infra/common-alb-listener-443-arn",
            ),
            load_balancer_arn=aws_ssm.StringParameter.value_from_lookup(
                self,
                f"/infra/common-alb-arn",
            ),
        )

        target_group = aws_elasticloadbalancingv2.ApplicationTargetGroup(
            self,
            f"nucleoni-storefront-alb-tg-{self.stage}",
            target_group_name=f"nucleoni-storefront-alb-tg-{self.stage}",
            port=80,
            targets=[
                self.storefront_ecs_service.load_balancer_target(
                    container_name=container.container_name,
                    container_port=port_mapping.container_port,
                ),
            ],
            vpc=self.vpc,
            health_check=aws_elasticloadbalancingv2.HealthCheck(
                enabled=True,
                path="/",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=5,
                healthy_http_codes="200",
                port="80",
            ),
        )

        aws_elasticloadbalancingv2.ApplicationListenerRule(
            self,
            id=f"nucleoni-storefront-listener-rule-{self.stage}",
            conditions=[
                aws_elasticloadbalancingv2.ListenerCondition.http_header(
                    name="x-atbion-app",
                    values=[
                        f"nucleoni-storefront-{self.stage}",
                    ],
                )
            ],
            priority=20 if self.stage == "dev" else 21,
            listener=listener,
            target_groups=[target_group],
        )

        storefront_provisioning_task_definition_sg = aws_ec2.SecurityGroup(
            self,
            f"storefront-provisioning-task-definition-sg-{self.stage}",
            vpc=self.vpc,
            description="Allow task definition for provisioning",
            allow_all_outbound=True,
        )

        aws_ssm.StringParameter(
            self,
            f"/infra/storefront-task-definition-arn/{self.stage}",
            parameter_name=f"/infra/storefront-task-definition-arn/{self.stage}",
            string_value=task_definition.task_definition_arn,
        )

        aws_ssm.StringParameter(
            self,
            f"/infra/storefront-provisioning-task-definition-sg-id/{self.stage}",
            parameter_name=f"/infra/storefront-provisioning-task-definition-sg-id/{self.stage}",
            string_value=storefront_provisioning_task_definition_sg.security_group_id,
        )

    def setup_storefront_cloud_front_distribution(self):
        self.storefront_cloud_front_distribution = aws_cloudfront.Distribution(
            self,
            f"nucleoni-storefront-cloud-front-distribution",
            default_behavior=aws_cloudfront.BehaviorOptions(
                origin=aws_cloudfront_origins.HttpOrigin(
                    domain_name="alb.atbion.com",
                    protocol_policy=aws_cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
                    custom_headers={
                        "x-atbion-app": f"nucleoni-storefront-{self.stage}",
                    },
                    origin_path="/",
                ),
                viewer_protocol_policy=aws_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=aws_cloudfront.AllowedMethods.ALLOW_ALL,
                cached_methods=None,
                cache_policy=aws_cloudfront.CachePolicy(
                    self,
                    f"nucleoni-storefront-cloud-front-cache-policy",
                    cache_policy_name=f"nucleoni-storefront-cloud-front-cache-policy",
                    comment=f"nucleoni-storefront-cloud-front-cache-policy",
                    default_ttl=Duration.minutes(0),
                    min_ttl=Duration.minutes(0),
                    max_ttl=Duration.minutes(1),
                    cookie_behavior=aws_cloudfront.CacheCookieBehavior.all(),
                    header_behavior=aws_cloudfront.CacheHeaderBehavior.allow_list(
                        "x-atbion-app",
                        "Accept",
                        "Accept-Language",
                        "Accept-Encoding",
                        "Authorization",
                        "Content-Type",
                    ),
                ),
                origin_request_policy=aws_cloudfront.OriginRequestPolicy(
                    self,
                    f"nucleoni-storefront-cloud-front-cache-policy-front-origin-request-policy",
                    origin_request_policy_name=f"nucleoni-storefront-cloud-front-origin-request-policy",
                    comment=f"nucleoni-storefront-cloud-front-origin-request-policy",
                    cookie_behavior=aws_cloudfront.OriginRequestCookieBehavior.all(),
                    header_behavior=aws_cloudfront.OriginRequestHeaderBehavior.all(),
                    query_string_behavior=aws_cloudfront.OriginRequestQueryStringBehavior.all(),
                ),
                compress=True,
            ),
            domain_names=[
                "storefront.nucleoni.com" if self.is_production else f"{self.stage}.storefront.nucleoni.com"],
            certificate=self.storefront_certificate,
        )

        aws_route53.ARecord(
            self,
            f"nucleoni-storefront-cloud-front-distribution-record",
            zone=self.hosted_zone,
            target=aws_route53.RecordTarget.from_alias(
                aws_route53_targets.CloudFrontTarget(
                    self.storefront_cloud_front_distribution
                )
            ),
            record_name="storefront.nucleoni.com" if self.is_production else f"{self.stage}.storefront.nucleoni.com",
        )
