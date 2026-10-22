"""
cup_engine.py : coupe à élimination directe, INDÉPENDANTE de la ligue (aucun Qt, 100 % déterministe).

La ligue sert seulement à qualifier / inscrire des équipes ; la coupe accepte n'importe quelle liste
d'équipes (classées par tête de série, la meilleure d'abord) :

    cup = Cup([team_a, team_b, ...])      # 2 équipes ou plus
    cup.play_next_round()                 # un tour à la fois
    cup.play_all()                        # ou toute la coupe

Taille du tableau : la plus grande puissance de 2 <= nombre d'équipes (2, 4, 8, 16, 32...).
Si le nombre d'équipes n'en est pas une, un tour de BARRAGES oppose les plus mal classées pour
redescendre à cette puissance de 2 ; les mieux classées sont exemptées du tour de barrages.
Match nul après 90 min : tirs au but, déterministes eux aussi.
"""
from __future__ import annotations

from dataclasses import dataclass

from league_engine import MatchResult, Team, TeamProfile, TeamState, build_profile, clamp, play_match


# =============================================================================
# 1. OUTILS DE TABLEAU
# =============================================================================
def next_power_of_two(n: int) -> int:
    """Plus petite puissance de 2 strictement supérieure à n (6 -> 8, 8 -> 16)."""
    return 1 << n.bit_length()


def bracket_size(n_teams: int) -> int:
    """Plus grande puissance de 2 <= n_teams (6 -> 4, 8 -> 8, 20 -> 16)."""
    return 1 << (n_teams.bit_length() - 1)


def seeding_order(size: int) -> list:
    """Têtes de série dans l'ordre du tableau : 1 contre `size`, 2 contre `size-1`...
    et 1 et 2 ne peuvent se retrouver qu'en finale."""
    order = [1]
    while len(order) < size:
        n = len(order) * 2
        order = [x for s in order for x in (s, n + 1 - s)]
    return order


def round_name(n_teams_in_round: int) -> str:
    return {2: "Finale", 4: "Demi-finales", 8: "Quarts de finale", 16: "8es de finale",
            32: "16es de finale", 64: "32es de finale"}.get(n_teams_in_round, f"Tour de {n_teams_in_round}")


def describe_structure(n_teams: int) -> str:
    """Ex. : '6 équipes : 2 barrages, puis demi-finales, finale'."""
    if n_teams < 2:
        return "Il faut au moins 2 équipes."
    size, extra = bracket_size(n_teams), n_teams - bracket_size(n_teams)
    parts = []
    if extra:
        parts.append(f"{extra} match{'s' if extra > 1 else ''} de barrage")
    s = size
    while s >= 2:
        parts.append(round_name(s).lower())
        s //= 2
    return f"{n_teams} équipes : " + ", puis ".join(parts)


# =============================================================================
# 2. TIRS AU BUT (déterministes)
# =============================================================================
def _shooter_rating(profile: TeamProfile) -> float:
    takers = sorted((0.5 * p.stats["finishing"] + 0.5 * p.stats["composure"]
                     for p, role, _ in profile.xi if role != "gk"), reverse=True)[:5]
    return sum(takers) / len(takers)


def _keeper_rating(profile: TeamProfile) -> float:
    keepers = [(p.stats["gk_reflexes"] + p.stats["gk_positioning"]) / 2 for p, role, _ in profile.xi if role == "gk"]
    return keepers[0] if keepers else 50.0


def penalty_shootout(profile_a: TeamProfile, profile_b: TeamProfile, id_a: int, id_b: int) -> tuple:
    """Renvoie (tirs au but marqués par A, par B). 5 tirs chacun, puis mort subite.
    Chaque tir est converti selon la qualité des tireurs et du gardien adverse (diffusion d'erreur
    comme pour les buts, donc aucun hasard)."""
    p_a = clamp(0.58 + (_shooter_rating(profile_a) - _keeper_rating(profile_b)) / 300, 0.50, 0.78)
    p_b = clamp(0.58 + (_shooter_rating(profile_b) - _keeper_rating(profile_a)) / 300, 0.50, 0.78)
    carry_a = carry_b = 0.5
    score_a = score_b = 0

    def kick(carry: float, p: float) -> tuple:
        carry += p
        if carry >= 1 - 1e-9:
            return carry - 1.0, 1
        return carry, 0

    for _ in range(5):
        carry_a, g = kick(carry_a, p_a); score_a += g
        carry_b, g = kick(carry_b, p_b); score_b += g
    for _ in range(3):                       # mort subite (3 tours maximum)
        if score_a != score_b:
            break
        carry_a, g = kick(carry_a, p_a); score_a += g
        carry_b, g = kick(carry_b, p_b); score_b += g
    if score_a == score_b:                   # égalité parfaite (équipes identiques) : meilleur tireur, puis id
        if (p_a, -id_a) >= (p_b, -id_b):
            score_a += 1
        else:
            score_b += 1
    return score_a, score_b


