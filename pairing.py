import random
from typing import List, Tuple

def round_robin(names: List[str]) -> List[Tuple[str, str]]:
    shuffled = names[:]
    random.shuffle(shuffled)
    pairs = list(zip(shuffled[::2], shuffled[1::2]))
    if len(shuffled) % 2:
        pairs.append((shuffled[-1], "— bye week —"))
    return pairs

def no_recent_repeats(history, new_pairs, lookback=3):
    recent = {frozenset(p) for rnd in history[-lookback:] for p in rnd}
    return all(frozenset(p) not in recent for p in new_pairs)

