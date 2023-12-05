#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
"""
Copyright (c) 2023 - present Atbion<atbion.com>
Yadisnel Galvez Velazquez <yadisnel@atbion.com>
"""
import os

import aws_cdk as cdk

from stacks.us_certificates import UsCertificatesStack
from stacks.storefront import StoreFrontStack

stage = os.environ.get("STAGE", "dev")
env_eu = cdk.Environment(account="486592719971", region="eu-west-1")
env_us = cdk.Environment(account="486592719971", region="us-east-1")

app = cdk.App()

us_certificates_stack = UsCertificatesStack(
    app,
    f"nucleoni-storefront-us-cert-stack-{stage}",
    env=env_us,
)

nucleoni_store_api_ecs_service_stack = StoreFrontStack(
    app,
    f"nucleoni-storefront-stack-{stage}",
    env=env_eu,
    storefront_certificate=us_certificates_stack.storefront_certificate,
    cross_region_references=True,
)

app.synth()
