# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 Cinc
#
# License: 3-clause BSD
#
from setuptools import setup

setup(
    name='TracRelations',
    version='0.0.1',
    packages=['tracrelations'],
    package_data={
        'tracrelations': [
        ]
    },
    install_requires=['Trac'],
    author='Cinc',
    author_email='',
    maintainer="Cinc-th",
    license='BSD',
    url='https://trac-hacks.org/',
    description='Trac relations',
    long_description="Trac relations",
    keywords='relations',
    classifiers=['Framework :: Trac'],
    entry_points={'trac.plugins': [
        'tracrelations = tracrelations',
    ]},
    test_suite='tracrelations.tests.test_suite'
)
