"""
league_engine.py : moteur de la ligue (AUCUN Qt ici, tout est testable en console).

  - construit plusieurs pays x divisions de N équipes (8 à 32, nombre pair ; 16 joueurs + capitaine + entraîneur)
    depuis players.db ; promotions / relégations ; qualifiés pour les coupes interligue (voir cup_engine.py)
  - calendrier aller-retour (2 x (N-1) journées), simulable journée par journée ou en une fois
  - formations (4-4-2, 4-3-3, 3-5-2...) choisies par le coach, buteurs ET passeurs décisifs
  - simulation 100 % déterministe : mêmes équipes = mêmes résultats, aucun hasard
  - marché des transferts (joueurs sans équipe dans la base) + échanges entre équipes

Modèle de score d'un match (détaillé dans MODEL_EXPLANATION en bas du fichier).
"""
from __future__ import annotations

import bisect
import colorsys
import random
import sqlite3
import unicodedata
import zlib
from dataclasses import dataclass, field, replace

from fake import Faker
from finance import (INTERLEAGUE_FACTOR, cup_income, initial_budget, league_prize, season_statement, ticket_price,
                     transfer_fee)

# =============================================================================
# 1. CONSTANTES
# =============================================================================
STATS = [
    "pace", "acceleration", "shooting", "finishing", "passing", "vision",
    "dribbling", "crossing", "heading", "tackling", "marking", "strength",
    "stamina", "aggression", "composure", "leadership",
    "gk_diving", "gk_handling", "gk_reflexes", "gk_positioning",
]
ROLES = ("gk", "def", "mid", "att")
ROLE_LABELS = {"gk": "GB", "def": "DEF", "mid": "MIL", "att": "ATT"}

# Chaque formation = lignes de l'arrière vers l'avant : (poste, nombre de joueurs).
# Les lignes servent aussi à dessiner le terrain.
FORMATIONS = {
    "4-4-2":   (("gk", 1), ("def", 4), ("mid", 4), ("att", 2)),
    "4-3-3":   (("gk", 1), ("def", 4), ("mid", 3), ("att", 3)),
    "3-5-2":   (("gk", 1), ("def", 3), ("mid", 5), ("att", 2)),
    "4-2-3-1": (("gk", 1), ("def", 4), ("mid", 2), ("mid", 3), ("att", 1)),
    "5-3-2":   (("gk", 1), ("def", 5), ("mid", 3), ("att", 2)),
    "3-4-3":   (("gk", 1), ("def", 3), ("mid", 4), ("att", 3)),
}
# (multiplicateur attaque, multiplicateur défense) : +-1 % sur les notes d'équipe, effet léger
FORMATION_MODS = {
    "4-4-2": (1.00, 1.00), "4-3-3": (1.01, 0.99), "3-5-2": (1.00, 1.00),
    "4-2-3-1": (1.00, 1.01), "5-3-2": (0.99, 1.01), "3-4-3": (1.01, 0.99),
}
DEFAULT_FORMATION = "4-4-2"


@dataclass
class GameOptions:
    """Options de jeu (modifiables dans le menu Options). Elles s'appliquent aux prochains matchs joués."""
    cards: bool = True            # cartons jaunes / rouges, suspensions, jeu à 10
    injuries: bool = True         # blessures (qui durent plusieurs matchs)
    crowd_bonus: bool = False     # l'affluence du stade donne un petit bonus à domicile
    relegation: bool = True       # promotions / relégations entre divisions en fin de saison
    interleague_groups: bool = False   # coupes interligue : phase de poules avant l'élimination directe
    finance_strict: bool = False  # True : un transfert plus cher que le budget est refusé (sinon indicatif seulement)


OPTIONS = GameOptions()

YELLOW_BASE = 0.15                # cartons jaunes attendus par joueur et par match (moyenne)
RED_BASE = 0.002                  # rouges directs attendus par joueur et par match
SECOND_YELLOW_RATE = 0.012        # chance qu'un joueur déjà averti prenne un second jaune
CARD_ROLE_WEIGHT = {"gk": 0.12, "def": 1.2, "mid": 1.1, "att": 0.75}
YELLOWS_FOR_BAN = 5               # 5 jaunes cumulés = 1 match de suspension
INJURY_BASE = 0.011               # blessures attendues par joueur et par match
RED_CARD_SELF_LOSS = 0.40         # une équipe à 10 perd ~40 % de ses buts attendus sur le temps restant
RED_CARD_OPP_GAIN = 0.15          # et l'adversaire en gagne ~15 %
NEUTRAL_CAPACITY = 80000          # stade neutre des finales
STADIUM_WORDS = ["Stade", "Parc des Sports", "Arena", "Stade Municipal", "Stade Olympique", "Colisée"]
SHIRT_PRIORITY = {"gk": [1], "def": [4, 5, 3, 2, 6], "att": [9, 11, 7], "mid": [10, 8, 6, 7, 11, 14, 16]}


def formation_counts(name: str) -> dict:
    counts = {role: 0 for role in ("gk", "def", "mid", "att")}
    for role, n in FORMATIONS[name]:
        counts[role] += n
    return counts


# Zones du classement final : (places interligue 1 = bleu, interligue 2 = orange, relégués = rouge)
def league_zones(n_teams: int) -> tuple:
    return (3, 3, 2) if n_teams >= 10 else (2, 2, 2)


MIN_TEAMS, MAX_TEAMS = 8, 32

SQUAD_XI = 11
SQUAD_COMPOSITION = {"gk": 2, "def": 5, "mid": 5, "att": 4}   # 16 joueurs
SQUAD_SIZE = sum(SQUAD_COMPOSITION.values())

# --- paramètres du modèle de match (tout est ici, modifiable) -----------------
BASE_GOALS = 1.30          # buts attendus d'une équipe moyenne contre une équipe moyenne
K = 2.6                    # sensibilité à l'écart de niveau attaque / défense
HOME_ATTACK = 1.07         # bonus de l'équipe qui reçoit
AWAY_ATTACK = 0.97         # malus de l'équipe qui se déplace
MOOD_MAX_DIFF = 6          # l'écart de buts cumulé des 3 derniers matchs est borné à +-6
MOOD_STRENGTH = 0.08       # humeur maximale = +-8 % de buts attendus
SCORING_ROLE_WEIGHT = {"gk": 0.0, "def": 0.15, "mid": 0.5, "att": 1.0}
ASSIST_RATE = 0.75         # part des buts qui ont un passeur décisif
ASSIST_ROLE_WEIGHT = {"gk": 0.02, "def": 0.35, "mid": 1.0, "att": 0.7}


# =============================================================================
# 2. MODÈLES
# =============================================================================
@dataclass(slots=True)
class Player:
    id: int
    first_name: str
    last_name: str
    age: int
    country: str
    city: str
    preferred_foot: str
    potential: int
    overall: float
    best_position: str
    ovr: dict            # {"gk":.., "def":.., "mid":.., "att":..}
    stats: dict          # les 20 stats
    injury_resistance: int = 60       # 1-99 : plus c'est haut, moins il se blesse
    number: int | None = None         # numéro de maillot
    nickname: str | None = None       # surnom gagné au fil des saisons

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def foul_index(self) -> float:
        """Propension à commettre des fautes (5-100) : agressivité, tacles, force, manque de sang-froid,
        + inexpérience (jeune et/or note basse = plus de fautes ; vétéran avec une bonne note = moins)."""
        s = self.stats
        base = 0.50 * s["aggression"] + 0.15 * s["tackling"] + 0.10 * s["strength"] + 0.25 * (100 - s["composure"])
        youth = max(0, 27 - self.age) * 1.4
        weak = max(0.0, 60 - self.overall) * 0.5
        veteran = max(0, self.age - 27) * 0.5 if self.overall >= 55 else 0.0
        return max(5.0, min(100.0, base + youth + weak - veteran))


@dataclass
class Coach:
    name: str
    tactics: int       # 1-99
    motivation: int    # 1-99

    @property
    def factor(self) -> float:
        """+-5 % maximum sur les buts attendus."""
        return 1 + ((self.tactics + self.motivation) / 2 - 50) / 1000


@dataclass
class Team:
    id: int
    name: str
    short: str
    city: str
    primary: str
    secondary: str
    pattern: str
    coach: Coach
    players: list = field(default_factory=list)
    captain_id: int | None = None
    formation: str = DEFAULT_FORMATION
    country: str = "France"
    division: int = 1
    stadium: str = ""
    capacity: int = 0
    budget: int = 0                   # budget au début de la saison (euros) ; indicatif

    def update_capacity(self) -> None:
        """La capacité du stade suit la note de l'équipe, mais ne diminue jamais."""
        self.capacity = max(self.capacity, capacity_for(self.overall_rating))

    @property
    def captain(self) -> Player | None:
        return next((p for p in self.players if p.id == self.captain_id), None)

    def elect_captain(self) -> None:
        """Le capitaine est le joueur au plus fort leadership (à égalité : le plus âgé)."""
        if self.players:
            best = max(self.players, key=lambda p: (p.stats["leadership"], p.age, -p.id))
            self.captain_id = best.id

    def best_xi(self, formation: str | None = None, exclude=None) -> list:
        """11 titulaires dans la formation : [(joueur, rôle), ...]. Choix glouton GB -> DEF -> ATT -> MIL.
        exclude : ids des joueurs indisponibles (blessés / suspendus), remplacés par les meilleurs disponibles."""
        counts = formation_counts(formation or self.formation)
        remaining = [p for p in self.players if not exclude or p.id not in exclude]
        if len(remaining) < SQUAD_XI:                       # sécurité : on rappelle des absents si besoin
            have = {p.id for p in remaining}
            remaining += [p for p in self.players if p.id not in have][:SQUAD_XI - len(remaining)]
        xi = []
        for role in ("gk", "def", "att", "mid"):
            remaining.sort(key=lambda p: (-p.ovr[role], p.id))
            chosen, remaining = remaining[:counts[role]], remaining[counts[role]:]
            xi += [(p, role) for p in chosen]
        return xi

    @property
    def overall_rating(self) -> float:
        if not self.players:
            return 0.0

        return round(
            sum(
                sum(p.ovr.values()) / len(p.ovr)
                for p in self.players
            ) / len(self.players),
            2
        )


# --- rapports de simulation ---------------------------------------------------
@dataclass
class TeamProfile:
    xi: list                  # [(joueur, rôle, note dans ce rôle)]
    attack: float
    defense: float
    depth_factor: float
    captain_factor: float
    coach_factor: float
    captain_in_xi: bool
    formation: str = DEFAULT_FORMATION


@dataclass
class SideReport:
    team_id: int
    attack: float
    defense: float
    ratio: float              # attaque / défense adverse
    last3: list               # 3 derniers écarts de buts
    mood_factor: float
    coach_factor: float
    captain_factor: float
    depth_factor: float
    multiplier: float
    venue_factor: float
    xg: float
    lineup: list              # [(nom, rôle, note)]
    formation: str = DEFAULT_FORMATION
    captain_name: str | None = None
    absent: list = field(default_factory=list)     # [(nom, raison)] absents pour ce match
    event_factor: float = 1.0                       # effet des incidents (rouge, blessure) sur les buts attendus


@dataclass
class CardEvent:
    minute: int
    team_id: int
    player_id: int
    player_name: str
    kind: str                  # "yellow" | "second_yellow" | "red"
    violent: bool = False
    ban: int = 0               # matchs de suspension


