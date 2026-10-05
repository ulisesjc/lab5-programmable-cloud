import argparse
import os
import time

import googleapiclient.discovery
import google.auth
from googleapiclient.errors import HttpError

NETWORK_TAG = 'allow-5000'

# The flask app is already installed on the image, so clones only need to start it
CLONE_STARTUP_SCRIPT = """#!/bin/bash
cd /opt/flask-app/flask-tutorial
export FLASK_APP=flaskr
nohup python3 -m flask run -h 0.0.0.0 > /var/log/flask.log 2>&1 &
"""


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


def create_snapshot(compute, project, zone, instance_name):
    snapshot_name = f'base-snapshot-{instance_name}'
    try:
        compute.snapshots().get(project=project, snapshot=snapshot_name).execute()
        print(f"Snapshot {snapshot_name} already exists")
        return snapshot_name
    except HttpError as e:
        if e.resp.status != 404:
            raise

    instance = compute.instances().get(project=project, zone=zone, instance=instance_name).execute()
    boot_disk = next(d for d in instance['disks'] if d.get('boot'))
    disk_name = boot_disk['source'].split('/')[-1]

    print(f"Creating snapshot {snapshot_name} of disk {disk_name}...")
    operation = compute.disks().createSnapshot(
        project=project, zone=zone, disk=disk_name, body={'name': snapshot_name}).execute()
    wait_for_zone_operation(compute, project, zone, operation['name'])
    print(f"Created snapshot {snapshot_name}")
    return snapshot_name


def create_image(compute, project, snapshot_name, instance_name):
    image_name = f'base-image-{instance_name}'
    try:
        compute.images().get(project=project, image=image_name).execute()
        print(f"Image {image_name} already exists")
        return image_name
    except HttpError as e:
        if e.resp.status != 404:
            raise

    print(f"Creating image {image_name} from snapshot {snapshot_name}...")
    body = {
        'name': image_name,
        'sourceSnapshot': f'global/snapshots/{snapshot_name}',
    }
    operation = compute.images().insert(project=project, body=body).execute()
    wait_for_global_operation(compute, project, operation['name'])
    print(f"Created image {image_name}")
    return image_name


def create_instance_from_image(compute, project, zone, name, machine_type, image_name):
    config = {
        'name': name,
        'machineType': f'zones/{zone}/machineTypes/{machine_type}',
        'disks': [{
            'boot': True,
            'autoDelete': True,
            'initializeParams': {'sourceImage': f'global/images/{image_name}'},
        }],
        'networkInterfaces': [{
            'network': 'global/networks/default',
            'accessConfigs': [{'type': 'ONE_TO_ONE_NAT', 'name': 'External NAT'}],
        }],
        'tags': {'items': [NETWORK_TAG]},
        'metadata': {
            'items': [{'key': 'startup-script', 'value': CLONE_STARTUP_SCRIPT}],
        },
    }
    operation = compute.instances().insert(project=project, zone=zone, body=config).execute()
    wait_for_zone_operation(compute, project, zone, operation['name'])


def get_external_ip(compute, project, zone, name):
    instance = compute.instances().get(project=project, zone=zone, instance=name).execute()
    return instance['networkInterfaces'][0]['accessConfigs'][0]['natIP']


def main():
    credentials, default_project = google.auth.default()

    parser = argparse.ArgumentParser(description='Clone the Part 1 VM via a snapshot and image')
    parser.add_argument('--project', default=default_project)
    parser.add_argument('--zone', default='us-west1-b')
    parser.add_argument('--instance', default='flask-vm', help='name of the Part 1 VM')
    parser.add_argument('--machine-type', default='f1-micro')
    parser.add_argument('--count', type=int, default=3)
    args = parser.parse_args()

    compute = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)

    snapshot_name = create_snapshot(compute, args.project, args.zone, args.instance)
    image_name = create_image(compute, args.project, snapshot_name, args.instance)

    timings = []
    for i in range(1, args.count + 1):
        name = f'{args.instance}-clone-{i}'
        print(f"Creating {name}...")
        start = time.time()
        create_instance_from_image(compute, args.project, args.zone, name, args.machine_type, image_name)
        elapsed = time.time() - start
        timings.append((name, elapsed))
        ip = get_external_ip(compute, args.project, args.zone, name)
        print(f"Created {name} in {elapsed:.2f} seconds - http://{ip}:5000")

    timing_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'TIMING.md')
    with open(timing_path, 'w') as f:
        f.write('# Instance creation times\n\n')
        f.write(f'Instances created from image `{image_name}` '
                f'(snapshot `{snapshot_name}`), machine type `{args.machine_type}`, '
                f'zone `{args.zone}`.\n\n')
        f.write('| Instance | Time (seconds) |\n')
        f.write('|----------|----------------|\n')
        for name, elapsed in timings:
            f.write(f'| {name} | {elapsed:.2f} |\n')
    print(f"Wrote timings to {timing_path}")


if __name__ == '__main__':
    main()
