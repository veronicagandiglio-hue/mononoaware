#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
traduci_racconto.py
════════════════════════════════════════════════════════════════════
Automatizza le 6 fasi che usi manualmente (copia-incolla tra prompt) per
tradurre un racconto giapponese e pubblicarlo sul sito Astro, partendo
da un URL con il testo originale:

  FASE 1 — Traduzione            (temp 0.5  / top-p 0.85)
  FASE 2 — Revisione             (temp 0.2  / top-p 0.70)
  FASE 3 — Oltre la lettura      (temp 0.65 / top-p 0.90)
  FASE 4 — Note al testo         (temp 0.15 / top-p 0.55)
  FASE 5 — Prompt immagine       (temp 0.6  / top-p 0.80)
  FASE 6 — Tag / categoria / SEO (temp 0.1  / top-p 0.50)

  + assemblaggio finale del file .md con lo stesso frontmatter richiesto
    da src/content.config.ts, pronto per src/content/racconti/.

I contenuti dei 6 prompt sono i tuoi, invariati. Due sole aggiunte
tecniche, necessarie per automatizzare ciò che a mano fai leggendo la
risposta e ricopiando a mano nel form:

  • FASE 4: al modello viene chiesto un formato a righe fisse
    (TESTO_ESATTO: / NOTA:) così lo script trova da solo il punto esatto
    nel testo tradotto e ci inserisce <span class="nota" data-nota="...">
    — lo stesso formato già usato nei racconti pubblicati sul sito.
  • FASE 6: al modello viene chiesto di restituire quattro righe fisse
    (Categoria: / Tag: / Excerpt: / Meta description:) per lo stesso
    motivo — parsing automatico invece di copia-incolla.

Ogni fase viene salvata su disco mano a mano (cartella di lavoro): se lo
script si interrompe (rete, quota API, Ctrl+C), rilancialo con --resume
e riparte dall'ultima fase completata, senza rifare (e ripagare) le
chiamate già andate a buon fine.

────────────────────────────────────────────────────────────────────
INSTALLAZIONE
────────────────────────────────────────────────────────────────────
    pip install requests beautifulsoup4      # bs4 opzionale, solo per --url

    Chiave API gratuita: https://aistudio.google.com/apikey
        export GEMINI_API_KEY="AIza..."
    oppure in un file .env nella stessa cartella:
        GEMINI_API_KEY=AIza...

    NB: Gemini 3.1 Pro Preview è a pagamento dall'aprile 2026. Il livello
    gratuito copre i modelli Flash — default di questo script:
    gemini-3.5-flash (cambiabile con --model).

────────────────────────────────────────────────────────────────────
ESEMPIO
────────────────────────────────────────────────────────────────────
  python traduci_racconto.py \\
      --url "https://www.aozora.gr.jp/cards/000035/files/301_14912.html" \\
      --author "Ryūnosuke Akutagawa" --title "Il paravento" \\
      --year 1918 --period "Periodo Taishō"

  (categoria, tag, excerpt e meta description vengono decisi dalla FASE 6
   sulle tue liste chiuse; puoi anche forzarli a mano con --category /
   --tags / --excerpt / --description)

  # Riprendere un lavoro interrotto:
  python traduci_racconto.py --url "..." --author "..." --title "..." --year ... --resume

  # Solo testare che chiave/modello funzionino:
  python traduci_racconto.py --test-connection