@dataclass
class InjuryEvent:
    minute: int
    team_id: int
    player_id: int
    player_name: str
    matches: int               # durée de l'absence (en matchs)
    label: str
    sub_id: int | None = None
    sub_name: str | None = None
    sub: object = None         # joueur remplaçant (objet)
    role: str = ""
    drop: float = 0.0          # perte de niveau entre le blessé et son remplaçant


@dataclass
class GoalEvent:
    minute: int
    team_id: int
    player_id: int
    player_name: str
    assist_id: int | None = None
    assist_name: str | None = None


@dataclass
class MatchResult:
    matchday: int
    home_id: int
    away_id: int
    home_goals: int
    away_goals: int
    home: SideReport
    away: SideReport
    goals: list
    cards: list = field(default_factory=list)
    injuries: list = field(default_factory=list)
    attendance: int = 0
    capacity: int = 0
    neutral: bool = False


@dataclass
class TableRow:
    team_id: int
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0
    pts: int = 0
    rank: int = 0
    form: list = field(default_factory=list)   # derniers résultats : "V", "N", "D"

    @property
    def gd(self) -> int:
        return self.gf - self.ga


@dataclass
class SeasonResult:
    matchdays: list           # list[list[MatchResult]] : uniquement les journées déjà jouées
    tables: list              # tables[i] = classement après la journée i (tables[0] = avant le début)
    scorers: dict             # player_id -> [nom, team_id, buts]
    assisters: dict           # player_id -> [nom, team_id, passes décisives]
    profiles: dict            # team_id -> TeamProfile
    total_days: int = 0

    @property
    def played(self) -> int:
        return len(self.matchdays)

    @property
    def finished(self) -> bool:
        return self.played >= self.total_days

    @property
    def current_table(self) -> list:
        return self.tables[-1]

    @property
    def final_table(self) -> list:
        return self.tables[-1]

    def matches_of(self, team_id: int) -> list:
        return [m for day in self.matchdays for m in day if team_id in (m.home_id, m.away_id)]

    def top_scorers(self, n: int = 30) -> list:
        return sorted(self.scorers.items(), key=lambda kv: (-kv[1][2], kv[1][0]))[:n]

    def top_assisters(self, n: int = 30) -> list:
        return sorted(self.assisters.items(), key=lambda kv: (-kv[1][2], kv[1][0]))[:n]


@dataclass
class TeamState:
    """État mutable d'une équipe PENDANT une simulation."""
    recent_diffs: list = field(default_factory=list)
    residual: float = 0.0                             # reste d'arrondi des buts (diffusion d'erreur)
    credit: dict = field(default_factory=dict)        # crédit de buts par joueur
    assist_credit: dict = field(default_factory=dict)  # crédit de passes décisives par joueur
    assist_carry: float = 0.25                        # reste d'arrondi des passes décisives


# =============================================================================
# 3. CALCUL DU MATCH (fonctions pures, déterministes)
# =============================================================================
def clamp(value, low, high):
    return max(low, min(high, value))


def _seed01(*parts) -> float:
    """Valeur pseudo-aléatoire STABLE dans [0, 1) : même entrée = même sortie (aucun vrai hasard)."""
    return zlib.crc32(":".join(str(p) for p in parts).encode()) % 10000 / 10000


def capacity_for(rating: float) -> int:
    """Capacité du stade selon la note générale de l'équipe (36 -> ~8 000 places, 56 et plus -> 80 000)."""
    x = clamp((rating - 36) / 20, 0.0, 1.0)
    return int(round((8000 + 72000 * x ** 1.3) / 500) * 500)


# --------------------------------------------------------------- numéros de maillot
def slot_numbers(formation: str) -> dict:
    """Numéros du onze selon la formation, par poste : {"gk": [1], "def": [4, 5, 3, 2], ...}.
    Le meilleur joueur d'un poste prend le premier numéro de la liste (ex. le meilleur milieu = le 10)."""
    counts, used, out = formation_counts(formation), set(), {}
    for role in ("gk", "def", "att", "mid"):
        numbers = [n for n in SHIRT_PRIORITY[role] if n not in used][:counts[role]]
        used.update(numbers)
        out[role] = numbers
    return out


def assign_numbers(team: Team) -> None:
    """Numérote l'effectif : les titulaires habituels prennent le numéro de leur poste (selon la formation),
    les remplaçants gardent leur numéro (12 et plus) s'il est libre, sinon prennent le premier libre.
    Un remplaçant qui devient titulaire hérite donc du numéro du poste (ex. le 10)."""
    nums = slot_numbers(team.formation)
    starters, by_role = {}, {}
    for p, role in team.best_xi(team.formation):
        by_role.setdefault(role, []).append(p)
    for role, players in by_role.items():
        for p, n in zip(players, nums[role]):
            starters[p.id] = n
    taken = set(starters.values())
    for p in team.players:
        if p.id in starters:
            p.number = starters[p.id]
    for p in sorted((p for p in team.players if p.id not in starters), key=lambda q: (-q.overall, q.id)):
        if p.number is not None and p.number >= 12 and p.number not in taken:
            taken.add(p.number)
        else:
            p.number = None
    n = 12
    for p in sorted((p for p in team.players if p.id not in starters and p.number is None),
                    key=lambda q: (-q.overall, q.id)):
        while n in taken:
            n += 1
        p.number, n = n, n + 1
        taken.add(p.number)


# --------------------------------------------------------------- disponibilité (cartons / blessures)
class Ledger:
    """Disponibilité et statistiques de saison de tous les joueurs. Partagé par les championnats et les coupes
    nationales : un joueur suspendu ou blessé ne joue aucun de ces matchs."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.yellows: dict = {}              # pid -> jaunes cumulés
        self.suspended: dict = {}            # pid -> matchs de suspension restants
        self.injured: dict = {}              # pid -> [matchs restants, nom de la blessure]
        self.credits: dict = {"y": {}, "r": {}, "s": {}, "i": {}}
        self.stats: dict = {}                # pid -> {games, goals, assists, yellow, red, injuries}
        self.scope_stats: dict = {}          # compétition -> {pid: [nom, team_id, buts, passes]}
        self.finance: dict = {}              # team_id -> {"billetterie"|"ventes"|"achats": euros} de la saison

    def new_season(self) -> None:
        """Nouvelle saison : les blessures en cours continuent, le reste repart à zéro."""
        self.yellows, self.suspended, self.stats, self.scope_stats, self.finance = {}, {}, {}, {}, {}

    def money(self, team_id: int, kind: str, amount: float) -> None:
        """Enregistre une recette ou une dépense réelle d'un club (billetterie, ventes ou achats de joueurs)."""
        row = self.finance.setdefault(team_id, {})
        row[kind] = row.get(kind, 0.0) + amount

    def aggregate(self, keep) -> dict:
        """Cumule buts et passes des compétitions pour lesquelles keep(scope) est vrai : {pid: [nom, team_id, buts, passes]}.
        scope = ("league", pays, division) | ("cup", pays) | ("inter", "blue" ou "orange")."""
        out: dict = {}
        for scope, rows in self.scope_stats.items():
            if keep(scope):
                for pid, (name, team_id, goals, assists) in rows.items():
                    row = out.setdefault(pid, [name, team_id, 0, 0])
                    row[2] += goals
                    row[3] += assists
        return out

    def stat(self, pid: int) -> dict:
        return self.stats.setdefault(pid, {"games": 0, "goals": 0, "assists": 0, "yellow": 0, "red": 0, "injuries": 0})

    def credit(self, kind: str, pid: int) -> float:
        return self.credits[kind].get(pid, _seed01(kind, pid))      # départ échelonné d'un joueur à l'autre

    def absent(self, team: Team) -> dict:
        """{id du joueur: raison} des joueurs indisponibles pour le prochain match de l'équipe."""
        out = {}
        for p in team.players:
            left = self.suspended.get(p.id, 0)
            if left > 0:
                out[p.id] = f"suspendu ({left} match{'s' if left > 1 else ''})"
            elif p.id in self.injured and self.injured[p.id][0] > 0:
                n, label = self.injured[p.id]
                out[p.id] = f"{label} ({n} match{'s' if n > 1 else ''})"
        return out

    def status_of(self, player: Player) -> str | None:
        left = self.suspended.get(player.id, 0)
        if left > 0:
            return f"⛔ suspendu ({left})"
        if player.id in self.injured and self.injured[player.id][0] > 0:
            return f"🩹 {self.injured[player.id][1]} ({self.injured[player.id][0]})"
        return None


INJURY_LABELS = [(2, "Petit coup"), (4, "Crampe tenace"), (6, "Élongation"), (10, "Entorse de la cheville"),
                 (15, "Déchirure musculaire"), (22, "Fracture du métatarse"), (30, "Rupture des ligaments croisés")]


def _tilt(player: Player) -> float:
    return clamp(player.foul_index / 50, 0.3, 2.0)


def injury_duration(key: str, player: Player) -> int:
    """Gravité : 1 à 30 matchs, selon un tirage stable et la résistance du joueur (plus il résiste, plus c'est court)."""
    u = _seed01(key, player.id, "sev") ** (0.7 + player.injury_resistance / 80)
    if u < 0.50:
        n = 1 + int(u / 0.5 * 2)
    elif u < 0.80:
        n = 3 + int((u - 0.5) / 0.3 * 4)
    elif u < 0.95:
        n = 7 + int((u - 0.8) / 0.15 * 9)
    else:
        n = 16 + int((u - 0.95) / 0.05 * 15)
    return min(n, 30)


def side_incidents(team: Team, prof: "TeamProfile", opp_prof: "TeamProfile", ledger: Ledger, key: str) -> tuple:
    """Cartons et blessures d'une équipe pour ce match. Déterministe : chaque joueur accumule du « crédit »
    (fautes, risque de blessure) qui se déclenche quand il atteint 1, avec un départ échelonné."""
    cards, injuries = [], []
    opts = OPTIONS
    opp_tilt = sum(_tilt(p) for p, _, _ in opp_prof.xi) / len(opp_prof.xi)       # adversaire dur = plus de blessés
    xi_ids = {p.id for p, _, _ in prof.xi}
    absent = ledger.absent(team)
    bench = [p for p in team.players if p.id not in xi_ids and p.id not in absent]
    for player, role, rating in prof.xi:
        t = _tilt(player)
        red_minute = None
        if opts.cards:
            y = ledger.credit("y", player.id) + YELLOW_BASE * CARD_ROLE_WEIGHT[role] * t
            got_yellow = y >= 1 - 1e-9
            ledger.credits["y"][player.id] = y - 1.0 if got_yellow else y
            r = ledger.credit("r", player.id) + RED_BASE * CARD_ROLE_WEIGHT[role] * t ** 1.5
            got_red = r >= 1 - 1e-9
            ledger.credits["r"][player.id] = r - 1.0 if got_red else r
            if got_red:
                red_minute = 8 + zlib.crc32(f"{key}:{player.id}:r".encode()) % 80
                violent = _seed01(key, player.id, "v") < min(0.6, 0.12 * t)
                cards.append(CardEvent(red_minute, team.id, player.id, player.name, "red", violent, 3 if violent else 2))
            elif got_yellow:
                m1 = 5 + zlib.crc32(f"{key}:{player.id}:y".encode()) % 70
                cards.append(CardEvent(m1, team.id, player.id, player.name, "yellow"))
                sc = ledger.credit("s", player.id) + SECOND_YELLOW_RATE * t
                if sc >= 1 - 1e-9:
                    sc -= 1.0
                    red_minute = min(90, m1 + 8 + zlib.crc32(f"{key}:{player.id}:y2".encode()) % 25)
                    cards.append(CardEvent(red_minute, team.id, player.id, player.name, "second_yellow", False, 1))
                ledger.credits["s"][player.id] = sc
        if opts.injuries and red_minute is None:
            p = (INJURY_BASE * (0.5 if role == "gk" else 1.0) * clamp(1.6 - player.injury_resistance / 80, 0.35, 1.6)
                 * (1 + max(0, player.age - 29) * 0.04 + max(0, 21 - player.age) * 0.02) * (0.75 + 0.5 * opp_tilt))
            i = ledger.credit("i", player.id) + p
            hurt = i >= 1 - 1e-9
            ledger.credits["i"][player.id] = i - 1.0 if hurt else i
            if hurt:
                minute = 3 + zlib.crc32(f"{key}:{player.id}:i".encode()) % 85
                matches = injury_duration(key, player)
                label = next(name for limit, name in INJURY_LABELS if matches <= limit)
                sub = max(bench, key=lambda b: (b.ovr[role], -b.id)) if bench else None
                if sub:
                    bench.remove(sub)
                injuries.append(InjuryEvent(minute, team.id, player.id, player.name, matches, label,
                                            sub.id if sub else None, sub.name if sub else None, sub, role,
                                            max(0.0, rating - sub.ovr[role]) if sub else 0.0))
    return cards, injuries


