#!/usr/bin/python

from __future__ import print_function

import argparse
import subprocess
import json
import sys
import time
import ci_utilities

from subprocess import Popen, PIPE
from multiprocessing import Pool
from docker_cmd_builder import DockerCommandsBuilder

def get_build_tag(base_os, stage, build_id):
    build_tag = base_os + '-' + stage + ':' + build_id
    return build_tag

def get_network_name(base_os, build_id):
    network_name = base_os + '_federation_net_' + build_id
    return network_name

def get_base_image(base_os, build_id):
    base_image = base_os + ':' + build_id
    return base_image

def get_test_name_prefix(base_os, prefix):
    test_name_prefix = base_os + '-' + prefix

def connect_to_network(machine_name, alias_name, network_name):
    network_cmd = ['docker', 'network', 'connect', '--alias', alias_name, network_name, machine_name]
    proc = Popen(network_cmd, stdout=PIPE, stderr=PIPE)
    _out, _err = proc.communicate()

def get_docker_cmd(zone, run_cmd, exec_cmd, stop_cmd, container_name, network_name, remote_zone, test_type, test_name):
    docker_cmd = {'alias_name': zone,
                  'run_cmd': run_cmd,
                  'exec_cmd': exec_cmd,
                  'stop_cmd': stop_cmd,
                  'container_name': container_name,
                  'network_name' : network_name,
                  'remote_zone': remote_zone,
                  'test_type': test_type,
                  'test_name': test_name
                 }
    return docker_cmd

def create_federation_args(remote_zone):
    remote_version_cmd = ['docker', 'exec', remote_zone, 'python', 'get_irods_version.py']
    remote_irods_version = None
    while remote_irods_version == None:
        proc = subprocess.Popen(remote_version_cmd, stdout = PIPE, stderr = PIPE)
        _out, _err = proc.communicate()
        if _out is not None or _out != 'None':
            remote_irods_version = _out
        time.sleep(1)

    irods_version = remote_irods_version.split('\n')[0].split('(')[1].split(')')[0].replace(', ','.')
    federation_args = ' '.join([irods_version, 'tempZone', 'icat.tempZone.example.org'])
    return federation_args

def run_command_in_container(run_cmd, exec_cmd, stop_cmd, container_name, network_name, alias_name, remote_zone, test_type, test_name):
    # the docker run command (stand up a container)
    run_proc = Popen(run_cmd, stdout=PIPE, stderr=PIPE)
    _out, _err = run_proc.communicate()
    _running = False
    state_cmd = ['docker', 'inspect', '-f', '{{.State.Running}}', container_name]
    while not _running:
        state_proc = Popen(state_cmd, stdout=PIPE, stderr=PIPE)
        _sout, _serr = state_proc.communicate()
        if 'true' in _sout:
            _running = True
        time.sleep(1)

    connect_to_network(container_name, alias_name, network_name)
    # execute a command in the running container
    exec_proc = Popen(exec_cmd, stdout=PIPE, stderr=PIPE)
    _eout, _eerr = exec_proc.communicate()
    _rc = exec_proc.returncode
    if _rc == 0 and 'otherZone' in alias_name:
        federation_args = create_federation_args(remote_zone)
        print(federation_args)
        run_test_cmd = ['docker', 'exec', container_name, 'python', 'run_tests_in_zone.py', '--test_type', test_type, '--specific_test', test_name, '--federation_args', federation_args]
        print('run test cmd', run_test_cmd)
        run_test_proc = Popen(run_test_cmd, stdout=PIPE, stderr=PIPE)
        _eout, _eerr = run_test_proc.communicate()
        _rc = run_test_proc.returncode

    print('alias_name', alias_name, 'return code ', _rc)
    if _rc != 0:
        print('output from exec_proc...')
        print('stdout:[' + str(_eout) + ']')
        print('stderr:[' + str(_eerr) + ']')
        print('return code:[' + str(_rc) + ']')
    # stop the container
    stop_proc = Popen(stop_cmd, stdout=PIPE, stderr=PIPE)
    return _rc

def build_federation(build_tag, base_image, database_type):
    docker_cmd =  ['docker build -t {0} --build-arg base_image={1} --build-arg arg_database_type={2} -f Dockerfile.fed .'.format(build_tag, base_image, database_type)]
    run_build = subprocess.check_call(docker_cmd, shell = True)

