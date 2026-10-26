"""Local integration checks: actual model inference and command-line failures."""
import subprocess
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path

from download_model import MODEL


@unittest.skipUnless(MODEL.exists(), 'Run download_model.py to enable model integration tests')
class ModelTests(unittest.TestCase):
    def test_blank_video_through_real_app(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'blank.mp4'
            output = Path(folder)/'annotated.mp4'
            writer = cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'mp4v'),30,(640,480))
            self.assertTrue(writer.isOpened())
            for _ in range(5):
                writer.write(np.zeros((480,640,3),dtype=np.uint8))
            writer.release()
            result = subprocess.run([sys.executable,str(Path(__file__).with_name('app.py')),
                '--source',str(source),'--headless','--output',str(output)],
                capture_output=True,text=True,timeout=60,
                env={**os.environ,'GYMBRO_API_URL':'','GYMBRO_SESSIONS_DIR':str(Path(folder)/'sessions')})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('"pose_frames": 0',result.stdout)
            self.assertIn('"reps": 0',result.stdout)
            saved = list((Path(folder)/'sessions').glob('*.json'))
            self.assertEqual(len(saved),1)
            summary = json.loads(saved[0].read_text())
            self.assertEqual(summary['rep_count'],0)
            self.assertEqual(summary['analysis']['frames'],5)
            capture = cv2.VideoCapture(str(output))
            try:
                self.assertTrue(capture.read()[0])
                self.assertEqual(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)),5)
            finally:
                capture.release()

    def test_missing_input(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable,str(Path(__file__).with_name('app.py')),
                '--source',str(Path(folder)/'missing.mp4'),'--headless'],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,1)
            self.assertIn('Cannot open',result.stderr)
            self.assertNotIn('Traceback',result.stderr)
