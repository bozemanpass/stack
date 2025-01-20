# See https://medium.com/nerd-for-tech/how-to-build-and-distribute-a-cli-tool-with-python-537ae41d9d78
from setuptools import setup, find_packages
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()
with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = fh.read()
with open("stack/data/version.txt", "r", encoding="utf-8") as fh:
    version = fh.readlines()[-1].strip(" \n")
setup(
    name='stack',
    version=version,
    author='BPI',
    author_email='info@bozemanpass.com',
    license='GNU Affero General Public License',
    description='Orchestrates deployment of the Laconic stack',
    long_description=long_description,
    long_description_content_type="text/markdown",
    url='https://github.com/bozemanpass/stack',
    py_modules=['stack'],
    packages=find_packages(),
    install_requires=[requirements],
    python_requires='>=3.7',
    include_package_data=True,
    package_data={'': ['data/**']},
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Operating System :: OS Independent",
    ],
    entry_points={
        'console_scripts': ['stack=stack.main:cli'],
    }
)
