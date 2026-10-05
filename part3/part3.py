import argparse
import os
import time

import googleapiclient.discovery
import google.oauth2.service_account as service_account
from googleapiclient.errors import HttpError

HERE = os.path.dirname(os.path.abspath(__file__))
VM2_NAME = 'flask-vm2'  # must match vm1-launch-vm2-code.py

#
# Use Google Service Account - See https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.service_account.html#module-google.oauth2.service_account
#
credentials_path = os.path.join(HERE, 'service-credentials.json')
credentials = service_account.Credentials.from_service_account_file(filename=credentials_path)
project = os.getenv('GOOGLE_CLOUD_PROJECT') or credentials.project_id
service = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)


def read_file(*path):
    with open(os.path.join(HERE, *path)) as f:
        return f.read()


def wait_for_zone_operation(compute, project, zone, operation):
    while True:
        result = compute.zoneOperations().wait(
            project=project, zone=zone, operation=operation).execute()
        if result['status'] == 'DONE':
            if 'error' in result:
                raise RuntimeError(result['error'])
            return result


def create_vm1(compute, project, zone, name, machine_type):
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
            'items': [
                {'key': 'startup-script', 'value': read_file('vm1-startup-script.sh')},
                {'key': 'vm1-launch-vm2-code', 'value': read_file('vm1-launch-vm2-code.py')},
                {'key': 'vm2-startup-script', 'value': read_file('..', 'part1', 'startup-script.sh')},
                {'key': 'service-credentials', 'value': read_file('service-credentials.json')},
                {'key': 'project', 'value': project},
            ],
        },
    }

    try:
        operation = compute.instances().insert(project=project, zone=zone, body=config).execute()
    except HttpError as e:
        if e.resp.status == 409:
            print(f"Instance {name} already exists, reusing it")
            return
        raise
    wait_for_zone_operation(compute, project, zone, operation['name'])
    print(f"Created VM-1 ({name})")


def wait_for_vm2(compute, project, zone, timeout):
    print(f"Waiting for VM-1 to create VM-2 ({VM2_NAME}); this takes a few minutes...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            instance = compute.instances().get(project=project, zone=zone, instance=VM2_NAME).execute()
            if 'allow-5000' in instance.get('tags', {}).get('items', []):
                return instance['networkInterfaces'][0]['accessConfigs'][0]['natIP']
        except HttpError as e:
            if e.resp.status != 404:
                raise
        time.sleep(15)
    return None


def main():
    parser = argparse.ArgumentParser(description='Create a VM that creates the flask VM')
    parser.add_argument('--zone', default='us-west1-b')
    parser.add_argument('--name', default='vm1-launcher')
    parser.add_argument('--machine-type', default='f1-micro')
    parser.add_argument('--timeout', type=int, default=900, help='seconds to wait for VM-2')
    args = parser.parse_args()

    create_vm1(service, project, args.zone, args.name, args.machine_type)

    ip = wait_for_vm2(service, project, args.zone, args.timeout)
    if ip is None:
        print(f"VM-2 did not appear within {args.timeout} seconds. SSH to {args.name} "
              "and check /var/log/vm1-launch-vm2.log and /var/log/syslog")
        return
    print()
    print("VM-2 is up. The Flask application will be available at "
          "(allow a few minutes for its startup script to finish):")
    print()
    print(f"    http://{ip}:5000")


if __name__ == '__main__':
    main()
