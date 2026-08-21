"""Native, screen-reader-friendly emoji picker shared by chat and Status."""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

import wx


# A curated set keeps navigation fast while covering the everyday WhatsApp
# categories.  Values are plain Unicode, so insertion needs no API conversion.
EMOJI_CATEGORIES = (
    ("emoji_category_frequent", "😀 😃 😄 😁 😂 😊 😍 🥰 😘 😎 😢 😭 😡 👍 👎 ❤️ 🎉 🙏 🔥"),
    ("emoji_category_smileys", "🙂 🙃 😉 😌 🤩 🥳 😏 😴 🤗 🤔 🤭 🤫 😐 🙄 😮 😱 🤢 🤧 😇 🤠"),
    ("emoji_category_people", "👋 🤚 🖐️ ✋ 🖖 👌 🤌 🤏 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ ✊ 👊 🤛 🤜 👏 🙌 👐 🤝 💪"),
    ("emoji_category_animals", "🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🐔 🐧 🐦 🦄 🐝 🦋 🐢 🐬"),
    ("emoji_category_food", "🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🫐 🍒 🍑 🥭 🍍 🥝 🍅 🥑 🍕 🍔 🍟 🌭 🍿 🍩 🎂 ☕"),
    ("emoji_category_activities", "⚽ 🏀 🏈 ⚾ 🎾 🏐 🎱 🏓 🏸 🥅 🏆 🥇 🎮 🎯 🎲 🎸 🎹 🎤 🎧 🎬 🎨"),
    ("emoji_category_travel", "🚗 🚕 🚌 🚑 🚒 🚲 🏍️ ✈️ 🚀 🚁 ⛵ 🚢 🗺️ 🏖️ 🏕️ 🏠 🏢 🏥 🏫 🌍 🌎 🌏"),
    ("emoji_category_objects", "⌚ 📱 💻 ⌨️ 🖥️ 🖨️ 📷 🎥 📺 📻 🔔 🔕 💡 🔦 📚 ✏️ 📝 📌 📎 🔒 🔑 🎁"),
    ("emoji_category_symbols", "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💯 ✅ ❌ ❓ ❗ ⚠️ ♻️ ➕ ➖ ✔️"),
    ("emoji_category_flags", "🏳️ 🏴 🏁 🚩 🏳️‍🌈 🏳️‍⚧️ 🇧🇷 🇵🇹 🇺🇸 🇪🇸 🇵🇱 🇦🇷 🇲🇽 🇨🇦 🇬🇧 🇫🇷 🇩🇪 🇮🇹 🇯🇵"),
)

