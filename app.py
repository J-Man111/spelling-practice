import html
import json
import os
import random
import re
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st
import streamlit.components.v1 as components
from spellchecker import SpellChecker

# Same folder practice.py uses, so lists are shared between the two apps
LISTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lists")
os.makedirs(LISTS_DIR, exist_ok=True)

# In a list file, words after this line are vocabulary words
VOCAB_HEADER = "[Vocabulary]"


@st.cache_resource
def get_spellchecker():
    return SpellChecker()


spell = get_spellchecker()

# Small words that can stay lowercase inside a name, like "Gulf of Mexico"
JOINING_WORDS = {"of", "the", "and", "de", "la", "du"}

# Abbreviations that start names, like "St. Louis" or "Mt. Everest"
ABBREVIATIONS = {"st.", "mt.", "ft.", "pt.", "mr.", "mrs.", "ms.", "dr."}


def letter_mistakes(a, b):
    # Counts wrong, missing, extra, or swapped letters needed to turn a into b
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def close_enough(answer, word):
    # True when the answer has at most two letter mistakes, e.g. "valient" for "valiant" (case is ignored)
    a, b = " ".join(answer.lower().split()), word.lower()
    return letter_mistakes(a, b) <= 2


def check_entry(entry):
    # Returns a problem message, or None if every word in the entry is spelled correctly
    parts = entry.split()
    if not parts:
        return "Please enter a word."
    # Entries with more than one word must be proper nouns, e.g. "Mediterranean Sea"
    is_name = all(p[0].isupper() for p in parts if p.lower() not in JOINING_WORDS)
    if len(parts) > 1 and not is_name:
        return "Entries with more than one word must be names, with each word capitalized (like Mediterranean Sea)."
    misspelled = [p for p in parts if p.lower() not in ABBREVIATIONS and not spell.known([p])]
    # Place names like "Los Angeles" use words the spell checker doesn't know, so look the whole name up instead
    if misspelled and is_name and len(parts) > 1 and is_known_name(entry):
        misspelled = []
    if misspelled:
        return f"Not real words: {', '.join(misspelled)}. Please check the spelling."
    return None


@st.cache_data(show_spinner=False)
def wiktionary_has(entry):
    # True/False when Wiktionary gives a clear answer (cached); other errors are raised so they're retried later
    try:
        fetch_definition(entry)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def is_known_name(entry):
    # If the lookup can't run (no internet), the name is accepted rather than blocking the list
    try:
        return wiktionary_has(entry)
    except Exception:
        return True


@st.cache_data(show_spinner=False)
def fetch_definition(word):
    # Wiktionary's definition API; it asks apps to identify themselves with a User-Agent.
    # Errors are raised rather than returned, so a failed lookup isn't cached and can be retried.
    request = urllib.request.Request(
        "https://en.wiktionary.org/api/rest_v1/page/definition/" + urllib.parse.quote(word),
        headers={"User-Agent": "SpellingPractice/1.0 (https://github.com/J-Man111/spelling-practice)"})
    with urllib.request.urlopen(request, timeout=5) as response:
        entries = json.load(response).get("en", [])
    for entry in entries:
        for item in entry.get("definitions", []):
            # Definitions come as HTML with links; keep just the text
            text = html.unescape(re.sub(r"<[^>]+>", "", item.get("definition", ""))).strip()
            if text:
                return text
    return ""


@st.cache_data(show_spinner=False)
def fetch_mw_definition(word, key, dictionary):
    # Merriam-Webster's API; the key only works with the dictionary it was registered for
    url = (f"https://www.dictionaryapi.com/api/v3/references/{dictionary}/json/"
           f"{urllib.parse.quote(word)}?key={urllib.parse.quote(key)}")
    with urllib.request.urlopen(url, timeout=5) as response:
        entries = json.load(response)
    # A word that isn't found comes back as a list of suggested spellings (plain strings)
    for entry in entries:
        if isinstance(entry, dict) and entry.get("shortdef"):
            return entry["shortdef"][0]
    return ""


def get_secret(name, default=""):
    # Secrets live in .streamlit/secrets.toml locally, or in the app's settings on Streamlit Cloud
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def look_up_definition(word):
    # Uses Merriam-Webster if a key is set up, otherwise Wiktionary.
    # Returns "" if the word isn't found or the site can't be reached.
    mw_key = get_secret("MW_API_KEY")
    mw_dictionary = get_secret("MW_DICTIONARY", "collegiate")
    for attempt in (word, word.lower()):
        try:
            if mw_key:
                definition = fetch_mw_definition(attempt, mw_key, mw_dictionary)
            else:
                definition = fetch_definition(attempt)
        except Exception:
            definition = ""
        if definition:
            return definition
    return ""


