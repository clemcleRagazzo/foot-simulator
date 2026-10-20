"""
Génère une grosse base SQLite de joueurs de foot avec ton module Faker maison (fake.py).

    python generate_players_db.py                         # 1 000 000 joueurs -> players.db
    python generate_players_db.py -n 200000 -o test.db
    python generate_players_db.py --seed 7

Même seed + même nombre de joueurs = exactement la même base.
"""
import argparse
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from fake import Faker   # si tu as renommé fake.py en faker.py : from faker import Faker

REF_DATE = date(2026, 7, 1)   # date "de référence" pour calculer les naissances


# =============================================================================
# 1. STATS
# =============================================================================
TECHNICAL_STATS = ["shooting", "finishing", "passing", "vision", "dribbling", "crossing", "heading"]
DEFENSIVE_STATS = ["tackling", "marking"]
PHYSICAL_STATS = ["pace", "acceleration", "strength", "stamina", "aggression"]
MENTAL_STATS = ["composure", "leadership"]
GOALKEEPER_STATS = ["gk_diving", "gk_handling", "gk_reflexes", "gk_positioning"]

STATS = TECHNICAL_STATS + DEFENSIVE_STATS + PHYSICAL_STATS + MENTAL_STATS + GOALKEEPER_STATS

# Aptitude à chaque poste = moyenne pondérée de stats (la somme des poids vaut 1)
POSITION_WEIGHTS = {
    "gk": {
        "gk_diving": 0.25, "gk_handling": 0.25, "gk_reflexes": 0.30, "gk_positioning": 0.20,
    },
    "def": {
        "tackling": 0.25, "marking": 0.25, "heading": 0.15, "strength": 0.15,
        "pace": 0.08, "passing": 0.07, "composure": 0.05,
    },
    "mid": {
        "passing": 0.25, "vision": 0.20, "stamina": 0.15, "dribbling": 0.12,
        "tackling": 0.08, "shooting": 0.08, "composure": 0.07, "crossing": 0.05,
    },
    "att": {
        "finishing": 0.28, "shooting": 0.20, "pace": 0.14, "dribbling": 0.14,
        "acceleration": 0.08, "composure": 0.08, "heading": 0.08,
    },
}


# =============================================================================
# 2. ARCHÉTYPES (servent seulement à façonner les stats, ils ne sont pas stockés)
#    Un joueur = mélange 70 % archétype A + 30 % archétype B -> profils hybrides.
# =============================================================================
@dataclass
class Archetype:
    frequency: int                                   # poids de tirage
    boosts: dict[str, int] = field(default_factory=dict)      # stats en plus
    penalties: dict[str, int] = field(default_factory=dict)   # stats en moins
    is_goalkeeper: bool = False

    def modifier(self, stat: str) -> int:
        """Bonus/malus pour une stat (-5 par défaut ; -50 en gardien pour un joueur de champ)."""
        if stat in self.boosts:
            return self.boosts[stat]
        if stat in self.penalties:
            return self.penalties[stat]
        if stat in GOALKEEPER_STATS and not self.is_goalkeeper:
            return -50
        return -5


