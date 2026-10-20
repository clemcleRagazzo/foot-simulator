"""
league_engine.py : moteur de la ligue (AUCUN Qt ici, tout est testable en console).

  - construit 20 équipes (16 joueurs + 1 capitaine + 1 entraîneur) depuis players.db
  - calendrier aller-retour (38 journées)
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

FORMATION = {"gk": 1, "def": 4, "mid": 4, "att": 2}           # 4-4-2
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

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}"


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

    @property
    def captain(self) -> Player | None:
        return next((p for p in self.players if p.id == self.captain_id), None)

    def elect_captain(self) -> None:
        """Le capitaine est le joueur au plus fort leadership (à égalité : le plus âgé)."""
        if self.players:
            best = max(self.players, key=lambda p: (p.stats["leadership"], p.age, -p.id))
            self.captain_id = best.id

    def best_xi(self) -> list:
        """11 titulaires en 4-4-2 : [(joueur, rôle), ...]. Choix glouton GB -> DEF -> ATT -> MIL."""
        remaining = list(self.players)
        xi = []
        for role in ("gk", "def", "att", "mid"):
            remaining.sort(key=lambda p: (-p.ovr[role], p.id))
            chosen, remaining = remaining[:FORMATION[role]], remaining[FORMATION[role]:]
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


@dataclass
class GoalEvent:
    minute: int
    team_id: int
    player_id: int
    player_name: str


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
    matchdays: list           # list[list[MatchResult]]
    tables: list              # tables[i] = classement après la journée i+1
    scorers: dict             # player_id -> [nom, team_id, buts]
    profiles: dict            # team_id -> TeamProfile

    @property
    def final_table(self) -> list:
        return self.tables[-1]

    def matches_of(self, team_id: int) -> list:
        return [m for day in self.matchdays for m in day if team_id in (m.home_id, m.away_id)]

    def top_scorers(self, n: int = 30) -> list:
        return sorted(self.scorers.items(), key=lambda kv: (-kv[1][2], kv[1][0]))[:n]


@dataclass
class TeamState:
    """État mutable d'une équipe PENDANT une simulation."""
    recent_diffs: list = field(default_factory=list)
    residual: float = 0.0                             # reste d'arrondi des buts (diffusion d'erreur)
    credit: dict = field(default_factory=dict)        # crédit de buts par joueur


# =============================================================================
# 3. CALCUL DU MATCH (fonctions pures, déterministes)
# =============================================================================
def clamp(value, low, high):
    return max(low, min(high, value))


def build_profile(team: Team) -> TeamProfile:
    xi = team.best_xi()
    xi_ids = {p.id for p, _ in xi}
    ratings = {role: [p.ovr[role] for p, r in xi if r == role] for role in ROLES}

    attack = (sum(ratings["att"]) + 0.5 * sum(ratings["mid"])) / (len(ratings["att"]) + 0.5 * len(ratings["mid"]))
    defense = (sum(ratings["def"]) + 0.4 * sum(ratings["mid"]) + 1.5 * sum(ratings["gk"])) / (
        len(ratings["def"]) + 0.4 * len(ratings["mid"]) + 1.5 * len(ratings["gk"]))

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
        coach_factor=team.coach.factor, captain_in_xi=in_xi,
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


def scoring_shares(profile: TeamProfile) -> dict:
    """Part de buts théorique de chaque titulaire (finition/tir, selon son rôle)."""
    raw = {}
    for player, role, _ in profile.xi:
        s = player.stats
        skill = (0.5 * s["finishing"] + 0.3 * s["shooting"] + 0.1 * s["composure"] + 0.1 * s["heading"]) / 100
        weight = skill ** 3 * SCORING_ROLE_WEIGHT[role]
        if weight > 0:
            raw[player.id] = weight
    total = sum(raw.values())
    return {pid: w / total for pid, w in raw.items()}


