"""One-time download of Google's pretrained pose model."""
from pathlib import Path
from urllib.request import urlopen
import zipfile

MODEL = Path(__file__).resolve().parent / 'models' / 'pose_landmarker_lite.task'
URL = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task'


def download():
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    if MODEL.exists() and zipfile.is_zipfile(MODEL):
        return MODEL
    temporary = MODEL.with_suffix('.tmp')
    try:
        with urlopen(URL, timeout=60) as response, temporary.open('wb') as out:
            while chunk := response.read(1024*1024):
                out.write(chunk)
        if not zipfile.is_zipfile(temporary):
            raise ValueError('Downloaded file is not a model bundle')
        temporary.replace(MODEL)
    finally:
        temporary.unlink(missing_ok=True)
    return MODEL


if __name__ == '__main__':
    print(download())
