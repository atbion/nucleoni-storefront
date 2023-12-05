# -*- encoding: utf-8 -*-
"""
Copyright (c) 2023 - present Atbion<atbion.com>
Yadisnel Galvez Velazquez <yadisnel@atbion.com>
"""
import os
from aws_cdk import aws_ssm


class UtilsService:
    @staticmethod
    def root_dir():
        file_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.abspath(os.path.join(file_dir, ".."))

    @staticmethod
    def build_storefront_environment(
        stage: str,
        region: str,
    ):
        return {
            "STAGE": stage,
            "DEPLOYMENT_REGION": region,
        }

    @staticmethod
    def get_ssm_parameter_arn(construct, parameter_name: str):
        value = aws_ssm.StringParameter.value_from_lookup(
            construct, parameter_name
        )
        if 'dummy-value' in value:
            value = 'arn:aws:service:eu-central-1:123456789012:entity/dummy-value'
        return value