# Extra everyday terms make the search useful in every shipped language;
# Unicode already supplies the complete English names.  Accents are removed
# during matching, so both "coração" and "coracao" work.
EMOJI_SEARCH_ALIASES = {
    "😀 😃 😄 😁 😂 😊 😍 🥰 😘 😎 😢 😭 😡 🙂 🙃 😉 😌 🤩 🥳 😏 😴 🤗 🤔 🤭 🤫 😐 🙄 😮 😱 🤢 🤧 😇 🤠":
        "face rosto cara carinha emoji emoção emocao expressão expressao",
    "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞":
        "heart hearts love amor coração coracao corazón corazon serce miłość milosc",
    "😀 😃 😄 😁 😊 🙂 😇":
        "smile smiling happy grin sorriso sorrir feliz sonrisa sonreír sonreir uśmiech usmiech szczęśliwy szczesliwy",
    "😂 🤣": "laugh laughing lol rir riso gargalhada reír reir risa śmiech smiech",
    "😢 😭": "sad crying cry triste chorar lágrima lagrima llorar llanto płacz placz smutny",
    "😡": "angry mad bravo raiva enojado enfadado zły zly",
    "👍": "thumb up like joinha curtir pulgar arriba kciuk góra gora",
    "👎": "thumb down dislike não nao gostei pulgar abajo kciuk dół dol",
    "🙏": "pray prayer thanks obrigado obrigada gracias dziękuję dziekuje",
    "🎉 🥳": "party celebration festa comemorar fiesta celebración celebracion impreza święto swieto",
    "🔥": "fire flame hot fogo chama calor fuego ogień ogien",
    "🐶": "dog puppy cachorro cão cao perro pies",
    "🐱": "cat kitten gato gata kot",
    "🍕": "pizza",
    "🍔": "burger hamburger hambúrguer hamburguer",
    "☕": "coffee café cafe kawa",
    "⚽": "football soccer futebol fútbol futbol piłka pilka",
    "🎵 🎤 🎧 🎸 🎹": "music música musica song som canción cancion muzyka",
    "🚗": "car automobile carro coche samochód samochod",
    "✈️": "airplane plane travel avião aviao viaje avión avion samolot podróż podroz",
    "🏠": "home house casa hogar dom",
    "📱": "phone mobile celular telefone teléfono telefono telefon",
    "🎁": "gift present presente regalo prezent",
    "✅ ✔️": "check correct done certo concluído concluido correcto gotowe",
    "❌": "cross wrong error errado cancelar incorrecto błąd blad",
    "❓": "question dúvida duvida pregunta pytanie",
    "❗ ⚠️": "warning alert attention atenção atencao alerta atención atencion ostrzeżenie ostrzezenie",
    "🙃": "upside down invertido cabeça para baixo cabeca de ponta cabeza abajo",
    "😉": "wink winking piscadela piscar guiño guino",
    "😌": "relieved calm aliviado calma tranquilo alivio",
    "😍 🥰": "love in love apaixonado apaixonada carinho enamorado corazones",
    "😘": "kiss kissing beijo beijando beso",
    "😎": "sunglasses cool óculos oculos escuro gafas sol",
    "🤩": "star eyes estrela olhos estrelas admirado",
    "😏": "smirk malicioso convencido sorriso maroto",
    "😴": "sleep sleeping sleepy sono dormir dormindo sueño sueno",
    "🤗": "hug hugging abraço abraco abraçando abrazando",
    "🤔": "think thinking pensando dúvida duvida pensativo",
    "🤭": "giggle hand mouth mão boca mao rindo escondido",
    "🤫": "quiet silence shush silêncio silencio calado secreto",
    "😐": "neutral expressionless neutro sem expressão expressao",
    "🙄": "rolling eyes revirando olhos impaciente",
    "😮": "surprised open mouth surpresa boca aberta",
    "😱": "scream fear afraid grito medo assustado",
    "🤢": "sick nausea nauseated doente enjoo enjoado náusea nausea",
    "🤧": "sneeze sneezing espirro espirrando resfriado",
    "😇": "angel halo anjo auréola aureola inocente",
    "🤠": "cowboy caubói cauboi chapéu chapeu",
    "👋": "wave waving hello goodbye acenar tchau olá ola saludo",
    "🤚 🖐️ ✋": "raised hand mão levantada mao aberta pare alto",
    "🖖": "vulcan prosper vida longa saudação saudacao",
    "👌": "ok perfect perfeito certo",
    "🤌": "pinched fingers dedos juntos italiano",
    "🤏": "pinching small pouco pequeno",
    "✌️": "victory peace vitória vitoria paz dois dedos",
    "🤞": "crossed fingers sorte dedos cruzados",
    "🤟": "love you amo linguagem sinais",
    "🤘": "rock horns metal chifres",
    "🤙": "call me ligar telefone mão mao",
    "👈": "left apontar esquerda dedo",
    "👉": "right apontar direita dedo",
    "👆 ☝️": "up apontar cima dedo",
    "👇": "down apontar baixo dedo",
    "✊ 👊 🤛 🤜": "fist punch punho soco força forca",
    "👏": "clap applause palmas aplauso aplaudir",
    "🙌": "raised hands celebrate mãos maos levantadas comemorar",
    "👐": "open hands mãos maos abertas",
    "🤝": "handshake acordo aperto mãos maos parceria",
    "💪": "muscle strong strength músculo musculo forte força forca",
    "🐭": "mouse rato ratinho ratón raton",
    "🐹": "hamster",
    "🐰": "rabbit bunny coelho conejo",
    "🦊": "fox raposa zorro",
    "🐻": "bear urso oso",
    "🐼": "panda",
    "🐨": "koala coala",
    "🐯": "tiger tigre",
    "🦁": "lion leão leao león leon",
    "🐮": "cow vaca",
    "🐷": "pig porco porquinho cerdo",
    "🐸": "frog sapo rana",
    "🐵": "monkey macaco mono",
    "🐔": "chicken hen galinha pollo",
    "🐧": "penguin pinguim pingüino pinguino",
    "🐦": "bird pássaro passaro ave pájaro pajaro",
    "🦄": "unicorn unicórnio unicornio",
    "🐝": "bee abelha abeja",
    "🦋": "butterfly borboleta mariposa",
    "🐢": "turtle tartaruga tortuga",
    "🐬": "dolphin golfinho delfín delfin",
    "🍎": "apple maçã maca manzana",
    "🍐": "pear pera",
    "🍊": "orange laranja naranja",
    "🍋": "lemon limão limao limón limon",
    "🍌": "banana",
    "🍉": "watermelon melancia sandía sandia",
    "🍇": "grapes uva uvas",
    "🍓": "strawberry morango fresa",
    "🫐": "blueberry mirtilo arándano arandano",
    "🍒": "cherry cherries cereja cerejas",
    "🍑": "peach pêssego pessego melocotón melocoton",
    "🥭": "mango manga",
    "🍍": "pineapple abacaxi piña pina",
    "🥝": "kiwi",
    "🍅": "tomato tomate",
    "🥑": "avocado abacate aguacate",
    "🍟": "fries chips batata frita papas fritas",
    "🌭": "hot dog cachorro quente",
    "🍿": "popcorn pipoca palomitas",
    "🍩": "donut doughnut rosquinha",
    "🎂": "cake birthday bolo aniversário aniversario cumpleaños cumpleanos",
    "🏀": "basketball basquete baloncesto",
    "🏈": "american football futebol americano",
    "⚾": "baseball beisebol béisbol beisbol",
    "🎾": "tennis tênis tenis",
    "🏐": "volleyball vôlei volei voleibol",
    "🎱": "pool billiards sinuca bilhar",
    "⚽ 🏀 🏈 ⚾ 🎾 🏐 🎱 🏓 🏸": "ball bola esporte jogo",
    "🏓": "ping pong table tennis tênis mesa tenis",
    "🏸": "badminton peteca",
    "🥅": "goal net gol rede",
    "🏆": "trophy champion troféu trofeu campeão campeao copa",
    "🥇": "gold medal first medalha ouro primeiro",
    "🎮": "game videogame controller jogo controle",
    "🎯": "target dart alvo dardo",
    "🎲": "dice dado sorte",
    "🎸": "guitar guitarra violão violao",
    "🎹": "piano keyboard teclado musical",
    "🎤": "microphone mic microfone cantar",
    "🎧": "headphones fone ouvido auscultadores",
    "🎬": "movie cinema film filme claquete",
    "🎨": "art paint palette arte pintura paleta",
    "🚕": "taxi táxi",
    "🚌": "bus ônibus onibus autocarro autobús autobus",
    "🚑": "ambulance ambulância ambulancia",
    "🚒": "fire truck bombeiro caminhão caminhao incêndio incendio",
    "🚲": "bicycle bike bicicleta bici",
    "🏍️": "motorcycle motorbike moto motocicleta",
    "🚀": "rocket foguete cohete espaço espaco",
    "🚁": "helicopter helicóptero helicoptero",
    "⛵": "sailboat barco vela velero",
    "🚢": "ship navio barco buque",
    "🗺️": "map mapa mundo",
    "🏖️": "beach praia playa",
    "🏕️": "camping campsite acampamento campamento",
    "🏢": "office building prédio predio escritório escritorio edificio",
    "🏥": "hospital saúde saude médico medico",
    "🏫": "school escola colegio",
    "🌍 🌎 🌏": "earth world globe terra mundo planeta globo",
    "⌚": "watch clock relógio relogio pulso",
    "💻": "laptop computer notebook computador",
    "⌨️": "keyboard teclado",
    "🖥️": "desktop monitor computer computador tela ecrã ecra",
    "🖨️": "printer impressora",
    "📷": "camera photo câmera camera foto",
    "🎥": "video camera câmera filmar",
    "📺": "television tv televisão televisao",
    "📻": "radio rádio",
    "🔔": "bell notification sino notificação notificacao campainha",
    "🔕": "muted bell silent notification sino mudo silencioso",
    "💡": "light bulb idea lâmpada lampada ideia luz",
    "🔦": "flashlight lanterna",
    "📚": "books livros biblioteca estudiar estudar",
    "✏️": "pencil lápis lapis escrever",
    "📝": "memo note anotação anotacao nota escrever",
    "📌": "pin pushpin alfinete marcador",
    "📎": "paperclip clipe anexo",
    "🔒": "lock locked cadeado fechado segurança seguranca",
    "🔑": "key chave llave senha",
    "💔": "broken heart coração partido coracao triste desamor",
    "💕 💞": "hearts love corações coracoes amor carinho",
    "💯": "hundred perfect cem perfeito nota máxima maxima",
    "➕": "plus add positive mais adicionar soma",
    "➖": "minus subtract negative menos subtrair",
    "♻️": "recycle recycling reciclar reciclagem",
    "🏁": "finish racing flag chegada corrida bandeira",
    "🚩": "red flag bandeira vermelha alerta",
    "🏳️‍🌈": "rainbow flag pride bandeira arco íris iris orgulho lgbt",
    "🏳️‍⚧️": "transgender flag bandeira trans orgulho",
    "🇧🇷": "brazil brasil brasileiro bandeira",
    "🇵🇹": "portugal português portugues bandeira",
    "🇺🇸": "united states usa estados unidos americano bandeira",
    "🇪🇸": "spain espanha españa bandeira",
    "🇵🇱": "poland polônia polonia polska bandeira",
    "🇦🇷": "argentina bandeira",
    "🇲🇽": "mexico méxico bandeira",
    "🇨🇦": "canada canadá bandeira",
    "🇬🇧": "united kingdom uk britain reino unido inglaterra bandeira",
    "🇫🇷": "france frança franca bandeira",
    "🇩🇪": "germany alemanha deutschland bandeira",
    "🇮🇹": "italy itália italia bandeira",
    "🇯🇵": "japan japão japao bandeira",
}

