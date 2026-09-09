import array
import math

from .dedupe import hamming

SIM_THRESHOLD = 0.86
SIMHASH_CLUSTER_DISTANCE = 6


def find_cluster_by_simhash(sh: int, reps: list[tuple[str, int]]) -> str | None:
    best_id = None
    best_dist = SIMHASH_CLUSTER_DISTANCE
    for cid, rsh in reps:
        d = hamming(sh or 0, rsh or 0)
        if d <= best_dist:
            best_dist = d
            best_id = cid
    return best_id


def pack_vec(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def unpack_vec(blob: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(blob)
    return list(a)


def cosine(a: list[float], b: list[float]) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def find_cluster(vec: list[float], reps: list[tuple[str, list[float]]]) -> str | None:
    best_id = None
    best_sim = SIM_THRESHOLD
    for cid, rvec in reps:
        s = cosine(vec, rvec)
        if s >= best_sim:
            best_sim = s
            best_id = cid
    return best_id
