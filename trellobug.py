# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import configparser
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import (
    Request,
    urlopen,
)

from trello import TrelloClient


DEFAULT_BUGZILLA_URL = 'https://bugzilla.mozilla.org/'
DEFAULT_COMPONENT = 'General'
DEFAULT_CONFIG_FILE = '.trello-to-bug'
DEFAULT_PRODUCT = 'Conduit'
DEFAULT_VERSION = 'unspecified'


card_path = re.compile('^/c/([^/]+)/')
story_name_with_points = re.compile('\([\d]+\)[\s]*(.*)')

bug_api_url_tmpl = '{}/rest/bug'
bug_url_tmpl = '{}/show_bug.cgi?id={}'
card_api_url_tmpl = 'https://api.trello.com/1/cards/{}/'


def get_bugzilla_error(e):
    error_body = e.read().decode('utf8')
    error_dict = None

    try:
        error_dict = json.loads(error_body)
    except json.decoder.JSONDecodeError:
        return error_body

    return 'Error {}: {}'.format(error_dict['code'], error_dict['message'])


def check_config(config):
    required_options = {
        'bugzilla': ('api_key',),
        'trello': ('api_key', 'api_secret', 'oauth_token',
                   'oauth_token_secret')
    }

    for section, options in required_options.items():
        for o in options:
            if o not in config[section]:
                print('"{}" not present in [{}] section of config '
                      'file.'.format(o, section))
                return False

    return True


def main(config_file, card_id):
    config = configparser.ConfigParser()
    config.read(config_file)

    if not check_config(config):
        return 1

    bz_config = config['bugzilla']
    trello_config = config['trello']

    trello = TrelloClient(
        api_key=trello_config['api_key'],
        api_secret=trello_config['api_secret'],
        token=trello_config['oauth_token'],
        token_secret=trello_config['oauth_token_secret']
    )

    card = trello.get_card(card_id)

    card_name = card.name
    m = story_name_with_points.match(card_name)

    if m:
        card_name = m.group(1)

    bugzilla_url_base = bz_config.get('url', DEFAULT_BUGZILLA_URL).rstrip('/')

    url = bug_api_url_tmpl.format(bugzilla_url_base)

    bug_data = {
        'api_key': bz_config['api_key'],
        'product': bz_config.get('product', DEFAULT_PRODUCT),
        'component': bz_config.get('component', DEFAULT_COMPONENT),
        'version': bz_config.get('version', DEFAULT_VERSION),
        'summary': card_name,
        'description': card.description,
        'url': card.short_url,
        'op_sys': 'Unspecified',
        'platform': 'Unspecified',
    }

    headers = {
        'Accept': 'application/json',
        'Content-type': 'application/json',
    }

    request = Request(
        url=url,
        data=json.dumps(bug_data).encode('utf8'),
        headers=headers,
        method='POST',
    )

    try:
        with urlopen(request) as f:
            response = json.loads(f.read().decode('utf8'))
    except HTTPError as e:
        error = get_bugzilla_error(e)
        print('Error sending request to Bugzilla: {}'.format(error))
        return 1

    print('Bug {} <{}> filed:'.format(
        response['id'],
        bug_url_tmpl.format(bugzilla_url_base, response['id']))
    )
    print('    {}'.format(card_name))
    return 0


if __name__ == '__main__':
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description='File a bug based on a Trello card.'
    )
    parser.add_argument('card_id_or_url')
    parser.add_argument('--config')
    args = parser.parse_args()

    if '/' in args.card_id_or_url:
        m = card_path.match(urlparse(args.card_id_or_url).path)
        if not m:
            print('"{}" does not contain a valid card path.')
            sys.exit(1)

        card_id = m.group(1)
    else:
        card_id = args.card_id_or_url

    config_file = args.config if args.config else DEFAULT_CONFIG_FILE

    sys.exit(main(config_file, card_id))
