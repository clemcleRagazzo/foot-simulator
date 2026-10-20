"""
Faker maison : prénoms, noms, villes, dates de naissance... sans aucune dépendance (ni Qt).

    from fake import Faker

    faker = Faker(seed=42)            # seed -> résultats reproductibles
    person = faker.get_person()       # prénom, nom, sexe, pays, ville, date de naissance
    faker.get_first_name_male("France")
    faker.get_birth_date(2026, minimum_age=17, maximum_age=38)

Pour l'utiliser comme ton ancien module : copie fake.py et fake_data.py dans source/utils/
(renomme fake.py en faker.py si tu veux garder l'import `from source.utils.faker import Faker`).
"""
import random
from dataclasses import dataclass
from datetime import date, timedelta

from fake_data import COUNTRIES, CountryData  # dans ton projet : from source.utils.fake_data import ...

MALE = 1
FEMALE = 0

VOWELS = "aeiouyéèêàâîïôûù"

PARTY_FIRST_WORDS = ["parti", "organisation", "groupe", "union", "alliance"]
PARTY_ADJECTIVES = [
    "écologiste", "continental", "nationaliste", "constructiviste", "fasciste", "capitaliste",
    "socialiste", "intégriste", "libéral", "démocrate", "méritocrate", "inclusif", "communiste",
    "humaniste", "réformiste", "souverainiste", "fédéraliste", "pacifiste", "progressiste",
]
PARTY_SLOGANS = [
    "Devenir avenir",
    "A bas la France",
    "Vive l'écologie",
    "Oui oui baguette",
    "Retrouvons notre saveur d'antan",
    "Ne fouillons plus le passé",
    "Admirez ce beau paysage",
    "Pour une France meilleure",
    "Ensemble, plus loin",
    "Le courage de changer",
    "Demain commence aujourd'hui",
    "Du pain, des jeux, des idées",
    "Un pays qui se tient debout",
    "Moins de bruit, plus de choix",
]


@dataclass
class Person:
    first_name: str
    last_name: str
    sex: int            # 1 = homme, 0 = femme
    country: str
    city: str
    birth_date: str     # "yyyy-MM-dd"


