import os
import json

from threading import Thread
from lib import ssh_lib


class TerraformController:
    def __init__(self, tf_configurator, debug=False):
        self.cloud_name = tf_configurator.cloud_name
        self.tf_configurator = tf_configurator
        self.debug = debug

        self.debug_sufix = ''
        if not debug:
            self.debug_sufix = '1> /dev/null'

    def create_infra(self):
        cmd_output = os.system(f'terraform init {self.debug_sufix}')
        if cmd_output:
            print('terraform init command failed, check configuration')
            exit(1)

        cmd_output = os.system(f'terraform apply -auto-approve {self.debug_sufix}')
        if cmd_output:
            print('terraform apply command failed, check configuration')
            exit(1)

        print('Waiting for the ssh server in the instance(s) to be ready...')
        self.wait_for_all_instances_ssh_up()

    def wait_for_all_instances_ssh_up(self):
        seconds_to_wait = 120
        instances = self.get_instances()

        threads = []
        for inst in instances.values():
            t = Thread(target=ssh_lib.wait_for_host_ssh_up,
                       args=[inst['public_dns'], seconds_to_wait])
            t.start()
            threads.append(t)

        [t.join() for t in threads]

    def get_instances(self):
        output = os.popen('terraform show --json')
        output = output.read()
        print(output)
        json_output = json.loads(output)

        resources = json_output['values']['root_module']['resources']

        if self.cloud_name == 'aws':
            instances_info = self.get_instances_aws(resources)
        elif self.cloud_name == 'azure':
            instances_info = self.get_instances_azure(resources)
        else:
            raise Exception(f'Unsupported cloud provider: {self.cloud_name}')

        return instances_info

    def get_instances_aws(self, resources):
        instances_info = {}

        # 'address' key corresponds to the tf resource id
        for resource in resources:
            if resource['type'] != 'aws_instance':
                continue

            ami_name = resource['values']['ami']
            username = self.tf_configurator.get_aws_username_by_ami_name(ami_name)

            instances_info[resource['address']] = {
                'name': resource['name'],
                'instance_id': resource['values']['id'],
                'public_ip': resource['values']['public_ip'],
                'public_dns': resource['values']['public_dns'],
                'availability_zone': resource['values']['availability_zone'],
                'ami': ami_name,
                'username': username,
            }

        return instances_info

    def get_instances_azure(self, resources):
        instances_info = {}

        for resource in resources:
            if resource['type'] != 'azurerm_linux_virtual_machine':
                continue

            public_dns = '{}.{}.cloudapp.azure.com'.format(resource['values']['computer_name'],
                                                           resource['values']['location'])

            image = self._get_azure_image_data_from_resource(resource)

            instances_info[resource['address']] = {
                'name': resource['name'],
                'instance_id': resource['values']['id'],
                'public_ip': resource['values']['public_ip_address'],
                'public_dns': public_dns,
                'location': resource['values']['location'],
                'image': image,
                'username': resource['values']['admin_username'],
            }

        return instances_info

    def _get_azure_image_data_from_resource(self, resource):
        if 'source_image_reference' in resource['values']:
            return resource['values']['source_image_reference']
        elif 'source_image_id' in resource['values']:
            return resource['values']['source_image_id']

    def destroy_resource(self, resource_id):
        cmd_output = os.system(f'terraform destroy -target={resource_id}')
        if cmd_output:
            raise Exception('terraform destroy specific resource command failed')

    def destroy_infra(self):
        cmd_output = os.system(f'terraform destroy -auto-approve {self.debug_sufix}')
        if cmd_output:
            raise Exception('terraform destroy command failed')