ARCHETYPES = {
    "gardien": Archetype(
        frequency=5, is_goalkeeper=True,
        boosts={"gk_diving": 25, "gk_handling": 25, "gk_reflexes": 28, "gk_positioning": 25,
                "composure": 8, "leadership": 5, "strength": 3},
        penalties={"finishing": -40, "shooting": -35, "tackling": -35, "marking": -35,
                   "dribbling": -30, "crossing": -30, "pace": -20, "acceleration": -20},
    ),
    "defenseur_central": Archetype(
        frequency=17,
        boosts={"tackling": 20, "marking": 20, "heading": 18, "strength": 15,
                "aggression": 8, "composure": 5},
        penalties={"finishing": -22, "shooting": -15, "dribbling": -15, "crossing": -12,
                   "pace": -8, "vision": -8},
    ),
    "lateral": Archetype(
        frequency=12,
        boosts={"stamina": 18, "pace": 14, "crossing": 14, "acceleration": 12,
                "tackling": 8, "marking": 6},
        penalties={"finishing": -12, "heading": -8, "strength": -4},
    ),
    "milieu_defensif": Archetype(
        frequency=11,
        boosts={"tackling": 16, "stamina": 14, "marking": 10, "passing": 10,
                "strength": 10, "aggression": 8},
        penalties={"finishing": -15, "dribbling": -6, "pace": -6},
    ),
    "milieu": Archetype(
        frequency=15,
        boosts={"passing": 18, "vision": 16, "stamina": 14, "dribbling": 8,
                "composure": 8, "shooting": 2},
        penalties={"heading": -8, "strength": -4},
    ),
    "meneur": Archetype(
        frequency=9,
        boosts={"vision": 22, "passing": 16, "dribbling": 16, "composure": 10,
                "shooting": 8, "crossing": 8},
        penalties={"tackling": -15, "marking": -15, "strength": -12, "heading": -12, "stamina": -4},
    ),
    "ailier": Archetype(
        frequency=11,
        boosts={"pace": 20, "acceleration": 20, "dribbling": 18, "crossing": 12,
                "shooting": 5, "finishing": 4},
        penalties={"tackling": -14, "marking": -14, "heading": -12, "strength": -10},
    ),
    "attaquant": Archetype(
        frequency=14,
        boosts={"finishing": 22, "shooting": 18, "composure": 10, "heading": 8,
                "pace": 6, "strength": 6},
        penalties={"tackling": -22, "marking": -22, "passing": -8, "vision": -8, "stamina": -4},
    ),
    "polyvalent": Archetype(
        frequency=6,
        boosts={"stamina": 8, "passing": 4, "tackling": 4, "dribbling": 4},
    ),
}
ARCHETYPE_NAMES = list(ARCHETYPES)
ARCHETYPE_FREQUENCIES = [a.frequency for a in ARCHETYPES.values()]


# =============================================================================
# 3. IDENTITÉS : tout vient de ton Faker maison (voir fake.py / fake_data.py)
# =============================================================================
# Rien à faire ici : les prénoms, noms, pays et villes sont tirés par Faker.get_person().


# =============================================================================
# 4. GÉNÉRATION D'UN JOUEUR
# =============================================================================
def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def development_factor(age: int) -> float:
    """Les jeunes n'ont pas atteint leur potentiel, les vieux déclinent."""
    if age < 25:
        return 0.78 + 0.22 * (age - 16) / 9
    if age <= 31:
        return 1.0
    return 1.0 - 0.018 * (age - 31)


def generate_stats(rng: random.Random, level: float) -> dict[str, int]:
    """Stats d'un joueur à partir de son niveau et d'un mélange de 2 archétypes."""
    main_name, second_name = rng.choices(ARCHETYPE_NAMES, ARCHETYPE_FREQUENCIES, k=2)
    main, second = ARCHETYPES[main_name], ARCHETYPES[second_name]
    second_share = 0.3 if main_name != second_name else 0.0

    stats = {}
    for stat in STATS:
        modifier = (1 - second_share) * main.modifier(stat) + second_share * second.modifier(stat)
        stats[stat] = int(clamp(level + modifier + rng.gauss(0, 6), 1, 99))
    return stats


def compute_position_ratings(stats: dict[str, int]) -> dict[str, float]:
    return {
        position: round(sum(stats[stat] * weight for stat, weight in weights.items()), 1)
        for position, weights in POSITION_WEIGHTS.items()
    }


