"""
exports.py : exports CSV de toutes les données du jeu (aucun Qt).

Format pensé pour Excel en français : séparateur « ; » et encodage UTF-8 avec BOM.
    export_all(world, "dossier")  ->  liste des fichiers écrits
"""
from __future__ import annotations

import csv
import os

from finance import player_salary, player_value, wage_bill
from league_engine import STATS


def write_csv(path: str, headers: list, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(headers)
        writer.writerows(rows)


def _query(world, sql: str):
    cur = world.con.execute(sql)
    return [d[0] for d in cur.description], cur.fetchall()


def export_all(world, folder: str) -> list:
    """Écrit un fichier CSV par thème dans `folder` et renvoie leurs noms."""
    os.makedirs(folder, exist_ok=True)
    written = []

    def out(name, headers, rows):
        write_csv(os.path.join(folder, name), headers, rows)
        written.append(name)

    teams, ledger = world.teams, world.ledger

    # classements actuels
    rows = []
    for (country, division), lg in world.competitions.items():
        for r in lg.season.result.current_table:
            rows.append([country, division, r.rank, teams[r.team_id].name, r.played, r.won, r.drawn, r.lost,
                         r.gf, r.ga, r.gd, r.pts])
    out("classements.csv", ["Pays", "Division", "Rang", "Équipe", "J", "V", "N", "D", "BP", "BC", "Diff", "Pts"], rows)

    # équipes + finances indicatives
    rows = []
    for t in teams.values():
        st = world.team_statement(t.id)
        rows.append([t.id, t.name, t.country, t.division, t.formation, round(t.overall_rating, 2), t.stadium,
                     t.capacity, t.coach.name, t.budget, t.budget + st["profit"], wage_bill(t),
                     st["total_revenus"], st["total_dépenses"], st["profit"]])
    out("equipes.csv", ["Id", "Équipe", "Pays", "Division", "Formation", "Note générale", "Stade", "Capacité",
                        "Entraîneur", "Budget début de saison", "Budget actuel (indicatif)", "Masse salariale annuelle",
                        "Recettes saison", "Dépenses saison", "Résultat saison"], rows)

    # joueurs
    rows = []
    for t in teams.values():
        for p in t.players:
            st = ledger.stats.get(p.id, {})
            rows.append([p.id, p.name, p.nickname or "", t.name, t.country, t.division, p.number, p.best_position,
                         p.age, p.country, round(p.overall, 1), p.potential, p.injury_resistance,
                         player_salary(p), player_value(p), st.get("games", 0), st.get("goals", 0),
                         st.get("assists", 0), st.get("yellow", 0), st.get("red", 0), st.get("injuries", 0),
                         *(p.stats[s] for s in STATS)])
    out("joueurs.csv", ["Id", "Joueur", "Surnom", "Équipe", "Pays du club", "Division", "Numéro", "Poste", "Âge",
                        "Nationalité", "Note", "Potentiel", "Résistance blessures", "Salaire annuel (€)",
                        "Valeur (€)", "Matchs", "Buts", "Passes", "Jaunes", "Rouges", "Blessures", *STATS], rows)

    # matchs de championnat
    rows = []
    for (country, division), lg in world.competitions.items():
        for day, matches in enumerate(lg.season.matchdays, start=1):
            for m in matches:
                rows.append([country, division, day, teams[m.home_id].name, teams[m.away_id].name, m.home_goals,
                             m.away_goals, m.attendance, m.capacity,
                             sum(1 for c in m.cards if c.kind == "yellow"), sum(1 for c in m.cards if c.kind != "yellow"),
                             len(m.injuries), round(m.home.xg, 2), round(m.away.xg, 2),
                             "; ".join(f"{g.minute}' {g.player_name}" + (f" (passe {g.assist_name})" if g.assist_name else "")
                                       for g in m.goals)])
    out("matchs_championnat.csv", ["Pays", "Division", "Journée", "Domicile", "Extérieur", "Buts dom.", "Buts ext.",
                                   "Affluence", "Capacité", "Jaunes", "Rouges", "Blessures", "xG dom.", "xG ext.",
                                   "Buteurs"], rows)

    # coupes (nationales + interligue)
    rows = []
    cups = [(f"Coupe {c}", cup) for c, cup in world.cups.items()]
    cups += [("Interligue 1" if k == "blue" else "Interligue 2", cup) for k, cup in world.interleague.items() if cup]
    for label, cup in cups:
        for index, matches in enumerate(cup.rounds):
            day = cup.round_days[index] if index < len(cup.round_days) else ""
            for cm in matches:
                rows.append([label, cm.round_name, day, teams[cm.home_id].name, teams[cm.away_id].name,
                             cm.result.home_goals, cm.result.away_goals,
                             f"{cm.pens[0]}-{cm.pens[1]}" if cm.pens else "", cm.result.attendance])
    out("matchs_coupes.csv", ["Compétition", "Tour", "Journée", "Domicile", "Extérieur", "Buts dom.", "Buts ext.",
                              "Tirs au but", "Affluence"], rows)

    # buteurs et passeurs, tout confondu
    rows = []
    for pid, (name, team_id, goals, assists) in sorted(ledger.aggregate(lambda sc: True).items(),
                                                       key=lambda kv: (-kv[1][2], -kv[1][3], kv[1][0])):
        rows.append([name, teams[team_id].name, teams[team_id].country, goals, assists])
    out("buteurs_passeurs.csv", ["Joueur", "Équipe", "Pays", "Buts", "Passes décisives"], rows)

    # amicaux
    rows = [[teams[m.home_id].name, teams[m.away_id].name, m.home_goals, m.away_goals, m.attendance]
            for m in world.friendlies]
    out("matchs_amicaux.csv", ["Domicile", "Extérieur", "Buts dom.", "Buts ext.", "Affluence"], rows)

    # historique (base de données)
    for filename, sql in (("historique_equipes.csv", "SELECT * FROM team_history ORDER BY season, country, division, rank"),
                          ("trophees.csv", "SELECT * FROM trophies ORDER BY season, kind"),
                          ("saisons_joueurs.csv", "SELECT * FROM player_seasons ORDER BY season, team_name"),
                          ("finances_historique.csv", "SELECT * FROM team_finances ORDER BY season, country, division")):
        headers, data = _query(world, sql)
        out(filename, headers, [list(r) for r in data])
    return written