"""

from __future__ import annotations

import argparse
import html as html_module
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    sys.exit("Manca la libreria 'requests'. Installa con:  pip install requests")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


# ══════════════════════════════════════════════════════════════════
#  COSTANTI GENERALI
# ══════════════════════════════════════════════════════════════════

DEFAULT_MODEL = "gemini-3.6-flash"   # modello gratuito consigliato (ago 2026)
CHUNK_CHARS   = 7000      # caratteri per blocco nella FASE 1 (testi lunghi)
CONTEXT_CHARS = 1500      # coda del blocco precedente usata come memoria
MAX_RETRIES   = 4
RETRY_BASE_S  = 3.0
REQUEST_TIMEOUT_S = 180
MAX_OUTPUT_TOKENS = 8192
MAX_CONTINUATIONS = 5     # continuazioni automatiche se il modello si interrompe

CATEGORIE_SCHEMA = [
    "Naturalismo", "Romanzo dell'Io", "Estetismo", "Ero-Guro e Giallo",
    "Folklore e Fantasmi", "Satira e Critica Sociale", "Modernismo",
    "Realismo Storico",
]

NOTA_RE = re.compile(r'class="nota"')


# ══════════════════════════════════════════════════════════════════
#  LISTE CHIUSE — FASE 6 (categoria + tag)
# ══════════════════════════════════════════════════════════════════

CATEGORIE_FASE6 = [
    "naturalismo", "modernismo", "romanzo dell'io", "ero-guro e giallo",
    "fantasmi e folklore",
]

CATEGORY_MAP = {
    "naturalismo": "Naturalismo",
    "modernismo": "Modernismo",
    "romanzo dell'io": "Romanzo dell'Io",
    "ero-guro e giallo": "Ero-Guro e Giallo",
    "fantasmi e folklore": "Folklore e Fantasmi",
    "folklore e fantasmi": "Folklore e Fantasmi",
    "estetismo": "Estetismo",
    "satira e critica sociale": "Satira e Critica Sociale",
    "realismo storico": "Realismo Storico",
}

TAG_GROUPS = {
    "Emozioni/Psicologia": [
        "malinconia", "inquietudine", "solitudine", "alienazione", "ansia",
        "vergogna", "colpa", "ossessione", "smarrimento", "vuoto", "desiderio",
        "paura", "frustrazione", "umiliazione", "inadeguatezza", "sensibilita",
        "epifania", "depressione", "disillusione", "nostalgia", "vulnerabilità",
        "autoironia", "ambiguità",
    ],
    "Relazioni": [
        "famiglia", "amicizia", "amicizia virile", "matrimonio",
        "amore impossibile", "amore", "sessualità", "attesa", "fedeltà",
        "tenerezza", "tradimento",
    ],
    "Esistenza": [
        "morte", "identità", "fallimento", "memoria", "destino", "suicidio",
        "perdita", "autodistruzione", "autoinganno", "autosabotaggio",
        "assoluzione", "assurdo", "dolore", "rovina", "sopravvivenza",
        "verità", "illusione", "nichilismo", "realtà",
    ],
    "Sociale/Storico": [
        "povertà", "lavoro", "emarginazione", "modernizzazione", "guerra",
        "provincia", "città", "classe-sociale", "dipendenza-economica",
        "pressione-sociale", "fatalismo", "realta-materiale", "determinismo",
        "sacrificio", "società", "denaro", "debito", "dignità", "dovere",
        "eredità", "esilio", "impero", "storia", "cultura", "clan Taira",
        "obbedienza", "naturalismo",
    ],
    "Modernismo": [
        "meccanizzazione", "frammentazione", "velocita", "percezione",
        "modernità", "treno", "macchina", "luce", "città", "alienazione",
    ],
    "Romanzo dell'Io": [
        "inadeguatezza", "sensibilita", "epifania", "autoinganno",
        "autosabotaggio", "confessione", "autobiografico", "frammentario",
        "frammento", "io", "difetti",
    ],
    "Naturalismo": [
        "determinismo", "classe-sociale", "sacrificio", "frustrazione",
        "dipendenza-economica", "pressione-sociale", "umiliazione",
        "fatalismo", "realta-materiale", "fame", "corpo", "materia",
        "sopravvivenza",
    ],
    "Folklore/Soprannaturale": [
        "fantasma", "fantasmi", "spiriti", "spettri", "folklore", "yokai",
        "karma", "vendetta", "promessa", "rituale", "soprannaturale",
        "metamorfosi", "bosco", "spiriti-femminili", "onore",
        "destino-spirituale", "maledizione", "leggenda", "ignoto",
    ],
    "Ero-Guro/Giallo": [
        "mistero", "follia", "grottesco", "erotismo", "eros", "violenza",
        "doppio", "voyeurismo", "feticismo", "perversione", "corpo",
        "deformita", "doppia-identita", "paranoia", "indagine", "enigma",
        "tabu", "spazio-chiuso", "identita-frantumata", "delitto",
        "deduzione", "codice", "suspense", "macabro", "orrore",
        "curiosità morbosa",
    ],
    "Atmosfera": [
        "notturno", "onirico", "contemplativo", "claustrofobico",
        "claustrofobia", "spirituale", "fiabesco", "silenzio", "pioggia",
        "neve", "brivido", "perturbante", "sospensione", "sogno", "visione",
    ],
    "Stile/Forma": [
        "confessione", "autobiografico", "frammentario", "simbolico",
        "realistico", "dettaglio", "gesto", "disciplina", "movimento",
        "logica", "teatro", "maschera", "estetica", "grottesco",
    ],
    "Natura/Cultura": [
        "natura", "bellezza", "bellezza pericolosa", "tradizione",
        "infanzia", "animale", "cervo", "compassione", "fiaba", "ciliegi",
        "crisantemo", "fango", "luna", "montagna", "paesaggio", "primavera",
        "riflesso", "sangue",
    ],
    "Oggetti/Immagini ricorrenti": [
        "camera", "chirurgia", "fango", "lettera", "luna", "musica",
        "pozzo", "rosso", "stanza", "testamento",
    ],
    "Luoghi": [
        "Tokyo", "Kyoto", "Osaka", "Kamakura", "sottosuolo", "pellegrinaggio",
        "labirinto", "montagna", "bosco", "provincia", "città",
    ],
}


def tagify(text: str) -> str:
    """'amore impossibile' → 'amore-impossibile' — stessa trasformazione
    di addTag() in generatore-racconti.html."""
    return re.sub(r"\s+", "-", text.strip().lower())


TAGS_BLOCK_TEXT = "\n".join(
    f"{cat}: {', '.join(tags)}" for cat, tags in TAG_GROUPS.items()
)
TAG_WHITELIST = {tagify(t) for tags in TAG_GROUPS.values() for t in tags}


# ══════════════════════════════════════════════════════════════════
#  I 6 PROMPT (testo tuo, con solo i punti di iniezione e — per le
#  fasi 4 e 6 — un formato di output fisso per il parsing automatico)
# ══════════════════════════════════════════════════════════════════

PROMPT_FASE1 = """Agisci come un traduttore letterario professionista, specializzato in letteratura giapponese classica e del primo Novecento. Il tuo obiettivo è tradurre un racconto giapponese nel pubblico dominio in un italiano elegante, fluido e letterario.
Regole per la traduzione:
    1. Rispetta lo stile dell'autore: Se il testo originale ha frasi brevi e ansiogene, mantieni quel ritmo. Se è poetico ed evocativo o ironico, adatta l'italiano di conseguenza.
    2. Mantieni il sapore dell'epoca: Usa un vocabolario adatto al periodo storico in cui il racconto è stato scritto. Evita slang moderni o espressioni anacronistiche.
    3. Non appiattire la cultura: Se ci sono termini specifici, lasciali in giapponese (li spiegheremo poi nelle note) oppure usa una traduzione che non occidentalizzi troppo il concetto.
Di seguito ti fornisco il titolo, l'autore e il testo originale in giapponese. Ti mando il testo originale in più parti, fai attenzione a non cambiare termini e nomi tra parti diverse. Non fare note ora, le farò dopo, ora concentrati solo sulla traduzione. Procedi con la traduzione.

AUTORE: {autore}
TITOLO: {titolo}
{contesto_precedente}
TESTO ORIGINALE GIAPPONESE{parte_label}:
{testo}

Restituisci SOLO la traduzione italiana di questa parte, senza premesse, senza commenti, senza racchiuderla in blocchi di codice."""

PROMPT_FASE2 = """Agisci come un editor meticoloso e un revisore di bozze esperto di lingua giapponese e italiana. Ti fornirò un testo originale giapponese e la sua traduzione in italiano.
Il tuo compito è fare un "fine-tuning" della traduzione:
    1. Controllo fedeltà: Segnala se ci sono stati errori di traduzione, fraintendimenti di kanji o sfumature perse.
    2. Fluidità in italiano: Suggerisci miglioramenti per frasi che suonano "legnose" o troppo letterali, proponendo alternative più eleganti ma sempre fedeli al testo.
    3. Scelte lessicali: Verifica se un termine italiano scelto è davvero il più adatto al contesto storico e culturale del racconto originale.

REGOLA ASSOLUTA SULLA LUNGHEZZA: la tua risposta deve contenere l'INTERO testo italiano da cima a fondo, capitolo per capitolo, senza saltare né riassumere alcuna parte, anche se il testo è molto lungo. Non fermarti prima della fine e non sostituire porzioni di testo con riassunti, omissioni o frasi tipo "[...]" o "(il testo prosegue)". La lunghezza della tua risposta in output deve essere paragonabile a quella del testo tradotto che ti fornisco in input: se la tua risposta risulta sensibilmente più corta dell'originale fornito, hai commesso un errore. Se il testo è troppo lungo per una sola risposta, scrivi fino al limite consentito e poi fermati: verrà richiesto un seguito automaticamente.

Qui c'è il testo originale giapponese:
{testo_originale}

E qui la mia traduzione:
{testo_tradotto}

Restituisci SOLO il testo italiano corretto e riscritto per intero, dall'inizio alla fine senza saltare nulla, senza spiegazioni delle modifiche, senza premesse, senza racchiuderlo in blocchi di codice."""

