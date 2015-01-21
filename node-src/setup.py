"""
my docstring

"""
from distutils.core import setup

setup(
    name='pysolovideo',
    version='trunk',
    author=['Quentin Geissmann', 'Giorgio Gilestro', 'Luis Garcia'],
    author_email= ['quentin.geissmann13@imperial.ac.uk','g.gilestro@imperial.ac.uk', 'luis.garcia@polygonaltree.co.uk'],
    packages=['pysolovideo'],
    url="https://github.com/gilestrolab/pySolo-Video",
    license="GPL3",
    description='todo', #TODO
    long_description=open('README').read(),
    # data e.g. classifiers can be added as part of the package
    # TODO
    # package_data={'pysolovideo': ['data/classifiers/*.pkl']},
    # extras_require={
    #     'pipes': ['picamera>=1.8'],
    # },
    install_requires=[
        "numpy>=1.6.1",
        # "pandas>=0.13.1",
        "bottle>=0.12.8",
        # "scipy>=0.10.1",
        # "scikit-learn",
        # "picamera>=1.8",
        "pyserial>=2.7"
# TODO check opencv in installed
        # "opencv>=2.4.5",
    ],
)
