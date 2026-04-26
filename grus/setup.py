from setuptools import setup, find_packages

setup(
    name='grus',
    version='1.0.0',
    packages=find_packages(),
    install_requires=[
        'grpcio',
        'grpcio-tools',
        'protobuf',
        'textual',
        'tomli; python_version < "3.11"',
    ],
    entry_points={
        'console_scripts': [
            'grus=tui.main:main',
        ],
    },
)