PROMPT_FASE3 = """Ora agisci come un brillante saggista letterario, esperto di letteratura giapponese, psicologia del profondo e cultura del Giappone moderno.
Sto pubblicando gratuitamente il racconto giapponese che abbiamo appena tradotto sul mio sito. Il tuo obiettivo ora NON è fare una spiegazione scolastica del testo.
Il tuo compito è creare una sezione intitolata:
Oltre la lettura
L'effetto finale deve essere:
"Credevo di aver capito questo racconto, invece sotto c'era qualcosa di molto più inquietante." E poi lo spieghi. Devi mostrare riferimenti culturali non chiari al lettore occidentali, anche legati alla vita dell'autore. Devi mostrare gli aspetti piu' cupi ed esistenziale del racconto e dell'autore, il momento storico del Giappone, dettagli biografici dell'autore realmente rilevanti, elementi culturali invisibile a un lettore occidentale. E il senso generale, il significato cupo e profondo del racconto specialmente nei passaggi piu' oscuri.
NON fare introduzioni generiche o stile Wikipedia.
Deve sembrare una chiave di lettura unica e cupa, non banale, non le cose evidenti dal testo, specie per un occidentale.

AUTORE: {autore}
TITOLO: {titolo}
ANNO: {anno}

Testo tradotto del racconto:
{testo}

Restituisci solo il testo della sezione (senza ripetere il titolo "Oltre la lettura"), in paragrafi di prosa continua separati da una riga vuota, senza premesse tipo "Ecco la sezione richiesta"."""

PROMPT_FASE4 = """Ora agisci come un curatore editoriale. Devo inserire delle note a piè di pagina (o tooltip) per il racconto giapponese che abbiamo tradotto.
Sto pubblicando gratuitamente il racconto giapponese che abbiamo appena tradotto sul mio sito, ma ho fatto una pwa collegata al sito che assieme ai racconti permette di esplorare la cultura giapponese in un viaggio tra racconti e note nel testo.
Il tuo compito ora è concentrarti esclusivamente sui micro-elementi del testo. Estrai dal racconto i termini che necessitano di una spiegazione puntuale per un lettore italiano e forniscimi una breve nota per ciascuno. Concentrati su:
    1. Note Linguistiche: Giochi di parole, onomatopee particolari, espressioni idiomatiche giapponesi che ho dovuto adattare, o il motivo per cui ho lasciato un termine in originale.
    2. Oggetti e Vita Quotidiana: Cibi, vestiario, architettura, oggetti tradizionali menzionati nel testo.
    3. Geografia e Riferimenti Specifici: Nomi di quartieri, città, stazioni, o personaggi storici citati di sfuggita.
    4. Riferimenti alla vita dell'autore e alla storia giapponese.
    5. Elementi cupi non subito chiari.
Scrivi note brevi, chiare e dritte al punto, nell'ordine in cui compaiono nel racconto.

FONDAMENTALE: evita cose già scritte in "Oltre la lettura", che è questa:
{oltre_la_lettura}

AUTORE: {autore}
TITOLO: {titolo}

Testo tradotto del racconto:
{testo}

FORMATO DI OUTPUT OBBLIGATORIO (necessario per l'inserimento automatico delle note nel testo) — una nota per blocco, in questo formato ESATTO, senza numerarle tu stesso, senza testo introduttivo né conclusivo, senza markdown:

TESTO_ESATTO: <la parola o breve frase esatta del racconto, copiata carattere per carattere, a cui la nota si riferisce>
NOTA: <spiegazione breve, una o due frasi>
===

Ripeti questo blocco per ogni nota, nell'ordine in cui il testo a cui si riferiscono compare nel racconto. TESTO_ESATTO deve essere una stringa breve (poche parole) che esiste letteralmente, carattere per carattere, nel "Testo tradotto del racconto" qui sopra, scelta in modo che sia inequivocabile a quale punto del testo si riferisce."""

PROMPT_FASE5 = """Agisci come un esperto "Prompt Engineer" per generatori di immagini AI (come Midjourney). Il tuo compito è leggere il racconto giapponese che ti fornirò e creare un prompt in inglese per generare l'immagine di copertina (hero image) del sito.
Regole per il soggetto:
Estrapola dal testo l'immagine più iconica, poetica o malinconica (es. un personaggio in una posa specifica, un paesaggio, un oggetto simbolico). Non descrivere scene d'azione caotiche, ma momenti di sospensione e contemplazione.
Regola stilistica TASSATIVA:
L'immagine deve avere SEMPRE questo esatto stile visivo fisso. Non deviare mai da questi parametri: un acquerello monocromatico / sumi-e, con toni di grigio e nero su uno sfondo bianco sporco/pergamena chiarissimo. I bordi della scena devono sfumare dolcemente nel vuoto o nella nebbia (spazio negativo). Devono esserci macchie d'inchiostro (ink splatters) e un'atmosfera malinconica, eterea e wabi-sabi.
Restituiscimi solo il prompt in inglese, strutturato esattamente con questa formula:
/imagine prompt: [Inserisci qui 1 o 2 frasi in inglese che descrivono il soggetto principale e l'ambientazione estrapolati dal racconto], traditional Japanese ink wash painting style, sumi-e, monochrome watercolor, shades of grey and black on a soft off-white paper background. Minimalist, ethereal, wabi-sabi aesthetic, misty background fading into white fog, expressive brushstrokes, ink splatters, delicate textures, wide negative space, melancholic and poetic atmosphere --ar 16:9 --v 6.0

TESTO DEL RACCONTO (o un suo riassunto):
{testo}

Restituisci solo il prompt richiesto, nel formato esatto indicato, senza altro testo."""

PROMPT_FASE6 = """Agisci come un archivista letterario. Il tuo compito è classificare il racconto giapponese che ti fornirò, scegliendo i metadati ESCLUSIVAMENTE da due liste chiuse. Non ti è permesso inventare tag o categorie non presenti in questo elenco.
1. SCEGLI UNA SOLA CATEGORIA tra queste 5:
    • naturalismo
    • modernismo
    • romanzo dell'io
    • ero-guro e giallo
    • fantasmi e folklore
2. SCEGLI DA 3 A 5 TAG ESATTI da questa lista:
{tags_block}

REGOLA GEOGRAFICA TASSATIVA: Verifica con estrema attenzione se il racconto è ambientato o menziona esplicitamente una (o più) di queste quattro città: Tokyo, Kyoto, Kamakura, Osaka. Se la risposta è sì, DEVI assolutamente includere il nome della città esatta tra i tag.

TESTO DEL RACCONTO:
{testo}

FORMATO DI OUTPUT OBBLIGATORIO — esattamente queste quattro righe, in questo ordine, senza altro testo prima o dopo, senza markdown:
Categoria: <una categoria dalla lista>
Tag: <3-5 tag dalla lista, separati da virgola>
Excerpt: <breve estratto per il sito, in italiano, massimo 160 caratteri>
Meta description: <meta description SEO, in italiano, massimo 160 caratteri>"""

CONTINUA_FASE2 = ('Continua a riscrivere il testo italiano corretto esattamente da dove ti sei '
                   'interrotto, stesso stile, senza ripetere quanto già scritto, senza premesse.')
CONTINUA_FASE3 = ('Continua il saggio "Oltre la lettura" esattamente da dove ti sei interrotto, '
                   'stesso tono, senza ripetere quanto già scritto, senza premesse.')
