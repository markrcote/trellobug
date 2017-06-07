# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='trellobug',
    version='1.1.1',
    description='Files Bugzilla bugs from Trello cards',
    long_description=long_description,
    url='https://github.com/markrcote/trellobug/',
    author='Mark Côté',
    author_email='mark.cote@uwaterloo.ca',
    license='MPL 2.0',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development',
    ],
    keywords='trello bugzilla',
    packages=find_packages(),
    install_requires=[
        'oauthlib==2.0.1',
        'py-trello==0.9.0',
        'python-dateutil==2.6.0',
        'pytz==2016.10',
        'requests==2.13.0',
        'requests-oauthlib==0.8.0',
        'six==1.10.0',
    ],
    entry_points={
        'console_scripts': [
            'trellobug=trellobug.trellobug:main'
        ],
    },
)
