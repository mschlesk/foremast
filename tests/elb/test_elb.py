#   Foremast - Pipeline Tooling
#
#   Copyright 2016 Gogo, LLC
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""Test ELB creation functions."""
from unittest import mock
import json

from foremast.elb.format_listeners import format_listeners, format_cert_name
from foremast.elb.splay_health import splay_health
from foremast.elb import SpinnakerELB


def test_elb_splay():
    """Splay should split Health Checks properly."""
    health = splay_health('HTTP:80/test')
    assert health.path == '/test'
    assert health.port == '80'
    assert health.proto == 'HTTP'
    assert health.target == 'HTTP:80/test'

    health = splay_health('TCP:8000/test')
    assert health.path == ''
    assert health.port == '8000'
    assert health.proto == 'TCP'
    assert health.target == 'TCP:8000'

    health = splay_health('HTTPS:8000/test')
    assert health.path == '/test'
    assert health.port == '8000'
    assert health.proto == 'HTTPS'
    assert health.target == 'HTTPS:8000/test'

    health = splay_health('HTTPS:80')
    assert health.path == '/healthcheck'
    assert health.port == '80'
    assert health.proto == 'HTTPS'
    assert health.target == 'HTTPS:80/healthcheck'


@mock.patch('foremast.elb.format_listeners.get_env_credential')
def test_elb_format_listeners(mock_creds):
    """Listeners should be formatted in list of dicts."""
    mock_creds.return_value = { 'accountId': '0100' }

    config = {
        'certificate': None,
        'i_port': 8080,
        'i_proto': 'HTTP',
        'lb_port': 80,
        'lb_proto': 'HTTP',
        'policies': None,
    }
    generated = [{
        'externalPort': 80,
        'externalProtocol': 'HTTP',
        'internalPort': 8080,
        'internalProtocol': 'HTTP',
        'sslCertificateId': None,
        'listenerPolicies': None,
    }]

    # check defaults
    assert generated == format_listeners(elb_settings=config)

    # 'ports' key should override old style definitions
    config['ports'] = [{'instance': 'HTTP:8000', 'loadbalancer': 'http:500'}]
    generated = [{
        'externalPort': 500,
        'externalProtocol': 'HTTP',
        'internalPort': 8000,
        'internalProtocol': 'HTTP',
        'sslCertificateId': None,
        'listenerPolicies': [],
    }]

    # check ports
    assert generated == format_listeners(elb_settings=config)

    config['ports'].append({
        'certificate': 'kerby',
        'instance': 'http:80',
        'loadbalancer': 'https:443',
    })
    generated.append({
        'externalPort': 443,
        'externalProtocol': 'HTTPS',
        'internalPort': 80,
        'internalProtocol': 'HTTP',
        'sslCertificateId': 'arn:aws:iam::0100:server-certificate/kerby',
        'listenerPolicies': [],
    })

    # check certificate
    assert generated == format_listeners(elb_settings=config)


def test_elb_format_cert_name():
    """Test the format_cert_name method"""
    assert None == format_cert_name()

    full_cert_name = 'arn:aws:123'
    assert full_cert_name == format_cert_name(certificate=full_cert_name)

    compiled_cert = 'arn:aws:iam::dev:server-certificate/mycert1'
    assert compiled_cert == format_cert_name(account='dev', certificate='mycert1')


@mock.patch.object(SpinnakerELB, 'add_listener_policy')
@mock.patch('foremast.elb.create_elb.check_task')
@mock.patch('foremast.elb.create_elb.post_task')
@mock.patch.object(SpinnakerELB, 'make_elb_json', return_value={})
@mock.patch('foremast.elb.create_elb.get_properties')
def test_elb_create_elb(mock_get_properties, mock_elb_json, mock_post_task, mock_check_task, mock_listener_policy):
    """Test SpinnakerELB create_elb method"""
    elb = SpinnakerELB(app='myapp', env='dev', region='us-east-1')
    elb.create_elb()
    mock_listener_policy.assert_called_with(mock_elb_json())


@mock.patch('foremast.elb.create_elb.get_vpc_id', return_value='vpc-100')
@mock.patch('foremast.elb.create_elb.format_listeners')
@mock.patch('foremast.elb.create_elb.get_subnets')
@mock.patch('foremast.elb.create_elb.get_properties')
def test_elb_make_elb_json(mock_get_properties, mock_get_subnets, mock_format_listeners, mock_vpc_id):
    """Test SpinnakerELB make_elbj_json method"""
    properties = {
        'elb': {
            'health': {
                'interval': 10,
                'timeout': 1,
                'threshold': 2,
                'unhealthy_threshold': 3,
            }
        },
        'security_group': {'elb_extras': []},
    }

    subnets = {'us-east-1': ['subnet-1']}
    listeners = []

    mock_get_properties.return_value = properties
    mock_get_subnets.return_value = subnets
    mock_format_listeners.return_value = listeners

    # internal elb
    elb = SpinnakerELB(app='myapp', env='dev', region='us-east-1')
    elb_str = elb.make_elb_json()
    assert isinstance(elb_str, str)
    elb_json = json.loads(elb_str)
    assert elb_json['job'][0]['isInternal']

    # external elb
    properties['elb'].update({'subnet_purpose': 'external'})
    elb = SpinnakerELB(app='myapp', env='dev', region='us-east-1')
    elb_json = json.loads(elb.make_elb_json())
    assert not elb_json['job'][0]['isInternal']


@mock.patch('foremast.elb.create_elb.boto3.session.Session')
@mock.patch('foremast.elb.create_elb.get_properties')
def test_elb_add_listener_policy(mock_get_properties, mock_boto3_session):

    json_data = {
       'job': [
            {
                'listeners': [
                    {
                        'externalPort': 80,
                        'listenerPolicies': ['policy_name']
                    },
                ],
            }
       ],
    }
    client = mock_boto3_session.return_value.client.return_value

    elb = SpinnakerELB(app='myapp', env='dev', region='us-east-1')
    elb.add_listener_policy(json.dumps(json_data))
    assert client.set_load_balancer_policies_of_listener.called

@mock.patch('foremast.elb.create_elb.boto3.session.Session')
@mock.patch('foremast.elb.create_elb.get_properties')
def test_elb_add_backend_policy(mock_get_properties, mock_boto3_session):

    json_data = {
       'job': [
            {
                'listeners': [
                    {
                        'internalPort': 80,
                        'backendPolicies': ['policy_name']
                    },
                ],
            }
       ],
    }
    client = mock_boto3_session.return_value.client.return_value

    elb = SpinnakerELB(app='myapp', env='dev', region='us-east-1')
    elb.add_backend_policy(json.dumps(json_data))
    assert client.set_load_balancer_policies_of_listener.called
