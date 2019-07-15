from setuptools import setup, find_packages

setup(
    name='ethoscope_node',
    version='trunk',
    author=['Quentin Geissmann', 'Giorgio Gilestro', 'Luis Garcia'],
    author_email=['quentin.geissmann@gmail.com', 'giorgio@gilest.ro', 'luis.garcia@uni-muenster.de'],
    packages=find_packages(),
    url="https://github.com/gilestrolab/ethoscope",
    license="GPL3",
    description='Ethoscope node server Python utils- http://lab.gilest.ro/ethoscope',
    long_description="TODO", # TODO open('README').read(),
    # data e.g. classifiers can be added as part of the package
    # TODO
    # package_data={'ethoscope': ['data/classifiers/*.pkl']},
    # extras_require={
    #     'pipes': ['picamera>=1.8'],
    # },
    install_requires=[
        "bottle>=0.12.8",
        "mysql-connector-python >= 8.0.15",
        "netifaces >= 0.10.4",
        "cherrypy >= 3.6.0",
        "GitPython >=1.0.1",
        "zeroconf >= 0.23.0"
    ]
)