def assign_scorers(team: Team, profile: TeamProfile, state: TeamState, goals: int, key: str) -> list:
    """Attribue chaque but au joueur dont le crédit est le plus élevé (méthode du plus fort reste)."""
    shares = scoring_shares(profile)
    names = {p.id: p.name for p, _, _ in profile.xi}
    events = []
    for k in range(goals):
        for pid, share in shares.items():
            state.credit[pid] = state.credit.get(pid, 0.0) + share
        scorer = max(shares, key=lambda pid: (state.credit[pid], -pid))
        state.credit[scorer] -= 1.0
        base = (k + 1) * 90 / (goals + 1)
        jitter = zlib.crc32(f"{key}:{team.id}:{k}".encode()) % 21 - 10        # déterministe
        minute = int(clamp(round(base + jitter), 1, 90))
        events.append(GoalEvent(minute, team.id, scorer, names[scorer]))
    return events


def play_match(matchday: int, home: Team, away: Team, profiles: dict, states: dict) -> MatchResult:
    ph, pa = profiles[home.id], profiles[away.id]
    sh, sa = states[home.id], states[away.id]

    mood_h, last3_h = mood_factor(sh, home.coach)
    mood_a, last3_a = mood_factor(sa, away.coach)
    mult_h = mood_h * ph.coach_factor * ph.captain_factor * ph.depth_factor
    mult_a = mood_a * pa.coach_factor * pa.captain_factor * pa.depth_factor

    xg_h = expected_goals(ph.attack, pa.defense, mult_h, mult_a, HOME_ATTACK)
    xg_a = expected_goals(pa.attack, ph.defense, mult_a, mult_h, AWAY_ATTACK)
    goals_h = convert_to_goals(sh, xg_h)
    goals_a = convert_to_goals(sa, xg_a)

    key = f"{matchday}:{home.id}:{away.id}"
    events = assign_scorers(home, ph, sh, goals_h, key) + assign_scorers(away, pa, sa, goals_a, key)
    events.sort(key=lambda e: (e.minute, e.team_id))

    sh.recent_diffs.append(goals_h - goals_a)
    sa.recent_diffs.append(goals_a - goals_h)

    def report(team, prof, opp, last3, mood, mult, venue, xg):
        return SideReport(
            team_id=team.id, attack=prof.attack, defense=prof.defense, ratio=prof.attack / opp.defense,
            last3=last3, mood_factor=mood, coach_factor=prof.coach_factor, captain_factor=prof.captain_factor,
            depth_factor=prof.depth_factor, multiplier=mult, venue_factor=venue, xg=xg,
            lineup=[(p.name, r, rating) for p, r, rating in prof.xi],
        )

    return MatchResult(
        matchday, home.id, away.id, goals_h, goals_a,
        report(home, ph, pa, last3_h, mood_h, mult_h, HOME_ATTACK, xg_h),
        report(away, pa, ph, last3_a, mood_a, mult_a, AWAY_ATTACK, xg_a),
        events,
    )


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


def simulate_season(teams: list) -> SeasonResult:
    teams = sorted(teams, key=lambda t: t.id)
    by_id = {t.id: t for t in teams}
    profiles = {t.id: build_profile(t) for t in teams}
    states = {t.id: TeamState() for t in teams}
    rows = {t.id: TableRow(t.id) for t in teams}

    matchdays, tables = [], []
    scorers: dict = {}

    for matchday, pairs in enumerate(round_robin([t.id for t in teams]), start=1):
        day = []
        for home_id, away_id in pairs:
            m = play_match(matchday, by_id[home_id], by_id[away_id], profiles, states)
            day.append(m)
            for team_id, gf, ga in ((home_id, m.home_goals, m.away_goals), (away_id, m.away_goals, m.home_goals)):
                r = rows[team_id]
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
                entry = scorers.setdefault(e.player_id, [e.player_name, e.team_id, 0])
                entry[2] += 1
        matchdays.append(day)

        ordered = sorted(rows.values(), key=lambda r: (-r.pts, -r.gd, -r.gf, by_id[r.team_id].name))
        tables.append([replace(r, rank=i + 1, form=list(r.form)) for i, r in enumerate(ordered)])

    return SeasonResult(matchdays, tables, scorers, profiles)


