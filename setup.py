# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os
from setuptools import setup, find_packages

try:
    here = os.path.dirname(os.path.abspath(__file__))
    description = file(os.path.join(here, 'README.md')).read()
except IOError:
    description = ''

version = "1.0"

dependencies = ['mozhttpd',
                'mozfile',
                'mozlog>=3.0',
                'moznetwork',
                'mozprofile>=0.27',
                'mozprocess',
                'mozrunner',
                'mozdevice>=0.46',
               ]

setup(name='steeplechase',
      version=version,
      description="""
                  Steeplechase is a test harness for running WebRTC tests
                  between pairs of client machines to test NAT traversal.
                  """,
      long_description=description,
      classifiers=[], # Get strings from http://www.python.org/pypi?%3Aaction=list_classifiers
      author='Ted Mielczarek',
      author_email='ted@mielczarek.org',
      url='https://wiki.mozilla.org/WebRTC_Automation',
      license='MPL 2.0',
      packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
      include_package_data=True,
      package_data={'': ['*.js', '*.css', '*.html', '*.txt', '*.xpi', '*.rdf', '*.xul', '*.jsm', '*.xml'],},
      zip_safe=False,
      install_requires=dependencies,
      )
