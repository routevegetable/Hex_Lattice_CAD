import math


def vec_add(a: tuple[float,float], b: tuple[float,float]) -> tuple[float,float]:
    ax,ay = a
    bx,by = b
    return (ax+bx), (ay+by)

def vec_neg(a: tuple[float,float]) -> tuple[float,float]:
    ax,ay = a
    return (-ax), (-ay)

def vec_sub(a: tuple[float,float], b: tuple[float,float]) -> tuple[float,float]:
    return vec_add(a, vec_neg(b))

def vec_len(a: tuple[float,float]) -> float:
    ax,ay = a
    return math.sqrt(ax*ax + ay*ay)

def vec_norm(a: tuple[float, float]) -> tuple[float, float]:
    ax,ay = a
    len = vec_len(a)
    if len == 0:
        return a
    return ax / len, ay / len

def vec_dot(a: tuple[float,float], b: tuple[float,float]) -> float:
    ax,ay = a
    bx,by = b
    return ax * bx + ay * by 

def vec_ccw(a: tuple[float, float]) -> tuple[float,float]:
    ax,ay = a
    return -ay, ax

def vec_mul(a: tuple[float,float], b: tuple[float,float]) -> tuple[float,float]:
    ax,ay = a
    bx,by = b
    return ax * bx, ay * by 

def vec_rot(a: tuple[float, float], cw: float) -> tuple[float,float]:
    ax,ay = a
    s = math.sin(cw)
    c = math.cos(cw)
    return (ax * c + ay * -s), (ax * s + ay * c)