# Connector words describe the phrase, not the emoji. Ignoring them lets
# natural searches such as "fone de ouvido", "bandeira do Brasil" and
# "emoji de coração" validate against the meaningful terms.
SEARCH_STOP_WORDS = {
    "a", "as", "com", "da", "das", "de", "do", "dos", "e", "em",
    "emoji", "emogi", "o", "os", "para", "por", "um", "uma",
    "and", "for", "of", "the", "with",
    "con", "del", "el", "la", "las", "los", "y",
}


def _search_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _unicode_name(emoji: str) -> str:
    return " ".join(
        unicodedata.name(ch, "")
        for ch in emoji
        if ch not in ("\ufe0f", "\u200d") and unicodedata.name(ch, "")
    )


def _aliases_by_emoji() -> dict[str, str]:
    """Merge, rather than overwrite, every keyword group for an emoji."""
    merged: dict[str, list[str]] = {}
    for emoji_group, terms in EMOJI_SEARCH_ALIASES.items():
        for emoji in emoji_group.split():
            merged.setdefault(emoji, []).append(terms)
    return {emoji: " ".join(groups) for emoji, groups in merged.items()}


def _word_matches(needle: str, candidate: str) -> bool:
    """Accent-insensitive word matching with conservative typo tolerance."""
    if not needle or not candidate:
        return False
    if needle == candidate:
        return True
    # Prefix/substring matching makes singulars, plurals and partial terms
    # useful ("tartar" -> "tartaruga") without fuzzy-matching tiny words.
    if min(len(needle), len(candidate)) >= 3 and needle in candidate:
        return True
    if len(needle) >= 5 and len(candidate) >= 5:
        return SequenceMatcher(None, needle, candidate).ratio() >= 0.84
    return False


