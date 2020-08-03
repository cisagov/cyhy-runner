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


import daemon
from docopt import docopt
import lockfile
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import signal
import subprocess
import sys
import time

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

runningDirs = set()
processes = []
isRunning = True


def setupLogging(console=False):
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


def setupDirectories():
    """Set up running and done directories."""
    for directory in (RUNNING_DIR, DONE_DIR):
        if not os.path.exists(directory):
            logger.info("Creating directory '{}'.".format(directory))
            os.makedirs(directory)


def checkForNewWork():
    """Check for ready file in running directory."""
    dirs = set(os.listdir(RUNNING_DIR))
    for d in dirs.difference(runningDirs):
        logger.info("New directory discovered '{}'.".format(d))
        # check for ready file
        readyFile = os.path.join(RUNNING_DIR, d, READY_FILE)
        doneFile = os.path.join(RUNNING_DIR, d, DONE_FILE)
        if os.path.exists(doneFile):
            logger.warning("Found old '{}' file in new job. Removing.".format(doneFile))
        if os.path.exists(readyFile):
            runningDirs.add(d)
            doWork(d)
        else:
            logger.info(
                "Not starting work, no '{}' file found in '{}'".format(READY_FILE, d)
            )


def doWork(jobDir):
    """Perform work on a ready file via a subprocess."""
    jobDir = os.path.join(RUNNING_DIR, jobDir)
    jobFile = os.path.join(jobDir, JOB_FILE)
    if not os.path.exists(jobFile):
        logger.warning("No job file found in '{}'. Moving to done.".format(jobDir))
        destDir = moveJobToDone(jobDir)
        writeStatusFile(destDir, -111)
        return
    outFile = open(os.path.join(jobDir, STDOUT_FILE), "wb")
    errFile = open(os.path.join(jobDir, STDERR_FILE), "wb")
    logger.info("Starting work in '{}'.".format(jobDir))
    os.chmod(jobFile, 0o755)
    process = subprocess.Popen(
        JOB_FILE, cwd=jobDir, shell=True, stdout=outFile, stderr=errFile
    )
    process.jobDir = jobDir
    processes.append(process)


def moveJobToDone(jobDir):
    """Move job directory to done directory."""
    dirName = os.path.basename(jobDir)
    destDir = os.path.join(DONE_DIR, dirName)
    readyFile = os.path.join(RUNNING_DIR, dirName, READY_FILE)
    if os.path.exists(readyFile):
        os.remove(readyFile)
    shutil.move(jobDir, destDir)
    return destDir


def writeStatusFile(jobDir, returnCode):
    """Save return code as done flag file."""
    statusFile = open(os.path.join(jobDir, DONE_FILE), "wb")
    print(returnCode, file=statusFile)
    statusFile.close()


def checkForDoneWork():
    """Check for subprocess completion and moves job to done."""
    for p in processes:
        returnCode = p.poll()
        if returnCode is not None:
            logger.info(
                "Process in '{}' completed with return code {}.".format(
                    p.jobDir, returnCode
                )
            )
            destDir = moveJobToDone(p.jobDir)
            writeStatusFile(destDir, returnCode)
            processes.remove(p)
            runningDirs.remove(os.path.basename(p.jobDir))


def run():
    """Run main processing loop."""
    logger.info("Starting up.")
    setupDirectories()
    while isRunning:
        try:
            checkForNewWork()
            checkForDoneWork()
        except Exception as e:
            logger.critical(e)
        time.sleep(POLL_INTERVAL)
    logger.info("Shutting down.")


def handle_term(signal, frame):
    """Handle term code and shut down gracefully."""
    global isRunning
    logger.warning("Received signal {}.  Shutting down.".format(signal))
    isRunning = False


if __name__ == "__main__":
    args = docopt(__doc__, version="v0.0.2")
    group = args["--group"]
    if group:
        print("Setting effective group to '{}'".format(group), file=sys.stderr)
        import grp

        new_gid = grp.getgrnam(group).gr_gid
        os.setegid(new_gid)
        # enable group write
        os.umask(0o002)

    workingDir = os.path.join(os.getcwd(), args["<working-dir>"])
    if not os.path.exists(workingDir):
        print(
            "Working directory '{}' does not exist. ".format(workingDir)
            + "Attempting to create...",
            file=sys.stderr,
        )
        os.mkdir(workingDir)
    os.chdir(workingDir)
    lockpath = os.path.join(workingDir, LOCK_FILENAME)
    lock = lockfile.LockFile(lockpath, timeout=0)
    if lock.is_locked():
        print(
            "Cannot start.  There is already a cyhy-runner executing in "
            + "this working directory.",
            file=sys.stderr,
        )
        sys.exit(-1)

    setupLogging(console=args["--stdout-log"])

    if args["--background"]:
        context = daemon.DaemonContext(
            working_directory=workingDir, umask=0o007, pidfile=lock
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