def event_factors(cards: list, injuries: list) -> tuple:
    """(facteur sur ses propres buts attendus, facteur sur ceux de l'adversaire) dû aux incidents du match."""
    own = opp = 1.0
    for c in cards:
        if c.kind in ("red", "second_yellow"):
            f = (90 - c.minute) / 90
            own *= 1 - RED_CARD_SELF_LOSS * f
            opp *= 1 + RED_CARD_OPP_GAIN * f
    for inj in injuries:
        f = (90 - inj.minute) / 90
        own *= 1 - (clamp(inj.drop, 0, 30) / 100 * 0.3 * f if inj.sub else 0.10 * f)
    return own, opp


def compute_attendance(home: Team, away: Team, state: "TeamState", matchday: int, neutral: bool) -> tuple:
    """(affluence, capacité). Dépend de la note du club, de sa forme, du niveau de l'adversaire et du jour."""
    if neutral:
        capacity, rating = NEUTRAL_CAPACITY, (home.overall_rating + away.overall_rating) / 2
    else:
        capacity, rating = home.capacity or capacity_for(home.overall_rating), home.overall_rating
    rel = clamp((rating - 36) / 20, 0.0, 1.0)
    form = clamp(sum(state.recent_diffs[-5:]) / 10, -1.0, 1.0) * 0.06
    opp = (clamp((away.overall_rating - 36) / 20, 0.0, 1.0) - 0.5) * 0.10
    day = (zlib.crc32(f"{home.id}:{matchday}".encode()) % 9 - 4) / 100
    fill = clamp(0.50 + 0.30 * rel + form + opp + day, 0.25, 1.0)
    return int(round(capacity * fill / 10) * 10), capacity


# --------------------------------------------------------------- profils
def attack_defense(team: Team, formation: str, exclude=None) -> tuple:
    """(attaque, défense, onze) de l'équipe dans une formation donnée, modificateur de formation inclus."""
    xi = team.best_xi(formation, exclude)
    ratings = {role: [p.ovr[role] for p, r in xi if r == role] for role in ROLES}
    attack = (sum(ratings["att"]) + 0.5 * sum(ratings["mid"])) / (len(ratings["att"]) + 0.5 * len(ratings["mid"]))
    defense = (sum(ratings["def"]) + 0.4 * sum(ratings["mid"]) + 1.5 * sum(ratings["gk"])) / (
        len(ratings["def"]) + 0.4 * len(ratings["mid"]) + 1.5 * len(ratings["gk"]))
    mod_att, mod_def = FORMATION_MODS[formation]
    return attack * mod_att, defense * mod_def, xi


def choose_formation(team: Team, exclude=None) -> str:
    """Le coach choisit la formation qui met le mieux en valeur son effectif (attaque x défense)."""
    best, best_score = DEFAULT_FORMATION, -1.0
    for name in FORMATIONS:
        attack, defense, _ = attack_defense(team, name, exclude)
        if attack * defense > best_score + 1e-9:
            best, best_score = name, attack * defense
    return best


def build_profile(team: Team, exclude=None) -> TeamProfile:
    """exclude : ids des absents. Le coach adapte alors sa formation à l'effectif disponible."""
    formation = choose_formation(team, exclude) if exclude else team.formation
    attack, defense, xi = attack_defense(team, formation, exclude)
    xi_ids = {p.id for p, _ in xi}

    bench = [p for p in team.players if p.id not in xi_ids]
    bench_avg = sum(max(p.ovr.values()) for p in bench) / len(bench) if bench else 60.0
    depth_factor = 1 + (bench_avg - 60) / 600                      # banc : +-1.6 %

    captain = team.captain
    leadership = captain.stats["leadership"] if captain else 50
    in_xi = bool(captain and captain.id in xi_ids)
    captain_factor = 1 + (leadership - 50) / 1500 * (1.0 if in_xi else 0.5)   # +-3 %

    return TeamProfile(
        xi=[(p, r, p.ovr[r]) for p, r in xi],
        attack=attack, defense=defense,
        depth_factor=depth_factor, captain_factor=captain_factor,
        coach_factor=team.coach.factor, captain_in_xi=in_xi, formation=formation,
    )


def mood_factor(state: TeamState, coach: Coach) -> tuple:
    """Humeur = écart de buts cumulé sur les 3 derniers matchs. Un coach motivé amplifie l'effet."""
    last3 = state.recent_diffs[-3:]
    index = clamp(sum(last3), -MOOD_MAX_DIFF, MOOD_MAX_DIFF) / MOOD_MAX_DIFF      # -1 .. +1
    amplification = 0.75 + 0.5 * coach.motivation / 100                          # 0.75 .. 1.25
    return 1 + MOOD_STRENGTH * index * amplification, list(last3)


def expected_goals(att_attack: float, def_defense: float, att_mult: float, def_mult: float, venue: float) -> float:
    """xG = BASE x (attaque / défense adverse)^K x forme x lieu / racine(forme adverse)."""
    ratio = att_attack / def_defense
    return BASE_GOALS * ratio ** K * att_mult / def_mult ** 0.5 * venue


def convert_to_goals(state: TeamState, xg: float) -> int:
    """Diffusion d'erreur : on arrondit xG + reste des matchs précédents, puis on garde le nouveau reste.
    Déterministe, et sur une saison le total de buts colle exactement au total de buts attendus."""
    value = xg + state.residual
    goals = max(0, int(value + 0.5))
    state.residual = value - goals
    return goals


# --------------------------------------------------------------- buteurs et passeurs
def active_players(prof: TeamProfile, cards: list, injuries: list, minute: int) -> list:
    """[(joueur, rôle)] sur le terrain à cette minute : ni exclus, ni blessés, avec les remplaçants entrés."""
    active = {p.id: (p, r) for p, r, _ in prof.xi}
    changes = [(c.minute, 0, c) for c in cards if c.kind in ("red", "second_yellow")]
    changes += [(i.minute, 1, i) for i in injuries]
    for m, _, ev in sorted(changes, key=lambda x: (x[0], x[1])):
        if m > minute:
            break
        active.pop(ev.player_id, None)
        if isinstance(ev, InjuryEvent) and ev.sub is not None:
            active[ev.sub.id] = (ev.sub, ev.role)
    return list(active.values())


def scoring_shares(active: list) -> dict:
    """Part de buts théorique de chaque joueur sur le terrain (finition/tir, selon son rôle)."""
    raw = {}
    for player, role in active:
        s = player.stats
        skill = (0.5 * s["finishing"] + 0.3 * s["shooting"] + 0.1 * s["composure"] + 0.1 * s["heading"]) / 100
        weight = skill ** 3 * SCORING_ROLE_WEIGHT[role]
        if weight > 0:
            raw[player.id] = weight
    total = sum(raw.values()) or 1.0
    return {pid: w / total for pid, w in raw.items()}


def assist_weights(active: list) -> dict:
    """Poids de passeur de chaque joueur sur le terrain (passe, vision, centres, selon son poste)."""
    raw = {}
    for player, role in active:
        s = player.stats
        skill = (0.45 * s["passing"] + 0.35 * s["vision"] + 0.20 * s["crossing"]) / 100
        raw[player.id] = skill ** 3 * ASSIST_ROLE_WEIGHT[role]
    return raw


def assign_scorers(team: Team, prof: TeamProfile, state: TeamState, goals: int, key: str,
                   cards: list | None = None, injuries: list | None = None) -> list:
    """Attribue chaque but au joueur dont le crédit est le plus élevé (méthode du plus fort reste), parmi ceux
    qui sont sur le terrain à la minute du but. Puis ASSIST_RATE des buts ont un passeur décisif."""
    cards, injuries = cards or [], injuries or []
    events = []
    for k in range(goals):
        base = (k + 1) * 90 / (goals + 1)
        jitter = zlib.crc32(f"{key}:{team.id}:{k}".encode()) % 21 - 10        # déterministe
        minute = int(clamp(round(base + jitter), 1, 90))
        active = active_players(prof, cards, injuries, minute)
        names = {p.id: p.name for p, _ in active}
        shares = scoring_shares(active)
        for pid, share in shares.items():
            state.credit[pid] = state.credit.get(pid, 0.0) + share
        scorer = max(shares, key=lambda pid: (state.credit[pid], -pid))
        state.credit[scorer] -= 1.0

        assist_id = None
        state.assist_carry += ASSIST_RATE
        if state.assist_carry >= 1 - 1e-9:
            state.assist_carry -= 1.0
            pool = {pid: w for pid, w in assist_weights(active).items() if pid != scorer}
            if pool:
                total = sum(pool.values())
                for pid, w in pool.items():
                    state.assist_credit[pid] = state.assist_credit.get(pid, 0.0) + w / total
                assist_id = max(pool, key=lambda pid: (state.assist_credit[pid], -pid))
                state.assist_credit[assist_id] -= 1.0
        events.append(GoalEvent(minute, team.id, scorer, names[scorer],
                                assist_id, names[assist_id] if assist_id else None))
    return events


def ledger_after_match(ledger: Ledger, side: dict) -> None:
    """Met à jour suspensions, blessures, cartons et statistiques après un match (pour une équipe)."""
    for pid in side["absent"]:                                   # un match manqué de plus
        if ledger.suspended.get(pid, 0) > 0:
            ledger.suspended[pid] -= 1
            if ledger.suspended[pid] <= 0:
                del ledger.suspended[pid]
        if pid in ledger.injured:
            ledger.injured[pid][0] -= 1
            if ledger.injured[pid][0] <= 0:
                del ledger.injured[pid]
    for p, _, _ in side["prof"].xi:
        ledger.stat(p.id)["games"] += 1
    for inj in side["injuries"]:
        ledger.injured[inj.player_id] = [inj.matches, inj.label]
        ledger.stat(inj.player_id)["injuries"] += 1
        if inj.sub_id is not None:
            ledger.stat(inj.sub_id)["games"] += 1
    for c in side["cards"]:
        st = ledger.stat(c.player_id)
        if c.kind == "yellow":
            st["yellow"] += 1
            ledger.yellows[c.player_id] = ledger.yellows.get(c.player_id, 0) + 1
            if ledger.yellows[c.player_id] >= YELLOWS_FOR_BAN:
                ledger.yellows[c.player_id] = 0
                ledger.suspended[c.player_id] = max(ledger.suspended.get(c.player_id, 0), 1)
        else:
            st["red"] += 1
            ledger.suspended[c.player_id] = max(ledger.suspended.get(c.player_id, 0), c.ban)
    scope_rows = ledger.scope_stats.setdefault(side["scope"], {}) if side.get("scope") is not None else None
    for e in side["goals"]:
        ledger.stat(e.player_id)["goals"] += 1
        if scope_rows is not None:
            scope_rows.setdefault(e.player_id, [e.player_name, e.team_id, 0, 0])[2] += 1
        if e.assist_id is not None:
            ledger.stat(e.assist_id)["assists"] += 1
            if scope_rows is not None:
                scope_rows.setdefault(e.assist_id, [e.assist_name, e.team_id, 0, 0])[3] += 1


