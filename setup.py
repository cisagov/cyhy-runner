"""
This is the setup module for the cyhy-runner project.

Based on:

- https://packaging.python.org/distributing/
- https://github.com/pypa/sampleproject/blob/master/setup.py
- https://blog.ionelmc.ro/2014/05/25/python-packaging/#the-structure
"""

# Standard Python Libraries

# Third-Party Libraries
from setuptools import find_packages, setup


def readme():
    """Read in and return the contents of the project's README.md file."""
    with open("README.md", encoding="utf-8") as f:
        return f.read()


def package_vars(version_file):
    """Read in and return the variables defined by the version_file."""
    pkg_vars = {}
    with open(version_file) as f:
        exec(f.read(), pkg_vars)  # nosec
    return pkg_vars


setup(
    name="cyhy-runner",
    description="Job runner daemon for Cyber Hygiene remote scanners",
    long_description=readme(),
    long_description_content_type="text/markdown",
    # Versions should comply with PEP440
    version=package_vars("src/example/_version.py")["__version__"],
    author="Mark Feldhousen Jr.",
    author_email="mark.feldhousen@cisa.dhs.gov",
    packages=["cyhy_runner"],
    scripts=["bin/cyhy-runner"],
    license="LICENSE.txt",
    install_requires=[
        "lockfile >= 0.9.1",
        "python-daemon >= 1.6",
        "docopt >= 0.6.2",
        "requests >= 2.13",
    ],
)