def make_player(player_id: int, seed: int, faker: Faker) -> tuple:
    rng = random.Random(seed * 1_000_003 + player_id)

    # Âge et niveau
    age = int(clamp(rng.triangular(16, 38, 24), 16, 38))
    potential = clamp(rng.gauss(60, 11), 30, 92)
    level = potential * development_factor(age)

    # Stats
    stats = generate_stats(rng, level)
    stats["leadership"] = int(clamp(stats["leadership"] + (age - 24) * 1.2, 1, 99))
    ratings = compute_position_ratings(stats)
    best_position = max(ratings, key=ratings.get)

    # Identité et physique
    person = faker.get_person(sex=1)   # footballeurs = hommes
    birth_date = REF_DATE - timedelta(days=age * 365 + rng.randint(0, 364))
    height = int(clamp(rng.gauss(180, 6) + (6 if best_position == "gk" else 0), 160, 205))
    weight = int(clamp((height - 100) + rng.gauss(0, 5), 55, 105))
    preferred_foot = rng.choices(["R", "L", "B"], [70, 24, 6])[0]

    return (
        player_id, person.first_name, person.last_name, birth_date.isoformat(), age,
        person.country, person.city,
        height, weight, preferred_foot, int(potential), ratings[best_position], best_position,
        ratings["gk"], ratings["def"], ratings["mid"], ratings["att"],
        *(stats[stat] for stat in STATS),
    )


# =============================================================================
# 5. SQLITE
# =============================================================================
COLUMNS = (
    [("id", "INTEGER PRIMARY KEY"),
     ("first_name", "TEXT"), ("last_name", "TEXT"),
     ("date_of_birth", "TEXT"), ("age", "INTEGER"),
     ("country", "TEXT"), ("city", "TEXT"),
     ("height_cm", "INTEGER"), ("weight_kg", "INTEGER"), ("preferred_foot", "TEXT"),
     ("potential", "INTEGER"), ("overall", "REAL"), ("best_position", "TEXT"),
     ("ovr_gk", "REAL"), ("ovr_def", "REAL"), ("ovr_mid", "REAL"), ("ovr_att", "REAL")]
    + [(stat, "INTEGER") for stat in STATS]
)
INDEXED_COLUMNS = ["overall", "best_position", "country", "age", "team_id"]


def build_database(path: str, count: int, seed: int, batch_size: int = 50_000) -> None:
    faker = Faker(seed=seed)

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = OFF")
    connection.execute("PRAGMA synchronous = OFF")
    connection.execute("DROP TABLE IF EXISTS players")

    # team_id est ajouté en dernier : vide pour l'instant, rempli plus tard
    definitions = ", ".join(f"{name} {sql_type}" for name, sql_type in COLUMNS + [("team_id", "INTEGER")])
    connection.execute(f"CREATE TABLE players ({definitions})")

    column_names = ", ".join(name for name, _ in COLUMNS)
    placeholders = ", ".join("?" * len(COLUMNS))
    insert_sql = f"INSERT INTO players ({column_names}) VALUES ({placeholders})"

    started = time.time()
    for first_id in range(1, count + 1, batch_size):
        last_id = min(first_id + batch_size - 1, count)
        rows = [make_player(pid, seed, faker) for pid in range(first_id, last_id + 1)]
        connection.executemany(insert_sql, rows)
        connection.commit()
        print(f"{last_id:>9,} / {count:,}  ({time.time() - started:.0f}s)")

    for column in INDEXED_COLUMNS:
        connection.execute(f"CREATE INDEX idx_players_{column} ON players({column})")
    connection.commit()
    connection.close()
    print(f"Terminé : {path}")


# =============================================================================
# 6. POINT D'ENTRÉE
# =============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère une base SQLite de joueurs de foot.")
    parser.add_argument("-n", "--count", type=int, default=100_000, help="nombre de joueurs")
    parser.add_argument("-o", "--output", default="players.db", help="fichier SQLite de sortie")
    parser.add_argument("--seed", type=int, default=42, help="graine de reproductibilité")
    args = parser.parse_args()

    build_database(args.output, args.count, args.seed)