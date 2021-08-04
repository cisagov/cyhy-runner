#!/usr/bin/env python

"""Cyber Hygiene job runner.

Reads job files sent from commander.  Starts and monitors processes, and
bundles results for pickup by the commander.

Usage:
  cyhy-runner [options] <working-dir>
  cyhy-runner (-h | --help)
  cyhy-runner --version

Options:
  -b --background                Run in background (daemonize).
  -g GROUP --group=GROUP         Change effective group.
  -l --stdout-log                Log to standard out.

"""


# Standard Python Libraries
import grp
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import signal
import subprocess  # nosec
import sys
import time
from typing import Set

# Third-Party Libraries
import daemon
from docopt import docopt
import lockfile

from ._version import __version__

RUNNING_DIR = "running"
DONE_DIR = "done"
READY_FILE = ".ready"
DONE_FILE = ".done"
JOB_FILE = "./job"
STDOUT_FILE = "job.out"
STDERR_FILE = "job.err"
POLL_INTERVAL = 15
LOG_FILE = "/var/log/cyhy/runner.log"
LOGGER_FORMAT = "%(asctime)-15s %(levelname)s %(message)s"
LOGGER_LEVEL = logging.DEBUG
LOG_FILE_MAX_SIZE = pow(1024, 2) * 16
LOG_FILE_BACKUP_COUNT = 9
LOCK_FILENAME = "cyhy-runner"

logger = logging.getLogger(__name__)

running_dirs: Set[str] = set()
processes = []
IS_RUNNING = True


def setup_logging(console=False):
    """Set up logging."""
    logger.setLevel(LOGGER_LEVEL)
    if console:
        handler = logging.StreamHandler()
    else:
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_FILE_MAX_SIZE, backupCount=LOG_FILE_BACKUP_COUNT
        )
    logger.addHandler(handler)
    formatter = logging.Formatter(LOGGER_FORMAT)
    handler.setFormatter(formatter)


def setup_directories():
    """Set up running and done directories."""
    for directory in (RUNNING_DIR, DONE_DIR):
        if not os.path.exists(directory):
            logger.info('Creating directory "%s".', directory)
            os.makedirs(directory)


def check_for_new_work():
    """Check for ready file in running directory."""
    dirs = set(os.listdir(RUNNING_DIR))
    for new_dir in dirs.difference(running_dirs):
        if new_dir in running_dirs:
            # Skip directory we're already running
            continue

        logger.info('New directory discovered "%s".', new_dir)
        # check for ready file
        ready_file = os.path.join(RUNNING_DIR, new_dir, READY_FILE)
        done_file = os.path.join(RUNNING_DIR, new_dir, DONE_FILE)
        if os.path.exists(done_file):
            logger.warning('Found old "%s" file in new job. Removing.', done_file)
        if os.path.exists(ready_file):
            running_dirs.add(new_dir)
            do_work(new_dir)
        else:
            logger.info(
                'Not starting work, no "%s" file found in "%s"', READY_FILE, new_dir
            )


def do_work(job_dir):
    """Perform work on a ready file via a subprocess."""
    job_dir = os.path.join(RUNNING_DIR, job_dir)
    job_file = os.path.join(job_dir, JOB_FILE)

    if not os.path.exists(job_file):
        logger.warning('No job file found in "%s". Moving to done.', job_dir)
        dest_dir = move_job_to_done(job_dir)
        write_status_file(dest_dir, -111)
        return

    out_file = open(os.path.join(job_dir, STDOUT_FILE), "wb")
    err_file = open(os.path.join(job_dir, STDERR_FILE), "wb")

    logger.info('Starting work in "%s".', job_dir)
    os.chmod(job_file, 0o755)  # nosec
    process = subprocess.Popen(  # nosec
        JOB_FILE, cwd=job_dir, shell=True, stdout=out_file, stderr=err_file
    )
    process.job_dir = job_dir
    processes.append(process)


def move_job_to_done(job_dir):
    """Move job directory to done directory."""
    dir_name = os.path.basename(job_dir)
    dest_dir = os.path.join(DONE_DIR, dir_name)
    ready_file = os.path.join(RUNNING_DIR, dir_name, READY_FILE)

    if os.path.exists(ready_file):
        os.remove(ready_file)

    shutil.move(job_dir, dest_dir)

    return dest_dir


def write_status_file(job_dir, return_code):
    """Save return code as done flag file."""
    with open(os.path.join(job_dir, DONE_FILE), "w") as status_file:
        print(return_code, file=status_file)


def check_for_done_work():
    """Check for subprocess completion and moves job to done."""
    for proc in processes:
        return_code = proc.poll()
        if return_code is not None:
            logger.info(
                'Process in "%s" completed with return code %d.',
                proc.job_dir,
                return_code,
            )
            dest_dir = move_job_to_done(proc.job_dir)
            write_status_file(dest_dir, return_code)
            processes.remove(proc)
            running_dirs.remove(os.path.basename(proc.job_dir))


def run():
    """Run main processing loop."""
    logger.info("Starting up.")
    setup_directories()
    while IS_RUNNING:
        try:
            check_for_new_work()
            check_for_done_work()
        except Exception as ex:
            logger.critical(ex)
        time.sleep(POLL_INTERVAL)
    logger.info("Shutting down.")


def handle_term(signal, frame):
    """Handle term code and shut down gracefully."""
    global IS_RUNNING
    logger.warning("Received signal %d.  Shutting down.", signal)
    IS_RUNNING = False


def main():
    """Set up logging and handle command-line arguments to the job runner."""
    args = docopt(__doc__, version=__version__)

    group = args["--group"]
    if group:
        print('Setting effective group to "{}".'.format(group), file=sys.stderr)

        new_gid = grp.getgrnam(group).gr_gid
        os.setegid(new_gid)
        # enable group write
        os.umask(0o002)

    working_dir = os.path.join(os.getcwd(), args["<working-dir>"])
    if not os.path.exists(working_dir):
        print(
            'Working directory "{}" does not exist.'.format(working_dir),
            end="",
            file=sys.stderr,
        )
        print("  Attempting to create...", file=sys.stderr)
        os.mkdir(working_dir)
    os.chdir(working_dir)
    lockpath = os.path.join(working_dir, LOCK_FILENAME)
    lock = lockfile.LockFile(lockpath, timeout=0)
    if lock.is_locked():
        print(
            "Cannot start.  There is already a cyhy-runner executing in "
            "this working directory.",
            file=sys.stderr,
        )
        sys.exit(-1)

    setup_logging(console=args["--stdout-log"])

    if args["--background"]:
        context = daemon.DaemonContext(
            working_directory=working_dir, umask=0o007, pidfile=lock
        )
        context.signal_map = {
            signal.SIGTERM: handle_term,
            signal.SIGCHLD: signal.SIG_IGN,
        }
        with context:
            run()
    else:
        signal.signal(signal.SIGTERM, handle_term)
        signal.signal(signal.SIGINT, handle_term)
        run()


if __name__ == "__main__":
    sys.exit(main())