def play_match(matchday: int, home: Team, away: Team, profiles: dict, states: dict,
               neutral: bool = False, ledger: Ledger | None = None, scope=None) -> MatchResult:
    """ledger = None : effectifs complets, aucun incident (ex. coupes interligue)."""
    key = f"{matchday}:{home.id}:{away.id}"
    absent_h = ledger.absent(home) if ledger else {}
    absent_a = ledger.absent(away) if ledger else {}
    ph = build_profile(home, set(absent_h)) if absent_h else profiles[home.id]
    pa = build_profile(away, set(absent_a)) if absent_a else profiles[away.id]
    sh, sa = states[home.id], states[away.id]

    attendance, capacity = compute_attendance(home, away, sh, matchday, neutral)
    fill = attendance / capacity if capacity else 0.0
    mood_h, last3_h = mood_factor(sh, home.coach)
    mood_a, last3_a = mood_factor(sa, away.coach)
    mult_h = mood_h * ph.coach_factor * ph.captain_factor * ph.depth_factor
    mult_a = mood_a * pa.coach_factor * pa.captain_factor * pa.depth_factor

    venue_h, venue_a = (1.0, 1.0) if neutral else (HOME_ATTACK, AWAY_ATTACK)
    if OPTIONS.crowd_bonus and not neutral:
        venue_h *= 1 + 0.05 * fill ** 2
        venue_a *= 1 - 0.02 * fill ** 2
    xg_h = expected_goals(ph.attack, pa.defense, mult_h, mult_a, venue_h)
    xg_a = expected_goals(pa.attack, ph.defense, mult_a, mult_h, venue_a)

    cards_h = inj_h = cards_a = inj_a = []
    if ledger:
        cards_h, inj_h = side_incidents(home, ph, pa, ledger, key)
        cards_a, inj_a = side_incidents(away, pa, ph, ledger, key)
    own_h, opp_h = event_factors(cards_h, inj_h)
    own_a, opp_a = event_factors(cards_a, inj_a)
    xg_h *= own_h * opp_a
    xg_a *= own_a * opp_h
    goals_h = convert_to_goals(sh, xg_h)
    goals_a = convert_to_goals(sa, xg_a)

    events = (assign_scorers(home, ph, sh, goals_h, key, cards_h, inj_h)
              + assign_scorers(away, pa, sa, goals_a, key, cards_a, inj_a))
    events.sort(key=lambda e: (e.minute, e.team_id))

    sh.recent_diffs.append(goals_h - goals_a)
    sa.recent_diffs.append(goals_a - goals_h)

    names = {p.id: p.name for t in (home, away) for p in t.players}

    def report(team, prof, opp, last3, mood, mult, venue, xg, absent, event_factor):
        return SideReport(
            team_id=team.id, attack=prof.attack, defense=prof.defense, ratio=prof.attack / opp.defense,
            last3=last3, mood_factor=mood, coach_factor=prof.coach_factor, captain_factor=prof.captain_factor,
            depth_factor=prof.depth_factor, multiplier=mult, venue_factor=venue, xg=xg,
            lineup=[(p.name, r, rating) for p, r, rating in prof.xi], formation=prof.formation,
            captain_name=team.captain.name if team.captain else None,
            absent=[(names[pid], reason) for pid, reason in absent.items()], event_factor=event_factor,
        )

    all_cards = sorted(cards_h + cards_a, key=lambda c: (c.minute, c.team_id))
    all_inj = sorted(inj_h + inj_a, key=lambda i: (i.minute, i.team_id))
    result = MatchResult(
        matchday, home.id, away.id, goals_h, goals_a,
        report(home, ph, pa, last3_h, mood_h, mult_h, venue_h, xg_h, absent_h, own_h * opp_a),
        report(away, pa, ph, last3_a, mood_a, mult_a, venue_a, xg_a, absent_a, own_a * opp_h),
        events, all_cards, all_inj, attendance, capacity, neutral,
    )
    if ledger:                                                   # recettes de billetterie
        if neutral:
            each = attendance * (ticket_price(home) + ticket_price(away)) / 2 * 0.4
            ledger.money(home.id, "billetterie", each)
            ledger.money(away.id, "billetterie", each)
        else:
            ledger.money(home.id, "billetterie", attendance * ticket_price(home))
        for team, prof, absent, cards, injuries in ((home, ph, absent_h, cards_h, inj_h), (away, pa, absent_a, cards_a, inj_a)):
            ledger_after_match(ledger, {"absent": absent, "prof": prof, "cards": cards, "injuries": injuries,
                                        "goals": [e for e in events if e.team_id == team.id], "scope": scope})
    return result



# =============================================================================
# 4. CALENDRIER ET SAISON
# =============================================================================
def round_robin(ids: list) -> list:
    """Méthode du cercle : 19 journées aller + 19 journées retour pour 20 équipes."""
    n, arr, rounds = len(ids), list(ids), []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = arr[i], arr[n - 1 - i]
            if (r + i) % 2 == 1:
                a, b = b, a
            pairs.append((a, b))
        rounds.append(pairs)
        arr = [arr[0], arr[-1]] + arr[1:-1]
    return rounds + [[(b, a) for a, b in rd] for rd in rounds]


class SeasonSim:
    """Saison simulable journée par journée (ou d'un coup). 100 % déterministe :
    jouer 1 journée x 38 donne exactement le même résultat que tout simuler d'un coup."""

    def __init__(self, teams: list, ledger: Ledger | None = None, scope=None):
        self.ledger = ledger
        self.scope = scope
        self.teams = sorted(teams, key=lambda t: t.id)
        self.by_id = {t.id: t for t in self.teams}
        self.profiles = {t.id: build_profile(t) for t in self.teams}
        self.states = {t.id: TeamState() for t in self.teams}
        self.rows = {t.id: TableRow(t.id) for t in self.teams}
        self.schedule = round_robin([t.id for t in self.teams])
        self.total_days = len(self.schedule)
        self.matchdays: list = []
        self.scorers: dict = {}
        self.assisters: dict = {}
        initial = sorted(self.rows.values(), key=lambda r: self.by_id[r.team_id].name)
        self.tables: list = [[replace(r, rank=i + 1) for i, r in enumerate(initial)]]

    @property
    def played(self) -> int:
        return len(self.matchdays)

    @property
    def finished(self) -> bool:
        return self.played >= self.total_days

    @property
    def result(self) -> SeasonResult:
        return SeasonResult(self.matchdays, self.tables, self.scorers, self.assisters,
                            self.profiles, self.total_days)

    def play_day(self) -> list:
        if self.finished:
            return []
        matchday = self.played + 1
        day = []
        for home_id, away_id in self.schedule[matchday - 1]:
            m = play_match(matchday, self.by_id[home_id], self.by_id[away_id], self.profiles, self.states,
                           ledger=self.ledger, scope=self.scope)
            day.append(m)
            for team_id, gf, ga in ((home_id, m.home_goals, m.away_goals), (away_id, m.away_goals, m.home_goals)):
                r = self.rows[team_id]
                r.played += 1
                r.gf += gf
                r.ga += ga
                result = "V" if gf > ga else "N" if gf == ga else "D"
                r.won += result == "V"
                r.drawn += result == "N"
                r.lost += result == "D"
                r.pts += 3 if result == "V" else 1 if result == "N" else 0
                r.form = (r.form + [result])[-5:]
            for e in m.goals:
                entry = self.scorers.setdefault(e.player_id, [e.player_name, e.team_id, 0])
                entry[2] += 1
                if e.assist_id is not None:
                    a = self.assisters.setdefault(e.assist_id, [e.assist_name, e.team_id, 0])
                    a[2] += 1
        self.matchdays.append(day)

        ordered = sorted(self.rows.values(), key=lambda r: (-r.pts, -r.gd, -r.gf, self.by_id[r.team_id].name))
        self.tables.append([replace(r, rank=i + 1, form=list(r.form)) for i, r in enumerate(ordered)])
        return day

    def play_until(self, day: int) -> None:
        while self.played < min(day, self.total_days):
            self.play_day()

    def play_all(self) -> SeasonResult:
        self.play_until(self.total_days)
        return self.result


def simulate_season(teams: list) -> SeasonResult:
    return SeasonSim(teams).play_all()


# =============================================================================
# 5. BASE DE DONNÉES + CRÉATION DE LA LIGUE + TRANSFERTS
# =============================================================================
PLAYER_SELECT = ("id, first_name, last_name, age, country, city, preferred_foot, potential, overall, "
                 "best_position, ovr_gk, ovr_def, ovr_mid, ovr_att, " + ", ".join(STATS)
                 + ", injury_resistance, shirt, nickname")

TEAM_PREFIXES = ["FC", "AS", "US", "Olympique", "Racing", "Sporting", "Stade", "Athletic", "Union", "SC"]
LOGO_PATTERNS = ["stripes", "split", "band", "hoops", "cross", "plain"]


def row_to_player(row) -> Player:
    return Player(
        id=row[0], first_name=row[1], last_name=row[2], age=row[3], country=row[4], city=row[5],
        preferred_foot=row[6], potential=row[7], overall=row[8], best_position=row[9],
        ovr={"gk": row[10], "def": row[11], "mid": row[12], "att": row[13]},
        stats=dict(zip(STATS, row[14:14 + len(STATS)])),
        injury_resistance=row[14 + len(STATS)] or 60, number=row[15 + len(STATS)], nickname=row[16 + len(STATS)],
    )


def _ascii_letters(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if c.isalpha() and unicodedata.category(c) != "Mn").upper()


DIVISION_QUALITY_STEP = 5     # chaque division inférieure : joueurs ~5 points plus faibles
NATIONAL_SHARE = 0.65         # part des joueurs d'un club qui ont la nationalité du pays
MAX_COUNTRIES, MAX_DIVISIONS = 8, 3


def _nearest_free(players: list, keys: list, target: float, used: set):
    """Joueur non utilisé dont la note est la plus proche de target (liste triée par note)."""
    i = bisect.bisect_left(keys, target)
    lo, hi = i - 1, i
    while lo >= 0 or hi < len(keys):
        take_lo = hi >= len(keys) or (lo >= 0 and abs(keys[lo] - target) <= abs(keys[hi] - target))
        j = lo if take_lo else hi
        lo, hi = (lo - 1, hi) if take_lo else (lo, hi + 1)
        if players[j].id not in used:
            return players[j]
    return None


