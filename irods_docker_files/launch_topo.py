#!/usr/bin/python

from __future__ import print_function

import argparse
import subprocess
import json
import sys
import time
import ci_utilities
import docker_cmd_builder

from subprocess import Popen, PIPE
from multiprocessing import Pool
from docker_cmd_builder import DockerCommandsBuilder

def get_network_name(base_os, build_id):
    network_name = base_os + '_topo_net_' + build_id
    return network_name

def get_test_name_prefix(base_os, prefix):
    test_name_prefix = base_os + '-' + prefix

def connect_to_network(machine_name, alias_name, network_name):
    network_cmd = ['docker', 'network', 'connect', '--alias', alias_name, network_name, machine_name]
    proc = Popen(network_cmd, stdout=PIPE, stderr=PIPE)
    _out, _err = proc.communicate()

def get_docker_cmd(alias_name, test_type, exec_cmd, stop_cmd, container_name, network_name):
    docker_cmd = {
                  'alias_name': alias_name,
                  'test_type': test_type,
                  'exec_cmd': exec_cmd,
                  'stop_cmd': stop_cmd,
                  'container_name': container_name,
                  'network_name': network_name
                 }
    return docker_cmd

def is_container_running(container_name):
    _running = False
    state_cmd = ['docker', 'inspect', '-f', '{{.State.Running}}', container_name]
    while not _running:
        state_proc = Popen(state_cmd, stdout=PIPE, stderr=PIPE)
        _sout, _serr = state_proc.communicate()
        if 'true' in _sout:
            _running = True
        time.sleep(1)
    return _running

def run_command_in_container(exec_cmd, stop_cmd, container_name, network_name, alias_name, machine_list):
    _running = is_container_running(container_name)
    if _running:
        connect_to_network(container_name, alias_name, network_name)

    exec_proc = Popen(exec_cmd, stdout=PIPE, stderr=PIPE)
    _out, _err = exec_proc.communicate()
    _rc = exec_proc.returncode
    if _rc != 0:
        print('output from exec_proc...')
        print('stdout:[' + str(_out) + ']')
        print('stderr:[' + str(_err) + ']')
        print('return code:[' + str(_rc) + ']')

    stop_proc = Popen(stop_cmd, stdout=PIPE, stderr=PIPE)
    return _rc

def install_irods(build_tag, base_image, install_database):
    docker_cmd =  ['docker build -t {0} --build-arg base_image={1} --build-arg arg_install_database={2} -f Dockerfile.topo .'.format(build_tag, base_image, install_database)]
    run_build = subprocess.check_call(docker_cmd, shell = True)

def build_topo_containers(cmd_line_args):
    base_image = ci_utilities.get_base_image(cmd_line_args.platform_target, cmd_line_args.build_id)
    provider_tag = ci_utilities.get_build_tag(cmd_line_args.platform_target, 'topo_provider', cmd_line_args.build_id)
    install_irods(provider_tag, base_image, 'True')
    consumer_tag_list = []
    machine_list = []
    for x in range(cmd_line_args.consumers):
        consumer_id = x + 1
        stage = 'topo_consumer_' + str(consumer_id)
        consumer_tag = ci_utilities.get_build_tag(cmd_line_args.platform_target, stage, cmd_line_args.build_id)
        install_irods(consumer_tag, base_image, 'False')
        consumer_tag_list.append(consumer_tag)
        consumer_name = cmd_line_args.platform_target + '-' + cmd_line_args.test_name_prefix + '-consumer-' + str(consumer_id)
        machine_list.append(consumer_name)

    network_name = get_network_name(cmd_line_args.platform_target, cmd_line_args.build_id)
    ci_utilities.create_network(network_name)
    create_topology(cmd_line_args, provider_tag, consumer_tag_list, machine_list, network_name)