def load_list(name):
    # Spelling words come first, then the [Vocabulary] line, then "word<tab>definition" lines
    spelling_words, vocab_words, definitions = [], [], {}
    in_vocab = False
    with open(os.path.join(LISTS_DIR, name + ".txt")) as f:
        for line in f:
            if line.strip() == VOCAB_HEADER:
                in_vocab = True
                continue
            word, _, definition = line.strip().partition("\t")
            word, definition = word.strip(), definition.strip()
            if not word:
                continue
            # Older lists kept definitions next to spelling words; treat those as vocabulary words
            if in_vocab or definition:
                vocab_words.append(word)
                if definition:
                    definitions[word] = definition
            else:
                spelling_words.append(word)
    return spelling_words, vocab_words, definitions


def save_list(name, spelling_words, vocab_words, definitions):
    with open(os.path.join(LISTS_DIR, name + ".txt"), "w") as f:
        for word in spelling_words:
            f.write(word + "\n")
        if vocab_words:
            f.write(VOCAB_HEADER + "\n")
            for word in vocab_words:
                f.write(f"{word}\t{definitions.get(word, '')}\n")


state = st.session_state
state.setdefault("screen", "home")
state.setdefault("spelling_words", [])
state.setdefault("vocab_words", [])
state.setdefault("definitions", {})
state.setdefault("word_count", 0)
state.setdefault("mode", "spelling")
state.setdefault("test_words", [])
state.setdefault("current", 0)
state.setdefault("correct_count", 0)
state.setdefault("mistakes", [])
state.setdefault("misspelled", [])
state.setdefault("list_name", "")
state.setdefault("notice", None)
state.setdefault("speak_id", 0)


def go(screen):
    state.screen = screen
    st.rerun()


def forget_table_edits():
    # The list editor is rebuilt from spelling_words/vocab_words the next time it's shown
    state.editor_ready = False


def new_row(word="", definition=""):
    # Each row gets an id that's never reused, so its text boxes keep their own values
    state.next_id = state.get("next_id", 0) + 1
    state[f"w{state.next_id}"] = word
    state[f"d{state.next_id}"] = definition
    return state.next_id


def setup_editor():
    state.spelling_ids = [new_row(w) for w in state.spelling_words]
    state.vocab_ids = [new_row(w, state.definitions.get(w, "")) for w in state.vocab_words]
    state.list_name_input = state.list_name
    state.editor_ready = True


# Button callbacks for the list editor; they run before the page redraws
def move_row(row_id, to_vocab):
    source, target = (state.spelling_ids, state.vocab_ids) if to_vocab else (state.vocab_ids, state.spelling_ids)
    source.remove(row_id)
    target.append(row_id)


def delete_row(row_id):
    for ids in (state.spelling_ids, state.vocab_ids):
        if row_id in ids:
            ids.remove(row_id)


def add_row(to_vocab):
    (state.vocab_ids if to_vocab else state.spelling_ids).append(new_row())


def look_up_missing():
    found, not_found = 0, []
    for i in state.vocab_ids:
        word = " ".join(state.get(f"w{i}", "").split())
        if word and not state.get(f"d{i}", "").strip():
            definition = look_up_definition(word)
            if definition:
                state[f"d{i}"] = definition
                found += 1
            else:
                not_found.append(word)
    state.notice = f"Filled in {found} definitions. Check them against your book before saving."
    if not_found:
        state.notice += " No definition found for: " + ", ".join(not_found) + "."


def editor_pairs(ids):
    # The (word, definition) pairs currently typed into the editor, skipping blank rows
    pairs = [(" ".join(state.get(f"w{i}", "").split()), state.get(f"d{i}", "").strip()) for i in ids]
    return [(w, d) for w, d in pairs if w]


