# -*- coding: utf-8 -*-
#
# Copyright (C) Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

try:
    from Queue import Queue
    from Queue import Empty as q_Empty
except ImportError:
    from queue import Queue
    from queue import Empty as q_Empty

import logging
import os
import re
import signal
import subprocess
import sys
import time

import gerrit
import paramiko
from paramiko.client import WarningPolicy
import settings
import zuul


LOG = logging.getLogger()


def setup_logging():

    LOG.setLevel(logging.DEBUG)
    stream_handler = logging.StreamHandler(stream=sys.stdout)

    try:
        import colorlog
        formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s :: %(levelname)s :: %(message)s",
            datefmt=None,
            reset=True,
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red'
            }
        )
        stream_handler.setFormatter(formatter)
    except ImportError:
        pass

    stream_handler.setLevel(logging.DEBUG)
    LOG.addHandler(stream_handler)


def parse_event(event):
    """
    Parse the Gerrit's event and create a specific dict with the
    following values:
        - review_url
        - dci_rpm_build_url
        - rpm_url
        - review_number
        - patchset_version
        - patchset_ref
    """
    event_parsed = {}
    if 'project' in event and event['project'] == 'dci-rhel-agent':
        LOG.info(str(event))
        if event['type'] == 'comment-added':
            if event['author']['username'] == 'zuul':
                for vote in event['approvals']:
                    if vote['type'] == 'Verified' and vote['value'] == '1':
                        LOG.info('Patchset %s has been verified by Zuul' % event['change']['url'])  # noqa
                        dci_rpm_build_url = zuul.getDciRpmBuildUrl(event['comment'])  # noqa
                        LOG.info('dci-rpm-build %s' % dci_rpm_build_url)
                        rpm_url = zuul.getRpmUrl(dci_rpm_build_url)
                        LOG.info('rpm url: %s' % rpm_url)
                        LOG.info('patch url: %s' % event['change']['url'])
                        LOG.info('review number: %s' % event['change']['number'])  # noqa
                        LOG.info('patchset version: %s' % event['patchSet']['number'])  # noqa
                        LOG.info('patchset ref: %s' % event['patchSet']['ref'])
                        event_parsed['review_url'] = event['change']['url']
                        event_parsed['dci_rpm_build_url'] = dci_rpm_build_url
                        event_parsed['rpm_url'] = rpm_url
                        event_parsed['review_number'] = event['change']['number']  # noqa
                        event_parsed['patchset_version'] = event['patchSet']['number']  # noqa
                        event_parsed['patchset_ref'] = event['patchSet']['ref']
    else:
        LOG.debug('event type %s' % event['type'])
    return event_parsed


def exec_remote_command(client, command):
    try:
        LOG.debug(command)
        _, stdout, stderr = client.exec_command(command)
        return stdout.channel.recv_exit_status(), stdout, stderr
    except paramiko.ssh_exception.SSHException as e:
        raise Exception('ssh exception %s' % str(e))

def bootstrap_libvirt_infra(dci_client_id, dci_api_secret):
    LOG.debug('bootstrap the libvirt setup')
    os.chdir("%s/virtual-setup" % settings.RHEL_AGENT_DIR)

    command = 'ansible-playbook site.yml -e "hook_action=cleanup" -e "dci_client_id=lol" -e "dci_api_secret=lol"'
    LOG.debug(command)
    proc = subprocess.Popen(command, shell=True)
    rc = proc.wait()
    if rc != 0:
        raise Exception('error while running the bootstrap libvirt infra')

    command = 'ansible-playbook site.yml -e "ssh_key=id_rsa_rhel_ci dci_client_id=%s dci_api_secret=%s"' % (dci_client_id, dci_api_secret)
    LOG.debug(command)
    proc = subprocess.Popen(command, shell=True)
    rc = proc.wait()
    if rc != 0:
        raise Exception('error while running the bootstrap libvirt infra')
    return subprocess.getoutput("sudo virsh domifaddr jumpbox|grep 192.168.122| tr -s ' '|cut -d ' ' -f5|cut -d '/' -f1")


