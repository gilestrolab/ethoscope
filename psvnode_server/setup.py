"""
my docstring

"""
from distutils.core import setup

setup(
    name='psvnode',
    version='trunk',
    author=['Quentin Geissmann', 'Giorgio Gilestro', 'Luis Garcia'],
    author_email=['quentin.geissmann13@imperial.ac.uk', 'g.gilestro@imperial.ac.uk', 'luis.garcia@polygonaltree.co.uk'],
    packages=['psvnode'],
    url="https://github.com/gilestrolab/pySolo-Video",
    license="GPL3",
    description='todo',  #TODO
    long_description="TODO", # TODO open('README').read(),
    # data e.g. classifiers can be added as part of the package
    # TODO
    # package_data={'pysolovideo': ['data/classifiers/*.pkl']},
    # extras_require={
    #     'pipes': ['picamera>=1.8'],
    # },
    install_requires=[
        "bottle>=0.12.8",
        "pexpect>=3.3", # FIXME possibly not needed anymore
        "MySQL-python >= 1.2.5",
    ],
)
