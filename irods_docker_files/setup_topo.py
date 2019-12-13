#!/usr/bin/python
from __future__ import print_function

import argparse
import os
import sys
import irods_python_ci_utilities
import subprocess
import shutil
import socket
import time
import ci_utilities
import enable_ssl
from subprocess import Popen, PIPE

def get_irods_packages_directory():
    return '/irods_build/' + irods_python_ci_utilities.get_irods_platform_string()

def check_ports_open(machine_name):
    print(machine_name)
    listen_cmd = ['nc', '-vz', machine_name, '1247']
    status = 'refused'
    while status == 'refused':
        proc = subprocess.Popen(listen_cmd, stdout = PIPE, stderr = PIPE)
        _out, _err = proc.communicate()
        print('_err ', _err)
        if 'open' in (_err):
            status = 'open'
        if not 'Connection refused' in (_err):
            status = 'open'
        time.sleep(1)
        print('status ', status)

    return status

def set_univmss():
    irods_directory = '/var/lib/irods'
    univmss_testing = os.path.join(irods_directory, 'msiExecCmd_bin', 'univMSSInterface.sh')
    if not os.path.exists(univmss_testing):
        univmss_template = os.path.join(irods_directory, 'msiExecCmd_bin', 'univMSSInterface.sh.template')
        with open(univmss_template) as f:
            univmss_contents = f.read().replace('template-','')
        with open(univmss_testing, 'w') as f:
            f.write(univmss_contents)
        os.chmod(univmss_testing, 0o544)

def setup_consumer():
    status = check_ports_open('icat.example.org')
    print("setup_consumer")
    if status == 'open':
        p = subprocess.check_call(['python /var/lib/irods/scripts/setup_irods.py < /irods_consumer.input'], shell=True)
        #enable_ssl.enable_ssl('consumer')

def setup_provider():
    p = subprocess.check_call(['python /var/lib/irods/scripts/setup_irods.py < /var/lib/irods/packaging/localhost_setup_postgres.input'], shell=True)
    
def run_tests(test_type, test_name):
    print("let's try to run tests")
    _rc, _out, _err = irods_python_ci_utilities.subprocess_get_output(['python run_tests_in_zone.py --test_type {0} --specific_test {1}'.format(test_type, test_name)], shell=True, check_rc=True)
    return _rc

def check_topo_state(machine_name):
    is_running = True
    while is_running:
        cmd = ['ping', '-W', '10', '-c', '1', machine_name]
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
        output, err = proc.communicate()
        _rc = proc.returncode
        if _rc != 0:
            gather_logs()
            sys.exit(_rc)

def gather_logs():
    output_directory = '/irods_test_env/{0}/{1}'.format(irods_python_ci_utilities.get_irods_platform_string(),socket.gethostname())
    irods_python_ci_utilities.gather_files_satisfying_predicate('/var/lib/irods/log', output_directory, lambda x: True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--is_provider', action='store_true', default=False)
    parser.add_argument('--consumer_name', type=str)
    parser.add_argument('--provider_name', type=str, required=False)
    parser.add_argument('-d', '--database_type', default='postgres', help='database type', required=True)
    parser.add_argument('--install_externals', action='store_true', default=False)
    parser.add_argument('--test_type', type=str)
    parser.add_argument('--test_name', type=str)
    parser.add_argument('--network_name', type=str, required=False)
    parser.add_argument('--alias_name', type=str, required=False)
    parser.add_argument('--consumer_list', type=str)

    args = parser.parse_args()
  
    distribution = irods_python_ci_utilities.get_distribution()
    ci_utilities.install_irods_packages(args.database_type, args.install_externals, get_irods_packages_directory(), is_provider = args.is_provider)

    if not args.is_provider:
        setup_consumer()
        if args.test_type == 'topology_resource' and args.alias_name == 'resource1.example.org':
            check_ports_open('icat.example.org')
            rc = run_tests(args.test_type, args.test_name)
            sys.exit(rc)
        else:
            set_univmss()
            check_ports_open('icat.example.org')
            check_topo_state('icat.example.org')
    else:
        ci_utilities.setup_irods(args.database_type)
        #enable_ssl.enable_ssl('provider')

        if args.test_type == 'topology_icat':
            status = check_ports_open('resource1.example.org')
            if status == 'open':
                rc = run_tests(args.test_type, args.test_name)
                sys.exit(rc)
        else:
            set_univmss()
            check_ports_open('resource1.example.org')
            check_topo_state('resource1.example.org')


if __name__ == '__main__':
    main()