def run_agent_on_jumpbox(jumpbox_ip, event_parsed):

    def _download_patchset(client, event):
        review_number = event['review_number']
        patchset_version = event['patchset_version']
        LOG.debug('fetch patchset %s,%s' % (review_number, patchset_version))
        command = 'cd /home/dci/dci-rhel-agent; git fetch "https://softwarefactory-project.io/r/dci-rhel-agent" %s && git checkout FETCH_HEAD' % (event['patchset_ref'])
        rc, stdout, stderr = exec_remote_command(client, command)
        if rc != 0:
            LOG.error('fail to download the patchset from the jumphost: stdout: %s, stderr: %s' % (stdout.readlines(), stderr.readlines()))        

    def _install_rpm_review(client, rpm_url):
        LOG.debug('install rpm of the review: %s' % rpm_url)
        rpm_name = rpm_url.split('/')[-1]
        command = 'wget %s -O /tmp/%s' % (rpm_url, rpm_name)
        LOG.debug(command)
        rc, stdout, stderr = exec_remote_command(client, command)
        if rc != 0:
            LOG.error('fail to download the rpm from the jumphost: stdout: %s, stderr: %s' % (stdout.readlines(), stderr.readlines()))

        command = 'sudo rpm -i --force /tmp/%s' % rpm_name
        LOG.debug(command)
        rc, stdout, stderr = exec_remote_command(client, command)
        if rc != 0:
            LOG.error('fail to install the rpm in the the jumphost: stdout: %s, stderr: %s' % (stdout.readlines(), stderr.readlines()))

    def _build_container(client):
        LOG.debug('build the container locally')
        command = 'cd /home/dci/dci-rhel-agent; sudo dci-rhel-agent-ctl --build'
        LOG.debug(command)
        rc, stdout, stderr = exec_remote_command(client, command)
        if rc != 0:
            LOG.error('fail to build the container in the jumphost: stdout: %s, stderr: %s' % (stdout.readlines(), stderr.readlines()))

    def _run_agent(client):
        LOG.debug('start the agent')
        command = 'cd /home/dci/dci-rhel-agent; sudo dci-rhel-agent-ctl --start --url localhost/dci-rhel-agent:latest --local --skip-download'
        LOG.debug(command)
        rc, stdout, stderr = exec_remote_command(client, command)
        if rc != 0:
            LOG.error('agent failed: stdout: %s, stderr: %s' % (stdout.readlines(), stderr.readlines()))
            return rc, None
        job_output = str(stdout.read())
        job_id = re.search('\"job_id\": \"(\w{8}-\w{4}-\w{4}-\w{4}-\w{12})\".*', job_output, re.IGNORECASE)
        job_id_str = 'job_not_found'
        if len(job_id.groups(0)) > 0:
            job_id_str = job_id.groups(0)[0]
        return rc, job_id_str

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(WarningPolicy())
    client.connect(hostname=jumpbox_ip,
                   username='dci',
                   key_filename=settings.HOST_SSH_KEY_FILENAME,
                   look_for_keys=True,
                   timeout=5000)
    client.get_transport().set_keepalive(60)

    _download_patchset(client, event_parsed)
    _install_rpm_review(client, event_parsed['rpm_url'])
    _build_container(client)
    return _run_agent(client)


def handleGerritEvent(event):
    """
    Handle the gerrit event
    """
    LOG.info('handling event')
    event_parsed = parse_event(event)
    if 'review_number' in event_parsed and 'patchset_version' in event_parsed:
        gerrit.comment(event_parsed['review_number'], event_parsed['patchset_version'], "dci-third-party starting job...")
        jumpbox_ip = bootstrap_libvirt_infra(settings.RHEL_DCI_CLIENT_ID,
                                             settings.RHEL_DCI_API_SECRET)
        LOG.info('jumpbox ip address: %s' % jumpbox_ip)
        rc, job_id = run_agent_on_jumpbox(jumpbox_ip, event_parsed)
        vote = 1
        if rc != 0:
            vote = -1
        gerrit.vote_on_review(event_parsed['review_number'],
                              event_parsed['patchset_version'],
                              vote, job_id)
        LOG.debug('voted %s' % vote)
    else:
        LOG.debug('no vote for %s\n' % str(event_parsed))


if __name__ == "__main__":
    setup_logging()

    event_queue = Queue()
    running = True

    def _receiveSignal(signumber, frame):
        global running
        running = False
        LOG.debug('signal received, stop main loop')

    signal.signal(signal.SIGINT, _receiveSignal)

    options = {}
    options['port'] = settings.GERRIT_PORT
    options['username'] = settings.GERRIT_USERNAME
    options['hostname'] = settings.GERRIT_HOSTNAME
    options['key_filename'] = settings.GERRIT_SSH_KEY_FILENAME

    LOG.info('using connection options: %s' % str(options))

    os.chdir(settings.RHEL_AGENT_DIR)

    gerrit_events_stream = gerrit.GerritEventsStream(event_queue, options)
    gerrit_events_stream.daemon = True
    gerrit_events_stream.setName('GerritEventsStream')
    gerrit_events_stream.start()

    LOG.info('ready to receive gerrit stream events...')
    while running:
        try:
            event = event_queue.get(block=False)
            handleGerritEvent(event)
        except q_Empty:
            pass
        time.sleep(1)

    LOG.info('waiting for GerritEventsStream to terminate')
    gerrit_events_stream.stop()
    gerrit_events_stream.join()