def create_topology(cmd_line_args, provider_tag, consumer_tag_list, machine_list, network_name):
    docker_run_list = []
    docker_cmds_list = []
    build_mount = cmd_line_args.irods_build_dir + ':/irods_build'
    results_mount = cmd_line_args.output_directory + ':/irods_test_env'
    upgrade_mount = None
    run_mount = None
    externals_mount = None
    mysql_mount = None
    provider_name = cmd_line_args.platform_target + '-' + cmd_line_args.test_name_prefix + '-provider'
    print(network_name)
    machine_list.append(provider_name)

    cmdsBuilder = DockerCommandsBuilder()
    cmdsBuilder.core_constructor(provider_name, build_mount, upgrade_mount, results_mount, run_mount, externals_mount, mysql_mount, provider_tag, 'setup_topo.py', cmd_line_args.database_type, cmd_line_args.specific_test, cmd_line_args.test_type, False, True, None)
    cmdsBuilder.set_machine_list(machine_list)
    provider_run_cmd = cmdsBuilder.build_run_cmd()
    docker_run_list.append(provider_run_cmd)
    provider_exec_cmd = cmdsBuilder.build_exec_cmd()
    provider_stop_cmd = cmdsBuilder.build_stop_cmd()
    print(provider_run_cmd)
    print(provider_exec_cmd)
    docker_cmd = get_docker_cmd('icat.example.org', cmd_line_args.test_type, provider_exec_cmd, provider_stop_cmd, provider_name, network_name)
    docker_cmds_list.append(docker_cmd)
    
    for i, consumer_tag in enumerate(consumer_tag_list):
        consumer_name = machine_list[i]
        resource_name = 'resource' + str(i+1) + '.example.org'
        cmdsBuilder.set_machine_name(consumer_name)
        cmdsBuilder.set_is_provider(False)
        cmdsBuilder.set_hostname(resource_name)
        cmdsBuilder.set_image_name(consumer_tag)
        consumer_run_cmd = cmdsBuilder.build_run_cmd()
        docker_run_list.append(consumer_run_cmd)
        consumer_exec_cmd = cmdsBuilder.build_exec_cmd()
        
        print(consumer_run_cmd)
        print(consumer_exec_cmd)
        consumer_stop_cmd = cmdsBuilder.build_stop_cmd()
        docker_cmd = get_docker_cmd(resource_name, cmd_line_args.test_type, consumer_exec_cmd, consumer_stop_cmd, consumer_name, network_name)
        docker_cmds_list.append(docker_cmd)

    #enable_ssl_cmd = ['python', 'enable_ssl.py', '--machine_list', ' '.join(machine_list)]
    #print(enable_ssl_cmd)
    run_pool = Pool(processes=int(4))
    run_procs = [Popen(docker_cmd, stdout=PIPE, stderr=PIPE) for docker_cmd in docker_run_list]
    #proc = Popen(enable_ssl_cmd, stdout=PIPE, stderr=PIPE)
    #_ssl_out, _ssl_err = proc.communicate()
    #print(_ssl_out, _ssl_err)

    containers = [{'test_type': docker_cmd['test_type'],'alias_name':docker_cmd['alias_name'], 'proc': run_pool.apply_async(run_command_in_container, (docker_cmd['exec_cmd'], docker_cmd['stop_cmd'], docker_cmd['container_name'], docker_cmd['network_name'], docker_cmd['alias_name'], machine_list))} for docker_cmd in docker_cmds_list]
    container_error_codes = [{'test_type': c['test_type'], 'alias_name':c['alias_name'],'error_code': c['proc'].get()} for c in containers]
    print(container_error_codes)

    ci_utilities.delete_network(network_name)
    check_topo_state(machine_list, network_name, container_error_codes)

def check_topo_state(machine_list, network_name, container_error_codes):
    print("check_topo_state")

    failures = []
    for machine_name in machine_list:
        for ec in container_error_codes:
            if ec['error_code'] != 0 and ec['alias_name'] == 'icat.example.org' and ec['test_type'] == 'topology_icat':
                failures.append(ec['alias_name'])
    
    if len(failures) > 0:
        sys.exit(1)

    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description='Run tests in os-containers')
    parser.add_argument('-p', '--platform_target', type=str, required=True)
    parser.add_argument('-b', '--build_id', type=str, required=True)
    parser.add_argument('--irods_build_dir', type=str, required=True)
    parser.add_argument('--test_name_prefix', type=str)
    parser.add_argument('--test_type', type=str, required=False, choices=['standalone_icat', 'topology_icat', 'topology_resource', 'federation'])
    parser.add_argument('--specific_test', type=str)
    parser.add_argument('--consumers', type=int, default=3, help='number of consumers')
    parser.add_argument('--providers', type=int, default=1, help='number of providers')
    parser.add_argument('--database_type', default='postgres', help='database type', required=True)
    parser.add_argument('-o', '--output_directory', type=str, required=False)
    
    args = parser.parse_args()

    print('specific_test ', args.specific_test)
    print('test_type ' , args.test_type)

    build_topo_containers(args)

if __name__ == '__main__':
    main()

