"""Tests for Cyber Hygiene job runner."""

# Standard Python Libraries
import os
import sys
from unittest.mock import patch

# Third-Party Libraries
import pytest

# cisagov Libraries
import cyhy_runner.cyhy_runner

# define sources of version strings
RELEASE_TAG = os.getenv("RELEASE_TAG")
PROJECT_VERSION = cyhy_runner.__version__


def test_stdout_version(capsys):
    """Verify that version string sent to stdout agrees with the module version."""
    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["bogus", "--version"]):
            cyhy_runner.cyhy_runner.main()
    captured = capsys.readouterr()
    assert (
        captured.out == f"{PROJECT_VERSION}\n"
    ), "standard output by '--version' should agree with module.__version__"


def test_running_as_module(capsys):
    """Verify that the __main__.py file loads correctly."""
    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["bogus", "--version"]):
            # F401 is a "Module imported but unused" warning. This import
            # emulates how this project would be run as a module. The only thing
            # being done by __main__ is importing the main entrypoint of the
            # package and running it, so there is nothing to use from this
            # import. As a result, we can safely ignore this warning.
            # cisagov Libraries
            import cyhy_runner.__main__  # noqa: F401
    captured = capsys.readouterr()
    assert (
        captured.out == f"{PROJECT_VERSION}\n"
    ), "standard output by '--version' should agree with module.__version__"


@pytest.mark.skipif(
    RELEASE_TAG in [None, ""], reason="this is not a release (RELEASE_TAG not set)"
)
def test_release_version():
    """Verify that release tag version agrees with the module version."""
    assert (
        RELEASE_TAG == f"v{PROJECT_VERSION}"
    ), "RELEASE_TAG does not match the project version"


@pytest.fixture(autouse=True)
def reset_runner_state():
    """Clear the runner's module-level state around each test.

    do_work() and check_for_new_work() record their work in module-level
    collections, so a test that fails before it can tidy up would otherwise
    leak a running child process and a job directory name into whatever runs
    next.
    """
    runner = cyhy_runner.cyhy_runner
    runner.processes.clear()
    runner.running_dirs.clear()

    yield

    # Anything still here belongs to a test that did not finish.  Reap it
    # rather than leaving an orphan behind for the rest of the session.
    for process in runner.processes:
        process.kill()
        process.wait()
    runner.processes.clear()
    runner.running_dirs.clear()


def _write_job(job_dir, contents):
    """Create an executable job file with the given contents."""
    os.makedirs(job_dir)
    job_file = os.path.join(job_dir, "job")
    with open(job_file, "w") as f:
        f.write(contents)
    # The runner chmods the job file the same way before executing it.
    os.chmod(job_file, 0o755)  # nosec B103


def _run_job(tmp_path, contents):
    """Run a job file through do_work and return its captured stdout."""
    runner = cyhy_runner.cyhy_runner
    job_name = "a_job"
    with patch.object(runner, "RUNNING_DIR", str(tmp_path)):
        _write_job(os.path.join(str(tmp_path), job_name), contents)
        runner.do_work(job_name)
        assert len(runner.processes) == 1
        # reset_runner_state() owns the cleanup, so there is no need to pop
        # the process off the list to keep it out of later tests.
        assert runner.processes[0].wait() == 0
    with open(os.path.join(str(tmp_path), job_name, runner.STDOUT_FILE)) as f:
        return f.read()


def test_do_work_runs_a_job_with_a_shebang(tmp_path):
    """Verify that a job file with a shebang is run."""
    assert _run_job(tmp_path, "#!/bin/sh\necho with-shebang\n") == "with-shebang\n"


def test_do_work_runs_a_job_without_a_shebang(tmp_path):
    """Verify that a job file the kernel cannot execute is still run by a shell.

    A job file with no shebang is not directly executable, so running it
    raises OSError with ENOEXEC. do_work is called from check_for_new_work
    after the job has been added to running_dirs, so letting that escape
    leaves the job in running_dirs with nothing tracking it, and it is never
    moved to the done directory.
    """
    assert _run_job(tmp_path, "echo no-shebang\n") == "no-shebang\n"


def _offer_unstartable_job(tmp_path, contents):
    """Offer check_for_new_work() a job it cannot start and return its status.

    Contents of None leaves the job directory with no job file in it at all.
    Asserts the three things that distinguish a recorded failure from a
    stalled job, then returns the status recorded for it so that the caller
    can check the value.
    """
    runner = cyhy_runner.cyhy_runner
    running_dir = os.path.join(str(tmp_path), "running")
    done_dir = os.path.join(str(tmp_path), "done")
    os.makedirs(running_dir)
    os.makedirs(done_dir)
    job_name = "a_job"
    job_dir = os.path.join(running_dir, job_name)
    if contents is None:
        os.makedirs(job_dir)
    else:
        _write_job(job_dir, contents)
    # check_for_new_work() only starts a job the commander has finished
    # writing, and it is what adds the job to running_dirs.
    with open(os.path.join(job_dir, runner.READY_FILE), "w"):
        pass

    with patch.object(runner, "RUNNING_DIR", running_dir):
        with patch.object(runner, "DONE_DIR", done_dir):
            runner.check_for_new_work()

    # Nothing is tracking the job, so check_for_done_work() will never see it.
    assert runner.processes == []
    # It must not be left sitting in the running directory.
    assert not os.path.exists(job_dir)
    # check_for_new_work() skips any name still in running_dirs, so a stale
    # entry would blacklist that name for the life of the process.
    assert runner.running_dirs == set()

    # It must be recorded as a failure that the commander can collect.
    done_file = os.path.join(done_dir, job_name, runner.DONE_FILE)
    assert os.path.exists(done_file)
    with open(done_file) as f:
        return int(f.read())


def test_check_for_new_work_records_a_job_it_cannot_start(tmp_path):
    """Verify that a job the kernel cannot execute is recorded as a failure.

    A shebang naming an interpreter that does not exist fails with ENOENT
    rather than ENOEXEC, so the shell fallback does not apply and the job
    cannot be started at all.  That has to be recorded the way a missing job
    file is: run() only logs the exceptions it catches and keeps polling, so
    a job left in running_dirs with nothing in processes is never looked at
    again and never gets a status file.  It stalls rather than fails, which
    is harder to notice than a crash.
    """
    job = "#!/nonexistent/interpreter\necho unreachable\n"
    # The commander treats any status other than "0" as a failed job, so the
    # exact value matters less than it being non-zero.
    assert _offer_unstartable_job(tmp_path, job) != 0


def test_check_for_new_work_records_a_job_with_no_job_file(tmp_path):
    """Verify that a ready job directory with no job file is recorded.

    This path already moved the job to done and recorded a status for it, but
    it left the name in running_dirs, which check_for_new_work() filters
    against.  That silently blacklists the name for the life of the process.
    """
    assert _offer_unstartable_job(tmp_path, None) == -111
