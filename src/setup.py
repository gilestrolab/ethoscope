from setuptools import setup, find_packages

setup(
    name='ethoscope',
    version='1.0.0',
    author=['Quentin Geissmann', 'Giorgio Gilestro', 'Luis Garcia'],
    author_email=['quentin.geissmann@gmail.com', 'giorgio@gilest.ro', 'luis.garcia@uni-muenster.de'],
    packages=find_packages(),
    url="https://github.com/gilestrolab/ethoscope",
    license="GPL3",
    description='The API of the Ethoscope device.', #TODO
    long_description="TODO",

    keywords=["behaviour", "video tracking"],
    scripts=['scripts/device_server.py'],

    classifiers=[
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Topic :: Scientific/Engineering'
    ],
    # data e.g. classifiers can be added as part of the package
    # TODO
    # package_data={'ethoscope': ['data/classifiers/*.pkl']},
    extras_require={
         'device': ['picamera>=1.8', "GitPython >=1.0.1",
                    "mysql-connector-python >= 8.0.16", "cherrypy >= 3.6.0", "pyserial>=2.7", "bottle>=0.12.8"],
         'dev': ['Sphinx >= 1.4.4', "sphinx_rtd_theme >= 0.1.9", "mock >= 2.0.0"]
     },
    setup_requires=[
        "numpy>=1.6.1"
        ],
    install_requires=[
        "numpy>=1.6.1",
        "scipy >= 0.15.1",
    ],
    tests_require=['nose', 'mock'],
    test_suite='nose.collector'
)