# Shared browser-side speech code: the voice list only exists in the browser, so the chosen voice is
# remembered in the browser's localStorage rather than in Streamlit
VOICE_JS = """
const synth = (window.parent || window).speechSynthesis;
const VOICE_KEY = "spellingVoice";
function savedVoiceName() {
    try { return (window.parent || window).localStorage.getItem(VOICE_KEY) || ""; } catch (e) { return ""; }
}
function saveVoiceName(name) {
    try { (window.parent || window).localStorage.setItem(VOICE_KEY, name); } catch (e) {}
}
function englishVoices() {
    // Prefer the clearer neural voices (Edge "Natural"/"Online", Chrome "Google") over the old robotic ones.
    // "Multilingual" voices guess the language from the text, so single words like "prudent" come out French.
    const rank = v => (/multilingual/i.test(v.name) ? 10 : 0)
                    + (/natural/i.test(v.name) ? 0 : /online|google/i.test(v.name) ? 1 : 2)
                    + (v.lang === "en-US" ? 0 : 0.5);
    return synth.getVoices().filter(v => v.lang.startsWith("en")).sort((a, b) => rank(a) - rank(b));
}
function pickVoice() {
    const voices = englishVoices();
    return voices.find(v => v.name === savedVoiceName()) || voices[0];
}
function speak(text) {
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const voice = pickVoice();
    if (voice) { u.voice = voice; u.lang = voice.lang; }
    u.rate = 0.8;  // a bit slower so each sound is distinct
    synth.speak(u);
}
function whenVoicesReady(fn) {
    // The voice list loads in the background the first time, so wait for it if it's still empty
    if (synth.getVoices().length) fn();
    else synth.addEventListener("voiceschanged", fn, {once: true});
}
"""


def say(text):
    # speak_id changes every time so the snippet re-runs even for the same word
    state.speak_id += 1
    components.html(
        f"""<script>{VOICE_JS}
        whenVoicesReady(() => speak({json.dumps(text)}));
        </script><!-- {state.speak_id} -->""",
        height=0,
    )


def voice_picker():
    components.html(
        f"""
        <style>
            body {{ margin: 0; font-family: "Source Sans Pro", sans-serif; font-size: 14px; color: #31333f; }}
            @media (prefers-color-scheme: dark) {{ body {{ color: #fafafa; }} }}
            label {{ display: block; margin-bottom: 4px; }}
            select {{ width: 100%; padding: 6px; font-size: 14px; border-radius: 6px; margin-bottom: 8px; }}
            button {{ padding: 6px 12px; font-size: 14px; border-radius: 6px; cursor: pointer; }}
        </style>
        <label for="voice">Voice</label>
        <select id="voice"></select>
        <button id="test">Test voice</button>
        <script>{VOICE_JS}
        const menu = document.getElementById("voice");
        function fill() {{
            const current = pickVoice();
            menu.innerHTML = "";
            for (const v of englishVoices()) {{
                const opt = new Option(v.name + " (" + v.lang + ")", v.name);
                opt.selected = current && v.name === current.name;
                menu.add(opt);
            }}
            if (!menu.options.length) menu.add(new Option("No English voices found", ""));
        }}
        whenVoicesReady(fill);
        menu.addEventListener("change", () => {{ saveVoiceName(menu.value); speak("prudent"); }});
        document.getElementById("test").addEventListener("click", () => speak("prudent"));
        </script>""",
        height=110,
    )


def start_practice(mode=None):
    state.mode = mode or state.mode
    if state.mode == "definition":
        # Only vocabulary words with a definition are in the definition test
        state.test_words = [w for w in state.vocab_words if state.definitions.get(w)]
        random.shuffle(state.test_words)
    else:
        # The spelling test covers both spelling and vocabulary words, except on Ethan's lists,
        # which only test the spelling words (the name is checked in any capitalization)
        name = state.list_name or state.get("list_name_input", "")
        if "ethan" in name.lower():
            state.test_words = list(state.spelling_words)
        else:
            state.test_words = state.spelling_words + state.vocab_words
        if not state.test_words:
            state.notice = f"{name} has no spelling words to test yet."
            go("view")
            return
    state.current = 0
    state.correct_count = 0
    state.mistakes = []
    state.misspelled = []
    go("practice")


def show_notice():
    # Messages that need to survive a rerun, shown once
    if state.notice:
        st.info(state.notice)
        state.notice = None


with st.sidebar:
    voice_picker()

st.title("Spelling Practice")
st.caption("Listen to each word and type how it's spelled, or read a definition and type the word.")

