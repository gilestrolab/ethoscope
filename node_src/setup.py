from distutils.core import setup

setup(
    name='ethoscope_node',
    version='trunk',
    author=['Quentin Geissmann', 'Giorgio Gilestro', 'Luis Garcia'],
    author_email=['quentin.geissmann13@imperial.ac.uk', 'g.gilestro@imperial.ac.uk', 'luis.garcia@polygonaltree.co.uk'],
    packages=['ethoscope_node'],
    url="https://github.com/gilestrolab/ethoscope",
    license="GPL3",
    description='todo',  #TODO
    long_description="TODO", # TODO open('README').read(),
    # data e.g. classifiers can be added as part of the package
    # TODO
    # package_data={'ethoscope': ['data/classifiers/*.pkl']},
    # extras_require={
    #     'pipes': ['picamera>=1.8'],
    # },
    install_requires=[
        "bottle>=0.12.8",
        "MySQL-python >= 1.2.5",
        "netifaces >= 0.10.4",
        "cherrypy >= 3.6.0",
        "eventlet >= 0.17.1",
        "python-nmap >= 0.3.4",
        "futures >= 3.0.3",
        "GitPython >=1.0.1",
        "bjoern >= 1.4.2",
        "scapy == 2.3.2"
    ],
)
