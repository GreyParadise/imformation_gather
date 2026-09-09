import array
import math

SIM_THRESHOLD = 0.86


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
