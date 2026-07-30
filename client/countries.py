"""
Lista de países suportados pelo WhatsApp com seus códigos de discagem,
localizada de acordo com o idioma da interface selecionado pelo usuário.

Cada entrada de _COUNTRIES é uma tupla (chave_estável, código_discagem, nomes):
  • chave_estável: identificador interno, nunca muda (independe de idioma).
  • código_discagem: apenas dígitos, sem o "+".
  • nomes: dict {"pt": ..., "en": ..., "es": ...} com o nome do país em
    português (usado tanto para pt-BR quanto pt-PT), inglês e espanhol.

get_countries(lang) devolve [(nome_exibição, código_discagem), ...] na MESMA
ORDEM independentemente do idioma (Brasil primeiro, depois ordem alfabética
em português) — os diálogos que consomem esta lista indexam por posição
(ComboBox.GetSelection()), então a ordem não pode variar entre idiomas sem
também atualizar esses call sites.

COUNTRIES continua exportado como a lista estática em pt-BR, para código que
só precisa dos códigos de discagem (ex.: core/utils.py) e não da tradução.
"""

_LANG_ALIASES = {
    "pt-BR": "pt",
    "pt-PT": "pt",
    "en-US": "en",
    "es-ES": "es",
}

_COUNTRIES: list[tuple[str, str, dict[str, str]]] = [
    # ── Padrão ──────────────────────────────────────────────────────────────
    ("brazil",                    "55",   {"pt": "Brasil", "en": "Brazil", "es": "Brasil"}),

    # ── A ───────────────────────────────────────────────────────────────────
    ("afghanistan",               "93",   {"pt": "Afeganistão", "en": "Afghanistan", "es": "Afganistán"}),
    ("south_africa",              "27",   {"pt": "África do Sul", "en": "South Africa", "es": "Sudáfrica"}),
    ("albania",                   "355",  {"pt": "Albânia", "en": "Albania", "es": "Albania"}),
    ("germany",                   "49",   {"pt": "Alemanha", "en": "Germany", "es": "Alemania"}),
    ("andorra",                   "376",  {"pt": "Andorra", "en": "Andorra", "es": "Andorra"}),
    ("angola",                    "244",  {"pt": "Angola", "en": "Angola", "es": "Angola"}),
    ("antigua_and_barbuda",       "1268", {"pt": "Antígua e Barbuda", "en": "Antigua and Barbuda", "es": "Antigua y Barbuda"}),
    ("saudi_arabia",              "966",  {"pt": "Arábia Saudita", "en": "Saudi Arabia", "es": "Arabia Saudita"}),
    ("algeria",                   "213",  {"pt": "Argélia", "en": "Algeria", "es": "Argelia"}),
    ("argentina",                 "54",   {"pt": "Argentina", "en": "Argentina", "es": "Argentina"}),
    ("armenia",                   "374",  {"pt": "Armênia", "en": "Armenia", "es": "Armenia"}),
    ("aruba",                     "297",  {"pt": "Aruba", "en": "Aruba", "es": "Aruba"}),
    ("australia",                 "61",   {"pt": "Austrália", "en": "Australia", "es": "Australia"}),
    ("austria",                   "43",   {"pt": "Áustria", "en": "Austria", "es": "Austria"}),
    ("azerbaijan",                "994",  {"pt": "Azerbaijão", "en": "Azerbaijan", "es": "Azerbaiyán"}),

    # ── B ───────────────────────────────────────────────────────────────────
    ("bahamas",                   "1242", {"pt": "Bahamas", "en": "Bahamas", "es": "Bahamas"}),
    ("bangladesh",                "880",  {"pt": "Bangladesh", "en": "Bangladesh", "es": "Bangladés"}),
    ("barbados",                  "1246", {"pt": "Barbados", "en": "Barbados", "es": "Barbados"}),
    ("bahrain",                   "973",  {"pt": "Barein", "en": "Bahrain", "es": "Baréin"}),
    ("belgium",                   "32",   {"pt": "Bélgica", "en": "Belgium", "es": "Bélgica"}),
    ("belize",                    "501",  {"pt": "Belize", "en": "Belize", "es": "Belice"}),
    ("benin",                     "229",  {"pt": "Benim", "en": "Benin", "es": "Benín"}),
    ("bolivia",                   "591",  {"pt": "Bolívia", "en": "Bolivia", "es": "Bolivia"}),
    ("bosnia_and_herzegovina",    "387",  {"pt": "Bósnia e Herzegovina", "en": "Bosnia and Herzegovina", "es": "Bosnia y Herzegovina"}),
    ("botswana",                  "267",  {"pt": "Botsuana", "en": "Botswana", "es": "Botsuana"}),
    ("brunei",                    "673",  {"pt": "Brunei", "en": "Brunei", "es": "Brunéi"}),
    ("bulgaria",                  "359",  {"pt": "Bulgária", "en": "Bulgaria", "es": "Bulgaria"}),
    ("burkina_faso",              "226",  {"pt": "Burkina Faso", "en": "Burkina Faso", "es": "Burkina Faso"}),
    ("burundi",                   "257",  {"pt": "Burundi", "en": "Burundi", "es": "Burundi"}),
    ("bhutan",                    "975",  {"pt": "Butão", "en": "Bhutan", "es": "Bután"}),

    # ── C ───────────────────────────────────────────────────────────────────
    ("cape_verde",                "238",  {"pt": "Cabo Verde", "en": "Cape Verde", "es": "Cabo Verde"}),
    ("cambodia",                  "855",  {"pt": "Camboja", "en": "Cambodia", "es": "Camboya"}),
    ("cameroon",                  "237",  {"pt": "Camarões", "en": "Cameroon", "es": "Camerún"}),
    ("canada",                    "1",    {"pt": "Canadá", "en": "Canada", "es": "Canadá"}),
    ("qatar",                     "974",  {"pt": "Catar", "en": "Qatar", "es": "Catar"}),
    ("kazakhstan",                "7",    {"pt": "Cazaquistão", "en": "Kazakhstan", "es": "Kazajistán"}),
    ("chad",                      "235",  {"pt": "Chade", "en": "Chad", "es": "Chad"}),
    ("chile",                     "56",   {"pt": "Chile", "en": "Chile", "es": "Chile"}),
    ("china",                     "86",   {"pt": "China", "en": "China", "es": "China"}),
    ("cyprus",                    "357",  {"pt": "Chipre", "en": "Cyprus", "es": "Chipre"}),
    ("colombia",                  "57",   {"pt": "Colômbia", "en": "Colombia", "es": "Colombia"}),
    ("comoros",                   "269",  {"pt": "Comores", "en": "Comoros", "es": "Comoras"}),
    ("congo",                     "242",  {"pt": "Congo", "en": "Congo", "es": "Congo"}),
    ("north_korea",               "850",  {"pt": "Coreia do Norte", "en": "North Korea", "es": "Corea del Norte"}),
    ("south_korea",               "82",   {"pt": "Coreia do Sul", "en": "South Korea", "es": "Corea del Sur"}),
    ("ivory_coast",               "225",  {"pt": "Costa do Marfim", "en": "Ivory Coast", "es": "Costa de Marfil"}),
    ("costa_rica",                "506",  {"pt": "Costa Rica", "en": "Costa Rica", "es": "Costa Rica"}),
    ("croatia",                   "385",  {"pt": "Croácia", "en": "Croatia", "es": "Croacia"}),
    ("cuba",                      "53",   {"pt": "Cuba", "en": "Cuba", "es": "Cuba"}),
    ("curacao",                   "5999", {"pt": "Curaçao", "en": "Curaçao", "es": "Curazao"}),

    # ── D ───────────────────────────────────────────────────────────────────
    ("denmark",                   "45",   {"pt": "Dinamarca", "en": "Denmark", "es": "Dinamarca"}),
    ("djibouti",                  "253",  {"pt": "Djibuti", "en": "Djibouti", "es": "Yibuti"}),
    ("dominica",                  "1767", {"pt": "Dominica", "en": "Dominica", "es": "Dominica"}),

    # ── E ───────────────────────────────────────────────────────────────────
    ("egypt",                     "20",   {"pt": "Egito", "en": "Egypt", "es": "Egipto"}),
    ("el_salvador",               "503",  {"pt": "El Salvador", "en": "El Salvador", "es": "El Salvador"}),
    ("united_arab_emirates",      "971",  {"pt": "Emirados Árabes Unidos", "en": "United Arab Emirates", "es": "Emiratos Árabes Unidos"}),
    ("ecuador",                   "593",  {"pt": "Equador", "en": "Ecuador", "es": "Ecuador"}),
    ("eritrea",                   "291",  {"pt": "Eritreia", "en": "Eritrea", "es": "Eritrea"}),
    ("slovakia",                  "421",  {"pt": "Eslováquia", "en": "Slovakia", "es": "Eslovaquia"}),
    ("slovenia",                  "386",  {"pt": "Eslovênia", "en": "Slovenia", "es": "Eslovenia"}),
    ("spain",                     "34",   {"pt": "Espanha", "en": "Spain", "es": "España"}),
    ("united_states",             "1",    {"pt": "Estados Unidos", "en": "United States", "es": "Estados Unidos"}),
    ("estonia",                   "372",  {"pt": "Estônia", "en": "Estonia", "es": "Estonia"}),
    ("eswatini",                  "268",  {"pt": "Eswatini", "en": "Eswatini", "es": "Esuatini"}),
    ("ethiopia",                  "251",  {"pt": "Etiópia", "en": "Ethiopia", "es": "Etiopía"}),

    # ── F ───────────────────────────────────────────────────────────────────
    ("fiji",                      "679",  {"pt": "Fiji", "en": "Fiji", "es": "Fiyi"}),
    ("philippines",               "63",   {"pt": "Filipinas", "en": "Philippines", "es": "Filipinas"}),
    ("finland",                   "358",  {"pt": "Finlândia", "en": "Finland", "es": "Finlandia"}),
    ("france",                    "33",   {"pt": "França", "en": "France", "es": "Francia"}),

    # ── G ───────────────────────────────────────────────────────────────────
    ("gabon",                     "241",  {"pt": "Gabão", "en": "Gabon", "es": "Gabón"}),
    ("gambia",                    "220",  {"pt": "Gâmbia", "en": "Gambia", "es": "Gambia"}),
    ("ghana",                     "233",  {"pt": "Gana", "en": "Ghana", "es": "Ghana"}),
    ("georgia",                   "995",  {"pt": "Geórgia", "en": "Georgia", "es": "Georgia"}),
    ("gibraltar",                 "350",  {"pt": "Gibraltar", "en": "Gibraltar", "es": "Gibraltar"}),
    ("greece",                    "30",   {"pt": "Grécia", "en": "Greece", "es": "Grecia"}),
    ("grenada",                   "1473", {"pt": "Granada", "en": "Grenada", "es": "Granada"}),
    ("guatemala",                 "502",  {"pt": "Guatemala", "en": "Guatemala", "es": "Guatemala"}),
    ("guyana",                    "592",  {"pt": "Guiana", "en": "Guyana", "es": "Guyana"}),
    ("guinea",                    "224",  {"pt": "Guiné", "en": "Guinea", "es": "Guinea"}),
    ("guinea_bissau",             "245",  {"pt": "Guiné Bissau", "en": "Guinea-Bissau", "es": "Guinea-Bisáu"}),
    ("equatorial_guinea",         "240",  {"pt": "Guiné Equatorial", "en": "Equatorial Guinea", "es": "Guinea Ecuatorial"}),

    # ── H ───────────────────────────────────────────────────────────────────
    ("haiti",                     "509",  {"pt": "Haiti", "en": "Haiti", "es": "Haití"}),
    ("honduras",                  "504",  {"pt": "Honduras", "en": "Honduras", "es": "Honduras"}),
    ("hong_kong",                 "852",  {"pt": "Hong Kong", "en": "Hong Kong", "es": "Hong Kong"}),
    ("hungary",                   "36",   {"pt": "Hungria", "en": "Hungary", "es": "Hungría"}),

    # ── I ───────────────────────────────────────────────────────────────────
    ("yemen",                     "967",  {"pt": "Iêmen", "en": "Yemen", "es": "Yemen"}),
    ("cayman_islands",            "1345", {"pt": "Ilhas Cayman", "en": "Cayman Islands", "es": "Islas Caimán"}),
    ("cook_islands",              "682",  {"pt": "Ilhas Cook", "en": "Cook Islands", "es": "Islas Cook"}),
    ("faroe_islands",             "298",  {"pt": "Ilhas Faroe", "en": "Faroe Islands", "es": "Islas Feroe"}),
    ("marshall_islands",          "692",  {"pt": "Ilhas Marshall", "en": "Marshall Islands", "es": "Islas Marshall"}),
    ("solomon_islands",           "677",  {"pt": "Ilhas Salomão", "en": "Solomon Islands", "es": "Islas Salomón"}),
    ("turks_and_caicos_islands",  "1649", {"pt": "Ilhas Turks e Caicos", "en": "Turks and Caicos Islands", "es": "Islas Turcas y Caicos"}),
    ("british_virgin_islands",    "1284", {"pt": "Ilhas Virgens Britânicas", "en": "British Virgin Islands", "es": "Islas Vírgenes Británicas"}),
    ("us_virgin_islands",         "1340", {"pt": "Ilhas Virgens dos EUA", "en": "U.S. Virgin Islands", "es": "Islas Vírgenes de EE. UU."}),
    ("india",                     "91",   {"pt": "Índia", "en": "India", "es": "India"}),
    ("indonesia",                 "62",   {"pt": "Indonésia", "en": "Indonesia", "es": "Indonesia"}),
    ("iran",                      "98",   {"pt": "Irã", "en": "Iran", "es": "Irán"}),
    ("iraq",                      "964",  {"pt": "Iraque", "en": "Iraq", "es": "Irak"}),
    ("ireland",                   "353",  {"pt": "Irlanda", "en": "Ireland", "es": "Irlanda"}),
    ("iceland",                   "354",  {"pt": "Islândia", "en": "Iceland", "es": "Islandia"}),
    ("israel",                    "972",  {"pt": "Israel", "en": "Israel", "es": "Israel"}),
    ("italy",                     "39",   {"pt": "Itália", "en": "Italy", "es": "Italia"}),

    # ── J ───────────────────────────────────────────────────────────────────
    ("jamaica",                   "1876", {"pt": "Jamaica", "en": "Jamaica", "es": "Jamaica"}),
    ("japan",                     "81",   {"pt": "Japão", "en": "Japan", "es": "Japón"}),
    ("jordan",                    "962",  {"pt": "Jordânia", "en": "Jordan", "es": "Jordania"}),

    # ── K ───────────────────────────────────────────────────────────────────
    ("kuwait",                    "965",  {"pt": "Kuwait", "en": "Kuwait", "es": "Kuwait"}),
    ("kyrgyzstan",                "996",  {"pt": "Quirguistão", "en": "Kyrgyzstan", "es": "Kirguistán"}),

    # ── L ───────────────────────────────────────────────────────────────────
    ("laos",                      "856",  {"pt": "Laos", "en": "Laos", "es": "Laos"}),
    ("lesotho",                   "266",  {"pt": "Lesoto", "en": "Lesotho", "es": "Lesoto"}),
    ("latvia",                    "371",  {"pt": "Letônia", "en": "Latvia", "es": "Letonia"}),
    ("lebanon",                   "961",  {"pt": "Líbano", "en": "Lebanon", "es": "Líbano"}),
    ("liberia",                   "231",  {"pt": "Libéria", "en": "Liberia", "es": "Liberia"}),
    ("libya",                     "218",  {"pt": "Líbia", "en": "Libya", "es": "Libia"}),
    ("liechtenstein",             "423",  {"pt": "Liechtenstein", "en": "Liechtenstein", "es": "Liechtenstein"}),
    ("lithuania",                 "370",  {"pt": "Lituânia", "en": "Lithuania", "es": "Lituania"}),
    ("luxembourg",                "352",  {"pt": "Luxemburgo", "en": "Luxembourg", "es": "Luxemburgo"}),

    # ── M ───────────────────────────────────────────────────────────────────
    ("macau",                     "853",  {"pt": "Macau", "en": "Macau", "es": "Macao"}),
    ("madagascar",                "261",  {"pt": "Madagascar", "en": "Madagascar", "es": "Madagascar"}),
    ("malawi",                    "265",  {"pt": "Malawi", "en": "Malawi", "es": "Malaui"}),
    ("malaysia",                  "60",   {"pt": "Malásia", "en": "Malaysia", "es": "Malasia"}),
    ("maldives",                  "960",  {"pt": "Maldivas", "en": "Maldives", "es": "Maldivas"}),
    ("mali",                      "223",  {"pt": "Mali", "en": "Mali", "es": "Malí"}),
    ("malta",                     "356",  {"pt": "Malta", "en": "Malta", "es": "Malta"}),
    ("morocco",                   "212",  {"pt": "Marrocos", "en": "Morocco", "es": "Marruecos"}),
    ("mauritania",                "222",  {"pt": "Mauritânia", "en": "Mauritania", "es": "Mauritania"}),
    ("mauritius",                 "230",  {"pt": "Maurício", "en": "Mauritius", "es": "Mauricio"}),
    ("mexico",                    "52",   {"pt": "México", "en": "Mexico", "es": "México"}),
    ("micronesia",                "691",  {"pt": "Micronésia", "en": "Micronesia", "es": "Micronesia"}),
    ("myanmar",                   "95",   {"pt": "Mianmar", "en": "Myanmar", "es": "Myanmar"}),
    ("mozambique",                "258",  {"pt": "Moçambique", "en": "Mozambique", "es": "Mozambique"}),
    ("moldova",                   "373",  {"pt": "Moldávia", "en": "Moldova", "es": "Moldavia"}),
    ("monaco",                    "377",  {"pt": "Mônaco", "en": "Monaco", "es": "Mónaco"}),
    ("mongolia",                  "976",  {"pt": "Mongólia", "en": "Mongolia", "es": "Mongolia"}),
    ("montenegro",                "382",  {"pt": "Montenegro", "en": "Montenegro", "es": "Montenegro"}),

    # ── N ───────────────────────────────────────────────────────────────────
    ("namibia",                   "264",  {"pt": "Namíbia", "en": "Namibia", "es": "Namibia"}),
    ("nauru",                     "674",  {"pt": "Nauru", "en": "Nauru", "es": "Nauru"}),
    ("nepal",                     "977",  {"pt": "Nepal", "en": "Nepal", "es": "Nepal"}),
    ("nicaragua",                 "505",  {"pt": "Nicarágua", "en": "Nicaragua", "es": "Nicaragua"}),
    ("niger",                     "227",  {"pt": "Níger", "en": "Niger", "es": "Níger"}),
    ("nigeria",                   "234",  {"pt": "Nigéria", "en": "Nigeria", "es": "Nigeria"}),
    ("norway",                    "47",   {"pt": "Noruega", "en": "Norway", "es": "Noruega"}),
    ("new_zealand",               "64",   {"pt": "Nova Zelândia", "en": "New Zealand", "es": "Nueva Zelanda"}),

    # ── O ───────────────────────────────────────────────────────────────────
    ("oman",                      "968",  {"pt": "Omã", "en": "Oman", "es": "Omán"}),

    # ── P ───────────────────────────────────────────────────────────────────
    ("pakistan",                  "92",   {"pt": "Paquistão", "en": "Pakistan", "es": "Pakistán"}),
    ("palau",                     "680",  {"pt": "Palau", "en": "Palau", "es": "Palaos"}),
    ("panama",                    "507",  {"pt": "Panamá", "en": "Panama", "es": "Panamá"}),
    ("papua_new_guinea",          "675",  {"pt": "Papua Nova Guiné", "en": "Papua New Guinea", "es": "Papúa Nueva Guinea"}),
    ("paraguay",                  "595",  {"pt": "Paraguai", "en": "Paraguay", "es": "Paraguay"}),
    ("peru",                      "51",   {"pt": "Peru", "en": "Peru", "es": "Perú"}),
    ("poland",                    "48",   {"pt": "Polônia", "en": "Poland", "es": "Polonia"}),
    ("portugal",                  "351",  {"pt": "Portugal", "en": "Portugal", "es": "Portugal"}),
    ("puerto_rico",               "1787", {"pt": "Porto Rico", "en": "Puerto Rico", "es": "Puerto Rico"}),

    # ── Q ───────────────────────────────────────────────────────────────────

    # ── R ───────────────────────────────────────────────────────────────────
    ("united_kingdom",            "44",   {"pt": "Reino Unido", "en": "United Kingdom", "es": "Reino Unido"}),
    ("central_african_republic",  "236",  {"pt": "República Centro-Africana", "en": "Central African Republic", "es": "República Centroafricana"}),
    ("democratic_republic_congo", "243",  {"pt": "República Democrática do Congo", "en": "Democratic Republic of the Congo", "es": "República Democrática del Congo"}),
    ("dominican_republic",        "1809", {"pt": "República Dominicana", "en": "Dominican Republic", "es": "República Dominicana"}),
    ("czech_republic",            "420",  {"pt": "República Tcheca", "en": "Czech Republic", "es": "República Checa"}),
    ("romania",                   "40",   {"pt": "Romênia", "en": "Romania", "es": "Rumanía"}),
    ("rwanda",                    "250",  {"pt": "Ruanda", "en": "Rwanda", "es": "Ruanda"}),
    ("russia",                    "7",    {"pt": "Rússia", "en": "Russia", "es": "Rusia"}),

    # ── S ───────────────────────────────────────────────────────────────────
    ("samoa",                     "685",  {"pt": "Samoa", "en": "Samoa", "es": "Samoa"}),
    ("san_marino",                "378",  {"pt": "San Marino", "en": "San Marino", "es": "San Marino"}),
    ("saint_lucia",               "1758", {"pt": "Santa Lúcia", "en": "Saint Lucia", "es": "Santa Lucía"}),
    ("saint_kitts_and_nevis",     "1869", {"pt": "São Cristóvão e Nevis", "en": "Saint Kitts and Nevis", "es": "San Cristóbal y Nieves"}),
    ("sao_tome_and_principe",     "239",  {"pt": "São Tomé e Príncipe", "en": "São Tomé and Príncipe", "es": "Santo Tomé y Príncipe"}),
    ("saint_vincent_grenadines",  "1784", {"pt": "São Vicente e Granadinas", "en": "Saint Vincent and the Grenadines", "es": "San Vicente y las Granadinas"}),
    ("senegal",                   "221",  {"pt": "Senegal", "en": "Senegal", "es": "Senegal"}),
    ("sierra_leone",              "232",  {"pt": "Serra Leoa", "en": "Sierra Leone", "es": "Sierra Leona"}),
    ("serbia",                    "381",  {"pt": "Sérvia", "en": "Serbia", "es": "Serbia"}),
    ("seychelles",                "248",  {"pt": "Seychelles", "en": "Seychelles", "es": "Seychelles"}),
    ("singapore",                 "65",   {"pt": "Singapura", "en": "Singapore", "es": "Singapur"}),
    ("syria",                     "963",  {"pt": "Síria", "en": "Syria", "es": "Siria"}),
    ("somalia",                   "252",  {"pt": "Somália", "en": "Somalia", "es": "Somalia"}),
    ("sri_lanka",                 "94",   {"pt": "Sri Lanka", "en": "Sri Lanka", "es": "Sri Lanka"}),
    ("sudan",                     "249",  {"pt": "Sudão", "en": "Sudan", "es": "Sudán"}),
    ("south_sudan",               "211",  {"pt": "Sudão do Sul", "en": "South Sudan", "es": "Sudán del Sur"}),
    ("sweden",                    "46",   {"pt": "Suécia", "en": "Sweden", "es": "Suecia"}),
    ("switzerland",               "41",   {"pt": "Suíça", "en": "Switzerland", "es": "Suiza"}),
    ("suriname",                  "597",  {"pt": "Suriname", "en": "Suriname", "es": "Surinam"}),

    # ── T ───────────────────────────────────────────────────────────────────
    ("thailand",                  "66",   {"pt": "Tailândia", "en": "Thailand", "es": "Tailandia"}),
    ("taiwan",                    "886",  {"pt": "Taiwan", "en": "Taiwan", "es": "Taiwán"}),
    ("tanzania",                  "255",  {"pt": "Tanzânia", "en": "Tanzania", "es": "Tanzania"}),
    ("timor_leste",               "670",  {"pt": "Timor-Leste", "en": "Timor-Leste", "es": "Timor Oriental"}),
    ("togo",                      "228",  {"pt": "Togo", "en": "Togo", "es": "Togo"}),
    ("trinidad_and_tobago",       "1868", {"pt": "Trinidad e Tobago", "en": "Trinidad and Tobago", "es": "Trinidad y Tobago"}),
    ("tunisia",                   "216",  {"pt": "Tunísia", "en": "Tunisia", "es": "Túnez"}),
    ("turkmenistan",              "993",  {"pt": "Turcomenistão", "en": "Turkmenistan", "es": "Turkmenistán"}),
    ("turkey",                    "90",   {"pt": "Turquia", "en": "Turkey", "es": "Turquía"}),
    ("tuvalu",                    "688",  {"pt": "Tuvalu", "en": "Tuvalu", "es": "Tuvalu"}),

    # ── U ───────────────────────────────────────────────────────────────────
    ("ukraine",                   "380",  {"pt": "Ucrânia", "en": "Ukraine", "es": "Ucrania"}),
    ("uganda",                    "256",  {"pt": "Uganda", "en": "Uganda", "es": "Uganda"}),
    ("uruguay",                   "598",  {"pt": "Uruguai", "en": "Uruguay", "es": "Uruguay"}),
    ("uzbekistan",                "998",  {"pt": "Uzbequistão", "en": "Uzbekistan", "es": "Uzbekistán"}),

    # ── V ───────────────────────────────────────────────────────────────────
    ("vanuatu",                   "678",  {"pt": "Vanuatu", "en": "Vanuatu", "es": "Vanuatu"}),
    ("venezuela",                 "58",   {"pt": "Venezuela", "en": "Venezuela", "es": "Venezuela"}),
    ("vietnam",                   "84",   {"pt": "Vietnã", "en": "Vietnam", "es": "Vietnam"}),

    # ── Z ───────────────────────────────────────────────────────────────────
    ("zambia",                    "260",  {"pt": "Zâmbia", "en": "Zambia", "es": "Zambia"}),
    ("zimbabwe",                  "263",  {"pt": "Zimbábue", "en": "Zimbabwe", "es": "Zimbabue"}),
]


def get_countries(lang: str = "pt-BR") -> list[tuple[str, str]]:
    """Return [(display_name, dial_code), ...] localized for *lang*, same
    order as _COUNTRIES regardless of language — callers index into this
    list by ComboBox position, so the order must stay stable across
    languages. Falls back to Portuguese for any unrecognized lang code."""
    key = _LANG_ALIASES.get(lang, "pt")
    result = []
    for _, code, names in _COUNTRIES:
        name = names.get(key) or names["pt"]
        result.append((f"{name} (+{code})", code))
    return result


# Backward-compat: static pt-BR list for code that only needs the dial codes
# (e.g. core/utils.py's country-code matching), not the localized names.
COUNTRIES: list[tuple[str, str]] = get_countries("pt-BR")
