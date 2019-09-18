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


options = {}
options['port'] = 29418
options['username'] = 'ylamgarchal'
options['hostname'] = 'softwarefactory-project.io'
running = True
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
    def __init__(self, eventQueue):
        super(GerritEventsStream, self).__init__()
        self._eventQueue = eventQueue
        self._running = True

    def run(self):
        while self._running:
            LOG.debug('GerritEventsStream: running %s' % self._running)
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(**options)
                client.get_transport().set_keepalive(60)
                _, stdout, _ = client.exec_command('gerrit stream-events')
                while self._running:
                    LOG.debug('GerritEventsStream: checking incoming data')
                    if stdout.channel.recv_ready():
                        event = stdout.readline()
                        self._eventQueue.put(json.loads(event))
                    time.sleep(1)
                LOG.debug('GerritEventsStream: stop running')
            except Exception as e:
                print('gerrit error: %s' % str(e))
            finally:
                client.close()
            if self._running:
                time.sleep(3)
        print('GerritEventsStream: terminated')

    def stop(self):
        self._running = False


def handleGerritEvent(event):
    print('handling event')
    print(event)
    # if zuul +1 Verified then
    #    start third party ci


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
    gerrit.start()

    print('ready to receive gerrit stream events...')
    while running:
        try:
            event = eventQueue.get(block=False)
            handleGerritEvent(event)
        except Queue.Empty:
            pass
        time.sleep(1)

    print('waiting for GerritEventsStream to terminate')
    gerrit.stop()
    gerrit.join()