# =============================================================================
# 5. UNE COMPÉTITION (un championnat = un pays + une division)
# =============================================================================
class League:
    """Un championnat : ses équipes, sa saison, ses zones (qualifiés / promus / relégués)."""

    def __init__(self, con: sqlite3.Connection, teams: dict, country: str = "France",
                 division: int = 1, n_divisions: int = 1, ledger: Ledger | None = None):
        self.con = con
        self.ledger = ledger
        self.teams = teams
        self.country, self.division, self.n_divisions = country, division, n_divisions
        self.transfers: list = []
        self.season: SeasonSim | None = None
        self.previous: SeasonResult | None = None

    @property
    def label(self) -> str:
        return f"{self.country} · Division {self.division}"

    @property
    def result(self) -> SeasonResult | None:
        return self.season.result if self.season else None

    @property
    def n_teams(self) -> int:
        return len(self.teams)

    # ---------------------------------------------------------- simulation
    def start_season(self) -> SeasonSim:
        """Nouvelle saison à la journée 0 (avec les effectifs actuels). Si la précédente était terminée,
        elle sert de comparaison (colonnes Évol. et Δ Pts)."""
        if self.season is not None and self.season.finished:
            self.previous = self.season.result
        self.season = SeasonSim(list(self.teams.values()), self.ledger, ("league", self.country, self.division))
        return self.season

    def rebuild_if_unplayed(self) -> None:
        """Après un transfert : si aucune journée n'est jouée, on reconstruit les profils."""
        if self.season is not None and self.season.played == 0:
            self.season = SeasonSim(list(self.teams.values()), self.ledger, ("league", self.country, self.division))

    @property
    def in_progress(self) -> bool:
        return self.season is not None and 0 < self.season.played < self.season.total_days

    def play_days(self, days: int) -> None:
        if self.season is None:
            self.start_season()
        self.season.play_until(self.season.played + days)

    def play_all(self) -> SeasonResult:
        if self.season is None:
            self.start_season()
        return self.season.play_all()

    def simulate(self) -> SeasonResult:
        """Raccourci : nouvelle saison jouée en entier."""
        self.start_season()
        return self.play_all()

    # ------------------------------------------------------------- zones
    def zone_counts(self) -> dict:
        """Nombre d'équipes par zone. Division 1 : bleu (interligue 1), orange (interligue 2), rouge (relégués).
        Divisions inférieures : vert (promus) ; rouge (relégués) sauf dans la dernière division."""
        n_blue, n_orange, n_red = league_zones(self.n_teams)
        top = self.division == 1
        last_of_many = self.n_divisions > 1 and self.division == self.n_divisions
        if not OPTIONS.relegation:                          # option « pas de montées / descentes »
            n_red = 0
        return {"blue": n_blue if top else 0, "orange": n_orange if top else 0,
                "green": 0 if top else n_red, "red": 0 if last_of_many else n_red}

    def zones(self) -> dict:
        """Équipes (ids) par zone d'après le classement actuel."""
        empty = {"blue": [], "orange": [], "green": [], "red": []}
        if not self.season or self.season.played == 0:
            return empty
        table = [r.team_id for r in self.season.result.current_table]
        c = self.zone_counts()
        return {"blue": table[:c["blue"]], "orange": table[c["blue"]:c["blue"] + c["orange"]],
                "green": table[:c["green"]], "red": table[len(table) - c["red"]:] if c["red"] else []}

    def qualified_for_cup(self) -> dict:
        """Qualifiés pour les coupes interligue (division 1, saison terminée)."""
        if not self.season or not self.season.finished:
            return {"blue": [], "orange": []}
        z = self.zones()
        return {"blue": z["blue"], "orange": z["orange"]}

    def seed_order(self, team_ids: list) -> list:
        """Tête de série : classement actuel si des journées sont jouées, sinon note générale."""
        if self.season and self.season.played > 0:
            rank = {r.team_id: r.rank for r in self.season.result.current_table}
            return sorted(team_ids, key=lambda i: (rank[i], i))
        return sorted(team_ids, key=lambda i: (-self.teams[i].overall_rating, i))

    # -------------------------------------------------------------- marché
    def market(self, role: str | None = None, min_rating: float = 0, max_age: int = 45, name: str = "",
               limit: int = 200, *, country: str | None = None, min_age: int = 0, max_rating: float = 100,
               min_potential: int = 0, min_resistance: int = 0, foot: str | None = None) -> list:
        """Joueurs libres (sans club), triés par note décroissante, avec filtres."""
        column = f"ovr_{role}" if role else "overall"
        sql = (f"SELECT {PLAYER_SELECT} FROM players WHERE team_id IS NULL AND {column} >= ? AND {column} <= ? "
               f"AND age >= ? AND age <= ? AND potential >= ? AND injury_resistance >= ?")
        params: list = [min_rating, max_rating, min_age, max_age, min_potential, min_resistance]
        if country:
            sql += " AND country = ?"
            params.append(country)
        if foot:
            sql += " AND preferred_foot = ?"
            params.append(foot)
        if name:
            sql += " AND (last_name LIKE ? OR first_name LIKE ?)"
            params += [f"%{name}%", f"%{name}%"]
        sql += f" ORDER BY {column} DESC LIMIT ?"
        params.append(limit)
        return [row_to_player(r) for r in self.con.execute(sql, params)]

    # ----------------------------------------------------------- transferts
    def swap(self, team_id: int, out_player: Player, in_player: Player, from_team_id: int | None = None) -> str:
        """L'équipe team_id cède out_player et récupère in_player.
        from_team_id = None : in_player vient du marché libre et out_player y retourne.
        Sinon : échange de joueurs entre deux clubs du même championnat."""
        team = self.teams[team_id]
        if out_player.id not in {p.id for p in team.players}:
            raise ValueError(f"{out_player.name} n'est pas dans {team.name}.")
        other = self.teams[from_team_id] if from_team_id else None
        if other:
            if in_player.id not in {p.id for p in other.players}:
                raise ValueError(f"{in_player.name} n'est pas dans {other.name}.")
        else:
            row = self.con.execute("SELECT team_id FROM players WHERE id=?", (in_player.id,)).fetchone()
            if row is None or row[0] is not None:
                raise ValueError(f"{in_player.name} n'est plus disponible sur le marché.")

        free = other is None
        fee = transfer_fee(in_player, out_player, free_market=free)       # net payé par `team` (négatif = encaisse)
        if OPTIONS.finance_strict:                                         # option : budget strict (désactivée par défaut)
            if fee > team.budget:
                raise ValueError(f"Budget insuffisant : {team.name} doit payer {fee:,} € pour un budget de "
                                 f"{team.budget:,} €.".replace(",", " "))
            if other and -fee > other.budget:
                raise ValueError(f"Budget insuffisant pour {other.name}.")
        team.players = [p for p in team.players if p.id != out_player.id] + [in_player]
        if other:
            other.players = [p for p in other.players if p.id != in_player.id] + [out_player]
            self.con.execute("UPDATE players SET team_id=? WHERE id=?", (other.id, out_player.id))
        else:
            self.con.execute("UPDATE players SET team_id=NULL WHERE id=?", (out_player.id,))
        self.con.execute("UPDATE players SET team_id=? WHERE id=?", (team.id, in_player.id))

        for t in (team, other):
            if t and t.captain is None:
                t.elect_captain()
            if t:
                t.formation = choose_formation(t)
                assign_numbers(t)
                t.update_capacity()
                self.con.execute("UPDATE teams SET captain_id=?, formation=?, capacity=? WHERE id=?",
                                 (t.captain_id, t.formation, t.capacity, t.id))
                self.con.executemany("UPDATE players SET shirt=? WHERE id=?", [(p.number, p.id) for p in t.players])
        out_player.number = None
        self.con.execute("UPDATE players SET shirt=NULL WHERE id=?", (out_player.id,)) if not other else None
        self.con.commit()
        self.rebuild_if_unplayed()

        self.ledger.money(team.id, "achats" if fee > 0 else "ventes", abs(fee)) if self.ledger and fee else None
        if other and self.ledger and fee:
            self.ledger.money(other.id, "ventes" if fee > 0 else "achats", abs(fee))
        label = lambda p: f"{p.name} ({ROLE_LABELS[p.best_position]} {p.overall:.0f})"
        where = f"avec {other.name}" if other else "via le marché libre"
        text = f"{team.name} : {label(out_player)} part, {label(in_player)} arrive ({where})"
        self.transfers.append(text)
        return text


