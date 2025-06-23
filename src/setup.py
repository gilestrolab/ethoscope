from setuptools import setup, find_packages

setup(
    name='ethoscope',
    version='1.0.0',
    author='Giorgio Gilestro',
    author_email='giorgio@gilest.ro',
    packages=find_packages(),
    url="https://github.com/gilestrolab/ethoscope",
    license="GPL3",
    description='The API of the Ethoscope device for automated behavioral monitoring.',
    long_description="""
    The Ethoscope is a platform for high-throughput ethomics - the study of animal behavior.
    
    This package provides the core API and device components for the Ethoscope platform,
    enabling automated, long-term behavioral monitoring and analysis of small model organisms
    such as Drosophila melanogaster (fruit flies).
    
    The Ethoscope system allows researchers to:
    - Monitor animal behavior continuously over extended periods
    - Perform high-throughput behavioral experiments with automated tracking
    - Analyze behavioral patterns with computer vision algorithms
    - Control environmental conditions and deliver targeted perturbations
    - Process video data in real-time with minimal computational overhead
    
    This core ethoscope package provides the fundamental APIs, tracking algorithms,
    and device interfaces that power individual Ethoscope units.
    
    Key features:
    - Real-time video tracking and analysis
    - Modular stimulator and sensor interfaces
    - Data logging and experiment management
    - Integration with the broader Ethoscope ecosystem
    
    For more information, visit: http://lab.gilest.ro/ethoscope
    """,
    long_description_content_type="text/plain",
    keywords=["behaviour", "video tracking", "ethomics", "drosophila", "behavioral analysis"],
    scripts=['scripts/device_server.py'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Topic :: Scientific/Engineering :: Bio-Informatics',
        'Topic :: Scientific/Engineering :: Image Processing',
        'Topic :: Multimedia :: Video :: Capture',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
    ],
    python_requires='>=3.7',
    extras_require={
        'device': [
            'picamera>=1.8', 
            "GitPython>=1.0.1",
            "mysql-connector-python>=8.0.16", 
            "cherrypy>=3.6.0", 
            "pyserial>=2.7", 
            "bottle>=0.12.8",
            "opencv-python>=4.0.0"
        ],
        'dev': [
            'Sphinx>=1.4.4', 
            "sphinx_rtd_theme>=0.1.9", 
            "mock>=2.0.0",
            "pytest>=6.0.0",
            "pytest-cov>=2.10.0"
        ]
    },
    setup_requires=[
        "numpy>=1.6.1"
    ],
    install_requires=[
        "numpy>=1.6.1",
        "scipy>=0.15.1",
    ],
    tests_require=['pytest', 'mock'],
    test_suite='pytest'
)