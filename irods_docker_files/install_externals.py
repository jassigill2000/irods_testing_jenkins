#!/usr/bin/python
from __future__ import print_function

import irods_python_ci_utilities

def get_externals_directory():
    return '/irods_externals' + irods_python_ci_utilities.get_irods_platform_string()

def install_externals():
    irods_python_ci_utilities.install_os_packages([
         "irods-externals-avropre190cpp17-0",
         "irods-externals-boost1.67.0-0",
         "irods-externals-catch22.3.0-0",
         "irods-externals-clang-runtime6.0-0",
         "irods-externals-clang6.0-0",
         "irods-externals-cppzmq4.2.3-0",
         "irods-externals-jansson2.7-0",
         "irods-externals-json3.1.2-0",
         "irods-externals-libarchive3.3.2-1",
         "irods-externals-spdlog0.17.0-0",
         "irods-externals-zeromq4-14.1.6-0"])

def main():
    install_externals()

if __name__ == '__main__':
    main()
