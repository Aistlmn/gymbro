"""Pixel-space geometry. No machine learning or third-party imports here."""
from dataclasses import dataclass
from math import acos, degrees, hypot, isfinite


def angle(a, b, c):
    """Angle ABC in degrees; reject coincident points instead of inventing an angle."""
    u, v = (a[0]-b[0], a[1]-b[1]), (c[0]-b[0], c[1]-b[1])
    length = hypot(*u) * hypot(*v)
    if length < 1e-6:
        raise ValueError('Coincident landmarks')
    return degrees(acos(max(-1, min(1, (u[0]*v[0]+u[1]*v[1])/length))))


SIDES = {'left': (11, 23, 25, 27, 29, 31),
         'right': (12, 24, 26, 28, 30, 32)}


@dataclass
class Metrics:
    knee: float
    hip: float
    depth: float  # hip y minus knee y, divided by thigh length; positive is lower
    hip_y: float
    scale: float
    heel: float  # toe y minus heel y, divided by foot length
    points: list


def measure(landmarks, width, height, side):
    if not landmarks or len(landmarks) < 33:
        return None
    selected = [landmarks[i] for i in SIDES[side]]
    if any(not all(isfinite(v) for v in (p.x, p.y, p.visibility, p.presence))
           or min(p.visibility, p.presence) < .6
           or not (0 <= p.x <= 1 and 0 <= p.y <= 1) for p in selected):
        return None
    points = [(p.x*width, p.y*height) for p in selected]
    shoulder, hip, knee, ankle, heel, toe = points
    thigh = hypot(hip[0]-knee[0], hip[1]-knee[1])
    foot = hypot(heel[0]-toe[0], heel[1]-toe[1])
    if thigh < 20 or foot < 12:
        return None
    try:
        return Metrics(angle(hip, knee, ankle), angle(shoulder, hip, knee),
                       (hip[1]-knee[1])/thigh, hip[1], thigh,
                       (toe[1]-heel[1])/foot, points)
    except ValueError:
        return None
