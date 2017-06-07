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
from trello.exceptions import Unauthorized
from trello.util import create_oauth_token


DEFAULT_BUGZILLA_URL = 'https://bugzilla.mozilla.org/'
DEFAULT_COMPONENT = 'General'
DEFAULT_CONFIG_FILES = (
    '.trellobug',
    os.path.expanduser('~/.trellobug'),
)
DEFAULT_PRODUCT = 'Conduit'
DEFAULT_VERSION = 'unspecified'

card_path = re.compile('^/c/([^/]+)/')
story_name_with_points = re.compile('\([\d]+\)[\s]*(.*)')

bug_api_url_tmpl = '{}/rest/bug'
bz_whoami_api_url_tmpl = '{}/rest/whoami'
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


def check_trello_tokens(func):
    """Decorator to handle expired Trello OAuth tokens.

    Catches `Unauthorized` errors from trello and calls
    self.handle_expired_trello_tokens().  It will retry forever until
    successful.
    """
    def func_wrapper(*args, **kwargs):
        while True:
            try:
                func(*args, **kwargs)
                return
            except Unauthorized:
                print('Unauthorized!')
                args[0].handle_expired_trello_tokens()
    return func_wrapper


class TrelloBug(object):

    def __init__(self, config_file, bz_product=None, bz_component=None,
                 bz_version=None):
        self.config_file = config_file
        self._bz_product = bz_product
        self._bz_component = bz_component
        self._bz_version = bz_version
        self.config = None
        self.bz_config = None
        self.trello_config = None
        self.load_config()
        self.load_trello()

    @check_trello_tokens
    def trello_to_bug(self, card_id, assign_bug=False):
        card = self.trello.get_card(card_id)

        bug = self.file_trello_bug(card, assign_bug)

        if not bug:
            return False

        print('Bug {} <{}> filed:'.format(bug['id'], bug['url']))
        print('    {}'.format(bug['summary']))

        card.set_description('{}\n\n{}'.format(bug['url'],
                                               card.description))

        print ('Card {} updated.'.format(card.short_url))
        return True

    @property
    def bugzilla_url_base(self):
        return self.bz_config.get('url', DEFAULT_BUGZILLA_URL).rstrip('/')

    @property
    def bz_product(self):
        return (self._bz_product or
                self.bz_config.get('product', DEFAULT_PRODUCT))

    @property
    def bz_component(self):
        return (self._bz_component or
                self.bz_config.get('component', DEFAULT_COMPONENT))

    @property
    def bz_version(self):
        return (self._bz_version or
                self.bz_config.get('version', DEFAULT_VERSION))

    def query_option(self, section, option, desc, instructions):
        if option not in self.config[section]:
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

            self.config.set(section, option, val)
            return True

        return False

    @property
    def bugzilla_auth_request_headers(self):
        return {
            'Accept': 'application/json',
            'Content-type': 'application/json',
            'X-Bugzilla-API-Key': self.bz_config['api_key'],
        }

    def generate_trello_oauth_tokens(self):
        print('Press enter to generate.')
        input()

        access_token = create_oauth_token(
            expiration='30days',
            key=self.trello_config['api_key'],
            secret=self.trello_config['api_secret'],
            name='trello-to-bug',
            output=False,
        )

        for opt in ('oauth_token', 'oauth_token_secret'):
            self.trello_config[opt] = access_token[opt]

        print('\n'.join(textwrap.wrap(
            'Token generated.  It will expire in 30 days, after which this '
            'script will generate a new one.')))

    def load_trello(self):
        self.trello = TrelloClient(
            api_key=self.trello_config['api_key'],
            api_secret=self.trello_config['api_secret'],
            token=self.trello_config['oauth_token'],
            token_secret=self.trello_config['oauth_token_secret']
        )

    def handle_expired_trello_tokens(self):
        print('Trello OAuth token invalid or expired.')
        self.generate_trello_oauth_tokens()
        self.write_config()
        self.load_trello()

    def get_current_user(self):
        print('Querying current user...')
        url = bz_whoami_api_url_tmpl.format(self.bugzilla_url_base)

        request = Request(
            url=url,
            headers=self.bugzilla_auth_request_headers,
            method='GET',
        )

        try:
            with urlopen(request) as f:
                response = json.loads(f.read().decode('utf8'))
        except HTTPError as e:
            error = get_bugzilla_error(e)
            print('Error querying current user on Bugzilla: {}'.format(error))
            return None

        return response['name']

    def file_trello_bug(self, card, assign_bug):
        card_name = card.name
        m = story_name_with_points.match(card_name)

        if m:
            card_name = m.group(1)

        url = bug_api_url_tmpl.format(self.bugzilla_url_base)

        bug_data = {
            'product': self.bz_product,
            'component': self.bz_component,
            'version': self.bz_version,
            'summary': card_name,
            'description': card.description,
            'url': card.short_url,
            'op_sys': 'Unspecified',
            'platform': 'Unspecified',
        }

        if assign_bug:
            current_user = self.get_current_user()

            if not current_user:
                return None

            bug_data['status'] = 'ASSIGNED'
            bug_data['assigned_to'] = current_user

        request = Request(
            url=url,
            data=json.dumps(bug_data).encode('utf8'),
            headers=self.bugzilla_auth_request_headers,
            method='POST',
        )

        print('Filing bug...')

        try:
            with urlopen(request) as f:
                response = json.loads(f.read().decode('utf8'))
        except HTTPError as e:
            error = get_bugzilla_error(e)
            print('Error filing bug in Bugzilla: {}'.format(error))
            return None

        bug = {
            'id': response['id'],
            'url': bug_url_tmpl.format(self.bugzilla_url_base, response['id']),
            'summary': card_name,
        }

        return bug

    def write_config(self):
        print('Saving changes to {}.'.format(self.config_file))

        with open(self.config_file, 'w') as f:
            self.config.write(f)

        print()

    def load_config(self):
        self.config = configparser.ConfigParser()
        self.config.read(self.config_file)

        if 'bugzilla' not in self.config:
            self.config.add_section('bugzilla')

        if 'trello' not in self.config:
            self.config.add_section('trello')

        self.bz_config = self.config['bugzilla']
        self.trello_config = self.config['trello']

        if 'url' not in self.bz_config:
            print('Using the Bugzilla instance at {}'.format(
                DEFAULT_BUGZILLA_URL))

        changed = False

        changed |= self.query_option(
            'bugzilla', 'api_key', 'Bugzilla API key',
            'Please visit '
            'https://bugzilla.mozilla.org/userprefs.cgi?tab=apikey '
            'to see your existing API keys or to generate a new one.'
        )

        changed |= self.query_option(
            'trello', 'api_key', 'Trello API key',
            'You can see your API key at '
            'https://trello.com/1/appKey/generate in the top box.'
        )

        changed |= self.query_option(
            'trello', 'api_secret', 'Trello API secret',
            'You can see your API secret at https://trello.com/app-key at the '
            'bottom under "OAuth".'
        )

        if ('oauth_token' not in self.trello_config or
                'oauth_token_secret' not in self.trello_config):
            self.generate_trello_oauth_tokens()
            changed = True

        if changed:
            self.write_config()


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description='File a bug based on a Trello card.'
    )
    parser.add_argument('card_id_or_url')
    parser.add_argument(
        '--config',
        help='Specify config file to load',
    )
    parser.add_argument(
        '--assign',
        action='store_true',
        help='Assign bug to self'
    )
    parser.add_argument(
        '--product',
        help='Bugzilla product in which to file bug; overrides config file',
    )
    parser.add_argument(
        '--component',
        help='Bugzilla component in which to file bug; overrides config file',
    )
    parser.add_argument(
        '--version',
        help='Value for the version field of the new bug; overrides config '
        'file',
    )
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

    if config_file is None:
        print('Looking for config file...')
        for f in DEFAULT_CONFIG_FILES:
            if os.path.exists(f):
                config_file = f
                print('Found config file: {}.'.format(config_file))
                break
        else:
            config_file = DEFAULT_CONFIG_FILES[0]
            print('No config file found; using default: {}'.format(
                config_file))

    trello_to_bug = TrelloBug(config_file, args.product, args.component,
                              args.version)
    success = trello_to_bug.trello_to_bug(card_id, args.assign)
    rc = 0 if success else 1
    sys.exit(rc)


if __name__ == '__main__':
    main()
