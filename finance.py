"""
finance.py : salaires, valeur marchande, recettes / dépenses et budgets des clubs.

POUR L'INSTANT TOUT EST INDICATIF : rien ne bloque un transfert ni une action, les chiffres servent à comparer
les clubs et à voir l'équilibre financier d'une saison. Mais le module est prévu pour devenir une vraie gestion :

  * les barèmes sont des constantes en haut de fichier (faciles à régler) ;
  * `season_statement()` produit un état financier complet (lignes de recettes et de dépenses) ;
  * `transfer_fee()` donne l'indemnité d'un transfert, que le moteur applique aux budgets ;
  * l'option « budget strict » (menu Options, désactivée) refuse déjà un transfert plus cher que le budget ;
  * à ajouter plus tard sans casser l'existant : contrats (durée, clause), plafond salarial, prêts, primes.

Aucune dépendance : les fonctions reçoivent des objets « canard » (joueur, équipe, entraîneur du moteur).
"""
from __future__ import annotations

import math

# =============================================================================
# 1. BARÈMES (montants en euros)
# =============================================================================
SALARY_BASE = 40_000          # salaire annuel d'un joueur de note 40
SALARY_GROWTH = 0.118         # +11,8 % par point de note : 60 -> ~0,4 M€, 75 -> ~2,5 M€, 90 -> ~15 M€
VALUE_YEARS_BY_AGE = [(23, 5.0), (28, 4.0), (31, 2.8), (34, 1.4), (99, 0.6)]    # valeur = salaire x ce nombre d'années
SIGNING_BONUS_RATE = 0.10     # prime à la signature d'un joueur libre : 10 % du salaire annuel
TV_BY_DIVISION = {1: 12_000_000, 2: 3_000_000, 3: 1_000_000}
SPONSOR_BY_DIVISION = {1: 8_000_000, 2: 2_500_000, 3: 800_000}
PRIZE_BY_DIVISION = {1: (8_000_000, 1_000_000), 2: (2_000_000, 300_000), 3: (600_000, 100_000)}   # 1er -> dernier
UPKEEP_PER_SEAT = 60          # entretien du stade, par place et par an
OPERATING_RATE = 0.50         # staff, formation, fonctionnement : 50 % de la masse salariale
CUP_PER_MATCH, CUP_PER_WIN = 40_000, 60_000
CUP_FINALIST, CUP_CHAMPION = 200_000, 500_000
INTERLEAGUE_FACTOR = 4        # les coupes interligue rapportent 4 fois plus


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# =============================================================================
# 2. JOUEURS ET ENTRAÎNEURS
# =============================================================================
def player_salary(p) -> int:
    """Salaire annuel : exponentiel selon la note, réduit pour les très jeunes et les vétérans,
    majoré pour les jeunes à fort potentiel."""
    base = SALARY_BASE * math.exp(SALARY_GROWTH * (p.overall - 40))
    age_factor = 0.65 if p.age < 21 else 0.85 if p.age < 24 else 1.0 if p.age <= 30 else 0.85 if p.age <= 33 else 0.65
    potential_factor = 1 + max(0, p.potential - p.overall) / 100 * 0.8
    return int(round(base * age_factor * potential_factor / 1000) * 1000)


def player_value(p) -> int:
    """Valeur marchande : plusieurs années de salaire (beaucoup pour un jeune, peu pour un vétéran)."""
    years = next(y for limit, y in VALUE_YEARS_BY_AGE if p.age <= limit)
    return int(round(player_salary(p) * years / 10_000) * 10_000)


def coach_salary(coach) -> int:
    return 250_000 + int((coach.tactics + coach.motivation) * 9_000)


def wage_bill(team) -> int:
    """Masse salariale annuelle : joueurs + entraîneur."""
    return sum(player_salary(p) for p in team.players) + coach_salary(team.coach)


# =============================================================================
# 3. CLUBS
# =============================================================================
def _rel(team) -> float:
    """Niveau du club de 0 (faible) à 1 (très fort), d'après la note générale."""
    return _clamp((team.overall_rating - 36) / 20, 0.0, 1.0)


def ticket_price(team) -> float:
    return 8 + 20 * _rel(team)