def filter_emojis(query: str, category_index: int, category_labels) -> list[str]:
    """Return one category, or matching emoji from every category when searching."""
    if not query.strip():
        return EMOJI_CATEGORIES[category_index][1].split()

    needle = _search_text(query.strip())
    raw_query_words = needle.split()
    query_words = [word for word in raw_query_words if word not in SEARCH_STOP_WORDS]
    if not query_words:
        return []
    aliases = _aliases_by_emoji()
    matches = []
    seen = set()
    for index, (_key, values) in enumerate(EMOJI_CATEGORIES):
        category_name = category_labels[index]
        for emoji in values.split():
            haystack = _search_text(
                f"{emoji} {_unicode_name(emoji)} {category_name} {aliases.get(emoji, '')}"
            )
            words = haystack.split()
            direct_emoji = needle == _search_text(emoji)
            all_words_match = all(
                any(_word_matches(word, candidate) for candidate in words)
                for word in query_words
            )
            if (direct_emoji or all_words_match) and emoji not in seen:
                seen.add(emoji)
                matches.append(emoji)
    return matches


def insert_emoji(text_ctrl, emoji: str) -> bool:
    """Insert at the native selection and restore focus.

    WriteText delegates selection replacement and UTF-16 caret accounting to
    wx/Windows, avoiding broken caret positions around existing emoji.
    """
    if not emoji:
        return False
    text_ctrl.WriteText(emoji)
    text_ctrl.SetFocus()
    return True


