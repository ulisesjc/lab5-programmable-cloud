import argparse
import os

import googleapiclient.discovery
import google.auth
from googleapiclient.errors import HttpError

FIREWALL_RULE = 'allow-5000'
NETWORK_TAG = 'allow-5000'


def wait_for_zone_operation(compute, project, zone, operation):
    while True:
        result = compute.zoneOperations().wait(
            project=project, zone=zone, operation=operation).execute()
        if result['status'] == 'DONE':
            if 'error' in result:
                raise RuntimeError(result['error'])
            return result


def wait_for_global_operation(compute, project, operation):
    while True:
        result = compute.globalOperations().wait(
            project=project, operation=operation).execute()
        if result['status'] == 'DONE':
            if 'error' in result:
                raise RuntimeError(result['error'])
            return result


def create_instance(compute, project, zone, name, machine_type, startup_script):
    image = compute.images().getFromFamily(
        project='ubuntu-os-cloud', family='ubuntu-2204-lts').execute()

    config = {
        'name': name,
        'machineType': f'zones/{zone}/machineTypes/{machine_type}',
        'disks': [{
            'boot': True,
            'autoDelete': True,
            'initializeParams': {'sourceImage': image['selfLink']},
        }],
        'networkInterfaces': [{
            'network': 'global/networks/default',
            'accessConfigs': [{'type': 'ONE_TO_ONE_NAT', 'name': 'External NAT'}],
        }],
        'metadata': {
            'items': [{'key': 'startup-script', 'value': startup_script}],
        },
    }

    try:
        operation = compute.instances().insert(
            project=project, zone=zone, body=config).execute()
    except HttpError as e:
        if e.resp.status == 409:
            print(f"Instance {name} already exists, reusing it")
            return
        raise
    wait_for_zone_operation(compute, project, zone, operation['name'])
    print(f"Created instance {name}")


def ensure_firewall_rule(compute, project):
    result = compute.firewalls().list(
        project=project, filter=f'name = "{FIREWALL_RULE}"').execute()
    if result.get('items'):
        print(f"Firewall rule {FIREWALL_RULE} already exists")
        return

    body = {
        'name': FIREWALL_RULE,
        'network': 'global/networks/default',
        'direction': 'INGRESS',
        'sourceRanges': ['0.0.0.0/0'],
        'targetTags': [NETWORK_TAG],
        'allowed': [{'IPProtocol': 'tcp', 'ports': ['5000']}],
    }
    operation = compute.firewalls().insert(project=project, body=body).execute()
    wait_for_global_operation(compute, project, operation['name'])
    print(f"Created firewall rule {FIREWALL_RULE}")


def add_network_tag(compute, project, zone, name, tag):
    instance = compute.instances().get(project=project, zone=zone, instance=name).execute()
    tags = instance.get('tags', {})
    items = tags.get('items', [])
    if tag in items:
        return
    operation = compute.instances().setTags(
        project=project, zone=zone, instance=name,
        body={'items': items + [tag], 'fingerprint': tags['fingerprint']}).execute()
    wait_for_zone_operation(compute, project, zone, operation['name'])
    print(f"Applied network tag {tag} to {name}")


def get_external_ip(compute, project, zone, name):
    instance = compute.instances().get(project=project, zone=zone, instance=name).execute()
    return instance['networkInterfaces'][0]['accessConfigs'][0]['natIP']


def main():
    credentials, default_project = google.auth.default()

    parser = argparse.ArgumentParser(description='Create a VM running the flask tutorial app')
    parser.add_argument('--project', default=default_project)
    parser.add_argument('--zone', default='us-west1-b')
    parser.add_argument('--name', default='flask-vm')
    parser.add_argument('--machine-type', default='f1-micro')
    args = parser.parse_args()

    compute = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)

    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'startup-script.sh')
    with open(script_path) as f:
        startup_script = f.read()

    create_instance(compute, args.project, args.zone, args.name, args.machine_type, startup_script)
    ensure_firewall_rule(compute, args.project)
    add_network_tag(compute, args.project, args.zone, args.name, NETWORK_TAG)
    ip = get_external_ip(compute, args.project, args.zone, args.name)

    print()
    print("The Flask application will be available at (allow a few minutes for the startup script to finish):")
    print()
    print(f"    http://{ip}:5000")


if __name__ == '__main__':
    main()
