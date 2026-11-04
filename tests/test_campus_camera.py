import shutil
import subprocess
import unittest
from pathlib import Path


class CampusCameraTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
    def test_camera_lifecycle(self):
        script=Path(__file__).with_name('campus_camera_harness.cjs')
        subprocess.run([shutil.which('node'),str(script)],check=True,capture_output=True,text=True)
