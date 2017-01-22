#!/usr/bin/env python
"""
Copyright (c) 2015 Andrew Azarov
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from datetime import datetime
from subprocess import Popen, PIPE
from singletony import Singlet
__LOCK__ = Singlet()
import yaml
import json
import signal
import sys
import os


def assrt(check, error=None):
    if check:
        return 1
    else:
        if error:
            raise AssertionError(error)
        raise AssertionError


def do(line):
    return Popen(line, shell=True, bufsize=4096, stdout=PIPE)


class gnt_ext_backup(object):

    """gnt_ext_backup object

    Keyword arguments:

    unique_id           -- Unique identifier for backups (default set to current date and hour)
    retention_period    -- Backup retention period (default set to 1 day)
    backup_user_server  -- login@server.hostname credentials for SSH (default not set). Key auth for SSH should be setup beforehand,
                            I suggest chroot on target (or even jail) with only lz4, sh, dd and find commands
    lv_backup_extension -- Extension for LV name of backup snapshot, without dot (default is bak)
    backup_folder       -- Remote server folder to place backups (default is ./upload/)
    backup_extension    -- Extension for resulting backup files (default is raw)
    compression         -- Dictionary of ingress and egress (default lz4 commands, do not remove the pipes!)
    debug               -- Do not perform actions if set, just print them
    ignore_suspended    -- Defaults to False. Whether to ignore suspended instances
    no_cleanup          -- Defaults to False. Whether to cleanup old backups after backup


    """

    def __init__(self, **kwargs):
        # Set instance defaults
        # For simplicity set to timestamp
        self.unique_id = datetime.now().strftime("%Y-%m-%d-%H")
        self.retention_period = 7
        self.backup_user_server = None
        self.lv_backup_extension = 'bak'
        self.backup_folder = './upload/'
        self.backup_extension = 'raw'
        self.compression = {'egress': '| lz4 -1c |', 'ingress': 'lz4 -dc |'}
        self.debug = 0
        self.instances_names = None
        self.dd_buffer = '128M'
        self.lv_size = '1G'
        self.instances_complete = 0
        self.stop = 0
        self.ignore_suspended = False
        self.no_cleanup = False
        for i in ['unique_id', 'retention_period', 'backup_user_server',
                  'lv_backup_extension', 'backup_extension', 'backup_folder',
                  'compression', 'debug', 'instances_names', 'dd_buffer', 'lv_size', 'ignore_suspended', 'no_cleanup']:
            if i in kwargs and kwargs[i]:
                setattr(self, i, kwargs[i])
            if i != 'instances_names':  # It can be None
                assrt(self.__dict__[i] is not None, "%s is not set" % i)

        if not self.instances_names:
            instances_raw_info = do('gnt-instance info --all')
        else:
            instances_raw_info = do(
                'gnt-instance info ' + ' '.join(self.instances_names))
        self.instances = yaml.load(instances_raw_info.stdout.read())

        self.ssh_cmd = 'ssh -c aes128-ctr -oCompression=no -oStrictHostKeyChecking=no ' + \
            self.backup_user_server
        assrt(isinstance(self.retention_period, int), "%r is not int" %
              self.retention_period)
        assrt([isinstance(ids, str) for ids in self.compression.values()],
              "%r is not correct" % self.compression)
        assrt(isinstance(self.lv_backup_extension, str), "%r is not str" %
              self.lv_backup_extension)
        assrt(isinstance(self.backup_extension, str), "%r is not str" %
              self.backup_extension)
        assrt(isinstance(self.backup_folder, str), "%r is not str" %
              self.backup_folder)
        assrt(isinstance(self.backup_user_server, str), "%r is not str" %
              self.backup_user_server)
        assrt(len(self.backup_user_server.split('@')) == 2, "%r is incorrect" %
              self.backup_user_server)
        signal.signal(signal.SIGHUP, self.wall)
        signal.signal(signal.SIGTERM, self.cancel)

    def wall(self, signum, frame):
        do('echo "{}% backup done" | wall'.format(
            int((float(self.instances_complete) / len(self.instances)) * 100)))

    def cancel(self, signum, frame):
        self.stop = 1
        do('echo "{}% backup done, waiting for jobs to finish" | wall'.format(
            int((float(self.instances_complete) / len(self.instances)) * 100)))

    def perform_backup(self):
        if self.stop:
            sys.exit(1)
        for instance in self.instances:
            if 'state is down' in instance['State'] and self.ignore_suspended:
                continue
            name = instance['Instance name']
            primary_node = [i['primary']
                            for i in instance['Nodes'] if 'primary' in i][0]
            disks = [(i['logical_id'], i['on primary'].split()[0])
                     for i in instance['Disks']]
            command = "gnt-cluster command -n " + primary_node
            for disk in disks:
                drive = {}
                drive['vg'], drive['lv'] = disk[0].split('/')
                print(
                    '{}: Backing up {} {}'.format(self.unique_id, name, disk[0]))
                cmd_list = [
                    [
                        command,
                        "\"lvcreate -L" + self.lv_size + " -s -n",
                        '.'.join(
                            [drive['lv'], self.unique_id, self.lv_backup_extension]),
                        disk[1],
                        "\""
                    ],
                    [
                        command,
                        "\"dd if=" +
                        '.'.join(
                            [disk[1], self.unique_id, self.lv_backup_extension]),
                        "bs=" + self.dd_buffer,
                        self.compression['egress'],
                        self.ssh_cmd,
                        "'" + self.compression['ingress'],
                        "dd bs=" + self.dd_buffer,
                        "of=" + self.backup_folder +
                        '.'.join(
                            [self.unique_id, drive['lv'], name, primary_node, self.backup_extension]),
                        "'\""
                    ],
                    [
                        command,
                        "\"lvremove -f",
                        '.'.join(
                            [disk[0], self.unique_id, self.lv_backup_extension]),
                        "\""
                    ]
                ]
                for cmd in cmd_list:
                    if self.debug:
                        print(' '.join(cmd))
                    else:
                        do(' '.join(cmd)).wait()
                print('{}: Done {} {}'.format(self.unique_id, name, disk[0]))
                print('-' * 100)
                self.instances_complete += 1
        if not self.no_cleanup:
            cmd = [
                self.ssh_cmd,
                "\"",
                'find',
                self.backup_folder,
                '-name \'' + '.'.join(
                    ['*', '*', '*', '*', self.backup_extension]) + '\'',
                '-ctime +' + str(self.retention_period),
                '-delete',
                "\""
            ]
            if self.debug:
                print(' '.join(cmd))
            else:
                do(' '.join(cmd)).wait()
            print('Done cleaning old backups')
            print('-' * 100)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-i",
                        "--id",
                        dest='unique_id',
                        type=str,
                        default=None,
                        help="Unique id to identify backups, default is date with hour",
                        required=False)
    parser.add_argument("-I",
                        "--ignore-suspended",
                        dest='ignore_suspended',
                        action='store_true',
                        help="Whether to ignore or not the suspended systems",
                        required=False)
    parser.add_argument("-N",
                        "--no-cleanup",
                        dest='no_cleanup',
                        action='store_true',
                        help="Disable cleanup of old backups (you cleanup on your own)",
                        required=False)
    parser.add_argument("-n",
                        "--instances_names",
                        dest='instances_names',
                        type=str,
                        nargs='+',
                        help="Space separated list of instances to backup",
                        required=False)
    parser.add_argument("-r",
                        "--retention_period",
                        dest='retention_period',
                        type=int,
                        default=None,
                        help="Backup retention period in days, default is 1",
                        required=False)
    parser.add_argument("-b",
                        "--backup_user_server",
                        dest='backup_user_server',
                        type=str,
                        default=None,
                        help="Backup login and server ssh style: login@backup.server",
                        required=True)
    parser.add_argument("-l",
                        "--lv_backup_extension",
                        type=str,
                        dest='lv_backup_extension',
                        default=None,
                        help="LV backup snapshot extension to identify",
                        required=False)
    parser.add_argument("-e",
                        "--backup_extension",
                        type=str,
                        dest='backup_extension',
                        default=None,
                        help="Backup extension for files on the backup target",
                        required=False)
    parser.add_argument("-f",
                        "--backup_folder",
                        type=str,
                        dest='backup_folder',
                        default=None,
                        help="Backup folder on remote server",
                        required=False)
    parser.add_argument("-c",
                        "--compression",
                        type=json.loads,
                        dest='compression',
                        default=None,
                        help="JSON array like {'egress': '| lz4 -1c |', 'ingress': 'lz4 -dc >'}",
                        required=False)
    parser.add_argument("-d",
                        "--debug",
                        type=int,
                        dest='debug',
                        default=None,
                        help="If debug is 1 - disable performing actions and just print them out",
                        required=False)
    parser.add_argument("--lv_size",
                        type=str,
                        dest='lv_size',
                        default=None,
                        help="LV snapshot size - default 1G, check man lvcreate for snapshot sizes",
                        required=False)
    parser.add_argument("--dd_buffer",
                        type=str,
                        dest='dd_buffer',
                        default=None,
                        help="dd buffer size, default 128MB for fast gbit transfers, adjust to your memory and network size",
                        required=False)
    a = parser.parse_args()
    arguments = {}
    for i in ['unique_id', 'retention_period', 'backup_user_server',
              'lv_backup_extension', 'backup_extension', 'backup_folder',
              'compression', 'debug', 'instances_names', 'lv_size', 'dd_buffer', 'ignore_suspended', 'no_cleanup']:
        if hasattr(a, i) and getattr(a, i):
            arguments[i] = getattr(a, i)
    backup_job = gnt_ext_backup(**arguments)
    backup_job.perform_backup()
