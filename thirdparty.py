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
                        LOG.info('patch url: %s' % event['change']['url'])
                        LOG.info('review number: %s' % event['change']['number'])  # noqa
                        LOG.info('patchset version: %s' % event['patchSet']['number'])  # noqa
                        LOG.info('patchset ref: %s' % event['patchSet']['ref'])
                        event_parsed['review_url'] = event['change']['url']
                        event_parsed['dci_rpm_build_url'] = dci_rpm_build_url
                        event_parsed['rpm_url'] = rpm_url
                        event_parsed['review_number'] = event['change']['number']  # noqa
                        event_parsed['patchset_version'] = event['patchSet']['number']  # noqa
                        event_parsed['patched_ref'] = event['patchSet']['ref']
    else:
        LOG.debug('event type %s' % event['type'])
    return event_parsed


def handleGerritEvent(event):
    """
    Handle the gerrit event for new comment added on the dci-rhel-agent project
    """
    LOG.info('handling event')
    event_parsed = parse_event(event)
    LOG.info(event_parsed)
    if 'review_number' in event_parsed and 'patchset_version' in event_parsed:
        LOG.info('running deployment...')
        gerrit.vote_on_review(event_parsed['review_number'],
                              event_parsed['patchset_version'],
                              1)
        LOG.debug('voted 1')


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

    gerrit_events_stream = gerrit.GerritEventsStream(event_queue, options)
    gerrit_events_stream.daemon = True
    gerrit_events_stream.setName('GerritEventsStream')
    gerrit_events_stream.start()

    LOG.info('ready to receive gerrit stream events...')
    while running:
        try:
            event = event_queue.get(block=False)
            handleGerritEvent(event)
        except Queue.Empty:
            pass
        time.sleep(1)

    LOG.info('waiting for GerritEventsStream to terminate')
    gerrit_events_stream.stop()
    gerrit_events_stream.join()
