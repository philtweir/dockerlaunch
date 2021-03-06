from daemon.runner import DaemonRunner
import os
import logging
import pwd
import yaml

from .app import DockerLaunchApp
from .utils import _find_urandom_fd
from dockerlaunch.config import etc_location


def init_config():
    """Load the configuration file."""

    config_file = os.path.join(etc_location, 'dockerlaunch.yml')

    try:
        with open(config_file, 'r') as config_fileh:
            docker_settings = yaml.safe_load(config_fileh)
    except IOError:
        logging.warning("[no config file found]")
        docker_settings = {
            'allowed_images': [
                'gosmart/glossia-fenics',
                'gosmart/gfoam',
                'gosmart/glossia-goosefoot'
            ],
            'max_containers': 30,
        }

    return docker_settings


def run(indocker=None):
    docker_settings = init_config()

    log_location = '/var/log/dockerlaunch'
    run_location = '/var/run/dockerlaunch'
    lib_location = '/var/lib/dockerlaunch'

    socket_name = 'dockerlaunch.sock'
    log_name = 'dockerlaunch.log'
    pid_name = 'dockerlaunch.pid'
    script_name = 'docker-launch-inner.py'

    if not os.path.exists(lib_location):
        os.makedirs(lib_location)
        os.chmod(lib_location, 0o755)

    if indocker is None:
        indocker = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'indocker.py')

    script_filename = os.path.join(lib_location, script_name)
    with open(script_filename, 'w') as f, open(indocker, 'r') as g:
        # Any processing of indocker here
        f.write(g.read())

    os.chmod(script_filename, 0o644)
    docker_settings['script_filename'] = script_filename

    # Drop privileges
    docker_launch_pwd = pwd.getpwnam('dockerlaunch')
    docker_launch_uid = docker_launch_pwd.pw_uid
    docker_launch_gid = docker_launch_pwd.pw_gid

    os.setgid(docker_launch_gid)
    # This pulls in the docker group (of which dockerlaunch should be a member)
    os.initgroups('dockerlaunch', docker_launch_gid)

    # http://www.gavinj.net/2012/06/building-python-daemon-process.html
    for location in (run_location, log_location):
        if not os.path.exists(location):
            # NOTE: while there is a mode arg, it's overridden by umask
            os.makedirs(location)
            os.chmod(location, 0o750)
            os.chown(
                location,
                docker_launch_uid,
                docker_launch_gid
            )

    socket_filename = os.path.join(run_location, socket_name)
    pid_filename = os.path.join(run_location, pid_name)

    logger = logging.getLogger("DockerLaunchLog")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    log_filename = os.path.join(log_location, log_name)

    if not os.path.exists(log_filename):
        open(log_filename, 'a').close()

    os.chown(log_filename, docker_launch_uid, docker_launch_gid)
    os.chmod(log_filename, 0o755)

    handler = logging.FileHandler(log_filename)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    docker_app = DockerLaunchApp(
        docker_settings,
        socket_filename,
        pid_filename,
        logger=logger
    )

    runner = DaemonRunner(docker_app)
    runner.daemon_context.uid = docker_launch_uid
    runner.daemon_context.gid = docker_launch_gid
    runner.daemon_context.umask = 0o027
    runner.daemon_context.files_preserve = [handler.stream, _find_urandom_fd()]
    runner.do_action()