# =============================================================================
# 3. MODÈLES
# =============================================================================
@dataclass
class CupMatch:
    round_index: int
    round_name: str
    home_id: int
    away_id: int
    result: MatchResult
    pens: tuple | None          # (tirs au but dom., ext.) si égalité après 90 min
    neutral: bool

    @property
    def winner_id(self) -> int:
        r = self.result
        if r.home_goals != r.away_goals:
            return self.home_id if r.home_goals > r.away_goals else self.away_id
        return self.home_id if self.pens[0] > self.pens[1] else self.away_id

    @property
    def loser_id(self) -> int:
        return self.away_id if self.winner_id == self.home_id else self.home_id


# =============================================================================
# 4. LA COUPE
# =============================================================================
class Cup:
    def __init__(self, teams: list):
        """teams : liste d'équipes, la mieux classée (tête de série 1) en premier."""
        if len(teams) < 2:
            raise ValueError("Une coupe demande au moins 2 équipes.")
        self.teams = {t.id: t for t in teams}
        self.seed = {t.id: i + 1 for i, t in enumerate(teams)}           # id -> tête de série
        n = len(teams)
        self.size = bracket_size(n)
        self.extra = n - self.size                                        # nombre de matchs de barrage
        self.profiles = {t.id: build_profile(t) for t in teams}
        self.states = {t.id: TeamState() for t in teams}

        self.bracket_order = seeding_order(self.size)                     # tête de série par position
        self.slots: list = [None] * self.size                             # slots[s-1] = équipe de tête de série s
        for i, t in enumerate(teams[:self.size - self.extra]):
            self.slots[i] = t.id
        # barrages : les plus mal classées ; la meilleure rencontre la moins bien classée
        self.barrage_slots = [self.size - self.extra + i + 1 for i in range(self.extra)]   # séries à pourvoir
        self.barrage_pairs = [(teams[self.size - self.extra + i].id, teams[n - 1 - i].id) for i in range(self.extra)]

        self.round_defs: list = []                                        # [(nom, nb de matchs)]
        if self.extra:
            self.round_defs.append(("Barrages", self.extra))
        s = self.size
        while s >= 2:
            self.round_defs.append((round_name(s), s // 2))
            s //= 2

        self.rounds: list = []                                            # tours joués : list[list[CupMatch]]
        self.field: list | None = None                                    # équipes encore en lice (ordre du tableau)
        self.champion_id: int | None = None
        if not self.extra:
            self.field = [self.slots[s - 1] for s in self.bracket_order]

    # ------------------------------------------------------------- état
    @property
    def finished(self) -> bool:
        return self.champion_id is not None

    @property
    def champion(self) -> Team | None:
        return self.teams[self.champion_id] if self.finished else None

    @property
    def has_barrages(self) -> bool:
        return self.extra > 0

    def first_round_entries(self) -> list:
        """Équipes du premier tour du tableau principal, dans l'ordre (None = barrage pas encore joué)."""
        return [self.slots[s - 1] for s in self.bracket_order]

    # ------------------------------------------------------- simulation
    def _play(self, round_index: int, name: str, id_a: int, id_b: int, neutral: bool) -> CupMatch:
        home_id, away_id = (id_a, id_b) if self.seed[id_a] < self.seed[id_b] else (id_b, id_a)
        result = play_match(round_index + 1, self.teams[home_id], self.teams[away_id],
                            self.profiles, self.states, neutral=neutral)
        pens = None
        if result.home_goals == result.away_goals:
            pens = penalty_shootout(self.profiles[home_id], self.profiles[away_id], home_id, away_id)
        return CupMatch(round_index, name, home_id, away_id, result, pens, neutral)

    def play_next_round(self) -> list:
        if self.finished:
            return []
        index = len(self.rounds)
        name = self.round_defs[index][0]

        if self.extra and index == 0:                                     # barrages
            matches = [self._play(0, name, a, b, False) for a, b in self.barrage_pairs]
            for slot_seed, m in zip(self.barrage_slots, matches):
                self.slots[slot_seed - 1] = m.winner_id
            self.field = [self.slots[s - 1] for s in self.bracket_order]
        else:
            neutral = len(self.field) == 2                                # la finale se joue sur terrain neutre
            matches = [self._play(index, name, self.field[i], self.field[i + 1], neutral)
                       for i in range(0, len(self.field), 2)]
            self.field = [m.winner_id for m in matches]
            if len(self.field) == 1:
                self.champion_id = self.field[0]
        self.rounds.append(matches)
        return matches

    def play_all(self) -> None:
        while not self.finished:
            self.play_next_round()

    @property
    def next_round_name(self) -> str | None:
        return None if self.finished else self.round_defs[len(self.rounds)][0]
