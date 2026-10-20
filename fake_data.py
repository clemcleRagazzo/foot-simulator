"""
Données du Faker : prénoms, noms, villes par pays.

Pour ajouter un pays : copie un bloc CountryData(...) dans COUNTRIES.
  - weight         : fréquence de tirage du pays (plus c'est grand, plus il apparaît)
  - surname_style  : "single"        -> un nom          (Dupont)
                     "hyphen"        -> un nom, parfois double avec tiret (Dupont-Martin)
                     "two_surnames"  -> toujours deux noms (García López)
  - street_format  : format d'adresse, avec {n} (numéro) et {name} (nom de rue)
"""
from dataclasses import dataclass


def names(text: str) -> list[str]:
    """Transforme 'A, B, C' en ['A', 'B', 'C'] (permet de garder les listes lisibles)."""
    return [item.strip() for item in text.replace("\n", " ").split(",") if item.strip()]


@dataclass(frozen=True)
class CountryData:
    name: str
    weight: int
    surname_style: str
    street_format: str
    first_names_male: list[str]
    first_names_female: list[str]
    last_names: list[str]
    cities: list[str]


COUNTRIES: list[CountryData] = [
    # ------------------------------------------------------------------ EUROPE
    CountryData(
        name="France", weight=6, surname_style="hyphen", street_format="{n} rue {name}",
        first_names_male=names("""
            Adrien, Alexandre, Amine, Antoine, Arnaud, Axel, Baptiste, Bastien, Benjamin, Clément,
            Corentin, Damien, Dylan, Enzo, Étienne, Florian, Gaël, Hugo, Jules, Julien, Kévin,
            Kylian, Léo, Loïc, Louis, Lucas, Mathis, Maxime, Mehdi, Nathan, Nicolas, Olivier,
            Quentin, Raphaël, Rémi, Romain, Théo, Thomas, Tristan, Valentin, Victor, Yanis"""),
        first_names_female=names("""
            Adeline, Alice, Amélie, Anaïs, Camille, Chloé, Clara, Emma, Inès, Jade, Julie, Léa,
            Louise, Manon, Marie, Océane, Pauline, Sarah, Sophie, Zoé"""),
        last_names=names("""
            Martin, Bernard, Dubois, Thomas, Robert, Richard, Petit, Durand, Leroy, Moreau, Simon,
            Laurent, Lefebvre, Michel, Garcia, David, Bertrand, Roux, Vincent, Fournier, Morel,
            Girard, André, Mercier, Dupont, Lambert, Bonnet, François, Martinez, Legrand, Garnier,
            Faure, Rousseau, Blanc, Guérin, Muller, Henry, Roussel, Perrin, Morin, Mathieu, Gauthier,
            Dumont, Lopez, Fontaine, Chevalier, Robin, Masson, Aubert, Barbier, Baron, Bazin,
            Boucher, Boyer, Brun, Caron, Charpentier, Colin, Dufour, Dumas, Dupuis, Gaillard,
            Hamon, Jacquet, Lemaire, Lemoine, Maillard, Marchand, Menard, Noël, Pelletier, Picard,
            Renard, Renaud, Rigaud, Tessier, Vasseur, Verdier, Vidal"""),
        cities=names("""
            Paris, Marseille, Lyon, Toulouse, Nice, Nantes, Strasbourg, Montpellier, Bordeaux,
            Lille, Rennes, Reims, Le Havre, Saint-Étienne, Toulon, Grenoble, Dijon, Angers,
            Nîmes, Brest, Amiens, Metz, Lens, Auxerre, Clermont-Ferrand, Lorient, Limoges,
            Perpignan, Caen, Orléans, Tours, Troyes, Nancy, Pau, Bayonne, La Rochelle"""),
    ),
    CountryData(
        name="Espagne", weight=5, surname_style="two_surnames", street_format="Calle {name}, {n}",
        first_names_male=names("""
            Alejandro, Álvaro, Carlos, Daniel, David, Diego, Fernando, Francisco, Iker, Javier,
            Jorge, José, Juan, Manuel, Marcos, Mario, Miguel, Pablo, Pedro, Rubén, Sergio, Unai,
            Víctor, Raúl, Adrián, Borja, Gonzalo, Ander, Aitor, Jon"""),
        first_names_female=names("Ana, Carmen, Lucía, María, Laura, Marta, Paula, Sara, Elena, Isabel"),
        last_names=names("""
            García, Fernández, González, Rodríguez, López, Martínez, Sánchez, Pérez, Gómez, Martín,
            Jiménez, Ruiz, Hernández, Díaz, Moreno, Álvarez, Muñoz, Romero, Alonso, Gutiérrez,
            Navarro, Torres, Domínguez, Vázquez, Ramos, Gil, Serrano, Blanco, Molina, Morales,
            Suárez, Ortega, Delgado, Castro, Iglesias, Medina, Garrido, Cortés, Etxeberria, Urrutia"""),
        cities=names("""
            Madrid, Barcelone, Séville, Valence, Bilbao, Malaga, Saragosse, Villarreal, Vigo,
            Grenade, Pampelune, Getafe, Vitoria, Gijón, Oviedo, Alicante, Majorque, Elche"""),
    ),
    CountryData(
        name="Portugal", weight=3, surname_style="two_surnames", street_format="Rua {name}, {n}",
        first_names_male=names("""
            João, Tiago, Rúben, Diogo, André, Bernardo, Pedro, Rui, Nuno, Miguel, Gonçalo, Rafael,
            Francisco, Bruno, Ricardo, Hugo, Vasco, Duarte, Filipe, Fábio"""),
        first_names_female=names("Ana, Beatriz, Inês, Joana, Mariana, Sofia, Catarina, Margarida"),
        last_names=names("""
            Silva, Santos, Ferreira, Pereira, Oliveira, Costa, Rodrigues, Martins, Jesus, Sousa,
            Fernandes, Gonçalves, Gomes, Lopes, Marques, Alves, Almeida, Ribeiro, Pinto, Carvalho,
            Teixeira, Moreira, Correia, Mendes, Nunes, Soares, Vieira, Monteiro, Cardoso, Rocha"""),
        cities=names("""
            Lisbonne, Porto, Braga, Coimbra, Guimarães, Faro, Setúbal, Funchal, Aveiro,
            Vila do Conde, Famalicão, Estoril"""),
    ),
    CountryData(
        name="Italie", weight=4, surname_style="single", street_format="Via {name} {n}",
        first_names_male=names("""
            Marco, Luca, Matteo, Andrea, Federico, Lorenzo, Davide, Alessandro, Francesco,
            Giovanni, Simone, Stefano, Riccardo, Gianluca, Nicolò, Domenico, Fabio, Leonardo,
            Emanuele, Paolo, Alberto, Salvatore, Antonio, Giacomo"""),
        first_names_female=names("Giulia, Sofia, Chiara, Francesca, Martina, Alessia, Sara, Elisa"),
        last_names=names("""
            Rossi, Russo, Ferrari, Esposito, Bianchi, Romano, Colombo, Ricci, Marino, Greco, Bruno,
            Gallo, Conti, De Luca, Costa, Giordano, Mancini, Rizzo, Lombardi, Moretti, Barbieri,
            Fontana, Santoro, Mariani, Rinaldi, Caruso, Ferrara, Galli, Martini, Leone, Longo,
            Gentile, Martinelli, Vitale, Serra, Coppola, De Santis, D'Angelo, Marchetti"""),
        cities=names("""
            Rome, Milan, Naples, Turin, Bologne, Florence, Gênes, Bergame, Vérone, Udine, Lecce,
            Cagliari, Parme, Empoli, Sassuolo, Monza"""),
    ),
    CountryData(
        name="Allemagne", weight=4, surname_style="single", street_format="{name}straße {n}",
        first_names_male=names("""
            Lukas, Jonas, Leon, Felix, Maximilian, Tim, Paul, Jan, Niklas, Moritz, Kai, Florian,
            Fabian, Julian, Leroy, Joshua, Marcel, Sebastian, Tobias, Matthias, Stefan, Marvin,
            Dennis, Bastian"""),
        first_names_female=names("Anna, Lena, Hannah, Marie, Laura, Julia, Lea, Sophie"),
        last_names=names("""
            Müller, Schmidt, Schneider, Fischer, Weber, Meyer, Wagner, Becker, Schulz, Hoffmann,
            Schäfer, Koch, Bauer, Richter, Klein, Wolf, Schröder, Neumann, Schwarz, Zimmermann,
            Braun, Krüger, Hofmann, Hartmann, Lange, Schmitt, Werner, Krause, Meier, Lehmann,
            Schmid, Schulze, Maier, Köhler, Herrmann, König, Walter, Mayer, Huber, Kaiser"""),
        cities=names("""
            Berlin, Munich, Hambourg, Dortmund, Cologne, Francfort, Stuttgart, Leipzig, Brême,
            Fribourg, Wolfsburg, Mayence, Augsbourg, Leverkusen, Gelsenkirchen, Düsseldorf"""),
    ),
    CountryData(
        name="Angleterre", weight=5, surname_style="single", street_format="{n} {name} Road",
        first_names_male=names("""
            Jack, Harry, Oliver, George, Charlie, Jamie, Callum, Thomas, James, William, Joe,
            Declan, Marcus, Jordan, Kyle, Ben, Luke, Mason, Reece, Conor, Phil, Ryan, Aaron, Liam"""),
        first_names_female=names("Emily, Olivia, Amelia, Isla, Charlotte, Lucy, Grace, Ella"),
        last_names=names("""
            Smith, Jones, Taylor, Brown, Wilson, Evans, Walker, Davies, Johnson, Williams,
            Thompson, Roberts, Robinson, Wright, Hughes, Edwards, Green, Hall, Wood, Harris,
            Lewis, Martin, Jackson, Clarke, Turner, Hill, Scott, Cooper, Morris, Ward, Moore,
            King, Watson, Baker, Harrison, Morgan, Patel, Young, Allen, Fletcher, Fleming"""),
        cities=names("""
            Londres, Manchester, Liverpool, Birmingham, Leeds, Newcastle, Sheffield, Brighton,
            Southampton, Leicester, Nottingham, Bristol, Wolverhampton, Norwich, Burnley,
            Bournemouth"""),
    ),
    CountryData(
        name="Pays-Bas", weight=3, surname_style="single", street_format="{name}straat {n}",
        first_names_male=names("""
            Daan, Sem, Lucas, Milan, Levi, Luuk, Bram, Jesse, Thijs, Ruben, Stijn, Joris, Sven,
            Max, Jasper, Tim, Mees, Wout, Denzel, Jurgen, Teun, Niek"""),
        first_names_female=names("Emma, Sophie, Julia, Anna, Lotte, Fleur, Sanne, Eva"),
        last_names=names("""
            de Jong, Jansen, de Vries, van den Berg, van Dijk, Bakker, Janssen, Visser, Smit,
            Meijer, de Boer, Mulder, de Groot, Bos, Vos, Peters, Hendriks, van Leeuwen, Dekker,
            Brouwer, de Wit, Dijkstra, Smits, de Graaf, van der Meer, van der Linden, Kok,
            Jacobs, de Haan, Vermeulen"""),
        cities=names("""
            Amsterdam, Rotterdam, La Haye, Utrecht, Eindhoven, Groningue, Alkmaar, Arnhem,
            Tilburg, Heerenveen, Enschede, Zwolle"""),
    ),
    CountryData(
        name="Belgique", weight=3, surname_style="hyphen", street_format="{n} rue {name}",
        first_names_male=names("""
            Thibaut, Axel, Yannick, Dries, Kevin, Jan, Wout, Lars, Maxime, Arthur, Nathan, Simon,
            Thomas, Youri, Timothy, Leandro, Jeremy, Hans, Koen, Jorne"""),
        first_names_female=names("Emma, Louise, Lotte, Marie, Charlotte, Elise"),
        last_names=names("""
            Peeters, Janssens, Maes, Jacobs, Mertens, Willems, Claes, Goossens, Wouters, De Smet,
            Dubois, Lambert, Dupont, Martin, Lemaire, Hermans, Declercq, Vermeulen,
            Van den Broeck, Leclercq"""),
        cities=names("""
            Bruxelles, Anvers, Gand, Bruges, Liège, Charleroi, Genk, Louvain, Malines, Courtrai,
            Mons, Namur"""),
    ),
    CountryData(
        name="Pologne", weight=2, surname_style="single", street_format="ul. {name} {n}",
        first_names_male=names("""
            Jakub, Jan, Kacper, Mateusz, Michał, Piotr, Paweł, Krzysztof, Marcin, Łukasz, Bartosz,
            Adam, Tomasz, Szymon, Kamil, Dawid, Wojciech, Robert, Sebastian, Przemysław"""),
        first_names_female=names("Anna, Katarzyna, Magdalena, Zuzanna, Maja"),
        last_names=names("""
            Nowak, Kowalski, Wiśniewski, Wójcik, Kowalczyk, Kamiński, Dąbrowski, Szymański,
            Woźniak, Kozłowski, Jankowski, Mazur, Kwiatkowski, Krawczyk, Piotrowski, Grabowski,
            Pawłowski, Michalski, Zając, Król, Wieczorek, Jabłoński, Wróbel, Majewski, Olszewski,
            Stępień, Malinowski, Jaworski, Adamczyk"""),
        cities=names("""
            Varsovie, Cracovie, Łódź, Wrocław, Poznań, Gdańsk, Szczecin, Lublin, Katowice,
            Białystok, Gliwice, Chorzów"""),
    ),
    CountryData(
        name="Croatie", weight=2, surname_style="single", street_format="Ulica {name} {n}",
        first_names_male=names("""
            Luka, Ivan, Marko, Ante, Josip, Mateo, Mario, Nikola, Domagoj, Duje, Filip, Borna,
            Dominik, Tomislav, Stipe, Petar, Dario, Dejan, Marin, Lovro"""),
        first_names_female=names("Ana, Marija, Ivana, Petra, Maja"),
        last_names=names("""
            Horvat, Kovačević, Babić, Marić, Jurić, Novak, Knežević, Vuković, Marković, Petrović,
            Matić, Tomić, Kovač, Pavlović, Božić, Blažević, Grgić, Pavić, Radić, Perić, Filipović,
            Šarić, Lovrić, Vidović, Perković"""),
        cities=names("""
            Zagreb, Split, Rijeka, Osijek, Zadar, Pula, Dubrovnik, Varaždin, Šibenik,
            Slavonski Brod"""),
    ),
    CountryData(
        name="Serbie", weight=2, surname_style="single", street_format="Ulica {name} {n}",
        first_names_male=names("""
            Nikola, Marko, Luka, Stefan, Aleksandar, Dušan, Filip, Miloš, Nemanja, Vladimir, Uroš,
            Đorđe, Lazar, Mihailo, Ivan, Andrija, Predrag, Sergej, Strahinja, Darko"""),
        first_names_female=names("Milica, Jelena, Ana, Ivana, Marija"),
        last_names=names("""
            Jovanović, Petrović, Nikolić, Marković, Đorđević, Stojanović, Ilić, Stanković,
            Pavlović, Milošević, Popović, Obradović, Živković, Kostić, Savić, Todorović, Lazarević,
            Janković, Mitrović, Ristić, Simić, Vasić, Tomić, Mihajlović, Radovanović"""),
        cities=names("""
            Belgrade, Novi Sad, Niš, Kragujevac, Subotica, Čačak, Kraljevo, Zrenjanin, Valjevo"""),
    ),
    CountryData(
        name="Suède", weight=1, surname_style="single", street_format="{name}gatan {n}",
        first_names_male=names("""
            Erik, Lars, Anders, Johan, Oskar, Viktor, Emil, Marcus, Filip, Alexander, Gustav,
            Axel, Hugo, Elias, Albin, Linus, Carl, Mattias, Joel, Jesper"""),
        first_names_female=names("Emma, Maja, Alice, Ebba, Elsa, Linnea"),
        last_names=names("""
            Andersson, Johansson, Karlsson, Nilsson, Eriksson, Larsson, Olsson, Persson, Svensson,
            Gustafsson, Pettersson, Jonsson, Jansson, Hansson, Bengtsson, Lindberg, Lindström,
            Lindgren, Axelsson, Berg, Bergström, Lundberg, Lind, Lundgren, Lundqvist, Mattsson,
            Berglund, Fredriksson, Sandberg, Henriksson"""),
        cities=names("""
            Stockholm, Göteborg, Malmö, Uppsala, Norrköping, Helsingborg, Örebro, Västerås,
            Linköping, Jönköping"""),
    ),
    CountryData(
        name="Turquie", weight=2, surname_style="single", street_format="{name} Caddesi No:{n}",
        first_names_male=names("""
            Mehmet, Mustafa, Ahmet, Ali, Hasan, Emre, Burak, Can, Cengiz, Hakan, Arda, Kerem,
            Orkun, Yusuf, Ozan, Serdar, Merih, Cenk, Efe, Barış"""),
        first_names_female=names("Ayşe, Fatma, Elif, Zeynep, Emine"),
        last_names=names("""
            Yılmaz, Kaya, Demir, Şahin, Çelik, Yıldız, Yıldırım, Öztürk, Aydın, Özdemir, Arslan,
            Doğan, Kılıç, Aslan, Çetin, Kara, Koç, Kurt, Özkan, Şimşek, Polat, Korkmaz, Çakır,
            Tekin, Aksoy, Acar, Karaca, Güneş"""),
        cities=names("""
            Istanbul, Ankara, Izmir, Bursa, Antalya, Trabzon, Konya, Adana, Gaziantep, Kayseri,
            Samsun, Eskişehir"""),
    ),
    # ---------------------------------------------------------- AMÉRIQUES
    CountryData(
        name="Brésil", weight=7, surname_style="single", street_format="Rua {name}, {n}",
        first_names_male=names("""
            Gabriel, Matheus, Rafael, Thiago, Vinícius, Bruno, Léo, Lucas, Pedro, Gustavo, Felipe,
            Rodrigo, Caio, Diego, Eduardo, Fábio, João, Luiz, Marcelo, Danilo, Éderson, Wesley,
            Everton, Douglas"""),
        first_names_female=names("Ana, Beatriz, Camila, Fernanda, Juliana, Larissa, Mariana, Letícia"),
        last_names=names("""
            Silva, Santos, Oliveira, Souza, Pereira, Costa, Rodrigues, Almeida, Nascimento, Lima,
            Araújo, Fernandes, Carvalho, Gomes, Martins, Rocha, Ribeiro, Alves, Monteiro, Mendes,
            Barros, Freitas, Barbosa, Pinto, Moreira, Cavalcanti, Dias, Castro, Campos, Cardoso"""),
        cities=names("""
            São Paulo, Rio de Janeiro, Salvador, Recife, Porto Alegre, Belo Horizonte, Fortaleza,
            Curitiba, Brasília, Santos, Goiânia, Belém, Manaus, Florianópolis"""),
    ),
    CountryData(
        name="Argentine", weight=4, surname_style="single", street_format="Calle {name} {n}",
        first_names_male=names("""
            Santiago, Matías, Nicolás, Facundo, Lautaro, Franco, Juan, Agustín, Emiliano, Gonzalo,
            Ezequiel, Julián, Rodrigo, Leandro, Maximiliano, Marcos, Federico, Cristian, Lucas, Tomás"""),
        first_names_female=names("Valentina, Camila, Sofía, Martina, Lucía, Julieta"),
        last_names=names("""
            González, Rodríguez, Gómez, Díaz, Romero, Acosta, Fernández, López, Martínez, Pérez,
            Sosa, Álvarez, Torres, Ruiz, Ramírez, Flores, Benítez, Medina, Herrera, Castro,
            Suárez, Giménez, Molina, Silva, Rojas, Ortiz, Núñez, Luna, Cabrera, Ríos"""),
        cities=names("""
            Buenos Aires, Rosario, Córdoba, Mendoza, La Plata, Tucumán, Santa Fe, Salta,
            Avellaneda, Mar del Plata"""),
    ),
    CountryData(
        name="Uruguay", weight=2, surname_style="single", street_format="Calle {name} {n}",
        first_names_male=names("""
            Federico, Darwin, Maximiliano, Nicolás, Rodrigo, Matías, Sebastián, Diego, Facundo,
            Martín, Mathías, Ronald, Giorgian, Agustín, Brian, Gastón"""),
        first_names_female=names("Valentina, Martina, Camila, Lucía"),
        last_names=names("""
            Rodríguez, González, Pérez, Fernández, García, Silva, Martínez, Núñez, Suárez, Cabrera,
            Olivera, Ferreira, Techera, Píriz, Bentancur, Acosta, Pereira, Sosa, Methol, Rivero"""),
        cities=names("Montevideo, Salto, Paysandú, Rivera, Maldonado, Colonia, Rocha, Tacuarembó"),
    ),
    CountryData(
        name="Colombie", weight=3, surname_style="two_surnames", street_format="Calle {n} #{name}",
        first_names_male=names("""
            Juan, Santiago, Andrés, Camilo, Carlos, Duván, Jhon, Luis, Mateo, Yerry, Wilmar,
            Davinson, Jefferson, Daniel, Sebastián, Johan"""),
        first_names_female=names("Valentina, Daniela, Mariana, Luisa"),
        last_names=names("""
            Rodríguez, Gómez, González, Martínez, García, López, Hernández, Díaz, Ramírez, Pérez,
            Sánchez, Torres, Vargas, Ospina, Muñoz, Mina, Zapata, Arias, Cardona, Bedoya, Restrepo"""),
        cities=names("""
            Bogotá, Medellín, Cali, Barranquilla, Cartagena, Bucaramanga, Manizales, Pereira"""),
    ),
    CountryData(
        name="Mexique", weight=3, surname_style="two_surnames", street_format="Calle {name} {n}",
        first_names_male=names("""
            José, Luis, Carlos, Jesús, Miguel, Raúl, Hirving, Edson, Diego, Guillermo, Héctor,
            Jorge, Rodolfo, Alexis, César, Orbelín, Uriel, Santiago, Ángel, Roberto"""),
        first_names_female=names("Guadalupe, María, Fernanda, Ximena, Sofía"),
        last_names=names("""
            Hernández, García, Martínez, López, González, Pérez, Rodríguez, Sánchez, Ramírez, Cruz,
            Flores, Gómez, Morales, Vázquez, Reyes, Jiménez, Torres, Díaz, Gutiérrez, Ruiz,
            Mendoza, Aguilar, Ortiz, Moreno, Castillo, Romero, Álvarez, Chávez, Rivera, Juárez"""),
        cities=names("""
            Mexico, Guadalajara, Monterrey, Puebla, Toluca, Tijuana, León, Pachuca, Querétaro,
            Cancún"""),
    ),
    CountryData(
        name="États-Unis", weight=3, surname_style="single", street_format="{n} {name} Street",
        first_names_male=names("""
            Christian, Tyler, Weston, Brenden, Matt, Josh, Tim, Gio, Zack, Jordan, Cole, Brandon,
            Ethan, Michael, Ryan, Kyle, Jackson, Noah, Cameron, Dylan"""),
        first_names_female=names("Emily, Ashley, Jessica, Megan, Sarah, Taylor"),
        last_names=names("""
            Smith, Johnson, Williams, Brown, Jones, Miller, Davis, Garcia, Rodriguez, Wilson,
            Martinez, Anderson, Taylor, Thomas, Moore, Jackson, Martin, Lee, Thompson, White,
            Harris, Clark, Lewis, Robinson, Walker, Young, Allen, King, Wright, Scott, Adams,
            Nelson, Carter, Mitchell, Roberts"""),
        cities=names("""
            New York, Los Angeles, Chicago, Houston, Seattle, Atlanta, Portland, Miami, Boston,
            Dallas, Philadelphie, Columbus"""),
    ),
    # ------------------------------------------------------------- AFRIQUE
    CountryData(
        name="Maroc", weight=3, surname_style="single", street_format="{n} rue {name}",
        first_names_male=names("""
            Mohamed, Youssef, Amine, Achraf, Hakim, Sofiane, Nayef, Ayoub, Bilal, Karim, Mehdi,
            Zakaria, Anas, Yassine, Hamza, Soufiane, Omar, Idriss, Walid, Reda"""),
        first_names_female=names("Fatima, Salma, Yasmine, Khadija, Imane, Sara"),
        last_names=names("""
            Alaoui, Bennani, El Amrani, Benali, Haddad, Idrissi, Tazi, Berrada, Chraibi, Lahlou,
            Fassi, Benjelloun, El Idrissi, Ouali, Bouazza, Mansouri, Belhaj, Cherkaoui, Naciri,
            Skalli, Zniber, Lamrani, Kettani"""),
        cities=names("""
            Casablanca, Rabat, Marrakech, Fès, Tanger, Agadir, Meknès, Oujda, Tétouan, Kénitra,
            Berkane"""),
    ),
    CountryData(
        name="Algérie", weight=3, surname_style="single", street_format="{n} rue {name}",
        first_names_male=names("""
            Mohamed, Riyad, Ismaël, Sofiane, Islam, Yacine, Karim, Rayan, Aïssa, Nabil, Hichem,
            Djamel, Farid, Mehdi, Walid, Bilal, Adem, Amir, Ramy, Said"""),
        first_names_female=names("Amina, Lina, Yasmine, Nesrine, Sarah"),
        last_names=names("""
            Benali, Bouzid, Boudiaf, Khelifi, Haddad, Messaoud, Bensaid, Belkacem, Cherif, Hamidi,
            Larbi, Slimani, Bouchama, Meziane, Benabdallah, Taleb, Ferhat, Saadi, Merabet,
            Zerrouki, Brahimi, Amrani, Chaabane, Hadjadj, Lakhdar"""),
        cities=names("""
            Alger, Oran, Constantine, Annaba, Blida, Sétif, Tlemcen, Batna, Béjaïa, Tizi Ouzou"""),
    ),
    CountryData(
        name="Sénégal", weight=3, surname_style="single", street_format="{n} avenue {name}",
        first_names_male=names("""
            Idrissa, Cheikh, Moussa, Ismaïla, Boulaye, Kalidou, Pape, Famara, Abdou, Mamadou,
            Ousmane, Papa, Lamine, Youssouf, Alioune, Habib, Saliou, Ibrahima, Mbaye"""),
        first_names_female=names("Aminata, Fatou, Awa, Khady, Mariama"),
        last_names=names("""
            Diop, Ndiaye, Fall, Sow, Diallo, Gueye, Sarr, Faye, Mbaye, Ba, Sy, Cissé, Ndoye, Thiam,
            Camara, Diouf, Sane, Kane, Seck, Badji, Niang, Mendy, Samb, Touré"""),
        cities=names("Dakar, Thiès, Saint-Louis, Touba, Kaolack, Ziguinchor, Mbour, Rufisque"),
    ),
    CountryData(
        name="Côte d'Ivoire", weight=3, surname_style="single", street_format="{n} boulevard {name}",
        first_names_male=names("""
            Seko, Wilfried, Franck, Serge, Eric, Nicolas, Max, Ibrahim, Simon, Jean, Amad, Evan,
            Oumar, Willy, Hamed, Lassina, Gervais, Cheick, Emmanuel"""),
        first_names_female=names("Aïcha, Mariam, Fatoumata, Adjoua, Akissi"),
        last_names=names("""
            Koné, Traoré, Diabaté, Ouattara, Touré, Coulibaly, Konaté, Yao, Kouassi, Kouamé, Bamba,
            Soro, Bakayoko, N'Guessan, Diomandé, Sangaré, Dosso, Fofana, Yéo, Koffi, Kouadio,
            Cissé, Doumbia"""),
        cities=names("Abidjan, Yamoussoukro, Bouaké, San-Pédro, Daloa, Korhogo, Man, Gagnoa"),
    ),
    CountryData(
        name="Nigeria", weight=3, surname_style="single", street_format="{n} {name} Street",
        first_names_male=names("""
            Chinedu, Emeka, Oluwaseun, Victor, Kelechi, Ahmed, Samuel, Ola, Moses, Ademola, Taiwo,
            Wilfred, Tunde, Chidi, Ifeanyi, Obinna, Femi, Uche, Sadiq"""),
        first_names_female=names("Chioma, Ngozi, Amara, Funmilayo, Aisha"),
        last_names=names("""
            Okafor, Adeyemi, Okonkwo, Balogun, Ibrahim, Eze, Nwosu, Obi, Adebayo, Ogunleye, Musa,
            Abubakar, Chukwu, Onyeka, Bello, Lawal, Igwe, Olawale, Nnamdi, Ojo, Usman, Danjuma,
            Akinola, Aliyu"""),
        cities=names("Lagos, Abuja, Kano, Ibadan, Port Harcourt, Enugu, Kaduna, Benin City, Owerri"),
    ),
    CountryData(
        name="Ghana", weight=2, surname_style="single", street_format="{n} {name} Road",
        first_names_male=names("""
            Kwame, Kofi, Kwesi, Kojo, Yaw, Samuel, Daniel, Thomas, Mohammed, Abdul, Jordan,
            Alexander, Richmond, Baba, Emmanuel, Joseph, Isaac, Gideon, Ernest"""),
        first_names_female=names("Ama, Abena, Akosua, Efua, Adwoa"),
        last_names=names("""
            Mensah, Owusu, Boateng, Asante, Appiah, Addo, Ofori, Osei, Agyeman, Amoah, Tetteh,
            Adjei, Quaye, Annan, Darko, Opoku, Sarpong, Nartey, Yeboah, Acheampong"""),
        cities=names("Accra, Kumasi, Tamale, Takoradi, Cape Coast, Sekondi, Tema, Sunyani"),
    ),
    CountryData(
        name="Cameroun", weight=2, surname_style="single", street_format="{n} rue {name}",
        first_names_male=names("""
            Eric, Samuel, Vincent, André, Joël, Collins, Karl, Bryan, Christian, Jean, Patrick,
            Pierre, Alexandre, Olivier, Stéphane, Georges, Nicolas, Fabrice, Ernest, Clinton"""),
        first_names_female=names("Estelle, Chantal, Nadège, Carine"),
        last_names=names("""
            Mbarga, Fotso, Essomba, Ndzomo, Kamdem, Tchoumi, Nana, Eboué, Mbida, Atangana, Ekambi,
            Bikoko, Fouda, Manga, Ngoma, Tabi, Belinga, Nguema, Mvondo, Ateba, Etoundi, Nkeng,
            Biyik, Tagne, Ngono"""),
        cities=names("Yaoundé, Douala, Garoua, Bafoussam, Bamenda, Maroua, Limbé, Kribi, Ngaoundéré"),
    ),
    CountryData(
        name="Égypte", weight=2, surname_style="single", street_format="{n} rue {name}",
        first_names_male=names("""
            Mohamed, Ahmed, Mahmoud, Omar, Mostafa, Ali, Karim, Hassan, Youssef, Tarek, Amr,
            Ibrahim, Hossam, Khaled, Walid, Ramy, Sherif, Essam, Hany, Nabil"""),
        first_names_female=names("Fatma, Nour, Mariam, Salma, Yasmin"),
        last_names=names("""
            Hassan, Ibrahim, Ali, Mahmoud, Abdelrahman, Farouk, Mansour, Hussein, Saleh, Nasser,
            Youssef, Mostafa, Soliman, Khalil, Fahmy, Zaki, Gamal, Said, Sabry, El Sayed, Ashraf,
            Fathy, Ghaly"""),
        cities=names("""
            Le Caire, Alexandrie, Gizeh, Port-Saïd, Suez, Louxor, Assouan, Ismaïlia, Tanta,
            Mansoura"""),
    ),
    # ---------------------------------------------------------------- ASIE
    CountryData(
        name="Japon", weight=2, surname_style="single", street_format="{name}-dori {n}",
        first_names_male=names("""
            Takumi, Haruto, Yuto, Sota, Ren, Kaito, Daiki, Shota, Kenta, Hiroki, Ryo, Takeshi,
            Yuki, Kosuke, Masato, Naoki, Shun, Tatsuya, Taiki, Kazuki"""),
        first_names_female=names("Yui, Hina, Sakura, Rin, Aoi"),
        last_names=names("""
            Sato, Suzuki, Takahashi, Tanaka, Watanabe, Ito, Yamamoto, Nakamura, Kobayashi, Kato,
            Yoshida, Yamada, Sasaki, Yamaguchi, Matsumoto, Inoue, Kimura, Hayashi, Shimizu,
            Yamazaki, Mori, Abe, Ikeda, Hashimoto, Ishikawa"""),
        cities=names("""
            Tokyo, Osaka, Yokohama, Nagoya, Kobe, Kyoto, Sapporo, Fukuoka, Hiroshima, Kashima,
            Saitama, Sendai"""),
    ),
    CountryData(
        name="Corée du Sud", weight=2, surname_style="single", street_format="{name}-ro {n}",
        first_names_male=names("""
            Min-jun, Seo-jun, Ji-hoon, Hyun-woo, Dong-hyun, Sung-min, Jae-won, Tae-yang, Woo-jin,
            Joon-ho, Seung-ho, Young-jae, Chan-ho, Hyeon-gyu, Ji-sung"""),
        first_names_female=names("Ji-woo, Seo-yeon, Min-seo, Ha-eun"),
        last_names=names("""
            Kim, Lee, Park, Choi, Jung, Kang, Cho, Yoon, Jang, Lim, Han, Oh, Seo, Shin, Kwon,
            Hwang, Ahn, Song, Yoo, Hong"""),
        cities=names("""
            Séoul, Busan, Incheon, Daegu, Daejeon, Gwangju, Ulsan, Suwon, Jeonju, Pohang"""),
    ),
]
