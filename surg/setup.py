from setuptools import setup

setup(
    name='surg',
    version='1.0.0',
    py_modules=['main', 'config', 'grpc_client', 'streams', 'socket_server'],
    install_requires=[
        'fastapi',
        'uvicorn[standard]',
        'python-socketio',
        'grpcio',
        'protobuf',
    ],
    entry_points={
        'console_scripts': [
            'surg=main:main',
        ],
    },
)
