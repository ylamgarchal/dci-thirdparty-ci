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

import logging
import requests

LOG = logging.getLogger()


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
    for tree in zuul_manifest.json()['tree']:
        if tree['name'] == 'buildset':
            rpm_name = tree['children'][0]['children'][0]['children'][0]['children'][1]['name']  # noqa
            return '%s/buildset/el/7/x86_64/%s' % (log_url, rpm_name)
    LOG.debug('rpm url not found')
    return None


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
