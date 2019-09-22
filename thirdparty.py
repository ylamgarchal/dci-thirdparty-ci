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

import Queue
import json
import logging
import signal
import sys
import threading
import time

import paramiko
import requests
import settings


options = {}
options['port'] = settings.GERRIT_PORT
options['username'] = settings.GERRIT_USERNAME
options['hostname'] = settings.GERRIT_HOSTNAME

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
    stream_handler.setFormatter(formatter)
    LOG.addHandler(stream_handler)


class GerritEventsStream(threading.Thread):
    """
    This thread class is responsible to receive the Gerrit streams
    events in the background. Every message is pushed to a message queue that
    can be read by the main thread.
    """
    def __init__(self, eventQueue):
        """
        The event queue used to push the messages.
        """
        super(GerritEventsStream, self).__init__()
        self._eventQueue = eventQueue
        self._running = True

    def run(self):
        while self._running:
            LOG.debug('%s: running %s' % (self.getName(), self._running))
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(**options)
                client.get_transport().set_keepalive(60)
                _, stdout, _ = client.exec_command('gerrit stream-events')
                while self._running:
                    LOG.debug('%s: checking incoming data' % self.getName())
                    # check if there is some data in the underlying paramiko
                    # channel, this for the thread to not sleep on IO.
                    if stdout.channel.recv_ready():
                        event = stdout.readline()
                        self._eventQueue.put(json.loads(event))
                    if self._running:
                        time.sleep(5)
                LOG.debug('%s: stop running' % self.getName())
            except Exception as e:
                LOG.exception('gerrit error: %s' % str(e))
            finally:
                client.close()
            if self._running:
                time.sleep(5)
        LOG.info('%s: terminated' % self.getName())

    def stop(self):
        """
        Stop the running thread.
        """
        self._running = False


def getRpmUrl(dci_rpm_build_url):
    """
    Given the dci-rpm-build job url, get the dci-rhel-agent rpm url.
    """
    build_id = dci_rpm_build_url.split('/')[-1]
    build_url = 'https://softwarefactory-project.io/zuul/api/tenant/local/build/%s' % build_id  # noqa
    build = requests.get(build_url)
    build = build.json()
    log_url = build['log_url']
    zuul_manifest_url = '%s/zuul-manifest.json' % log_url
    zuul_manifest = requests.get(zuul_manifest_url)
    rpm_name = zuul_manifest.json()['tree'][1]['children'][0]['children'][0]['children'][0]['children'][1]['name']  # noqa
    return '%s/buildset/el/7/x86_64/%s' % (log_url, rpm_name)


def getDciRpmBuildUrl(comment):
    """
    Given the patchset's comment, parse and get the dci-rpm-build job url.
    """
    commentLines = comment.split('\n')
    for line in commentLines:
        if 'dci-rpm-build' in line:
            for token in line.split(' '):
                if token.startswith('https'):
                    return token
    return None


def handleGerritEvent(event):
    """
    Handle the gerrit event for new comment added on the dci-rhel-agent project
    """
    LOG.info('handling event')
    if event['type'] == 'comment-added':
        if event['project'] == 'dci-rhel-agent':
            if event['author']['username'] == 'zuul':
                for vote in event['approvals']:
                    if vote['type'] == 'Verified' and vote['value'] == '1':
                        LOG.info('Patchset %s has been verified by Zuul' % event['change']['url'])  # noqa
                        dci_rpm_build_url = getDciRpmBuildUrl(event['comment'])
                        LOG.info('dci-rpm-build %s' % dci_rpm_build_url)
                        rpm_url = getRpmUrl(dci_rpm_build_url)
                        LOG.info('rpm url: %s' % rpm_url)
    else:
        LOG.debug('event type %s' % event['type'])


if __name__ == "__main__":
    setup_logging()

    eventQueue = Queue.Queue()
    running = True

    def _receiveSignal(signumber, frame):
        global running
        running = False
        LOG.debug('signal received, stop main loop')

    signal.signal(signal.SIGINT, _receiveSignal)

    gerrit = GerritEventsStream(eventQueue)
    gerrit.daemon = True
    gerrit.setName('GerritEventsStream')
    gerrit.start()

    LOG.info('ready to receive gerrit stream events...')
    while running:
        try:
            event = eventQueue.get(block=False)
            handleGerritEvent(event)
        except Queue.Empty:
            pass
        time.sleep(1)

    LOG.info('waiting for GerritEventsStream to terminate')
    gerrit.stop()
    gerrit.join()