class Faker:
    def __init__(self, seed: int | None = None, diaspora_rate: float = 0.12) -> None:
        """
        seed          : même seed = mêmes résultats (dans le même ordre d'appels).
        diaspora_rate : proba qu'un joueur ait des origines (prénom + nom) d'un autre pays
                        que celui où il est né (ex. un Français avec un nom marocain).
        """
        self.rng = random.Random(seed)
        self.diaspora_rate = diaspora_rate
        self._by_name: dict[str, CountryData] = {c.name: c for c in COUNTRIES}
        self.countries: list[str] = list(self._by_name)
        self._weights: list[int] = [c.weight for c in COUNTRIES]

    # ------------------------------------------------------------------ pays
    def _resolve_country(self, country) -> CountryData:
        """Accepte None (au hasard), un nom de pays (str) ou un objet avec un attribut .name."""
        if country is None:
            return self.rng.choices(COUNTRIES, self._weights)[0]
        name = country if isinstance(country, str) else country.name
        return self._by_name[name]

    def _name_origin(self, country) -> CountryData:
        """Pays dont on tire les noms : le pays lui-même, ou (diaspora) un autre pays."""
        home = self._resolve_country(country)
        if self.rng.random() < self.diaspora_rate:
            return self.rng.choices(COUNTRIES, self._weights)[0]
        return home

    def get_country(self) -> str:
        return self._resolve_country(None).name

    def get_countries(self) -> list[str]:
        return list(self.countries)

    # ---------------------------------------------------------------- sexe
    def get_sex(self) -> int:
        return self.rng.randint(0, 1)

    # ------------------------------------------------------------- prénoms
    def _first_name(self, origin: CountryData, sex: int) -> str:
        names = origin.first_names_male if sex == MALE else origin.first_names_female
        return self.rng.choice(names)

    def get_first_name(self, country=None) -> str:
        return self._first_name(self._name_origin(country), self.get_sex())

    def get_first_name_male(self, country=None) -> str:
        return self._first_name(self._name_origin(country), MALE)

    def get_first_name_female(self, country=None) -> str:
        return self._first_name(self._name_origin(country), FEMALE)

    # ----------------------------------------------------------------- noms
    def _last_name(self, origin: CountryData) -> str:
        if origin.surname_style == "two_surnames":
            first, second = self.rng.sample(origin.last_names, 2)
            return f"{first} {second}"
        if origin.surname_style == "hyphen" and self.rng.randint(0, 5) == 5:
            first, second = self.rng.sample(origin.last_names, 2)
            return f"{first}-{second}"
        return self.rng.choice(origin.last_names)

    def get_last_name(self, country=None) -> str:
        return self._last_name(self._name_origin(country))

    def get_full_name(self, country=None) -> str:
        origin = self._name_origin(country)
        return f"{self._first_name(origin, self.get_sex())} {self._last_name(origin)}"

    # --------------------------------------------------------------- villes
    @property
    def cities(self) -> dict[str, list[str]]:
        return {c.name: list(c.cities) for c in COUNTRIES}

    def get_cities(self, country=None) -> list[str]:
        """Toutes les villes d'un pays, ou de tous les pays si country est None."""
        if country is None:
            return [city for c in COUNTRIES for city in c.cities]
        return list(self._resolve_country(country).cities)

    def get_city(self) -> str:
        return self.rng.choice(self._resolve_country(None).cities)

    def get_city_by_country(self, country) -> str | None:
        if not country:
            return None
        return self.rng.choice(self._resolve_country(country).cities)

    def get_address(self, country=None) -> str:
        data = self._resolve_country(country)
        street = self.rng.choice(data.last_names)
        number = self.rng.randint(1, 200)
        line = data.street_format.format(n=number, name=street)
        return f"{line}, {self.rng.choice(data.cities)}, {data.name}"

    # ------------------------------------------------------- date naissance
    @staticmethod
    def _year_of(current_date) -> int:
        """Année de 'current_date' : None, int, str 'yyyy-MM-dd', date, ou objet avec get_date()."""
        if current_date is None:
            return date.today().year
        if isinstance(current_date, int):
            return current_date
        if isinstance(current_date, str):
            return int(current_date[:4])
        if hasattr(current_date, "get_date"):             # ancien objet Time
            return Faker._year_of(current_date.get_date())
        year = current_date.year
        return year() if callable(year) else year

    def get_birth_date(self, current_date=None, minimum_age: int = 18, maximum_age: int = 64) -> str:
        """Date de naissance au format 'yyyy-MM-dd', pour un âge entre minimum_age et maximum_age."""
        year = self._year_of(current_date)
        start = date(year - maximum_age, 1, 1)
        end = date(year - minimum_age, 12, 31)
        birth = start + timedelta(days=self.rng.randint(0, (end - start).days))
        return birth.isoformat()

    # ---------------------------------------------------------- personnes
    def get_person(self, country=None, sex: int | None = None, current_date=None,
                   minimum_age: int = 18, maximum_age: int = 64) -> Person:
        """Identité complète et cohérente (prénom + nom de la même origine)."""
        home = self._resolve_country(country)
        origin = self._name_origin(home.name)
        sex = self.get_sex() if sex is None else sex
        return Person(
            first_name=self._first_name(origin, sex),
            last_name=self._last_name(origin),
            sex=sex,
            country=home.name,
            city=self.rng.choice(home.cities),
            birth_date=self.get_birth_date(current_date, minimum_age, maximum_age),
        )

    # ------------------------------------------------- partis / alliances
    @staticmethod
    def _combining_form(adjective: str) -> str:
        """'écologiste' -> 'écologo', 'inclusif' -> 'inclusivo', 'libéral' -> 'libéralo'."""
        if adjective.endswith("iste"):
            adjective = adjective[:-4]
        elif adjective[-1] in VOWELS:
            adjective = adjective[:-1]
        if adjective.endswith("f"):
            adjective = adjective[:-1] + "v"
        return adjective + "o"

    def get_part_name(self) -> str:
        first_word = self.rng.choice(PARTY_FIRST_WORDS)
        article = ""
        if self.rng.randint(0, 1) == 1:
            article = "l'" if first_word[0] in VOWELS else "le "

        left, right = self.rng.sample(PARTY_ADJECTIVES, 2)
        name = f"{article}{first_word} {self._combining_form(left)}-{right}"
        return name.strip().capitalize()

    def get_party_slogan(self) -> str:
        return self.rng.choice(PARTY_SLOGANS)

    def get_alliance_name(self) -> str:
        return self.get_part_name()

    def get_alliance_slogan(self) -> str:
        return self.get_party_slogan()