if state.screen == "home":
    show_notice()
    st.subheader("Saved lists")
    saved_lists = sorted(f[:-4] for f in os.listdir(LISTS_DIR) if f.endswith(".txt"))
    if not saved_lists:
        st.write("No saved lists yet.")
    for name in saved_lists:
        st.markdown(f"**{name}**")
        if state.get("confirm_delete") == name:
            # Deleting can't be undone, so ask first
            st.warning(f"Delete {name} for good? This can't be undone.")
            yes_col, no_col = st.columns(2)
            if yes_col.button("Yes, delete it", key="yes_del_" + name, type="primary", use_container_width=True):
                os.remove(os.path.join(LISTS_DIR, name + ".txt"))
                state.confirm_delete = None
                state.notice = f"Deleted {name}."
                st.rerun()
            if no_col.button("Cancel", key="no_del_" + name, use_container_width=True):
                state.confirm_delete = None
                st.rerun()
            continue
        spelling_col, definition_col, view_col, delete_col = st.columns(4)
        spelling = spelling_col.button("Spelling test", key="spell_" + name, use_container_width=True)
        definition = definition_col.button("Definition test", key="def_" + name, use_container_width=True)
        view = view_col.button("View list", key="view_" + name, use_container_width=True)
        if delete_col.button("Delete list", key="del_" + name, use_container_width=True):
            state.confirm_delete = name
            st.rerun()
        if spelling or definition or view:
            state.spelling_words, state.vocab_words, state.definitions = load_list(name)
            state.list_name = name
            if spelling:
                start_practice("spelling")
            if definition:
                if any(state.definitions.get(w) for w in state.vocab_words):
                    start_practice("definition")
                state.notice = (f"{name} has no vocabulary words with definitions yet. "
                                "Add them in the Vocabulary words table, then save.")
            forget_table_edits()
            go("view")
    if st.button("Make a new list", type="primary"):
        go("count")

elif state.screen == "count":
    st.subheader("New list")
    with st.form("count_form"):
        count = st.number_input("How many words? (spelling and vocabulary together)", min_value=1, step=1)
        if st.form_submit_button("Next", type="primary"):
            state.word_count = int(count)
            state.spelling_words = []
            state.vocab_words = []
            state.definitions = {}
            state.list_name = ""
            forget_table_edits()
            go("enter")
    if st.button("Cancel"):
        go("home")

elif state.screen == "enter":
    entered = len(state.spelling_words) + len(state.vocab_words)
    # The total can be changed while entering words, but not below the words already entered
    state.word_count = int(st.number_input(
        "Total words in list", min_value=max(1, entered), value=state.word_count, step=1))
    if entered >= state.word_count:
        go("review")
    st.subheader(f"Enter word {entered + 1} of {state.word_count}")
    with st.form("word_form", clear_on_submit=True):
        word = " ".join(st.text_input("Word").split())
        is_vocab = st.checkbox("This is a vocabulary word")
        definition = st.text_input("Definition (vocabulary words only)").strip()
        if st.form_submit_button("Add word", type="primary"):
            # Only accept dictionary words, so typos don't end up in the list
            problem = check_entry(word)
            if problem:
                st.error(problem)
            elif definition and not is_vocab:
                st.error("Only vocabulary words have definitions. Check \"This is a vocabulary word\" "
                         "or clear the definition.")
            else:
                if is_vocab:
                    state.vocab_words.append(word)
                    if definition:
                        state.definitions[word] = definition
                else:
                    state.spelling_words.append(word)
                go("enter" if entered + 1 < state.word_count else "review")
    if state.spelling_words:
        st.write("Spelling words so far: " + ", ".join(state.spelling_words))
    if state.vocab_words:
        st.write("Vocabulary words so far: " + ", ".join(state.vocab_words))
    if entered:
        if st.button("Finish list now"):
            go("review")
    if st.button("Cancel"):
        go("home")