def build_zones(cmd_line_args):
    base_image = get_base_image(cmd_line_args.platform_target, cmd_line_args.build_id)
    federation_tag_list=[]
    for x in range(cmd_line_args.zones):
        zone_id = x + 1    
        stage = 'federation_zone_' + str(zone_id)
        federation_tag = get_build_tag(cmd_line_args.platform_target, stage, cmd_line_args.build_id)
        build_federation(federation_tag, base_image, cmd_line_args.database_type)
        federation_tag_list.append(federation_tag)

    network_name = get_network_name(cmd_line_args.platform_target, cmd_line_args.build_id)

    ci_utilities.create_network(network_name)
    create_federation(federation_tag_list, network_name, cmd_line_args)

def create_federation(federation_tag_list, network_name, cmd_line_args):
    docker_cmds_list = []
    machine_list = []
    build_mount = cmd_line_args.irods_build_dir + ':/irods_build'
    results_mount = cmd_line_args.output_directory + ':/irods_test_env' 
    upgrade_mount = None
    run_mount = None
    externals_mount = None
    mysql_mount = '/projects/irods/vsphere-testing/externals/mysql-connector-odbc-5.3.7-linux-ubuntu16.04-x86-64bit.tar.gz:/projects/irods/vsphere-testing/externals/mysql-connector-odbc-5.3.7-linux-ubuntu16.04-x86-64bit.tar.gz'

    zone1 = 'tempZone'
    zone2 = 'otherZone'
    platform_target = cmd_line_args.platform_target
    test_name_prefix = cmd_line_args.test_name_prefix
    for i, federation_tag in enumerate(federation_tag_list, start=1):
        zone_name = zone2
        federated_zone_name = 'icat.otherZone.example.org'
        remote_federated_zone = platform_target + '-' + test_name_prefix + '-' + zone1
        if i == 1:
            zone_name = zone1
            federated_zone_name = 'icat.tempZone.example.org'
            remote_federated_zone = platform_target + '-' + test_name_prefix + '-' + zone2

        federation_name = platform_target + '-' + test_name_prefix + '-' + zone_name
        machine_list.append(federation_name)

        cmdsBuilder = DockerCommandsBuilder()
        cmdsBuilder.core_constructor(federation_name, build_mount, upgrade_mount, results_mount, run_mount, externals_mount, mysql_mount, federation_tag, 'setup_fed_and_test.py', cmd_line_args.database_type, cmd_line_args.specific_test, cmd_line_args.test_type, False, True, None)
        cmdsBuilder.set_hostname(federated_zone_name)
        cmdsBuilder.set_zone_name(zone_name)
        cmdsBuilder.set_remote_zone(remote_federated_zone)

        federation_run_cmd = cmdsBuilder.build_run_cmd()
        federation_exec_cmd = cmdsBuilder.build_exec_cmd()
        federation_stop_cmd = cmdsBuilder.build_stop_cmd()

        print(federation_run_cmd)
        print(federation_exec_cmd)
        print(federation_stop_cmd)

        docker_cmd = get_docker_cmd(federated_zone_name, federation_run_cmd, federation_exec_cmd, federation_stop_cmd, federation_name, network_name, remote_federated_zone, cmd_line_args.test_type, cmd_line_args.specific_test) 
        docker_cmds_list.append(docker_cmd)

    run_pool = Pool(processes=int(2))

    containers = [{'alias_name': docker_cmd['alias_name'], 'proc': run_pool.apply_async(run_command_in_container, (docker_cmd['run_cmd'], docker_cmd['exec_cmd'], docker_cmd['stop_cmd'], docker_cmd['container_name'], docker_cmd['network_name'], docker_cmd['alias_name'], docker_cmd['remote_zone'], docker_cmd['test_type'], docker_cmd['test_name']))} for docker_cmd in docker_cmds_list]
    container_error_codes = [{'alias_name': c['alias_name'], 'error_code': c['proc'].get()} for c in containers]
    check_fed_state(machine_list, network_name, container_error_codes)

def check_fed_state(machine_list, network_name, container_error_codes):
    failures = []
    for machine_name in machine_list:
        for ec in container_error_codes:
            if ec['error_code'] != 0 and 'otherZone' in ec['alias_name']:
                failures.append(ec['alias_name'])

    ci_utilities.delete_network(network_name)

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
    parser.add_argument('--zones', type=int, default=2, help='number of zones in the federation')
    parser.add_argument('--database_type', default='postgres', help='database type', required=True)
    parser.add_argument('-o', '--output_directory', type=str, required=False)
    
    args = parser.parse_args()

    print('specific_test ', args.specific_test)
    print('test_type ' , args.test_type)

    build_zones(args)

        
if __name__ == '__main__':
    main()

