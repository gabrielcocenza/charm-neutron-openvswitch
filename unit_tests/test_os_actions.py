# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import charmhelpers

from unittest import mock
from unittest.mock import patch, call

from test_utils import CharmTestCase

with patch('neutron_ovs_utils.register_configs') as configs:
    configs.return_value = 'test-config'
    import os_actions as actions


ENABLE_AGENTS = [
    {
        "id": "810c64f7-0e17-456c-aae9-8c99dc74f190",
        "agent_type": "Open vSwitch agent",
        "binary": "neutron-openvswitch-agent",
        "host": "juju-784de1-ovs-13.project.serverstack",
        "admin_state_up": True,
    },
    {
        "id": "03869b4a-6f5c-4c8d-b13e-e7e73267161d",
        "agent_type": "DHCP agent",
        "binary": "neutron-dhcp-agent",
        "host": "juju-784de1-ovs-13.project.serverstack",
        "admin_state_up": True,
    },
]

DISABLE_AGENTS = [
    {
        "id": "db53a05c-a357-49ee-81aa-3f619fe2af8f",
        "agent_type": "Metadata agent",
        "binary": "neutron-metadata-agent",
        "host": "juju-784de1-ovs-13.project.serverstack",
        "admin_state_up": False,
    },
    {
        "id": "f5bc7b8e-0013-4510-abb4-c687304fb05f",
        "agent_type": "L3 agent",
        "binary": "neutron-l3-agent",
        "host": "juju-784de1-ovs-13.project.serverstack",
        "admin_state_up": False,
    }
]

SERVICE_AGENTS = [
    "neutron-openvswitch-agent",
    "neutron-dhcp-agent",
    "neutron-metadata-agent",
    "neutron-l3-agent",
]


class DisableTestCase(CharmTestCase):

    def setUp(self):
        super(DisableTestCase, self).setUp(
            actions, ["_set_agents"])

    def test_disable_agents(self):
        actions.disable([])
        self._set_agents.assert_called_once_with(False)


class EnableTestCase(CharmTestCase):

    def setUp(self):
        super(EnableTestCase, self).setUp(
            actions, ["_set_agents"])

    def test_disable_agents(self):
        actions.enable([])
        self._set_agents.assert_called_once_with(True)


class RegisterToCloudTestCase(CharmTestCase):
    def setUp(self):
        super(RegisterToCloudTestCase, self).setUp(
            actions,
            [
                "_get_agents_binaries",
                "service_resume",
                "status_get",
                "status_set",
                "function_set",
            ],
        )

    def test_register_agents(self):
        """Test that action will reset unit state if the current state was
        set explicitly by 'remove-from-cloud' action and resume services"""
        self._get_agents_binaries.return_value = SERVICE_AGENTS
        self.status_get.return_value = (
            actions.WORKLOAD_STATES.BLOCKED.value,
            actions.UNIT_REMOVED_MSG,
        )
        actions.register_to_cloud([])
        for service in SERVICE_AGENTS:
            self.service_resume.assert_any_call(service)
        self.service_resume.call_count == len(SERVICE_AGENTS)
        self.status_set.assert_called_once_with(
            actions.WORKLOAD_STATES.ACTIVE, "Unit is ready"
        )
        self.function_set.assert_called_once()

    def test_dont_reset_unit_status(self):
        """Test that action won't reset unit state if the current state was not
        set explicitly by 'remove-from-cloud' action"""
        self.status_get.return_value = (
            actions.WORKLOAD_STATES.BLOCKED.value,
            'Unrelated reason for blocked status',
        )
        actions.register_to_cloud([])
        self.status_set.assert_not_called()


class RemoveFromCloudTestCase(CharmTestCase):

    def setUp(self):
        super(RemoveFromCloudTestCase, self).setUp(
            actions,
            [
                "service_pause",
                "status_set",
                "function_set",
                "config",
                "function_fail"
            ]
        )

    @patch.object(
        charmhelpers.contrib.openstack.neutron, 'get_network_agents_on_host'
    )
    @patch.object(
        charmhelpers.contrib.openstack.neutron, 'get_neutron'
    )
    def test_remove_agents(self, neutron_client, agents):
        """test that desabled agents are removed"""
        expected_calls = [call()]
        agents.return_value = DISABLE_AGENTS
        actions.remove_from_cloud([])
        for agent in DISABLE_AGENTS:
            self.service_pause.assert_any_call(agent['binary'])
            expected_calls.append(call().delete_agent(agent['id']))

        self.assertEqual(neutron_client.mock_calls, expected_calls)
        self.status_set.assert_called_once_with(
            actions.WORKLOAD_STATES.BLOCKED, actions.UNIT_REMOVED_MSG
        )
        self.function_set.assert_called_once()

    @patch.object(
        charmhelpers.contrib.openstack.neutron, 'get_network_agents_on_host'
    )
    @patch.object(charmhelpers.contrib.openstack.neutron, 'get_neutron')
    def test_remove_agents_fails(self, neutron_client, agents):
        """Test that enabled agents run function_fail."""
        agents.return_value = ENABLE_AGENTS
        actions.remove_from_cloud([])
        msg = "Consider disabling neutron agents before deletion"
        self.function_fail.assert_called_with(msg)


class PauseTestCase(CharmTestCase):

    def setUp(self):
        super(PauseTestCase, self).setUp(
            actions, ["pause_unit_helper"])

    def test_pauses_services(self):
        actions.pause([])
        self.pause_unit_helper.assert_called_once_with(
            'test-config', exclude_services=['openvswitch-switch'])


class ResumeTestCase(CharmTestCase):

    def setUp(self):
        super(ResumeTestCase, self).setUp(
            actions, ["resume_unit_helper"])

    def test_pauses_services(self):
        actions.resume([])
        self.resume_unit_helper.assert_called_once_with(
            'test-config', exclude_services=['openvswitch-switch'])


class MainTestCase(CharmTestCase):

    def setUp(self):
        super(MainTestCase, self).setUp(actions, ["action_fail"])

    def test_invokes_action(self):
        dummy_calls = []

        def dummy_action(args):
            dummy_calls.append(True)

        with mock.patch.dict(actions.ACTIONS, {"foo": dummy_action}):
            actions.main(["foo"])
        self.assertEqual(dummy_calls, [True])

    def test_unknown_action(self):
        """Unknown actions aren't a traceback."""
        exit_string = actions.main(["foo"])
        self.assertEqual("Action foo undefined", exit_string)

    def test_failing_action(self):
        """Actions which traceback trigger action_fail() calls."""
        dummy_calls = []

        self.action_fail.side_effect = dummy_calls.append

        def dummy_action(args):
            raise ValueError("uh oh")

        with mock.patch.dict(actions.ACTIONS, {"foo": dummy_action}):
            actions.main(["foo"])
        self.assertEqual(dummy_calls, ["Action foo failed: uh oh"])