elif state.screen in ("review", "view"):
    # "review" is the last step of making a new list; "view" opens a saved list from the home screen
    viewing = state.screen == "view"
    if not state.get("editor_ready"):
        setup_editor()
    st.subheader(state.list_name if viewing else "Check your list")
    show_notice()

    st.markdown("**Spelling words** (spelling test only)")
    for i in state.spelling_ids:
        word_col, move_col, delete_col = st.columns([5, 2, 1], vertical_alignment="center")
        word_col.text_input("Word", key=f"w{i}", label_visibility="collapsed", placeholder="Word")
        move_col.button("Move to vocab", key=f"move{i}", on_click=move_row, args=(i, True),
                        use_container_width=True)
        delete_col.button("✕", key=f"delete{i}", on_click=delete_row, args=(i,), help="Delete this word")
    st.button("+ Add spelling word", on_click=add_row, args=(False,))

    st.markdown("**Vocabulary words** (spelling test and definition test)")
    for i in state.vocab_ids:
        word_col, definition_col, move_col, delete_col = st.columns([3, 5, 2, 1], vertical_alignment="center")
        word_col.text_input("Word", key=f"w{i}", label_visibility="collapsed", placeholder="Word")
        definition_col.text_input("Definition", key=f"d{i}", label_visibility="collapsed", placeholder="Definition")
        move_col.button("Move to spelling", key=f"move{i}", on_click=move_row, args=(i, False),
                        use_container_width=True)
        delete_col.button("✕", key=f"delete{i}", on_click=delete_row, args=(i,), help="Delete this word")
    add_col, look_up_col = st.columns(2)
    add_col.button("+ Add vocabulary word", on_click=add_row, args=(True,))
    with look_up_col:
        st.button("Look up missing definitions", on_click=look_up_missing)

    st.divider()
    name = st.text_input("List name", key="list_name_input", placeholder="words").strip() or "words"
    if viewing:
        save_col, back_col = st.columns(2)
        save = save_col.button("Save changes", type="primary", use_container_width=True)
        skip = False
        back = back_col.button("Back to lists", use_container_width=True)
    else:
        save_col, skip_col = st.columns(2)
        save = save_col.button("Save and practice", type="primary", use_container_width=True)
        skip = skip_col.button("Practice without saving", use_container_width=True)
        back = False
    if back:
        go("home")

    spelling_pairs = editor_pairs(state.spelling_ids)
    vocab_pairs = editor_pairs(state.vocab_ids)
    if save or skip:
        # Re-check every word, since edits could have added typos
        problems = [f"{w}: {p}" for w, _ in spelling_pairs + vocab_pairs if (p := check_entry(w))]
        if not spelling_pairs and not vocab_pairs:
            st.error("The list needs at least one word.")
        elif problems:
            for p in problems:
                st.error(p)
        elif save and not re.fullmatch(r"[\w\- ]+", name):
            # Only allow simple names so a list name can't point outside the lists folder
            st.error("List names can only use letters, numbers, spaces, - and _.")
        else:
            state.spelling_words = [w for w, _ in spelling_pairs]
            state.vocab_words = [w for w, _ in vocab_pairs]
            state.definitions = {w: d for w, d in vocab_pairs if d}
            if save:
                save_list(name, state.spelling_words, state.vocab_words, state.definitions)
            if viewing:
                st.success(f"Saved {len(state.spelling_words)} spelling words and "
                           f"{len(state.vocab_words)} vocabulary words to {name}.")
            else:
                start_practice("spelling")

elif state.screen == "practice":
    word = state.test_words[state.current]
    st.subheader(f"Word {state.current + 1} of {len(state.test_words)}")

    if state.mode == "definition":
        # Hide the word itself if the definition happens to use it
        clue = re.sub(re.escape(word), "_____", state.definitions[word], flags=re.IGNORECASE)
        st.write("Type the word that matches this definition:")
        st.info(clue)
    else:
        st.write("Press Enter with no answer to hear the word again.")
    with st.form("answer_form", clear_on_submit=True):
        answer = st.text_input("Your answer", autocomplete="off")
        submitted = st.form_submit_button("Check", type="primary")
    if state.mode == "spelling" and (st.button("Hear again") or not submitted or answer == ""):
        say(word)
    elif submitted and answer != "":
        # Record the answer and move straight on; results are only shown at the end
        if answer == word:
            state.correct_count += 1
        elif state.mode == "definition" and close_enough(answer, word):
            # The definition test checks that you know the word, so a misspelling still counts
            state.correct_count += 1
            state.misspelled.append({"Your answer": answer, "Correct spelling": word})
        elif state.mode == "definition":
            state.mistakes.append({"Definition": state.definitions[word], "Your answer": answer, "Correct word": word})
        else:
            state.mistakes.append({"Your spelling": answer, "Correct spelling": word})
        state.current += 1
        go("practice" if state.current < len(state.test_words) else "results")

elif state.screen == "results":
    st.subheader("Test completed")
    st.metric("Score", f"{state.correct_count} out of {len(state.test_words)} correct")
    if state.mistakes:
        st.write("Words to work on:")
        st.dataframe(state.mistakes, hide_index=True)
    else:
        st.success("You got every word correct!")
    if state.misspelled:
        st.write("Right word, but check the spelling (these still counted as correct):")
        st.dataframe(state.misspelled, hide_index=True)
    if st.button("Practice again", type="primary"):
        start_practice()
    if st.button("Back to lists"):
        go("home")
