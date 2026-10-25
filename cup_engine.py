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

from league_engine import MatchResult, Team, TeamProfile, TeamState, build_profile, clamp, play_match, round_robin


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
    def winner_id(self) -> int | None:
        """Vainqueur du match ; None pour un nul en poule (pas de tirs au but)."""
        r = self.result
        if r.home_goals != r.away_goals:
            return self.home_id if r.home_goals > r.away_goals else self.away_id
        if self.pens is None:
            return None
        return self.home_id if self.pens[0] > self.pens[1] else self.away_id

    @property
    def loser_id(self) -> int | None:
        if self.winner_id is None:
            return None
        return self.away_id if self.winner_id == self.home_id else self.home_id


# =============================================================================
# 4. LA COUPE
# =============================================================================
class Cup:
    def __init__(self, teams: list, ledger=None, scope=None):
        """teams : liste d'équipes, la mieux classée (tête de série 1) en premier.
        ledger : registre cartons / blessures partagé avec le championnat (coupe nationale) ; None = effectifs complets."""
        self.ledger = ledger
        self.scope = scope                                                # pour les classements de buteurs
        self.round_days: list = []                                        # journées de championnat (coupe nationale)
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
        result = play_match(100 + round_index + 1, self.teams[home_id], self.teams[away_id],
                            self.profiles, self.states, neutral=neutral, ledger=self.ledger, scope=self.scope)
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

    def result_for(self, team_id: int) -> str:
        """Parcours d'une équipe : 'Vainqueur', 'Finaliste' ou 'Éliminé en <tour>'."""
        if self.champion_id == team_id:
            return "Vainqueur"
        for matches in reversed(self.rounds):
            for m in matches:
                if team_id in (m.home_id, m.away_id):
                    if m.winner_id == team_id:
                        continue
                    return "Finaliste" if m.round_name == "Finale" else f"Éliminé en {m.round_name.lower()}"
        return "Non joué"


# =============================================================================
# 5. COUPE AVEC PHASE DE POULES
# =============================================================================
def describe_groups(n_teams: int) -> str:
    """Ex. : '16 équipes : 4 poules de 4 (les 2 premiers se qualifient), puis quarts de finale, demi-finales, finale'."""
    groups = n_teams // 4
    parts, s = [], groups * 2
    while s >= 2:
        parts.append(round_name(s).lower())
        s //= 2
    return (f"{n_teams} équipes : {groups} poule{'s' if groups > 1 else ''} de 4 (les 2 premiers se qualifient), "
            f"puis " + ", ".join(parts))


