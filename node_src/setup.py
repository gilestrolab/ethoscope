from setuptools import setup, find_packages

setup(
    name='ethoscope_node',
    version='1.1',
    author='Giorgio Gilestro',
    author_email='giorgio@gilest.ro',
    packages=find_packages(),
    url="https://github.com/gilestrolab/ethoscope",
    license="GPL3",
    description='Ethoscope node server Python utils- http://lab.gilest.ro/ethoscope',
    long_description="""
    The Ethoscope is a platform for high-throughput ethomics - the study of animal behavior. 
    
    This package provides the node server components and Python utilities for the Ethoscope platform,
    which enables automated, long-term behavioral monitoring and analysis of small model organisms
    such as Drosophila melanogaster (fruit flies).
    
    The Ethoscope system allows researchers to:
    - Monitor animal behavior continuously over extended periods
    - Perform high-throughput behavioral experiments
    - Analyze behavioral patterns with automated tracking algorithms
    - Integrate environmental controls and perturbations
    
    This ethoscope_node package specifically handles the server-side functionality for managing
    individual Ethoscope devices, data collection, and communication within the Ethoscope network.
    
    For more information, visit: http://lab.gilest.ro/ethoscope
    """,
    long_description_content_type="text/plain",
    install_requires=[
        "bottle>=0.13.4",
        "cherrypy>=18.10.0", 
        "mysql-connector-python>=9.3.0",
        "netifaces>=0.11.0",
        "GitPython>=3.1.44",
        "zeroconf>=0.147.0",
        "numpy>=2.3.1",
        "opencv-python>=4.11.0.86",
        "pyserial>=3.5",
        "requests>=2.32.4",
        "scipy>=1.16.0",
        "python-dateutil>=2.9.0"
    ]
)