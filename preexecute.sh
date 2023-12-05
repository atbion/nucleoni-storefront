#!/usr/bin/env bash
virtualenv venv -p python3.11
. ./venv/bin/activate
pip install -r requirements_cdk.txt
