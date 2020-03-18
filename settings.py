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

import os

GERRIT_PORT = 29418
GERRIT_USERNAME = 'dci-ci-bot'
GERRIT_HOSTNAME = 'softwarefactory-project.io'
GERRIT_SSH_KEY_FILENAME = os.getenv('GERRIT_SSH_KEY_FILENAME',
                                    '/home/dci/dci_ci_bot_id_rsa')
RHEL_AGENT_DIR = os.getenv('RHEL_AGENT_DIR', '/home/dci/dci-rhel-agent')