# =============================================================================
# 6. LE MONDE : plusieurs pays, plusieurs divisions, coupes interligue
# =============================================================================
class World:
    """Tous les championnats (pays x divisions) autour d'une même base SQLite de joueurs.
    Tous les championnats avancent à la même journée. Fin de saison : promotions / relégations
    entre divisions d'un même pays ; les meilleurs de chaque division 1 sont qualifiés pour les coupes interligue."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.con = sqlite3.connect(db_path)
        self.teams: dict = {}
        self.competitions: dict = {}          # (pays, division) -> League
        self.countries: list = []
        self.n_divisions = 1
        self.n_teams_per_division = 20
        self.season_number = 1
        self.history: list = []
        self.ledger = Ledger()
        self.friendlies: list = []                                    # matchs amicaux joués (MatchResult)
        self.interleague: dict = {"blue": None, "orange": None}      # coupes interligue de la saison (objets Cup)
        self.qualifiers: dict | None = None                           # qualifiés (ids) issus de la saison précédente
        self.cups: dict = {}                                          # pays -> coupe nationale (toutes divisions)
        self._ensure_indexes()
        self._ensure_tables()

    # ------------------------------------------------------------------ DB
    def _ensure_indexes(self) -> None:
        tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "players" not in tables:
            raise RuntimeError(f"Pas de table 'players' dans {self.db_path} : génère d'abord la base.")
        for col in ("team_id", "ovr_gk", "ovr_def", "ovr_mid", "ovr_att"):
            self.con.execute(f"CREATE INDEX IF NOT EXISTS idx_players_{col} ON players({col})")
        columns = {r[1] for r in self.con.execute("PRAGMA table_info(players)")}
        if "injury_resistance" not in columns:          # ancienne base : on calcule une résistance stable
            self.con.execute("ALTER TABLE players ADD COLUMN injury_resistance INTEGER")
            self.con.execute("UPDATE players SET injury_resistance = MAX(10, MIN(99, "
                             "38 + ((id * 7919) % 55) - MAX(0, age - 30) * 2))")
        if "shirt" not in columns:
            self.con.execute("ALTER TABLE players ADD COLUMN shirt INTEGER")
        if "nickname" not in columns:
            self.con.execute("ALTER TABLE players ADD COLUMN nickname TEXT")
        self.con.commit()

    def _ensure_tables(self) -> None:
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS team_history (season INTEGER, team_id INTEGER, team_name TEXT, country TEXT,
            division INTEGER, rank INTEGER, points INTEGER, won INTEGER, drawn INTEGER, lost INTEGER, gf INTEGER,
            ga INTEGER, cup TEXT, interleague TEXT);
        CREATE TABLE IF NOT EXISTS trophies (season INTEGER, team_id INTEGER, team_name TEXT, country TEXT,
            kind TEXT, label TEXT);
        CREATE TABLE IF NOT EXISTS player_seasons (season INTEGER, player_id INTEGER, team_id INTEGER,
            team_name TEXT, country TEXT, division INTEGER, games INTEGER, goals INTEGER, assists INTEGER,
            yellow INTEGER, red INTEGER, injuries INTEGER);
        CREATE TABLE IF NOT EXISTS team_finances (season INTEGER, team_id INTEGER, team_name TEXT, country TEXT,
            division INTEGER, revenue INTEGER, expenses INTEGER, profit INTEGER, wages INTEGER, budget_end INTEGER);
        CREATE INDEX IF NOT EXISTS idx_tf_team ON team_finances(team_id);
        CREATE INDEX IF NOT EXISTS idx_th_team ON team_history(team_id);
        CREATE INDEX IF NOT EXISTS idx_tr_team ON trophies(team_id);
        CREATE INDEX IF NOT EXISTS idx_ps_player ON player_seasons(player_id);
        """)

    def _save_qualifiers(self) -> None:
        for kind in ("blue", "orange"):
            ids = ",".join(str(i) for i in (self.qualifiers or {}).get(kind, []))
            self.con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"q_{kind}", ids))
        self.con.commit()

    def _load_qualifiers(self) -> None:
        got = {}
        for kind in ("blue", "orange"):
            row = self.con.execute("SELECT value FROM meta WHERE key=?", (f"q_{kind}",)).fetchone()
            got[kind] = [int(x) for x in row[0].split(",") if x] if row else []
        self.qualifiers = got if any(len(v) >= 2 for v in got.values()) else None

    def _set_season_number(self, n: int) -> None:
        self.season_number = n
        self.con.execute("INSERT OR REPLACE INTO meta VALUES ('season', ?)", (str(n),))
        self.con.commit()

    @classmethod
    def load_or_create(cls, db_path: str, seed: int = 42, force_new: bool = False, countries: list | None = None,
                       n_divisions: int = 2, n_teams: int = 20) -> "World":
        world = cls(db_path)
        if not force_new and world._load():
            return world
        world._create(seed, countries or DEFAULT_COUNTRIES[:4], n_divisions, n_teams)
        return world

    def _load(self) -> bool:
        tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "teams" not in tables:
            return False
        columns = {r[1] for r in self.con.execute("PRAGMA table_info(teams)")}
        if not {"formation", "country", "division", "stadium", "capacity"} <= columns:   # ancienne base : on recrée tout
            return False
        if "budget" not in columns:                       # base d'avant les finances : on ajoute la colonne
            self.con.execute("ALTER TABLE teams ADD COLUMN budget INTEGER")
        rows = self.con.execute(
            "SELECT id, name, short, city, primary_color, secondary_color, pattern, captain_id, coach_name, "
            "coach_tactics, coach_motivation, formation, country, division, stadium, capacity, budget "
            "FROM teams ORDER BY id").fetchall()
        if not rows:
            return False
        self.teams = {
            r[0]: Team(r[0], r[1], r[2], r[3], r[4], r[5], r[6], Coach(r[8], r[9], r[10]), [], r[7],
                       r[11] if r[11] in FORMATIONS else DEFAULT_FORMATION, r[12], r[13], r[14], r[15], r[16] or 0)
            for r in rows
        }
        query = f"SELECT {PLAYER_SELECT}, team_id FROM players WHERE team_id IS NOT NULL"
        for row in self.con.execute(query):
            if row[-1] in self.teams:
                self.teams[row[-1]].players.append(row_to_player(row))
        if not all(len(t.players) == SQUAD_SIZE for t in self.teams.values()):
            return False
        for t in self.teams.values():
            if any(p.number is None for p in t.players):
                assign_numbers(t)
            if not t.budget:                                 # budget de départ des anciennes bases
                t.budget = initial_budget(t)
                self.con.execute("UPDATE teams SET budget=? WHERE id=?", (t.budget, t.id))
        self.con.commit()
        row = self.con.execute("SELECT value FROM meta WHERE key='season'").fetchone()
        self.season_number = int(row[0]) if row else 1
        self._load_qualifiers()
        self.countries = list(dict.fromkeys(t.country for t in self.teams.values()))
        self.n_divisions = max(t.division for t in self.teams.values())
        self._build_competitions()
        self.n_teams_per_division = min(lg.n_teams for lg in self.competitions.values())
        self.start_season()
        return True

    def _save(self) -> None:
        c = self.con
        c.execute("UPDATE players SET team_id=NULL WHERE team_id IS NOT NULL")
        c.execute("UPDATE players SET shirt=NULL")
        c.executemany("UPDATE players SET team_id=?, shirt=?, nickname=? WHERE id=?",
                      [(t.id, p.number, p.nickname, p.id) for t in self.teams.values() for p in t.players])
        c.execute("DROP TABLE IF EXISTS teams")
        c.execute("""CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT, short TEXT, city TEXT,
                     primary_color TEXT, secondary_color TEXT, pattern TEXT, captain_id INTEGER,
                     coach_name TEXT, coach_tactics INTEGER, coach_motivation INTEGER, formation TEXT,
                     country TEXT, division INTEGER, stadium TEXT, capacity INTEGER, budget INTEGER)""")
        c.executemany("INSERT INTO teams VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (t.id, t.name, t.short, t.city, t.primary, t.secondary, t.pattern, t.captain_id,
             t.coach.name, t.coach.tactics, t.coach.motivation, t.formation, t.country, t.division,
             t.stadium, t.capacity, t.budget)
            for t in self.teams.values()])
        c.commit()

    def _build_competitions(self) -> None:
        groups: dict = {}
        for t in self.teams.values():
            groups.setdefault((t.country, t.division), {})[t.id] = t
        order = {c: i for i, c in enumerate(self.countries)}
        self.competitions = {
            key: League(self.con, groups[key], key[0], key[1], self.n_divisions, self.ledger)
            for key in sorted(groups, key=lambda k: (order[k[0]], k[1]))
        }

    # ------------------------------------------------------------ création
    def _candidate_pools(self, need: dict) -> tuple:
        """Réserves de joueurs libres par poste (triées par note) + sous-réserves par pays."""
        pools, by_country = {}, {}
        for role in ROLES:
            rows = self.con.execute(
                f"SELECT {PLAYER_SELECT} FROM players WHERE best_position=? AND age BETWEEN 19 AND 34 "
                f"AND overall BETWEEN 34 AND 86 AND team_id IS NULL LIMIT 20000", (role,)).fetchall()
            players = sorted((row_to_player(r) for r in rows), key=lambda p: (p.ovr[role], p.id))
            if len(players) < max(120, need[role] * 1.5):
                raise RuntimeError(f"Pas assez de joueurs ({role}) : {len(players)} disponibles pour "
                                   f"{need[role]} postes. Génère une base plus grande (-n 200000).")
            pools[role] = (players, [p.ovr[role] for p in players])
            groups: dict = {}
            for p in players:
                groups.setdefault(p.country, []).append(p)
            by_country[role] = {c: (ps, [p.ovr[role] for p in ps]) for c, ps in groups.items()}
        return pools, by_country

    def _make_country_teams(self, country: str, faker, rng, pools: dict, by_country: dict, used_ids: set,
                            used_short: set, team_id: int) -> int:
        """Crée toutes les équipes d'un pays (toutes ses divisions), les ajoute à self.teams et renvoie le prochain id."""
        n_divisions, n_teams = self.n_divisions, self.n_teams_per_division
        cities = faker.get_cities(country)
        rng.shuffle(cities)
        names_taken: set = set()
        country_total = n_divisions * n_teams
        k = 0
        for division in range(1, n_divisions + 1):
            tiers = [i / (n_teams - 1) for i in range(n_teams)]          # 0 = plus faible, 1 = plus fort
            rng.shuffle(tiers)
            for i in range(n_teams):
                city = cities[k % len(cities)]
                prefix = TEAM_PREFIXES[rng.randrange(len(TEAM_PREFIXES))]
                while f"{prefix} {city}" in names_taken:                   # même ville : autre préfixe
                    prefix = TEAM_PREFIXES[rng.randrange(len(TEAM_PREFIXES))]
                names_taken.add(f"{prefix} {city}")
                letters = _ascii_letters(city)
                short, n = letters[:3], 1
                while short in used_short:
                    short = letters[:2] + str(n)
                    n += 1
                used_short.add(short)

                hue = (k * 360 / country_total + rng.uniform(0, 12)) % 360 / 360
                primary = "#%02x%02x%02x" % tuple(int(255 * c) for c in colorsys.hls_to_rgb(hue, 0.38, 0.70))
                secondary = rng.choice(["#ffffff", "#ffd400", "#111111", "#f2f2f2", "#ffb703"])
                coach_person = faker.get_person(country=country, sex=1, minimum_age=38, maximum_age=66,
                                                current_date=2026)
                coach = Coach(f"{coach_person.first_name} {coach_person.last_name}",
                              int(clamp(rng.gauss(55, 14), 20, 95)), int(clamp(rng.gauss(55, 14), 20, 95)))
                team = Team(team_id, f"{prefix} {city}", short, city, primary, secondary,
                            LOGO_PATTERNS[rng.randrange(len(LOGO_PATTERNS))], coach,
                            country=country, division=division,
                            stadium=f"{STADIUM_WORDS[rng.randrange(len(STADIUM_WORDS))]} {city}")

                quality = 56 + 14 * tiers[i] - DIVISION_QUALITY_STEP * (division - 1)
                for role, count in SQUAD_COMPOSITION.items():
                    for _ in range(count):
                        target = quality + rng.gauss(0, 3)
                        player = None
                        if rng.random() < NATIONAL_SHARE and country in by_country[role]:
                            players, keys = by_country[role][country]
                            player = _nearest_free(players, keys, target, used_ids)
                        if player is None:
                            players, keys = pools[role]
                            player = _nearest_free(players, keys, target, used_ids)
                        used_ids.add(player.id)
                        team.players.append(player)
                team.elect_captain()
                team.formation = choose_formation(team)
                team.update_capacity()           # la capacité de départ dépend de la note de départ
                team.budget = initial_budget(team)
                assign_numbers(team)
                self.teams[team_id] = team
                team_id += 1
                k += 1
        return team_id

    def _create(self, seed: int, countries: list, n_divisions: int = 2, n_teams: int = 20) -> None:
        if n_teams % 2 or not MIN_TEAMS <= n_teams <= MAX_TEAMS:
            raise ValueError(f"Nombre d'équipes pair entre {MIN_TEAMS} et {MAX_TEAMS} (reçu : {n_teams}).")
        if not 1 <= n_divisions <= MAX_DIVISIONS:
            raise ValueError(f"Entre 1 et {MAX_DIVISIONS} divisions.")
        if not 1 <= len(countries) <= MAX_COUNTRIES:
            raise ValueError(f"Entre 1 et {MAX_COUNTRIES} pays.")
        rng = random.Random(seed)
        faker = Faker(seed=seed)
        known = set(faker.get_countries())
        if any(c not in known for c in countries):
            raise ValueError("Pays inconnu : " + ", ".join(c for c in countries if c not in known))

        self.con.execute("UPDATE players SET team_id=NULL, shirt=NULL, nickname=NULL")
        for table in ("team_history", "trophies", "player_seasons", "team_finances"):
            self.con.execute(f"DELETE FROM {table}")
        self.countries, self.n_divisions, self.n_teams_per_division = list(countries), n_divisions, n_teams
        self.history = []
        self.friendlies = []
        self.qualifiers = None                    # première saison : pas de qualifiés, donc pas de coupe interligue
        self._save_qualifiers()
        self._set_season_number(1)

        total = len(countries) * n_divisions * n_teams
        need = {role: total * SQUAD_COMPOSITION[role] for role in ROLES}
        pools, by_country = self._candidate_pools(need)
        used_ids: set = set()
        used_short: set = set()
        self.teams = {}
        team_id = 1

        for country in countries:
            team_id = self._make_country_teams(country, faker, rng, pools, by_country, used_ids, used_short, team_id)
        self._save()
        self._build_competitions()
        self.start_season()

    def add_country(self, country: str) -> None:
        """Ajoute un pays complet (mêmes divisions et nombre d'équipes que le reste du monde) AVANT le début de la
        saison : après « Saison suivante » ou juste après la création."""
        if country in self.countries:
            raise ValueError(f"{country} est déjà dans le monde.")
        if len(self.countries) >= MAX_COUNTRIES:
            raise ValueError(f"Un monde contient au maximum {MAX_COUNTRIES} pays.")
        if self.played > 0:
            raise ValueError("Ajoute un pays avant le début de la saison (journée 0) : clique d'abord sur "
                             "« Saison suivante » ou « Rejouer la saison ».")
        faker = Faker(seed=zlib.crc32(country.encode()))
        if country not in set(faker.get_countries()):
            raise ValueError(f"Pays inconnu : {country}")
        rng = random.Random(zlib.crc32(country.encode()) + len(self.teams))
        need = {role: self.n_divisions * self.n_teams_per_division * SQUAD_COMPOSITION[role] for role in ROLES}
        pools, by_country = self._candidate_pools(need)
        self.countries.append(country)
        self._make_country_teams(country, faker, rng, pools, by_country, set(), {t.short for t in self.teams.values()},
                                 max(self.teams) + 1)
        self._save()
        groups: dict = {}
        for t in self.teams.values():
            if t.country == country:
                groups.setdefault(t.division, {})[t.id] = t
        for division in sorted(groups):
            league = League(self.con, groups[division], country, division, self.n_divisions, self.ledger)
            self.competitions[(country, division)] = league
            league.start_season()
        order = {c: i for i, c in enumerate(self.countries)}
        self.competitions = dict(sorted(self.competitions.items(), key=lambda kv: (order[kv[0][0]], kv[0][1])))
        self._build_national_cups()

    # ---------------------------------------------------------- simulation
    def start_season(self, carry: bool = False) -> None:
        """Nouvelle saison à la journée 0. carry=True (saison suivante) : les blessures en cours continuent."""
        self.ledger.new_season() if carry else self.ledger.reset()
        for lg in self.competitions.values():
            lg.start_season()
        self._build_national_cups()
        self._build_interleague()

    def _build_national_cups(self) -> None:
        """Une coupe nationale par pays, toutes divisions confondues (les petites divisions jouent un tour de
        barrages plus tôt). Ses tours sont répartis sur le calendrier du championnat."""
        from cup_engine import Cup            # import tardif : cup_engine importe league_engine
        self.cups = {}
        total = self.total_days
        for country in self.countries:
            teams = sorted((t for t in self.teams.values() if t.country == country),
                           key=lambda t: (t.division, -t.overall_rating, t.id))
            cup = Cup(teams, ledger=self.ledger, scope=("cup", country))
            cup.round_days = self._cup_days(len(cup.round_defs))
            self.cups[country] = cup

    def _cup_days(self, rounds: int, avoid=()) -> list:
        """Journées du championnat où tombent les tours d'une coupe (réparties sur la saison, jamais deux fois
        la même journée qu'une autre coupe de la liste avoid)."""
        total, days = self.total_days, []
        for k in range(rounds):
            d = max(days[-1] + 1 if days else 1, round(total * (k + 1) / (rounds + 1)))
            while d in avoid:
                d += 1
            days.append(d)
        return days

    def _build_interleague(self) -> None:
        """Coupes interligue de la saison, d'après les qualifiés de la saison PRÉCÉDENTE (aucune exempte)."""
        self.interleague = {"blue": None, "orange": None}
        for kind in ("blue", "orange"):
            ids = [i for i in (self.qualifiers or {}).get(kind, []) if i in self.teams]
            if len(ids) >= 2:
                self.build_interleague(kind, ids)

    def rebuild_interleague_if_unplayed(self) -> None:
        """Après un changement de format (poules ou non) : on refait les coupes interligue qui n'ont pas commencé."""
        for kind, cup in list(self.interleague.items()):
            if cup is not None and not cup.rounds:
                self.build_interleague(kind, list(cup.teams))

    def build_interleague(self, kind: str, team_ids: list) -> "Cup":
        """Crée (ou recrée) une coupe interligue ; le nombre d'équipes doit être une puissance de 2 pour qu'aucune
        équipe ne soit qualifiée d'office. team_ids : de la mieux classée à la moins bien classée."""
        from cup_engine import Cup, GroupCup
        teams = [self.teams[i] for i in team_ids]
        n = len(teams)
        if OPTIONS.interleague_groups and n >= 8 and n & (n - 1) == 0:           # poules de 4, puis élimination directe
            cup = GroupCup(teams, ledger=self.ledger, scope=("inter", kind))
        else:
            cup = Cup(teams, ledger=self.ledger, scope=("inter", kind))
        national_days = {d for c in self.cups.values() for d in c.round_days}
        cup.round_days = self._cup_days(len(cup.round_defs), national_days)
        self.interleague[kind] = cup
        return cup

    def rebuild_unplayed(self) -> None:
        """Après un transfert avant le début de la saison : on reconstruit profils et coupes."""
        for lg in self.competitions.values():
            lg.rebuild_if_unplayed()
        if self.played == 0:
            self._build_national_cups()
            self._build_interleague()

    @property
    def total_days(self) -> int:
        return max(lg.season.total_days for lg in self.competitions.values())

    @property
    def played(self) -> int:
        return min(lg.season.played for lg in self.competitions.values())

    @property
    def finished(self) -> bool:
        return all(lg.season.finished for lg in self.competitions.values())

    @property
    def in_progress(self) -> bool:
        return any(lg.in_progress for lg in self.competitions.values())

    def _play_day(self) -> None:
        for lg in self.competitions.values():
            lg.play_days(1)
        day = self.played
        for cup in list(self.cups.values()) + [c for c in self.interleague.values() if c is not None]:
            index = len(cup.rounds)               # les tours de coupe tombent certaines journées
            if not cup.finished and index < len(cup.round_days) and cup.round_days[index] == day:
                cup.play_next_round()

    def play_days(self, days: int) -> None:
        for _ in range(days):
            if self.finished:
                break
            self._play_day()

    def play_all(self) -> None:
        while not self.finished:
            self._play_day()

    def play_friendly(self, home_id: int, away_id: int, neutral: bool = False) -> MatchResult:
        """Match amical entre deux équipes quelconques (n'importe quel pays ou division). Effectifs complets, aucun
        carton ni blessure, sans effet sur la saison : seulement pour voir le résultat."""
        if home_id == away_id:
            raise ValueError("Choisis deux équipes différentes.")
        home, away = self.teams[home_id], self.teams[away_id]
        profiles = {t.id: build_profile(t) for t in (home, away)}
        states = {home.id: TeamState(), away.id: TeamState()}
        day = 500 + (home_id * 31 + away_id) % 100       # clé stable : rejouer le même match donne le même résultat
        result = play_match(day, home, away, profiles, states, neutral=neutral, ledger=None)
        self.friendlies.append(result)
        return result

    def competition_of(self, team_id: int) -> League:
        team = self.teams[team_id]
        return self.competitions[(team.country, team.division)]

    def top_leagues(self) -> list:
        return [lg for (c, d), lg in self.competitions.items() if d == 1]

    # --------------------------------------------------------------- coupes
    def qualified(self) -> dict:
        """Qualifiés interligue : {"blue": [ids], "orange": [ids]}, une fois TOUS les championnats de division 1
        terminés."""
        out = {"blue": [], "orange": []}
        tops = self.top_leagues()
        if not all(lg.season and lg.season.finished for lg in tops):
            return out
        for rank_group in ("blue", "orange"):
            groups = [lg.zones()[rank_group] for lg in tops]
            # on range d'abord tous les 1ers, puis les 2es...
            for pos in range(max(len(g) for g in groups)):
                out[rank_group] += [g[pos] for g in groups if pos < len(g)]
        return out

    def seed_order(self, team_ids: list) -> list:
        """Têtes de série mondiales : division, puis rang dans son championnat, puis note générale."""
        def key(tid):
            lg = self.competition_of(tid)
            rank = 0
            if lg.season and lg.season.played > 0:
                rank = next(r.rank for r in lg.season.result.current_table if r.team_id == tid)
            return (lg.division, rank, -self.teams[tid].overall_rating, tid)
        return sorted(team_ids, key=key)

    # ----------------------------------------------------- fin de saison
    def compute_qualifiers(self) -> dict:
        """Qualifiés pour les coupes interligue de la saison suivante : 3 premiers (bleu) et 3 suivants (orange) de chaque
        division 1. Chaque coupe est complétée avec les meilleurs non-qualifiés jusqu'à une puissance de 2, pour que
        toutes les équipes jouent le premier tour (aucune qualifiée d'office)."""
        q = self.qualified()
        used = set(q["blue"]) | set(q["orange"])
        pools = [[r.team_id for r in lg.season.result.final_table if r.team_id not in used] for lg in self.top_leagues()]
        extras = [pool[k] for k in range(max((len(p) for p in pools), default=0)) for pool in pools if k < len(pool)]
        out = {}
        for kind in ("blue", "orange"):
            ids = list(q[kind])
            target = 1 if len(ids) <= 1 else 1 << (len(ids) - 1).bit_length()
            while len(ids) < target and extras:
                ids.append(extras.pop(0))
            out[kind] = ids[:1 << (len(ids).bit_length() - 1)] if ids else []
        return out

    def team_statement(self, team_id: int) -> dict:
        """État financier INDICATIF de la saison en cours pour un club (voir finance.py)."""
        team = self.teams[team_id]
        lg = self.competition_of(team_id)
        season = lg.season
        fraction = season.played / season.total_days if season.total_days else 0.0
        money = self.ledger.finance.get(team_id, {})
        prize = 0
        if season.finished:
            rank = next(r.rank for r in season.result.final_table if r.team_id == team_id)
            prize = league_prize(team.division, rank, lg.n_teams)
        cups = cup_income(team_id, self.cups.get(team.country))
        cups += sum(cup_income(team_id, c, INTERLEAGUE_FACTOR) for c in self.interleague.values() if c is not None)
        return season_statement(team, fraction, money.get("billetterie", 0), money.get("ventes", 0),
                                money.get("achats", 0), cups, prize)

    def team_budget_now(self, team_id: int) -> int:
        """Budget de début de saison + résultat de la saison à ce jour (indicatif)."""
        return self.teams[team_id].budget + self.team_statement(team_id)["profit"]

    def team_finance_history(self, team_id: int) -> list:
        """[(saison, division, recettes, dépenses, résultat, salaires, budget en fin de saison)]."""
        return self.con.execute(
            "SELECT season, division, revenue, expenses, profit, wages, budget_end FROM team_finances "
            "WHERE team_id=? ORDER BY season DESC", (team_id,)).fetchall()

    def _record_season(self) -> None:
        """Enregistre dans la base : classements, parcours en coupes, trophées, statistiques des joueurs."""
        season, c = self.season_number, self.con
        cup_result = {tid: cup.result_for(tid) for cup in self.cups.values() for tid in cup.teams}
        inter = {}
        for kind, label in (("blue", "Interligue 1"), ("orange", "Interligue 2")):
            cup = self.interleague.get(kind)
            if cup is not None:
                for tid in cup.teams:
                    inter[tid] = f"{label} : {cup.result_for(tid)}"
        trophies = []
        for (country, division), lg in self.competitions.items():
            table = lg.season.result.final_table
            c.executemany("INSERT INTO team_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                (season, r.team_id, self.teams[r.team_id].name, country, division, r.rank, r.pts, r.won, r.drawn,
                 r.lost, r.gf, r.ga, cup_result.get(r.team_id, ""), inter.get(r.team_id, "")) for r in table])
            champ = self.teams[table[0].team_id]
            trophies.append((season, champ.id, champ.name, country, f"league{division}",
                             f"Champion {country} · Division {division}"))
        for country, cup in self.cups.items():
            if cup.finished:
                trophies.append((season, cup.champion_id, cup.champion.name, country, "cup", f"Coupe {country}"))
        for kind, label in (("blue", "Coupe interligue 1"), ("orange", "Coupe interligue 2")):
            cup = self.interleague.get(kind)
            if cup is not None and cup.finished:
                trophies.append((season, cup.champion_id, cup.champion.name, cup.champion.country,
                                 "interleague1" if kind == "blue" else "interleague2", label))
        c.executemany("INSERT INTO trophies VALUES (?,?,?,?,?,?)", trophies)
        rows = []
        for team in self.teams.values():
            for p in team.players:
                st = self.ledger.stats.get(p.id)
                if st and st["games"] > 0:
                    rows.append((season, p.id, team.id, team.name, team.country, team.division, st["games"],
                                 st["goals"], st["assists"], st["yellow"], st["red"], st["injuries"]))
        c.executemany("INSERT INTO player_seasons VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        finances = []
        for team in self.teams.values():                    # bilan financier de la saison, puis budget reporté
            st = self.team_statement(team.id)
            wages = next(v for k, v in st["dépenses"] if k == "Salaires des joueurs")
            team.budget += st["profit"]
            finances.append((season, team.id, team.name, team.country, team.division, st["total_revenus"],
                             st["total_dépenses"], st["profit"], wages, team.budget))
        c.executemany("INSERT INTO team_finances VALUES (?,?,?,?,?,?,?,?,?,?)", finances)
        c.executemany("UPDATE teams SET budget=? WHERE id=?", [(t.budget, t.id) for t in self.teams.values()])
        c.commit()

    NICKNAMES = {
        "scorer": ["Le Canonnier", "La Foudre", "Monsieur But", "Le Sniper"],
        "assist": ["Le Magicien", "Le Facteur", "Le Chef d'orchestre"],
        "rough": ["Le Boucher", "Le Bulldozer", "Tonton Flingueur"],
        "fragile": ["Cristal", "Porcelaine", "L'Infirmerie"],
        "wall": ["La Muraille", "Le Mur", "Mains de Velours"],
        "boss": ["Le Patron", "Le Boss", "Le Général"],
    }

    def _award_nicknames(self) -> None:
        """Un surnom se gagne : meilleur buteur / passeur, joueur dur, fragile, gardien d'un champion, capitaine
        d'un champion. Un joueur qui a déjà un surnom le garde."""
        players = {p.id: p for t in self.teams.values() for p in t.players}
        earned: dict = {}

        def give(pid, kind):
            p = players.get(pid)
            if p is not None and not p.nickname and pid not in earned:
                names = self.NICKNAMES[kind]
                earned[pid] = names[zlib.crc32(f"{pid}:{kind}:{self.season_number}".encode()) % len(names)]

        for lg in self.competitions.values():
            result = lg.season.result
            top = result.top_scorers(1)
            if top and top[0][1][2] >= 15:
                give(top[0][0], "scorer")
            top = result.top_assisters(1)
            if top and top[0][1][2] >= 10:
                give(top[0][0], "assist")
            champion = self.teams[result.final_table[0].team_id]
            keeper = max((p for p in champion.players if p.best_position == "gk"), key=lambda p: p.ovr["gk"], default=None)
            if keeper and keeper.ovr["gk"] >= 65 and self.ledger.stats.get(keeper.id, {}).get("games", 0) >= 25:
                give(keeper.id, "wall")
            if champion.captain and champion.captain.stats["leadership"] >= 70:
                give(champion.captain.id, "boss")
        for pid, st in self.ledger.stats.items():
            if st["red"] >= 3 or st["yellow"] >= 12:
                give(pid, "rough")
            elif st["injuries"] >= 3 and st["games"] >= 10:
                give(pid, "fragile")
        for pid, name in earned.items():
            players[pid].nickname = name
        self.con.executemany("UPDATE players SET nickname=? WHERE id=?", [(n, pid) for pid, n in earned.items()])
        self.con.commit()

    def next_season(self) -> dict:
        """Enregistre la saison, promotions / relégations (2 par division), surnoms, stades, nouvelle saison."""
        if not self.finished:
            raise RuntimeError("Termine d'abord la saison.")
        self._record_season()
        self._award_nicknames()
        self.qualifiers = self.compute_qualifiers()
        self._save_qualifiers()
        entry = {"season": self.season_number, "champions": {}, "promoted": [], "relegated": []}
        old = {key: (lg.season.result, lg.transfers) for key, lg in self.competitions.items()}
        for country in self.countries:
            entry["champions"][country] = self.teams[
                self.competitions[(country, 1)].season.result.final_table[0].team_id].name
            moves = []
            for d in range(1, self.n_divisions if OPTIONS.relegation else 1):
                upper, lower = self.competitions[(country, d)], self.competitions[(country, d + 1)]
                n = league_zones(upper.n_teams)[2]
                down = [r.team_id for r in upper.season.result.final_table[-n:]]
                up = [r.team_id for r in lower.season.result.final_table[:n]]
                moves += [(i, d + 1) for i in down] + [(i, d) for i in up]
                entry["relegated"] += [self.teams[i].name for i in down]
                entry["promoted"] += [self.teams[i].name for i in up]
            for tid, new_div in moves:
                self.teams[tid].division = new_div
                self.con.execute("UPDATE teams SET division=? WHERE id=?", (new_div, tid))
        for t in self.teams.values():                        # le stade ne rétrécit jamais, mais peut grandir
            t.update_capacity()
        self.con.executemany("UPDATE teams SET capacity=? WHERE id=?", [(t.capacity, t.id) for t in self.teams.values()])
        self.con.commit()
        self.history.append(entry)
        self._set_season_number(self.season_number + 1)
        self._build_competitions()
        for key, lg in self.competitions.items():
            lg.previous, lg.transfers = old[key]
        self.start_season(carry=True)
        return entry

    # ------------------------------------------------------------- historique
    def team_history(self, team_id: int) -> list:
        """[(saison, pays, division, rang, pts, V, N, D, BP, BC, coupe nationale, interligue)], saison la plus récente d'abord."""
        return self.con.execute(
            "SELECT season, country, division, rank, points, won, drawn, lost, gf, ga, cup, interleague "
            "FROM team_history WHERE team_id=? ORDER BY season DESC", (team_id,)).fetchall()

    def team_trophies(self, team_id: int) -> list:
        return self.con.execute("SELECT season, kind, label FROM trophies WHERE team_id=? ORDER BY season, kind",
                                (team_id,)).fetchall()

    def player_career(self, player_id: int) -> list:
        """[(saison, club, pays, division, matchs, buts, passes, jaunes, rouges, blessures)]."""
        return self.con.execute(
            "SELECT season, team_name, country, division, games, goals, assists, yellow, red, injuries "
            "FROM player_seasons WHERE player_id=? ORDER BY season", (player_id,)).fetchall()

    def palmares(self) -> list:
        """[(saison, pays, genre, club)] : champions de division 1, coupes nationales et interligue."""
        return self.con.execute(
            "SELECT season, country, kind, team_name FROM trophies WHERE kind IN "
            "('league1','cup','interleague1','interleague2') ORDER BY season, kind").fetchall()


DEFAULT_COUNTRIES = ["France", "Espagne", "Angleterre", "Italie", "Portugal", "Allemagne", "Pays-Bas", "Belgique"]


MODEL_EXPLANATION = f"""
<h3>Comment le score est calculé (aucun hasard)</h3>
<p><b>1. Onze de départ</b> : le coach choisit la formation (4-4-2, 4-3-3, 3-5-2, 4-2-3-1, 5-3-2, 3-4-3) qui convient le mieux à son effectif ; les titulaires sont les meilleurs de chaque poste. Chaque formation donne +-1 % à l'attaque ou à la défense.</p>
<p><b>2. Niveau d'une équipe</b> : <i>attaque</i> = attaquants + 0,5 x milieux ; <i>défense</i> = défenseurs + 0,4 x milieux + 1,5 x gardien.</p>
<p><b>3. Buts attendus (xG)</b> :<br>
xG = {BASE_GOALS} x (attaque / défense adverse)<sup>{K}</sup> x forme x lieu / racine(forme adverse)</p>
<p><b>4. Forme</b> = humeur x entraîneur x capitaine x banc :</p>
<ul>
<li><b>Humeur</b> : écart de buts cumulé des <b>3 derniers matchs</b> (borné à +-{MOOD_MAX_DIFF}), soit +-{MOOD_STRENGTH*100:.0f} % maximum, amplifié par la motivation du coach.</li>
<li><b>Entraîneur</b> : (tactique + motivation) / 2, +-5 %.</li>
<li><b>Capitaine</b> : leadership, +-3 % (moitié si le capitaine est remplaçant).</li>
<li><b>Banc</b> : niveau moyen des 5 remplaçants, +-1,6 %.</li>
</ul>
<p><b>5. Lieu</b> : x{HOME_ATTACK} à domicile, x{AWAY_ATTACK} à l'extérieur.</p>
<p><b>6. Buts réels</b> : on arrondit xG + le reste d'arrondi des matchs précédents de l'équipe
(diffusion d'erreur). C'est déterministe, et sur la saison le total de buts colle au total de xG.</p>
<p><b>7. Buteurs</b> : chaque but va au joueur dont la part théorique (finition, tir, poste) est la plus en retard.</p>
<p><b>9. Cartons</b> : chaque joueur accumule des fautes selon son agressivité, ses tacles, sa force, son manque de sang-froid, et son inexpérience (jeune et/ou note basse = plus de fautes, vétéran avec une bonne note = moins). Jaune à 5 cumulés = 1 match de suspension ; deux jaunes = rouge (1 match) ; rouge direct = 2 matchs (3 si violent). Une équipe à 10 perd environ 40 % de ses buts attendus sur le temps restant, l'adversaire en gagne environ 15 %.</p>
<p><b>10. Blessures</b> : risque selon la résistance du joueur, son âge et la dureté de l'adversaire. Durée de 1 à 30 matchs (plus la résistance est haute, plus c'est court). Le blessé est remplacé tout de suite ; un blessé ou un suspendu ne joue ni le championnat ni la coupe nationale.</p>
<p><b>11. Affluence</b> : selon la note du club, sa forme, le niveau de l'adversaire et la journée. Stade : sa capacité suit la note de l'équipe et ne régresse jamais. En option, un stade plein donne un petit bonus à domicile.</p>
<p><b>8. Passeurs décisifs</b> : environ {ASSIST_RATE*100:.0f} % des buts ont un passeur, choisi parmi les autres titulaires selon passe, vision et centres (les milieux passent plus que les défenseurs).</p>
"""
