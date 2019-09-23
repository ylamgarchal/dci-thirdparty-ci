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
import logging
import signal
import sys
import time

import gerrit
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
    stream_handler.setFormatter(formatter)
    LOG.addHandler(stream_handler)


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
                        dci_rpm_build_url = zuul.getDciRpmBuildUrl(event['comment'])  # noqa
                        LOG.info('dci-rpm-build %s' % dci_rpm_build_url)
                        rpm_url = zuul.getRpmUrl(dci_rpm_build_url)
                        LOG.info('rpm url: %s' % rpm_url)
    else:
        LOG.debug('event type %s' % event['type'])


if __name__ == "__main__":
    setup_logging()

    event_queue = Queue.Queue()
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

    gerrit = gerrit.GerritEventsStream(event_queue, options)
    gerrit.daemon = True
    gerrit.setName('GerritEventsStream')
    gerrit.start()

    LOG.info('ready to receive gerrit stream events...')
    while running:
        try:
            event = event_queue.get(block=False)
            handleGerritEvent(event)
        except Queue.Empty:
            pass
        time.sleep(1)

    LOG.info('waiting for GerritEventsStream to terminate')
    gerrit.stop()
    gerrit.join()
