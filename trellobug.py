# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import configparser
import json
import os.path
import re
import textwrap
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import (
    Request,
    urlopen,
)

from trello import TrelloClient
from trello.util import create_oauth_token


DEFAULT_BUGZILLA_URL = 'https://bugzilla.mozilla.org/'
DEFAULT_COMPONENT = 'General'
DEFAULT_CONFIG_FILES = (
    '.trello-to-bug',
    os.path.expanduser('~/.trello-to-bug'),
)
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


def query_option(config, section, option, desc, instructions):
    if option not in config[section]:
        val = None
        print('{} not found.'.format(desc))
        print('\n'.join(textwrap.wrap(instructions)))

        while not val:
            print()
            print('\n'.join(textwrap.wrap(
                'You can enter one here, or use ctrl-C to quit and add it '
                'manually to your config file as "[{}]{}":'.format(
                    section, option)
            )))
            val = input()

        config.set(section, option, val)


def generate_trello_oauth_tokens(config):
    access_token = create_oauth_token(
        expiration='30days',
        key=config['trello']['api_key'],
        secret=config['trello']['api_secret'],
        name='trello-to-bug',
        output=False,
    )
    for opt in ('oauth_token', 'oauth_token_secret'):
        config.set('trello', opt, access_token[opt])


def check_config(config):
    if 'bugzilla' not in config:
        config.add_section('bugzilla')

    if 'trello' not in config:
        config.add_section('trello')

    if 'url' not in config['bugzilla']:
        print('Using the Bugzilla instance at {}'.format(DEFAULT_BUGZILLA_URL))

    query_option(config, 'bugzilla', 'api_key', 'Bugzilla API key',
                 'Please visit '
                 'https://bugzilla.mozilla.org/userprefs.cgi?tab=apikey to '
                 'see your existing API keys or to generate a new one.')

    query_option(config, 'trello', 'api_key', 'Trello API key',
                 'You can see your API key at '
                 'https://trello.com/1/appKey/generate in the top box.')

    query_option(config, 'trello', 'api_secret', 'Trello API secret',
                 'You can see your API secret at '
                 'https://trello.com/app-key at the bottom under "OAuth".')

    if ('oauth_token' not in config['trello'] or
            'oauth_token_secret' not in config['trello']):
        print('Trello OAuth tokens not found.')
        print()
        print('Press enter to generate.')
        input()
        generate_trello_oauth_tokens(config)
        print('\n'.join(textwrap.wrap(
            'Token generated.  It will expire in 30 days, after which this '
            'script will generate a new one.')))


def main(config_file, card_id):
    if config_file is None:
        for f in DEFAULT_CONFIG_FILES:
            if os.path.exists(f):
                config_file = f
        else:
            config_file = DEFAULT_CONFIG_FILES[0]

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

    bug_id = response['id']
    bug_url = bug_url_tmpl.format(bugzilla_url_base, bug_id)

    print('Bug {} <{}> filed:'.format(bug_id, bug_url))
    print('    {}'.format(card_name))

    card.set_description('{}\n\n{}'.format(bug_url, card.description))
    print ('Card {} updated.'.format(card.short_url))
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

    config_file = args.config

    sys.exit(main(config_file, card_id))
