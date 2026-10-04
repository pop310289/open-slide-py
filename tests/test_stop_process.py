"""The viewer's Tcl/Tk process is asked to exit first and killed only when it does not stop."""
import subprocess
import unittest

from openslide_tk.viewer import stop_process


class FakeProcess:
    def __init__(self, exits_on_terminate=True, running=True):
        self.calls = []
        self.exits_on_terminate = exits_on_terminate
        self.returncode = None if running else 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.calls.append("terminate")
        if self.exits_on_terminate:
            self.returncode = -15

    def kill(self):
        self.calls.append("kill")
        self.returncode = -9

    def wait(self, timeout=None):
        self.calls.append(f"wait {timeout}")
        if self.returncode is None:
            raise subprocess.TimeoutExpired("wish", timeout)
        return self.returncode


class StopProcessTests(unittest.TestCase):
    def test_a_process_that_exits_is_not_killed(self):
        process = FakeProcess()
        stop_process(process, timeout=2)
        self.assertEqual(process.calls, ["terminate", "wait 2"])

    def test_a_process_that_ignores_terminate_is_killed(self):
        process = FakeProcess(exits_on_terminate=False)
        stop_process(process, timeout=2)
        self.assertEqual(process.calls, ["terminate", "wait 2", "kill", "wait 2"])
        self.assertEqual(process.returncode, -9)

    def test_a_finished_process_is_left_alone(self):
        process = FakeProcess(running=False)
        stop_process(process)
        self.assertEqual(process.calls, [])


if __name__ == "__main__":
    unittest.main()