class EmojiPickerDialog(wx.Dialog):
    def __init__(self, parent, i18n):
        super().__init__(parent, title=i18n.t("emoji_picker_title"), size=(420, 480))
        self._i18n = i18n
        self._selected_emoji = ""
        self._queued_emojis: list[str] = []
        main_window = getattr(parent, "main_window", None)
        self._announce = getattr(main_window, "output", None)

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        hint = wx.StaticText(panel, label=i18n.t("emoji_picker_hint"))
        sizer.Add(hint, 0, wx.EXPAND | wx.ALL, 8)

        self._search_button = wx.Button(panel, label=i18n.t("emoji_picker_search"))
        self._search_button.SetName(i18n.t("emoji_picker_search").replace("&", ""))
        self._search_button.Bind(wx.EVT_BUTTON, self._on_search_button)
        sizer.Add(self._search_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self._search = wx.SearchCtrl(panel, style=wx.TE_PROCESS_ENTER)
        # SetDescriptiveText is only a visual placeholder on Windows; it does
        # not reliably become the accessible name announced by NVDA/JAWS.
        # SetName gives the edit field an explicit role description.
        self._search.SetName(i18n.t("emoji_picker_search").replace("&", ""))
        self._search.SetDescriptiveText(i18n.t("emoji_picker_search_hint"))
        self._search.SetHelpText(i18n.t("emoji_picker_search_hint"))
        # Keep the edit out of the initial Tab order. Screen-reader users first
        # encounter the explicit native button above; activating it enables
        # and focuses this field, making the search interaction intentional
        # instead of adding an unexplained edit box to normal category/list
        # navigation.
        self._search.Disable()
        self._search.Bind(wx.EVT_TEXT, self._on_search_changed)
        self._search.Bind(wx.EVT_TEXT_ENTER, self._on_search_enter)
        sizer.Add(self._search, 0, wx.EXPAND | wx.ALL, 8)

        self._result_status = wx.StaticText(panel, label="")
        self._result_status.SetName(i18n.t("emoji_picker_search_results_label"))
        sizer.Add(self._result_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        category_label = wx.StaticText(panel, label=i18n.t("emoji_picker_category"))
        sizer.Add(category_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self._category = wx.Choice(
            panel,
            choices=[i18n.t(key) for key, _ in EMOJI_CATEGORIES],
        )
        self._category.SetSelection(0)
        self._category.Bind(wx.EVT_CHOICE, self._on_category_changed)
        sizer.Add(self._category, 0, wx.EXPAND | wx.ALL, 8)

        self._list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list.InsertColumn(0, i18n.t("emoji_picker_emoji"), width=340)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activated)
        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_selected)
        # Catch Ctrl+Enter before Windows turns Enter into the native
        # EVT_LIST_ITEM_ACTIVATED notification. A normal Enter is skipped and
        # keeps the established one-emoji insert-and-close path untouched.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        buttons = wx.StdDialogButtonSizer()
        insert_btn = wx.Button(panel, wx.ID_OK, i18n.t("emoji_picker_insert"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, i18n.t("cancel"))
        insert_btn.SetDefault()
        buttons.AddButton(insert_btn)
        buttons.AddButton(cancel_btn)
        buttons.Realize()
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(sizer)
        self._populate()
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.CentreOnParent()
        self._search_button.SetFocus()

    def _on_search_button(self, event):
        """Make the search field discoverable through a real native button."""
        self._search.Enable()
        self._search.SetFocus()
        self._search.SelectAll()

    def _populate(self):
        query = self._search.GetValue()
        self._list.DeleteAllItems()
        labels = [self._i18n.t(key) for key, _ in EMOJI_CATEGORIES]
        emojis = filter_emojis(query, self._category.GetSelection(), labels)
        for emoji in emojis:
            self._list.Append((emoji,))
        self._selected_emoji = emojis[0] if emojis else ""
        if emojis:
            result_text = self._i18n.t("emoji_picker_search_results").format(
                count=len(emojis)
            )
        else:
            result_text = self._i18n.t("emoji_picker_search_no_results")
        self._result_status.SetLabel(result_text)

        # Never move focus to the result list from inside EVT_TEXT. On native
        # Windows controls that steals the remainder of the current keyboard
        # input, which made the field keep only the first typed character.
        # Empty/category navigation may still select the first list item; a
        # search moves there only after the user validates it with Enter.
        if emojis:
            if not query.strip():
                self._list.Focus(0)
                self._list.Select(0)

    def _on_category_changed(self, event):
        self._populate()

    def _on_search_changed(self, event):
        self._populate()

    def _on_search_enter(self, event):
        if self._list.GetItemCount() > 0:
            self._list.Focus(0)
            self._list.Select(0)
            self._list.SetFocus()
        else:
            self._selected_emoji = ""
            wx.Bell()
            self._search.SetFocus()
            self._search.SelectAll()

    def _on_selected(self, event):
        index = event.GetIndex()
        if index >= 0:
            self._selected_emoji = self._list.GetItemText(index)

    def _current_emoji(self) -> str:
        index = self._list.GetFirstSelected()
        if index >= 0:
            return self._list.GetItemText(index)
        return self._selected_emoji

    def _queue_current_emoji(self) -> bool:
        """Keep one emoji and leave the picker open for another choice."""
        emoji = self._current_emoji()
        if not emoji:
            wx.Bell()
            return False
        self._queued_emojis.append(emoji)
        message = self._i18n.t("emoji_picker_queued").format(
            emoji=emoji, count=len(self._queued_emojis)
        )
        self._result_status.SetLabel(message)
        if callable(self._announce):
            try:
                self._announce(message, interrupt=True)
            except TypeError:
                self._announce(message)
        return True

    def _on_char_hook(self, event):
        if (self._list.HasFocus()
                and event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and event.ControlDown()):
            self._queue_current_emoji()
            return
        event.Skip()

    def _final_selection(self) -> str:
        """Queued emojis followed by the last, normally activated emoji."""
        current = self._current_emoji()
        return "".join(self._queued_emojis) + current

    def _on_activated(self, event):
        self._on_selected(event)
        selected = self._final_selection()
        if selected:
            self._selected_emoji = selected
            self.EndModal(wx.ID_OK)

    def _on_ok(self, event):
        selected = self._final_selection()
        if selected:
            self._selected_emoji = selected
            self.EndModal(wx.ID_OK)

    def get_selected_emoji(self) -> str:
        return self._selected_emoji


def choose_and_insert_emoji(parent, text_ctrl, i18n) -> bool:
    """Show the picker and insert the chosen emoji into ``text_ctrl``."""
    dialog = EmojiPickerDialog(parent, i18n)
    try:
        if dialog.ShowModal() != wx.ID_OK:
            text_ctrl.SetFocus()
            return False
        return insert_emoji(text_ctrl, dialog.get_selected_emoji())
    finally:
        dialog.Destroy()
