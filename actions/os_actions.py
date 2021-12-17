#!/usr/bin/env python3
#
# Copyright 2021 Canonical Ltd
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

import os
import sys

sys.path.append('hooks/')

import charmhelpers.contrib.openstack.deferred_events as deferred_events
import charmhelpers.contrib.openstack.utils as os_utils
import charmhelpers.contrib.openstack.neutron as neutron

from charmhelpers.contrib.openstack import context as os_context
from charmhelpers.core.hookenv import (
    action_get,
    action_fail,
    config,
    DEBUG,
    WARNING,
    function_set,
    function_fail,
    log,
    status_get,
    status_set,
    WORKLOAD_STATES,
)
from charmhelpers.core.host import (
    service_pause,
    service_resume,
)

import neutron_ovs_hooks
from neutron_ovs_utils import (
    assess_status,
    pause_unit_helper,
    resume_unit_helper,
    register_configs,
    use_fqdn_hint,
)

UNIT_REMOVED_MSG = 'Neutron agents were removed from the cloud'


def _get_agents_binaries():
    """Get valid agents binary services denpending on the charm config
    for enable-local-dhcp-and-metadata.

    :return: List of agents binary
    :rtype: [str]
    """
    agents_binaries = ["neutron-openvswitch-agent", "neutron-l3-agent"]
    if config("enable-local-dhcp-and-metadata"):
        agents_binaries.extend(
            ["neutron-metadata-agent", "neutron-dhcp-agent"]
        )

    return agents_binaries


def _get_agents(neutron_client):
    """Get agents from the unit filtering by expected agents binaries.
    Agents may depend on the enable-local-dhcp-and-metadata and if the
    unit was submited to OVN migration.

    :param neutron_client: neutron client
    :type neutron_client: neutronclient.v2_0.client.Client
    :return: List of agents able to be enable/disabe or removed by the unit
    :rtype: [Dict]
    """
    host_info = os_context.HostInfoContext(use_fqdn_hint_cb=use_fqdn_hint)()
    if host_info.get('use_fqdn_hint'):
        host_name = host_info.get('host_fqdn')
    else:
        host_name = host_info.get('host')

    agents = neutron.get_network_agents_on_host(host_name, neutron_client)
    if not agents:
        log("No agents registered", WARNING)
    agents_binaries = _get_agents_binaries()
    return [agent for agent in agents if agent['binary'] in agents_binaries]


def _set_agents(state):
    """Set all agents in the current unit to enable or disable state.
    Agents should be disabled before removing.

    :param state: State of the agent service
    :type state: Boolean
    """
    neutron_client = neutron.get_neutron()
    agents = _get_agents(neutron_client)
    for agent in agents:
        neutron_client.update_agent(
            agent['id'],
            {'agent': {'admin_state_up': state}}
        )
    log('Set neutron agents to admin_state_up: {}'.format(state))


def disable(args):
    """Disable all agents on this unit

    :param args: Unused
    """
    _set_agents(False)


def enable(args):
    """Enable all agents on this unit

    :param args: Unused
    """
    _set_agents(True)


def pause(args):
    """Pause the neutron-openvswitch services.
    @raises Exception should the service fail to stop.
    """
    pause_unit_helper(register_configs(),
                      exclude_services=['openvswitch-switch'])


def resume(args):
    """Resume the neutron-openvswitch services.
    @raises Exception should the service fail to start."""
    resume_unit_helper(register_configs(),
                       exclude_services=['openvswitch-switch'])


def register_to_cloud(args):
    """ This action reverts `remove-from-cloud` action.
    It starts neutron agents which will trigger its re-registration
    in the cloud.

    :param args: Unused
    """
    log("Starting neutron agents", DEBUG)
    agents_binaries = _get_agents_binaries()

    for binary in agents_binaries:
        service_resume(binary)

    current_status = status_get()
    if current_status[0] == WORKLOAD_STATES.BLOCKED.value and \
            current_status[1] == UNIT_REMOVED_MSG:
        status_set(WORKLOAD_STATES.ACTIVE, 'Unit is ready')

    function_set({
        'command': 'openstack network agent list',
        'message': 'Neutron agents started. Use the openstack command'
                   'to verify that agents are registered.'
    })


def remove_from_cloud(args):
    """This action is preparation for clean removal of neutron-openvswitch
    unit from juju model. It should be used also before removing
    nova-compute unit

    :param args: Unused
    """
    log("Stopping neutron-openvswitch service", DEBUG)
    neutron_client = neutron.get_neutron()
    agents = _get_agents(neutron_client)
    for agent in agents:
        if agent['admin_state_up']:
            function_fail(
                "Consider disabling neutron agents before deletion"
            )
        service_pause(agent['binary'])
        neutron_client.delete_agent(agent['id'])
    log("Deleted neutron agents", DEBUG)
    status_set(WORKLOAD_STATES.BLOCKED, UNIT_REMOVED_MSG)
    function_set({'message': UNIT_REMOVED_MSG})


def restart(args):
    """Restart services.

    :param args: Unused
    :type args: List[str]
    """
    deferred_only = action_get("deferred-only")
    services = action_get("services").split()
    # Check input
    if deferred_only and services:
        action_fail("Cannot set deferred-only and services")
        return
    if not (deferred_only or services):
        action_fail("Please specify deferred-only or services")
        return
    if action_get('run-hooks'):
        _run_deferred_hooks()
    if deferred_only:
        os_utils.restart_services_action(deferred_only=True)
    else:
        os_utils.restart_services_action(services=services)
    assess_status(register_configs())


def _run_deferred_hooks():
    """Run supported deferred hooks as needed.

    Run supported deferred hooks as needed. If support for deferring a new
    hook is added to the charm then this method will need updating.
    """
    if not deferred_events.is_restart_permitted():
        deferred_hooks = deferred_events.get_deferred_hooks()
        if deferred_hooks and 'config-changed' in deferred_hooks:
            neutron_ovs_hooks.config_changed(check_deferred_restarts=False)
            deferred_events.clear_deferred_hook('config-changed')


def run_deferred_hooks(args):
    """Run deferred hooks.

    :param args: Unused
    :type args: List[str]
    """
    _run_deferred_hooks()
    os_utils.restart_services_action(deferred_only=True)
    assess_status(register_configs())


def show_deferred_events(args):
    """Show the deferred events.

    :param args: Unused
    :type args: List[str]
    """
    os_utils.show_deferred_events_action_helper()


# A dictionary of all the defined actions to callables (which take
# parsed arguments).
ACTIONS = {
    "disable": disable,
    "enable": enable,
    "pause": pause,
    "resume": resume,
    "register-to-cloud": register_to_cloud,
    "remove-from-cloud": remove_from_cloud,
    "restart-services": restart,
    "show-deferred-events": show_deferred_events,
    "run-deferred-hooks": run_deferred_hooks,
}


def main(args):
    action_name = os.path.basename(args[0])
    try:
        action = ACTIONS[action_name]
    except KeyError:
        s = "Action {} undefined".format(action_name)
        action_fail(s)
        return s
    else:
        try:
            action(args)
        except Exception as e:
            action_fail("Action {} failed: {}".format(action_name, str(e)))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