# =============================================================================
# 5. BASE DE DONNÉES + CRÉATION DE LA LIGUE + TRANSFERTS
# =============================================================================
PLAYER_SELECT = ("id, first_name, last_name, age, country, city, preferred_foot, potential, overall, "
                 "best_position, ovr_gk, ovr_def, ovr_mid, ovr_att, " + ", ".join(STATS))

TEAM_PREFIXES = ["FC", "AS", "US", "Olympique", "Racing", "Sporting", "Stade", "Athletic", "Union", "SC"]
LOGO_PATTERNS = ["stripes", "split", "band", "hoops", "cross", "plain"]


def row_to_player(row) -> Player:
    return Player(
        id=row[0], first_name=row[1], last_name=row[2], age=row[3], country=row[4], city=row[5],
        preferred_foot=row[6], potential=row[7], overall=row[8], best_position=row[9],
        ovr={"gk": row[10], "def": row[11], "mid": row[12], "att": row[13]},
        stats=dict(zip(STATS, row[14:14 + len(STATS)])),
    )


def _ascii_letters(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if c.isalpha() and unicodedata.category(c) != "Mn").upper()


class League:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.con = sqlite3.connect(db_path)
        self.teams: dict = {}
        self.transfers: list = []
        self.result: SeasonResult | None = None
        self.previous: SeasonResult | None = None
        self._ensure_indexes()

    # ------------------------------------------------------------------ DB
    def _ensure_indexes(self) -> None:
        tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "players" not in tables:
            raise RuntimeError(f"Pas de table 'players' dans {self.db_path} : génère d'abord la base.")
        for col in ("team_id", "ovr_gk", "ovr_def", "ovr_mid", "ovr_att"):
            self.con.execute(f"CREATE INDEX IF NOT EXISTS idx_players_{col} ON players({col})")
        self.con.commit()

    @classmethod
    def load_or_create(cls, db_path: str, seed: int = 42, force_new: bool = False) -> "League":
        league = cls(db_path)
        if not force_new and league._load():
            return league
        league._create(seed)
        return league

    def _load(self) -> bool:
        tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "teams" not in tables:
            return False
        rows = self.con.execute(
            "SELECT id, name, short, city, primary_color, secondary_color, pattern, captain_id, "
            "coach_name, coach_tactics, coach_motivation FROM teams ORDER BY id").fetchall()
        if not rows:
            return False
        self.teams = {
            r[0]: Team(r[0], r[1], r[2], r[3], r[4], r[5], r[6], Coach(r[8], r[9], r[10]), [], r[7])
            for r in rows
        }
        query = f"SELECT {PLAYER_SELECT}, team_id FROM players WHERE team_id IS NOT NULL"
        for row in self.con.execute(query):
            if row[-1] in self.teams:
                self.teams[row[-1]].players.append(row_to_player(row))
        return all(len(t.players) == SQUAD_SIZE for t in self.teams.values())

    def _save(self) -> None:
        c = self.con
        c.execute("UPDATE players SET team_id=NULL WHERE team_id IS NOT NULL")
        c.executemany("UPDATE players SET team_id=? WHERE id=?",
                      [(t.id, p.id) for t in self.teams.values() for p in t.players])
        c.execute("DROP TABLE IF EXISTS teams")
        c.execute("""CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT, short TEXT, city TEXT,
                     primary_color TEXT, secondary_color TEXT, pattern TEXT, captain_id INTEGER,
                     coach_name TEXT, coach_tactics INTEGER, coach_motivation INTEGER)""")
        c.executemany("INSERT INTO teams VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            (t.id, t.name, t.short, t.city, t.primary, t.secondary, t.pattern, t.captain_id,
             t.coach.name, t.coach.tactics, t.coach.motivation) for t in self.teams.values()])
        c.commit()

    # ------------------------------------------------------------ création
    def _create(self, seed: int, n_teams: int = 20, country: str = "France") -> None:
        rng = random.Random(seed)
        faker = Faker(seed=seed)
        self.con.execute("UPDATE players SET team_id=NULL WHERE team_id IS NOT NULL")
        self.transfers.clear()
        self.result = self.previous = None

        # --- identités des clubs
        cities = faker.get_cities(country)
        rng.shuffle(cities)
        used_short: set = set()
        tiers = [i / (n_teams - 1) for i in range(n_teams)]       # 0 = plus faible, 1 = plus fort
        rng.shuffle(tiers)

        pools = self._candidate_pools()
        self.teams = {}
        for i in range(n_teams):
            city = cities[i]
            prefix = TEAM_PREFIXES[rng.randrange(len(TEAM_PREFIXES))]
            letters = _ascii_letters(city)
            short = letters[:3]
            n = 1
            while short in used_short:
                short = letters[:2] + str(n)
                n += 1
            used_short.add(short)

            hue = (i * 360 / n_teams + rng.uniform(0, 12)) % 360 / 360
            primary = "#%02x%02x%02x" % tuple(int(255 * c) for c in colorsys.hls_to_rgb(hue, 0.38, 0.70))
            secondary = rng.choice(["#ffffff", "#ffd400", "#111111", "#f2f2f2", "#ffb703"])
            coach_person = faker.get_person(sex=1, minimum_age=38, maximum_age=66, current_date=2026)
            coach = Coach(f"{coach_person.first_name} {coach_person.last_name}",
                          int(clamp(rng.gauss(55, 14), 20, 95)), int(clamp(rng.gauss(55, 14), 20, 95)))
            team = Team(i + 1, f"{prefix} {city}", short, city, primary, secondary,
                        LOGO_PATTERNS[rng.randrange(len(LOGO_PATTERNS))], coach)

            quality = 56 + 14 * tiers[i]                           # niveau cible des joueurs du club
            for role, count in SQUAD_COMPOSITION.items():
                for _ in range(count):
                    team.players.append(self._pick_nearest(pools[role], role, quality + rng.gauss(0, 3)))
            team.elect_captain()
            self.teams[team.id] = team
        self._save()

    def _candidate_pools(self) -> dict:
        pools = {}
        for role in ROLES:
            rows = self.con.execute(
                f"SELECT {PLAYER_SELECT} FROM players WHERE best_position=? AND age BETWEEN 19 AND 34 "
                f"AND overall BETWEEN 46 AND 84 AND team_id IS NULL LIMIT 4000", (role,)).fetchall()
            players = sorted((row_to_player(r) for r in rows), key=lambda p: (p.ovr[role], p.id))
            if len(players) < 120:
                raise RuntimeError(f"Pas assez de joueurs ({role}) dans la base : génère au moins 50 000 joueurs.")
            pools[role] = players
        return pools

    @staticmethod
    def _pick_nearest(pool: list, role: str, target: float) -> Player:
        keys = [p.ovr[role] for p in pool]
        i = bisect.bisect_left(keys, target)
        i = min(max(i, 0), len(pool) - 1)
        if i > 0 and abs(keys[i - 1] - target) <= abs(keys[i] - target):
            i -= 1
        return pool.pop(i)

    # ---------------------------------------------------------- simulation
    def simulate(self) -> SeasonResult:
        self.previous = self.result
        self.result = simulate_season(list(self.teams.values()))
        return self.result

    # -------------------------------------------------------------- marché
    def market(self, role: str | None = None, min_rating: float = 0, max_age: int = 45,
               name: str = "", limit: int = 200) -> list:
        column = f"ovr_{role}" if role else "overall"
        sql = f"SELECT {PLAYER_SELECT} FROM players WHERE team_id IS NULL AND {column} >= ? AND age <= ?"
        params: list = [min_rating, max_age]
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
        Sinon : échange de joueurs entre deux clubs."""
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
                self.con.execute("UPDATE teams SET captain_id=? WHERE id=?", (t.captain_id, t.id))
        self.con.commit()

        label = lambda p: f"{p.name} ({ROLE_LABELS[p.best_position]} {p.overall:.0f})"
        where = f"avec {other.name}" if other else "via le marché libre"
        text = f"{team.name} : {label(out_player)} part, {label(in_player)} arrive ({where})"
        self.transfers.append(text)
        return text


MODEL_EXPLANATION = f"""
<h3>Comment le score est calculé (aucun hasard)</h3>
<p><b>1. Onze de départ</b> : 4-4-2 choisi automatiquement parmi les 16 joueurs (meilleurs notes à chaque poste).</p>
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
"""
