from distutils.core import setup

setup(
    name='cyhy-runner',
    version='0.0.2',
    author='Mark Feldhousen Jr.',
    author_email='mark.feldhousen@hq.dhs.gov',
    packages=['cyhy_runner'],
    scripts=['bin/cyhy-runner'],
    #url='http://pypi.python.org/pypi/cyhy/',
    license='LICENSE.txt',
    description='Job runner daemon for Cyber Hygiene remote scanners',
    #long_description=open('README.txt').read(),
    install_requires=[
        "lockfile >= 0.9.1",
        "python-daemon >= 1.6",
        "docopt >= 0.6.2",
        "requests >= 2.13"
    ]
)
