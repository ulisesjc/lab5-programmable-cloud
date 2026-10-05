#!/bin/bash
# Startup script for VM-1. Pulls the files part3.py stored in metadata and runs
# the program that launches VM-2. Output is logged to /var/log/vm1-launch-vm2.log
set -e

mkdir -p /srv
cd /srv

MD=http://metadata/computeMetadata/v1/instance/attributes
curl -sf $MD/vm2-startup-script -H "Metadata-Flavor: Google" > vm2-startup-script.sh
curl -sf $MD/service-credentials -H "Metadata-Flavor: Google" > service-credentials.json
chmod 600 service-credentials.json
curl -sf $MD/vm1-launch-vm2-code -H "Metadata-Flavor: Google" > vm1-launch-vm2-code.py
export GOOGLE_CLOUD_PROJECT=$(curl -sf $MD/project -H "Metadata-Flavor: Google")

apt-get update
apt-get install -y python3 python3-pip
pip3 install --upgrade google-api-python-client google-auth google-auth-httplib2

python3 ./vm1-launch-vm2-code.py 2>&1 | tee /var/log/vm1-launch-vm2.log