def tv_income(team) -> int:
    return int(TV_BY_DIVISION.get(team.division, 500_000) * (0.7 + 0.6 * _rel(team)))


def sponsor_income(team) -> int:
    return int(SPONSOR_BY_DIVISION.get(team.division, 300_000) * (0.3 + 1.4 * _rel(team)))


def upkeep(team) -> int:
    return int(team.capacity * UPKEEP_PER_SEAT)


def initial_budget(team) -> int:
    """Budget de départ : environ 14 mois de salaires + de quoi faire vivre le stade."""
    return int(round((wage_bill(team) * 1.2 + team.capacity * 400) / 100_000) * 100_000)


def league_prize(division: int, rank: int, n_teams: int) -> int:
    """Prime de classement, du 1er au dernier (interpolation linéaire)."""
    top, bottom = PRIZE_BY_DIVISION.get(division, (200_000, 50_000))
    return int(top + (bottom - top) * (rank - 1) / max(1, n_teams - 1))


def cup_income(team_id: int, cup, factor: float = 1.0) -> int:
    """Primes de coupe : participation + victoire par match, bonus de finaliste / vainqueur."""
    if cup is None:
        return 0
    total = 0
    for matches in cup.rounds:
        for m in matches:
            if team_id in (m.home_id, m.away_id):
                total += CUP_PER_MATCH
                if m.winner_id == team_id:
                    total += CUP_PER_WIN
                if m.round_name == "Finale":
                    total += CUP_CHAMPION if m.winner_id == team_id else CUP_FINALIST
    return int(total * factor)


def transfer_fee(in_player, out_player=None, free_market: bool = False) -> int:
    """Indemnité NETTE payée par l'équipe qui reçoit `in_player` (négative = elle encaisse).
    Marché libre : seulement une prime à la signature. Échange entre clubs : écart des valeurs marchandes."""
    if free_market or out_player is None:
        return int(player_salary(in_player) * SIGNING_BONUS_RATE)
    return player_value(in_player) - player_value(out_player)


# =============================================================================
# 4. ÉTAT FINANCIER D'UNE SAISON
# =============================================================================
def season_statement(team, fraction: float, tickets: float, sales: float, purchases: float, cup_total: float,
                     prize: float) -> dict:
    """État financier à une date donnée de la saison.
    fraction : part de la saison écoulée (0 à 1) pour les postes annuels (TV, sponsors, salaires, entretien).
    tickets / sales / purchases : montants réels déjà encaissés ou payés. cup_total, prize : primes.
    Renvoie {"revenus": [(libellé, €)], "dépenses": [...], "total_revenus", "total_dépenses", "profit"}."""
    wages = sum(player_salary(p) for p in team.players)
    revenus = [("Billetterie", tickets), ("Droits TV", tv_income(team) * fraction),
               ("Sponsors", sponsor_income(team) * fraction), ("Primes de coupes", cup_total),
               ("Prime de classement", prize), ("Ventes de joueurs", sales)]
    depenses = [("Salaires des joueurs", wages * fraction), ("Salaire de l'entraîneur", coach_salary(team.coach) * fraction),
                ("Staff et fonctionnement", (wages + coach_salary(team.coach)) * OPERATING_RATE * fraction),
                ("Entretien du stade", upkeep(team) * fraction), ("Achats de joueurs", purchases)]
    total_in, total_out = sum(v for _, v in revenus), sum(v for _, v in depenses)
    return {"revenus": [(k, int(v)) for k, v in revenus], "dépenses": [(k, int(v)) for k, v in depenses],
            "total_revenus": int(total_in), "total_dépenses": int(total_out), "profit": int(total_in - total_out)}


# =============================================================================
# 5. AFFICHAGE
# =============================================================================
def fmt_money(value: float, signed: bool = False) -> str:
    """12 345 678 -> « 12,3 M€ » ; 450 000 -> « 450 k€ » ; 800 -> « 800 € »."""
    sign = "+" if signed and value > 0 else "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        text = f"{v / 1_000_000:.1f}".replace(".", ",") + " M€"
    elif v >= 1_000:
        text = f"{v / 1_000:.0f} k€"
    else:
        text = f"{v:.0f} €"
    return sign + text