CONTINUA_FASE4 = ('Continua a elencare le note esattamente da dove ti sei interrotto, stesso '
                   'formato TESTO_ESATTO/NOTA/===, senza ripetere le note già fornite sopra, '
                   'senza premesse.')


# ══════════════════════════════════════════════════════════════════
#  UTILITÀ VARIE
# ══════════════════════════════════════════════════════════════════

def log(msg: str) -> None:
    print(msg, flush=True)


def load_dotenv_if_present(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def slugify(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def strip_tags_for_reading(text: str) -> str:
    text = re.sub(r'<span class="nota"[^>]*>\[?\d*\]?</span>', "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text


def first_sentence(text: str, max_len: int = 155) -> str:
    clean = strip_tags_for_reading(text)
    clean = re.sub(r"\s+", " ", clean).strip()
    candidates = []
    for token in ["。", ". ", "! ", "? "]:
        i = clean.find(token)
        if i > 0:
            candidates.append(i + 1)
    end = min(candidates) if candidates else max_len
    return clean[: min(end, max_len)].strip()


def normalize_label(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"\s+", " ", text)
    return text


def yaml_escape(value: str) -> str:
    return value.replace('"', "'").strip()


def yaml_block_scalar(key: str, value: str) -> str:
    safe = value.replace("\r\n", "\n").strip()
    indented = safe.replace("\n", "\n  ")
    return f"{key}: |\n  " + indented


def model_display_name(model_id: str) -> str:
    return " ".join(w.capitalize() for w in model_id.split("-"))


def escape_note_html(text: str) -> str:
    """Come encodePopupNoteAttr() in generatore-racconti.html: prima si
    escapano i caratteri HTML, poi si convertono gli a-capo in <br>."""
    text = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    text = html_module.escape(text, quote=True)
    text = re.sub(r"\n{2,}", "<br><br>", text)
    text = text.replace("\n", "<br>")
    return text


# ══════════════════════════════════════════════════════════════════
#  ESTRAZIONE TESTO (file / url / incolla)
# ══════════════════════════════════════════════════════════════════

def clean_text(raw: str) -> str:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n[ \t]+", "\n", raw)
    raw = re.sub(r"[ \t]+\n", "\n", raw)
    raw = re.sub(r"\n{4,}", "\n\n\n", raw)
    return raw.strip()


def is_aozora(url: str) -> bool:
    return "aozora.gr.jp" in (url or "")


def extract_text_from_html(html_text: str, url: str = "") -> str:
    if not HAS_BS4:
        log("⚠ beautifulsoup4 non installato: uso un'estrazione HTML basilare "
            "(consigliato: pip install beautifulsoup4).")
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        return clean_text(text)

    soup = BeautifulSoup(html_text, "html.parser")

    if is_aozora(url):
        for tag in soup.select("rp, rt"):
            tag.decompose()
        keywords = ["底本：", "入力：", "校正：", "青空文庫", "NDC ", "翻訳底本", "翻訳者", "©", "Copyright "]
        for el in soup.find_all(["p", "div"]):
            t = el.get_text().strip()
            if len(t) < 500 and any(k in t for k in keywords):
                el.decompose()
        hrs = soup.find_all("hr")
        if hrs:
            last_hr = hrs[-1]
            for sib in list(last_hr.find_all_next()):
                sib.decompose()
            last_hr.decompose()

    junk_selectors = [
        "script", "style", "noscript", "nav", "header", "footer", "aside",
        "iframe", "form", "button",
        ".nav", ".menu", ".sidebar", ".widget", ".ad", ".ads", ".advertisement",
        ".banner", ".popup", ".modal", ".comment", ".comments",
        ".social-share", ".share", ".related", ".breadcrumb", ".pagination",
        "#nav", "#menu", "#footer", "#header", "#sidebar", "#comments",
        '[class*="cookie"]', '[class*="newsletter"]',
        '[role="navigation"]', '[role="banner"]',
        '[role="complementary"]', '[role="contentinfo"]',
    ]
    for sel in junk_selectors:
        for el in soup.select(sel):
            el.decompose()

    targets = [
        'article[class*="story"]', 'article[class*="text"]', "article",
        '[role="main"]', "main",
        "#honbun", ".honbun", ".main_text", "#works_text", ".works-text",
        ".content", ".post-content", ".entry-content", ".article-content",
        ".story-body", "#content", "#main", ".text-body",
    ]
    for sel in targets:
        el = soup.select_one(sel)
        if el:
            t = clean_text(el.get_text("\n"))
            if len(t) > 300:
                return t

    candidates = []
    for el in soup.find_all(["div", "section", "article", "td"]):
        if el.find(["nav", "header", "footer"]):
            continue
        t = el.get_text().strip()
        candidates.append((len(t), el))
    candidates.sort(key=lambda x: x[0], reverse=True)
    for length, el in candidates[:6]:
        if length > 400:
            return clean_text(el.get_text("\n"))

    return clean_text(soup.get_text("\n"))


def fetch_url(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; racconti-translator/1.0)"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def get_source_text(args) -> str:
    if args.input:
        path = Path(args.input)
        if not path.exists():
            sys.exit(f"File non trovato: {path}")
        return clean_text(path.read_text(encoding="utf-8"))

    if args.url:
        log(f"→ Scarico {args.url}")
        html_text = fetch_url(args.url)
        text = extract_text_from_html(html_text, args.url)
        if len(text) < 80:
            log("⚠ Estrazione automatica troppo corta, uso fallback grezzo.")
            text = clean_text(re.sub(r"<[^>]+>", " ", html_text))
        return text

    log("Incolla il testo originale, poi vai a capo e digita da solo su una riga: FINE")
    lines = []
    for line in sys.stdin:
        if line.strip() == "FINE":
            break
        lines.append(line)
    return clean_text("".join(lines))


# ══════════════════════════════════════════════════════════════════
#  CHUNKING (solo per la FASE 1, testi lunghi)
# ══════════════════════════════════════════════════════════════════

def find_split_point(text: str, near: int) -> int:
    candidates = [
        text.rfind("\n\n", 0, near),
        text.rfind("\n", 0, near),
        text.rfind("。", 0, near),
        text.rfind(". ", 0, near),
    ]
    candidates = [c for c in candidates if c > near * 0.3]
    return (max(candidates) + 1) if candidates else near


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks = []
    rem = text
    while rem:
        if len(rem) <= max_chars:
            chunks.append(rem.strip())
            break
        bp = max_chars
        pp = rem.rfind("\n\n", 0, max_chars)
        if pp > max_chars * 0.38:
            bp = pp + 2
        else:
            pn = rem.rfind("\n", 0, max_chars)
            if pn > max_chars * 0.38:
                bp = pn + 1
            else:
                pj = rem.rfind("。", 0, max_chars)
                pl = rem.rfind(". ", 0, max_chars)
                best = max(pj, pl)
                if best > max_chars * 0.38:
                    bp = best + 1
        chunks.append(rem[:bp].strip())
        rem = rem[bp:].strip()
    return [c for c in chunks if c]


# ══════════════════════════════════════════════════════════════════
#  CHIAMATA API GEMINI
# ══════════════════════════════════════════════════════════════════

class GeminiError(RuntimeError):
    pass


def call_gemini(prompt: str, api_key: str, model: str,
                 temperature: float = 0.4, top_p: float = 0.9,
                 max_retries: int = MAX_RETRIES) -> tuple[str, str]:
    """Ritorna (testo, finish_reason). Ritenta su errori di rete e su
    429/500/502/503, con backoff crescente."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "topP": top_p,
            "topK": 40,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, params={"key": api_key}, json=body,
                                  timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException as e:
            if attempt < max_retries:
                wait = RETRY_BASE_S * (attempt + 1)
                log(f"  ⚠ connessione fallita ({e}), ritento tra {wait:.0f}s…")
                time.sleep(wait)
                continue
            raise GeminiError(f"Connessione fallita dopo {max_retries} tentativi: {e}")

        if resp.status_code != 200:
            retriable = resp.status_code in (429, 500, 502, 503)
            try:
                err_msg = resp.json().get("error", {}).get("message", resp.text[:300])
            except Exception:
                err_msg = resp.text[:300]
            if retriable and attempt < max_retries:
                wait = RETRY_BASE_S * (attempt + 1) + (6 if resp.status_code == 429 else 0)
                log(f"  ⚠ Gemini HTTP {resp.status_code} ({err_msg}), ritento tra {wait:.0f}s…")
                time.sleep(wait)
                continue
            raise GeminiError(f"Gemini API HTTP {resp.status_code}: {err_msg}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = data.get("promptFeedback", {}).get("blockReason", "sconosciuto")
            raise GeminiError(f"Nessuna risposta da Gemini (motivo: {reason}).")
        cand = candidates[0]
        parts = cand.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        finish_reason = cand.get("finishReason", "STOP")

        if not text:
            raise GeminiError(f"Risposta vuota da Gemini (finishReason: {finish_reason})")
        return text, finish_reason

    raise GeminiError("Tentativi esauriti.")

    raise GeminiError("Tentativi esauriti (generazione immagine).")


def call_with_continuation(prompt: str, continua_msg: str, api_key: str, model: str,
                            temperature: float, top_p: float,
                            max_continuations: int = MAX_CONTINUATIONS) -> str:
    """Se il modello si interrompe (MAX_TOKENS), richiede automaticamente
    il seguito e concatena, invece di lasciare il testo troncato."""
    text, reason = call_gemini(prompt, api_key, model, temperature, top_p)
    full = text
    n = 0
    while reason == "MAX_TOKENS" and n < max_continuations:
        n += 1
        log(f"  ⚠ Risposta troncata (MAX_TOKENS), richiedo il seguito ({n}/{max_continuations})…")
        tail = full[-1200:]
        cont_prompt = f"{continua_msg}\n\nUltima parte già scritta (non ripeterla):\n…{tail}"
        more, reason = call_gemini(cont_prompt, api_key, model, temperature, top_p)
        full += more
    if reason == "MAX_TOKENS":
        log("  ⚠ Output troncato anche dopo le continuazioni: verifica manualmente.")
    return full


# ══════════════════════════════════════════════════════════════════
#  FASE 1 — TRADUZIONE (a blocchi, con memoria narrativa tra un blocco
#  e l'altro; niente note qui, come da prompt)
# ══════════════════════════════════════════════════════════════════

def build_context_block(prev_context: str) -> str:
    if not prev_context:
        return ""
    return (
        "CONTESTO — ultima porzione già tradotta nella parte precedente "
        "(solo per continuità di nomi propri e terminologia; NON tradurlo, "
        'NON ripeterlo nella risposta): "…' + prev_context + '…"\n'
    )


def translate_chunk_fase1(chunk: str, api_key: str, model: str, autore: str, titolo: str,
                           prev_context: str, parte_label: str, depth: int = 0) -> str:
    prompt = PROMPT_FASE1.format(
        autore=autore, titolo=titolo,
        contesto_precedente=build_context_block(prev_context),
        parte_label=parte_label, testo=chunk,
    )
    text, finish_reason = call_gemini(prompt, api_key, model, temperature=0.5, top_p=0.85)

    if finish_reason == "MAX_TOKENS" and len(chunk) > 1800 and depth < 3:
        log(f"  ⚠ MAX_TOKENS (profondità {depth}): divido il blocco e ritento…")
        sp = find_split_point(chunk, len(chunk) // 2)
        a, b = chunk[:sp].strip(), chunk[sp:].strip()
        result_a = translate_chunk_fase1(a, api_key, model, autore, titolo,
                                          prev_context, parte_label, depth + 1)
        result_b = translate_chunk_fase1(b, api_key, model, autore, titolo,
                                          result_a[-CONTEXT_CHARS:], parte_label, depth + 1)
        return result_a + "\n\n" + result_b
    elif finish_reason == "MAX_TOKENS":
        log("  ⚠ MAX_TOKENS non recuperabile: uso il testo parziale, verificalo a mano.")

    return text


def fase1_traduzione(original_text: str, api_key: str, model: str, autore: str,
                      titolo: str, chunk_chars: int, work_dir: Path,
                      resuming: bool = False) -> str:
    chunks = chunk_text(original_text, chunk_chars)
    total = len(chunks)
    parts: list[str] = []
    prev_ctx = ""

    for i, chunk in enumerate(chunks, start=1):
        step_name = f"01_traduzione_parte{i:03d}"
        label = f" (parte {i} di {total})" if total > 1 else ""

        cached = load_step(work_dir, step_name) if resuming else None
        if cached is not None:
            log(f"  ↺ Parte {i} di {total} già tradotta, recuperata dal checkpoint.")
            result = cached
        else:
            log(f"→ FASE 1 — Traduzione{label}…")
            result = translate_chunk_fase1(chunk, api_key, model, autore, titolo, prev_ctx, label)
            save_step(work_dir, step_name, result)

        parts.append(result)
        prev_ctx = result[-CONTEXT_CHARS:]
        if i < total and cached is None:
            time.sleep(0.6)

    return parts[0] if len(parts) == 1 else "\n\n".join(parts)


# ══════════════════════════════════════════════════════════════════
#  FASE 2 — REVISIONE (originale + traduzione insieme, testo intero)
# ══════════════════════════════════════════════════════════════════

def fase2_revisione(original_text: str, translated_text: str, api_key: str, model: str) -> str:
    log("→ FASE 2 — Revisione…")
    prompt = PROMPT_FASE2.format(testo_originale=original_text, testo_tradotto=translated_text)

    def _safe_call(p: str) -> str:
        result = call_with_continuation(p, CONTINUA_FASE2, api_key, model,
                                         temperature=0.2, top_p=0.70)
        # Rete di sicurezza: se il modello ha "riassunto" invece di riscrivere
        # per intero (capita su testi molto lunghi), la revisione risulta
        # sensibilmente più corta della traduzione di partenza. In tal caso
        # è più sicuro scartarla e tenere la traduzione della FASE 1, piuttosto
        # che pubblicare un racconto troncato senza che nessuno se ne accorga.
        if len(result) < len(translated_text) * 0.85:
            log(f"  ⚠ Revisione sospetta: {len(result)} caratteri contro i "
                f"{len(translated_text)} della traduzione (perdita >15%). "
                "Scarto la revisione e mantengo la traduzione della FASE 1 non rivista.")
            return translated_text
        return result

    try:
        return _safe_call(prompt)
    except GeminiError as e:
        log(f"  ⚠ Revisione su testo integrale fallita ({e}). "
            "Provo senza il testo originale a fianco (solo fluidità/refusi).")
        fallback_prompt = PROMPT_FASE2.format(
            testo_originale="[omesso per limiti di dimensione]",
            testo_tradotto=translated_text,
        )
        return _safe_call(fallback_prompt)


# ══════════════════════════════════════════════════════════════════
#  FASE 3 — OLTRE LA LETTURA
# ══════════════════════════════════════════════════════════════════

def fase3_oltre_la_lettura(translated_text: str, api_key: str, model: str,
                            autore: str, titolo: str, anno: str) -> str:
    log("→ FASE 3 — Oltre la lettura…")
    prompt = PROMPT_FASE3.format(autore=autore, titolo=titolo, anno=anno or "sconosciuto",
                                  testo=translated_text)
    return call_with_continuation(prompt, CONTINUA_FASE3, api_key, model,
                                   temperature=0.65, top_p=0.90).strip()


# ══════════════════════════════════════════════════════════════════
#  FASE 4 — NOTE AL TESTO (parsing + inserimento automatico degli span)
# ══════════════════════════════════════════════════════════════════

NOTE_BLOCK_RE = re.compile(
    r"TESTO_ESATTO:\s*(.+?)\s*\n\s*NOTA:\s*(.+?)\s*\n\s*===", re.S
)


def parse_note_blocks(raw: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2).strip()) for m in NOTE_BLOCK_RE.finditer(raw)]


def insert_notes(text: str, notes: list[tuple[str, str]]) -> tuple[str, int, list[str]]:
    """Inserisce <span class="nota" data-nota="...">[N]</span> subito dopo
    ogni TESTO_ESATTO trovato nel testo, in ordine. Ritorna (testo_annotato,
    quante inserite, elenco di TESTO_ESATTO non trovati)."""
    positions: list[tuple[int, str]] = []
    not_found: list[str] = []
    cursor = 0

    for phrase, nota in notes:
        if not phrase:
            continue
        idx = text.find(phrase, cursor)
        if idx == -1:
            idx = text.find(phrase)  # riprova dall'inizio
        if idx == -1:
            not_found.append(phrase)
            continue
        insert_at = idx + len(phrase)
        positions.append((insert_at, nota))
        cursor = insert_at

    positions.sort(key=lambda p: p[0])

    parts = []
    last = 0
    for n, (pos, nota) in enumerate(positions, start=1):
        parts.append(text[last:pos])
        parts.append(f'<span class="nota" data-nota="{escape_note_html(nota)}">[{n}]</span>')
        last = pos
    parts.append(text[last:])

    return "".join(parts), len(positions), not_found


def fase4_note(translated_text: str, oltre_la_lettura: str, api_key: str, model: str,
               autore: str, titolo: str) -> tuple[str, str]:
    """Ritorna (raw_output_modello, testo_annotato)."""
    log("→ FASE 4 — Note al testo…")
    prompt = PROMPT_FASE4.format(
        oltre_la_lettura=oltre_la_lettura or "(nessuna)",
        autore=autore, titolo=titolo, testo=translated_text,
    )
    raw = call_with_continuation(prompt, CONTINUA_FASE4, api_key, model,
                                  temperature=0.15, top_p=0.55)
    notes = parse_note_blocks(raw)
    annotated, n_inserted, not_found = insert_notes(translated_text, notes)
    log(f"  ✓ {n_inserted} note inserite nel testo.")
    if not_found:
        log(f"  ⚠ {len(not_found)} note non collocate (testo non trovato esattamente), "
            "scartate. Controlla il file dei checkpoint per inserirle a mano se vuoi:")
        for phrase in not_found:
            log(f"    · {phrase!r}")
    return raw, annotated


# ══════════════════════════════════════════════════════════════════
#  FASE 5 — PROMPT IMMAGINE (solo testo, nessuna generazione immagine)
# ══════════════════════════════════════════════════════════════════

def fase5_prompt_immagine(translated_text: str, api_key: str, model: str) -> str:
    log("→ FASE 5 — Prompt immagine di copertina…")
    prompt = PROMPT_FASE5.format(testo=translated_text[:12000])
    text, _ = call_gemini(prompt, api_key, model, temperature=0.6, top_p=0.80)
    return text.strip()


# ══════════════════════════════════════════════════════════════════
#  FASE 6 — TAG / CATEGORIA / EXCERPT / SEO
# ══════════════════════════════════════════════════════════════════

def parse_fase6(raw: str) -> dict:
    result = {"category": "", "tags": [], "excerpt": "", "description": ""}
    m = re.search(r"^\s*Categoria:\s*(.+)$", raw, re.M)
    if m:
        result["category"] = m.group(1).strip()
    m = re.search(r"^\s*Tag:\s*(.+)$", raw, re.M)
    if m:
        result["tags"] = [t.strip() for t in m.group(1).split(",") if t.strip()]
    m = re.search(r"^\s*Excerpt:\s*(.+)$", raw, re.M)
    if m:
        result["excerpt"] = m.group(1).strip()
    m = re.search(r"^\s*Meta description:\s*(.+)$", raw, re.M)
    if m:
        result["description"] = m.group(1).strip()
    return result


def resolve_category(raw_category: str) -> str:
    norm = normalize_label(raw_category)
    if norm in CATEGORY_MAP:
        return CATEGORY_MAP[norm]
    for k, v in CATEGORY_MAP.items():
        if k in norm or norm in k:
            return v
    sys.exit(f"Categoria restituita dal modello non riconosciuta: {raw_category!r}. "
              f"Passa --category a mano tra: {', '.join(CATEGORIE_SCHEMA)}")


def validate_tags(raw_tags: list[str]) -> list[str]:
    valid, dropped = [], []
    for t in raw_tags:
        if tagify(t) in TAG_WHITELIST:
            valid.append(tagify(t))
        else:
            dropped.append(t)
    if dropped:
        log(f"  ⚠ Tag fuori dalla lista chiusa, scartati: {', '.join(dropped)}")
    return valid


def fase6_classificazione(translated_text: str, api_key: str, model: str) -> dict:
    log("→ FASE 6 — Tag, categoria, excerpt, SEO…")
    prompt = PROMPT_FASE6.format(tags_block=TAGS_BLOCK_TEXT, testo=translated_text[:20000])
    raw, _ = call_gemini(prompt, api_key, model, temperature=0.1, top_p=0.50)
    parsed = parse_fase6(raw)
    parsed["category"] = resolve_category(parsed["category"]) if parsed["category"] else ""
    parsed["tags"] = validate_tags(parsed["tags"])
    return parsed


# ══════════════════════════════════════════════════════════════════
#  CHECKPOINT SU DISCO (per --resume)
# ══════════════════════════════════════════════════════════════════

STEPS = [
    "00_estratto", "01_traduzione", "02_revisione", "03_oltre_la_lettura",
    "04_note_raw", "04_testo_annotato", "05_prompt_immagine", "06_classificazione_raw",
]


def step_path(work_dir: Path, step: str) -> Path:
    return work_dir / f"{step}.txt"


def load_step(work_dir: Path, step: str) -> Optional[str]:
    p = step_path(work_dir, step)
    return p.read_text(encoding="utf-8") if p.exists() else None


def save_step(work_dir: Path, step: str, content: str) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    step_path(work_dir, step).write_text(content, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════
#  FRONTMATTER + FILE FINALE (stesso schema di content.config.ts)
# ══════════════════════════════════════════════════════════════════

def build_filename(anno: str, autore: str, titolo: str) -> str:
    y = str(anno).strip() if anno else ""
    a = slugify(autore.split()[-1]) if autore else ""
    t = slugify(titolo) if titolo else "racconto"
    segs = [s for s in (y, a, t) if s]
    return "-".join(segs) + ".md"


def build_markdown(args, body_text: str, oltre_text: str, category: str,
                    tags: list[str], description: str, excerpt: str) -> str:
    clean_body = strip_tags_for_reading(body_text)
    wc = word_count(clean_body)
    read_time = max(1, round(wc / 200)) if wc else None

    description = (description or first_sentence(body_text, 155)).strip()
    if len(description) > 160:
        description = description[:157].rstrip() + "…"
    excerpt = (excerpt or description).strip()

    tags_yaml = "[" + ", ".join(f'"{t}"' for t in tags) + "]"

    lines = ["---"]
    lines.append(f'title: "{yaml_escape(args.title)}"')
    lines.append(f'author: "{yaml_escape(args.author)}"')
    lines.append(f'originalLanguage: "{yaml_escape(args.orig_lang)}"')
    lines.append(f'translator: "{yaml_escape(args.translator)}"')
    lines.append(f'category: "{yaml_escape(category)}"')
    lines.append(f'country: "{yaml_escape(args.country)}"')
    if args.year:
        lines.append(f"yearOriginal: {int(args.year)}")
    lines.append(f"tags: {tags_yaml}")
    lines.append(f"isDraft: {str(args.draft).lower()}")
    lines.append(f'description: "{yaml_escape(description)}"')
    if excerpt:
        lines.append(f'excerpt: "{yaml_escape(excerpt)}"')
    lines.append(f'heroImage: "{yaml_escape(args.hero_image or "")}"')
    if args.title_jp:
        lines.append(f'titleJp: "{yaml_escape(args.title_jp)}"')
    if args.original_title:
        lines.append(f'originalTitle: "{yaml_escape(args.original_title)}"')
    if args.period:
        lines.append(f'period: "{yaml_escape(args.period)}"')
    if read_time:
        lines.append(f"readTime: {read_time}")
    if args.note:
        lines.append(f'note: "{yaml_escape(args.note.replace(chr(10), " "))}"')
    if oltre_text:
        lines.append(yaml_block_scalar("oltreLeParole", oltre_text))
    lines.append("---")

    return "\n".join(lines) + "\n\n" + body_text.strip() + "\n"


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Automatizza le 6 fasi di traduzione e produce il .md per src/content/racconti/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    src = p.add_mutually_exclusive_group()
    src.add_argument("--input", help="File di testo con il racconto originale (alternativa a --url).")
    src.add_argument("--url", help="URL con il testo originale (es. Aozora Bunko).")

    p.add_argument("--author", default="", help="Autore (es. 'Osamu Dazai'). Obbligatorio salvo --test-connection.")
    p.add_argument("--title", default="", help="Titolo in italiano. Obbligatorio salvo --test-connection.")
    p.add_argument("--year", default="", help="Anno di pubblicazione originale. Obbligatorio salvo --test-connection.")
    p.add_argument("--title-jp", default="", help="Titolo in giapponese (facoltativo).")
    p.add_argument("--original-title", default="", help="Titolo originale nella lingua di partenza.")
    p.add_argument("--country", default="Giappone")
    p.add_argument("--orig-lang", default="Giapponese", dest="orig_lang")
    p.add_argument("--period", default="", help="Periodo storico (es. 'Periodo Meiji').")
    p.add_argument("--translator", default="", help="Default: nome leggibile del modello usato.")
    p.add_argument("--hero-image", default="", help='Es. "/tigre.png" (file già in public/).')
    p.add_argument("--draft", action="store_true", help="isDraft: true nel frontmatter.")
    p.add_argument("--note", default="", help="Nota breve del traduttore (campo 'note').")

    p.add_argument("--category", default="",
                    help=f"Forza la categoria invece di farla decidere dalla FASE 6. "
                         f"Una tra: {', '.join(CATEGORIE_SCHEMA)}")
    p.add_argument("--tags", default="", help="Forza i tag (separati da virgola) invece della FASE 6.")
    p.add_argument("--description", default="", help="Forza la description invece della FASE 6.")
    p.add_argument("--excerpt", default="", help="Forza l'excerpt invece della FASE 6.")

    p.add_argument("--no-revisione", action="store_true", help="Salta la FASE 2.")
    p.add_argument("--no-oltre", action="store_true", help="Salta la FASE 3.")
    p.add_argument("--no-note", action="store_true", help="Salta la FASE 4.")
    p.add_argument("--no-immagine", action="store_true", help="Salta la FASE 5.")
    p.add_argument("--no-classificazione", action="store_true",
                    help="Salta la FASE 6 (richiede --category a mano).")

    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Default: {DEFAULT_MODEL}")
    p.add_argument("--api-key", default="", help="In alternativa a GEMINI_API_KEY / .env")
    p.add_argument("--chunk-chars", type=int, default=CHUNK_CHARS)

    p.add_argument("--output-dir", default="src/content/racconti")
    p.add_argument("--filename", default="", help="Sovrascrive il nome file automatico.")
    p.add_argument("--work-dir", default="", help="Cartella per i checkpoint intermedi.")
    p.add_argument("--resume", action="store_true", help="Riprende da un lavoro interrotto.")
    p.add_argument("--force", action="store_true", help="Ignora i checkpoint, rifà tutto da capo.")

    p.add_argument("--test-connection", action="store_true",
                    help="Verifica solo che chiave API e modello funzionino, poi esce.")
    p.add_argument("--dry-run", action="store_true",
                    help="Esegue solo l'estrazione e mostra il nome file, senza chiamare l'API.")

    return p


def resolve_api_key(args) -> str:
    load_dotenv_if_present()
    key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        sys.exit(
            "Manca la chiave API di Gemini.\n"
            "Impostala con:  export GEMINI_API_KEY=\"AIza...\"\n"
            "(chiave gratuita su https://aistudio.google.com/apikey)"
        )
    return key


def main() -> None:
    args = build_arg_parser().parse_args()
    if not args.translator:
        args.translator = model_display_name(args.model)

    if args.test_connection:
        api_key = resolve_api_key(args)
        log(f"→ Provo il modello {args.model}…")
        text, finish_reason = call_gemini("Rispondi con una sola parola: OK.", api_key,
                                           args.model, max_retries=1)
        log(f"✓ Risposta: {text!r} (finishReason: {finish_reason})")
        return

    mancanti = [nome for nome, val in
                (("--author", args.author), ("--title", args.title), ("--year", args.year))
                if not val]
    if mancanti:
        sys.exit(f"Argomenti obbligatori mancanti: {', '.join(mancanti)}")

    if args.category and args.category not in CATEGORIE_SCHEMA:
        sys.exit(f"Categoria non valida: {args.category!r}. Valori ammessi:\n  "
                  + "\n  ".join(CATEGORIE_SCHEMA))
    if args.no_classificazione and not args.category:
        sys.exit("--no-classificazione richiede --category (la FASE 6 è disattivata).")

    api_key = "" if args.dry_run else resolve_api_key(args)

    work_dir = Path(args.work_dir) if args.work_dir else Path(
        f"_traduzioni_tmp/{slugify(args.author)}-{slugify(args.title)}"
    )
    if args.force and work_dir.exists():
        for step in STEPS:
            step_path(work_dir, step).unlink(missing_ok=True)
    resuming = args.resume and any(step_path(work_dir, s).exists() for s in STEPS)
    if resuming:
        log(f"↺ Riprendo da: {work_dir}")

    # STEP 0 — estrazione ────────────────────────────────────────────
    original_text = load_step(work_dir, "00_estratto") if resuming else None
    if original_text is None:
        original_text = get_source_text(args)
        if len(original_text) < 40:
            sys.exit("Testo estratto troppo breve. Controlla il file/URL o incolla a mano.")
        save_step(work_dir, "00_estratto", original_text)
    log(f"✓ Testo originale: {word_count(original_text)} parole, {len(original_text)} caratteri.")

    if args.dry_run:
        filename = args.filename or build_filename(args.year, args.author, args.title)
        log(f"[dry-run] Nome file previsto: {filename}")
        log(f"[dry-run] Cartella di lavoro: {work_dir}")
        log("[dry-run] Nessuna chiamata API eseguita.")
        return

    # FASE 1 — traduzione ─────────────────────────────────────────────
    trans1 = load_step(work_dir, "01_traduzione") if resuming else None
    if trans1 is None:
        trans1 = fase1_traduzione(original_text, api_key, args.model, args.author,
                                   args.title, args.chunk_chars, work_dir, resuming)
        save_step(work_dir, "01_traduzione", trans1)
    log(f"  ✓ {word_count(trans1)} parole tradotte.")

    # FASE 2 — revisione ──────────────────────────────────────────────
    if args.no_revisione:
        trans2 = trans1
    else:
        trans2 = load_step(work_dir, "02_revisione") if resuming else None
        if trans2 is None:
            trans2 = fase2_revisione(original_text, trans1, api_key, args.model)
            save_step(work_dir, "02_revisione", trans2)
        log("  ✓ Revisione completata.")

    # FASE 3 — oltre la lettura ───────────────────────────────────────
    oltre_text = ""
    if not args.no_oltre:
        oltre_text = load_step(work_dir, "03_oltre_la_lettura") if resuming else None
        if oltre_text is None:
            oltre_text = fase3_oltre_la_lettura(trans2, api_key, args.model,
                                                 args.author, args.title, args.year)
            save_step(work_dir, "03_oltre_la_lettura", oltre_text)
        log("  ✓ Saggio 'Oltre la lettura' generato.")

    # FASE 4 — note ───────────────────────────────────────────────────
    if args.no_note:
        final_text = trans2
    else:
        annotated = load_step(work_dir, "04_testo_annotato") if resuming else None
        if annotated is None:
            raw_notes, annotated = fase4_note(trans2, oltre_text, api_key, args.model,
                                               args.author, args.title)
            save_step(work_dir, "04_note_raw", raw_notes)
            save_step(work_dir, "04_testo_annotato", annotated)
        final_text = annotated

    # FASE 5 — prompt immagine (solo testo, da usare a mano) ───────────
    if not args.no_immagine:
        img_prompt = load_step(work_dir, "05_prompt_immagine") if resuming else None
        if img_prompt is None:
            img_prompt = fase5_prompt_immagine(trans2, api_key, args.model)
            save_step(work_dir, "05_prompt_immagine", img_prompt)
        log(f"  ✓ Prompt immagine salvato in: {step_path(work_dir, '05_prompt_immagine')}")

    # FASE 6 — classificazione ──────────────────────────────────────────
    category, tags, description, excerpt = args.category, [], args.description, args.excerpt
    tags_cli = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    if not args.no_classificazione:
        raw6 = load_step(work_dir, "06_classificazione_raw") if resuming else None
        if raw6 is None:
            raw6 = call_gemini(
                PROMPT_FASE6.format(tags_block=TAGS_BLOCK_TEXT, testo=trans2[:20000]),
                api_key, args.model, temperature=0.1, top_p=0.50,
            )[0]
            save_step(work_dir, "06_classificazione_raw", raw6)
        parsed = parse_fase6(raw6)
        if not category and parsed["category"]:
            category = resolve_category(parsed["category"])
        if not tags_cli and parsed["tags"]:
            tags_cli = validate_tags(parsed["tags"])
        if not description and parsed["description"]:
            description = parsed["description"]
        if not excerpt and parsed["excerpt"]:
            excerpt = parsed["excerpt"]
        log(f"  ✓ Categoria: {category or '(non determinata)'} · Tag: {', '.join(tags_cli) or '(nessuno)'}")

    if not category:
        sys.exit("Nessuna categoria disponibile: passa --category oppure lascia attiva la FASE 6.")

    tags = tags_cli

    # ASSEMBLAGGIO FINALE ────────────────────────────────────────────
    markdown = build_markdown(args, final_text, oltre_text, category, tags, description, excerpt)

    filename = args.filename or build_filename(args.year, args.author, args.title)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(markdown, encoding="utf-8")

    log(f"\n✓ Fatto. File salvato in: {out_path}")
    if not args.no_immagine:
        log(f"  Prompt immagine (da usare a mano su Midjourney/altro): "
            f"{step_path(work_dir, '05_prompt_immagine')}")
    log(f"  Checkpoint intermedi in: {work_dir} (puoi cancellarli quando sei soddisfatto)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n⚠ Interrotto. Rilancia con --resume per riprendere da dove hai lasciato.")
        sys.exit(1)
    except GeminiError as e:
        sys.exit(f"Errore API Gemini: {e}")
