#!/bin/bash
# Startup script for the Flask tutorial VM. Runs as root on every boot.
set -e

mkdir -p /opt/flask-app
cd /opt/flask-app

apt-get update
apt-get install -y python3 python3-pip git

if [ ! -d flask-tutorial ]; then
    git clone https://github.com/cu-csci-4253-datacenter/flask-tutorial
fi
cd flask-tutorial

pip3 install -e .

export FLASK_APP=flaskr
# Only initialize the database the first time so reboots don't wipe posts
if [ ! -f instance/flaskr.sqlite ]; then
    python3 -m flask init-db
fi

nohup python3 -m flask run -h 0.0.0.0 > /var/log/flask.log 2>&1 &
