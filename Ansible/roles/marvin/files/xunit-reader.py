#!/usr/bin/env python
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
This script provides parsing of xunit xml files.

"""

import os
import argparse

import lxml.etree
from operator import itemgetter


def main():
    """
    Entry point for the parser

    """

    args = _generate_args()
    file_path_list = _generate_file_list(args)

    exit(parse_reports(file_path_list))


def _generate_args():
    parser = argparse.ArgumentParser(
        description='Command line utility for reading xunit xml files'
    )

    parser.add_argument(
        'path',
        metavar='/path/to/folder/containing/xunit-reports',
        type=str,
        help='A path to a folder containing xunit reports'
    )

    args = parser.parse_args()

    return vars(args)


def _generate_file_list(args):
    path = args.pop('path')
    file_path_list = []
    if path.endswith('.xml') and os.path.isfile(path):
        file_path_list.append(path)
    for (root, dirnames, filenames) in os.walk(path):
        for filename in filenames:
            if filename.endswith('.xml'):
                file_path_list.append(os.path.join(root, filename))

    return file_path_list


def parse_reports(file_path_list):
    print("")
    print("Test | Result | Time (s) | Test File")
    print("--- | --- | --- | ---")

    exit_code = 0

    tests = []
    for file_path in file_path_list:
        filename = file_path[file_path.find('test_'):].replace('.xml', '')
        data = lxml.etree.iterparse(file_path, tag='testcase')
        for event, elem in data:
            name = ''
            status = 'Success'
            time = ''
            if 'name' in elem.attrib:
                name = elem.attrib['name']
            if 'time' in elem.attrib:
                time = str(elem.attrib['time'])
            for children in elem.getchildren():
                if 'skipped' == children.tag:
                    status = 'Skipped'
                elif 'failure' == children.tag:
                    exit_code = 1
                    status = '`Failure`'
                elif 'error' == children.tag:
                    exit_code = 1
                    status = '`Error`'
            if status not in ['Success', 'Skipped']:
                tests.append([name, status, time, filename])

    for test in tests:
        print("%s | %s | %.2f | %s" % (test[0], test[1], float(test[2]), test[3]))
    print("")
    return exit_code


if __name__ == "__main__":
    main()
