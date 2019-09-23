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

import json
import logging
import threading
import time

import paramiko
import settings

LOG = logging.getLogger()


class GerritEventsStream(threading.Thread):
    """
    This thread class is responsible to receive the Gerrit streams
    events in the background. Every message is pushed to a message queue that
    can be read by the main thread.
    """

    def __init__(self, event_queue, connection_options):
        """
        The event queue used to push the messages.
        """
        super(GerritEventsStream, self).__init__()
        self._event_queue = event_queue
        self._connection_options = connection_options
        self._running = True

    def run(self):
        while self._running:
            LOG.debug('%s: running %s' % (self.getName(), self._running))
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(**self._connection_options)
                client.get_transport().set_keepalive(60)
                _, stdout, _ = client.exec_command('gerrit stream-events')
                while self._running:
                    LOG.debug('%s: checking incoming data' % self.getName())
                    # check if there is some data in the underlying paramiko
                    # channel, this for the thread to not sleep on IO.
                    if stdout.channel.recv_ready():
                        event = stdout.readline()
                        self._event_queue.put(json.loads(event))
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


def vote_on_review(review_number, patchset_version, vote):
    """
    Vote on a review given the review number, the patchet version and
    the vote status in (-1, 0, +1). This use the Verified label.
    """

    connection_options = {}
    connection_options['port'] = settings.GERRIT_PORT
    connection_options['username'] = settings.GERRIT_USERNAME
    connection_options['hostname'] = settings.GERRIT_HOSTNAME

    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.connect(**connection_options)
        client.get_transport().set_keepalive(60)
        client.exec_command('gerrit review --verified %s %s,%s' % (vote, review_number, patchset_version))  # noqa
    except Exception as e:
            LOG.exception('gerrit error: %s' % str(e))
    finally:
        client.close()