class GroupCup:
    """Coupe avec phase de poules : poules de 4 (un match contre chacun des 3 autres, 3 journées), les 2 premiers de
    chaque poule se qualifient pour une phase finale à élimination directe (un `Cup` classique, créé à la fin des
    poules). Même interface que `Cup` pour le calendrier, l'historique et les finances.

    Il faut au moins 8 équipes et une puissance de 2 (aucune équipe n'est qualifiée d'office)."""

    GROUP_ROUNDS = 3

    def __init__(self, teams: list, ledger=None, scope=None):
        n = len(teams)
        if n < 8 or n & (n - 1):
            raise ValueError("Une phase de poules demande 8, 16, 32… équipes.")
        self.ledger, self.scope = ledger, scope
        self.teams = {t.id: t for t in teams}
        self.seed = {t.id: i + 1 for i, t in enumerate(teams)}
        self.profiles = {t.id: build_profile(t) for t in teams}
        self.states = {t.id: TeamState() for t in teams}
        self.n_groups = n // 4
        # tirage en 4 chapeaux de têtes de série, « en serpent » pour équilibrer les poules
        g = self.n_groups
        self.groups: list = [[] for _ in range(g)]
        for k in range(4):
            pot = teams[k * g:(k + 1) * g]
            order = range(g) if k % 2 == 0 else range(g - 1, -1, -1)
            for index, team in zip(order, pot):
                self.groups[index].append(team.id)
        self.group_schedule = [round_robin(ids)[:self.GROUP_ROUNDS] for ids in self.groups]
        self.stats = {t.id: [0, 0, 0, 0, 0, 0, 0] for t in teams}           # J, V, N, D, BP, BC, Pts

        self.round_defs = [(f"Poules · journée {i + 1}", 2 * g) for i in range(self.GROUP_ROUNDS)]
        s = 2 * g
        while s >= 2:
            self.round_defs.append((round_name(s), s // 2))
            s //= 2
        self.group_rounds: list = []
        self.knockout: Cup | None = None
        self._round_days: list = []
        self.extra = 0
        self.has_barrages = False

    # ---------------------------------------------------------------- état
    @property
    def rounds(self) -> list:
        return self.group_rounds + (self.knockout.rounds if self.knockout else [])

    @property
    def round_days(self) -> list:
        return self._round_days

    @round_days.setter
    def round_days(self, days: list) -> None:
        self._round_days = list(days)
        if self.knockout is not None:
            self.knockout.round_days = self._round_days[self.GROUP_ROUNDS:]

    @property
    def finished(self) -> bool:
        return self.knockout is not None and self.knockout.finished

    @property
    def champion_id(self) -> int | None:
        return self.knockout.champion_id if self.knockout else None

    @property
    def champion(self) -> Team | None:
        return self.teams[self.champion_id] if self.finished else None

    @property
    def next_round_name(self) -> str | None:
        return None if self.finished else self.round_defs[len(self.rounds)][0]

    # --------------------------------------------------------------- poules
    def group_table(self, index: int) -> list:
        """[(id équipe, J, V, N, D, BP, BC, Pts)] de la poule, du 1er au dernier."""
        rows = [(tid, *self.stats[tid]) for tid in self.groups[index]]
        return sorted(rows, key=lambda r: (-r[7], -(r[5] - r[6]), -r[5], self.seed[r[0]]))

    def _play(self, round_index: int, name: str, home_id: int, away_id: int) -> CupMatch:
        result = play_match(100 + round_index + 1, self.teams[home_id], self.teams[away_id], self.profiles,
                            self.states, neutral=False, ledger=self.ledger, scope=self.scope)
        for tid, gf, ga in ((home_id, result.home_goals, result.away_goals), (away_id, result.away_goals, result.home_goals)):
            row = self.stats[tid]
            row[0] += 1
            row[4] += gf
            row[5] += ga
            if gf > ga:
                row[1] += 1
                row[6] += 3
            elif gf == ga:
                row[2] += 1
                row[6] += 1
            else:
                row[3] += 1
        return CupMatch(round_index, name, home_id, away_id, result, None, False)

    def _start_knockout(self) -> None:
        winners, runners = [], []
        for index in range(self.n_groups):
            table = self.group_table(index)
            winners.append((table[0], index))
            runners.append((table[1], index))
        key = lambda item: (-item[0][7], -(item[0][5] - item[0][6]), -item[0][5], self.seed[item[0][0]])
        winners.sort(key=key)
        runners.sort(key=key)
        # tête de série s contre 2G+1-s : on évite qu'un 1er retrouve tout de suite le 2e de sa propre poule
        for _ in range(3):
            for i, (w, wg) in enumerate(winners):
                j = self.n_groups - 1 - i
                if runners[j][1] == wg:
                    for k in range(self.n_groups):
                        if k != j and runners[k][1] != wg and winners[self.n_groups - 1 - k][1] != runners[j][1]:
                            runners[j], runners[k] = runners[k], runners[j]
                            break
        ordered = [self.teams[w[0][0]] for w in winners] + [self.teams[r[0][0]] for r in runners]
        self.knockout = Cup(ordered, ledger=self.ledger, scope=self.scope)
        self.knockout.round_days = self._round_days[self.GROUP_ROUNDS:]

    # ---------------------------------------------------------- simulation
    def play_next_round(self) -> list:
        if self.finished:
            return []
        k = len(self.group_rounds)
        if k < self.GROUP_ROUNDS:
            name = self.round_defs[k][0]
            matches = [self._play(k, name, h, a) for schedule in self.group_schedule for h, a in schedule[k]]
            self.group_rounds.append(matches)
            if k == self.GROUP_ROUNDS - 1:
                self._start_knockout()
            return matches
        return self.knockout.play_next_round()

    def play_all(self) -> None:
        while not self.finished:
            self.play_next_round()

    def result_for(self, team_id: int) -> str:
        if self.knockout is None:
            return "En poules"
        if team_id not in self.knockout.teams:
            return "Éliminé en poules"
        return self.knockout.result_for(team_id)
