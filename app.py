import json
import os
import re
import urllib.parse
import urllib.request

import pandas as pd
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


def check_entry(entry):
    # Returns a problem message, or None if every word in the entry is spelled correctly
    parts = entry.split()
    if not parts:
        return "Please enter a word."
    misspelled = [p for p in parts if not spell.known([p])]
    if misspelled:
        return f"Not real words: {', '.join(misspelled)}. Please check the spelling."
    # Entries with more than one word must be proper nouns, e.g. "Mediterranean Sea"
    if len(parts) > 1 and any(not p[0].isupper() for p in parts if p.lower() not in JOINING_WORDS):
        return "Entries with more than one word must be names, with each word capitalized (like Mediterranean Sea)."
    return None


@st.cache_data(show_spinner=False)
def look_up_definition(word):
    # Free dictionary API; returns "" if the word isn't found or the site can't be reached
    url = "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word)
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            entries = json.load(response)
        return entries[0]["meanings"][0]["definitions"][0]["definition"]
    except Exception:
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
state.setdefault("list_name", "")
state.setdefault("notice", None)
state.setdefault("speak_id", 0)


def go(screen):
    state.screen = screen
    st.rerun()


def forget_table_edits():
    # The tables remember edits under their keys; clear them when a different list is shown
    state.pop("spelling_editor", None)
    state.pop("vocab_editor", None)


def say(text):
    # Speech happens in the browser; speak_id changes every time so the snippet re-runs even for the same word
    state.speak_id += 1
    components.html(
        f"""<script>
        const synth = (window.parent || window).speechSynthesis;
        synth.cancel();
        synth.speak(new SpeechSynthesisUtterance({json.dumps(text)}));
        </script><!-- {state.speak_id} -->""",
        height=0,
    )


def start_practice(mode=None):
    state.mode = mode or state.mode
    if state.mode == "definition":
        # Only vocabulary words with a definition are in the definition test
        state.test_words = [w for w in state.vocab_words if state.definitions.get(w)]
    else:
        # The spelling test covers both spelling and vocabulary words
        state.test_words = state.spelling_words + state.vocab_words
    state.current = 0
    state.correct_count = 0
    state.mistakes = []
    go("practice")


def show_notice():
    # Messages that need to survive a rerun, shown once
    if state.notice:
        st.info(state.notice)
        state.notice = None


def clean_rows(rows):
    # Turn the table's rows into (word, definition) pairs, dropping empty rows
    def text(value):
        return value if isinstance(value, str) else ""  # New rows can hold None or NaN

    pairs = [(" ".join(text(row.get("Word")).split()), text(row.get("Definition")).strip())
             for row in rows.to_dict("records")]
    return [(w, d) for w, d in pairs if w]


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
        spelling_col, definition_col, view_col = st.columns(3)
        spelling = spelling_col.button("Spelling test", key="spell_" + name, use_container_width=True)
        definition = definition_col.button("Definition test", key="def_" + name, use_container_width=True)
        view = view_col.button("View list", key="view_" + name, use_container_width=True)
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
    st.subheader(state.list_name if viewing else "Check your list")
    show_notice()
    st.write("Click a word or definition to change it. Use the + below a table to add a word, "
             "or select a row and press Delete to remove it.")
    with st.form("review_form"):
        st.markdown("**Spelling words** (spelling test only)")
        spelling_rows = st.data_editor(
            pd.DataFrame({"Word": state.spelling_words}, dtype=str),
            num_rows="dynamic", hide_index=True, use_container_width=True, key="spelling_editor",
            column_config={"Word": st.column_config.TextColumn()})
        st.markdown("**Vocabulary words** (spelling test and definition test)")
        vocab_rows = st.data_editor(
            pd.DataFrame({"Word": state.vocab_words,
                          "Definition": [state.definitions.get(w, "") for w in state.vocab_words]}, dtype=str),
            num_rows="dynamic", hide_index=True, use_container_width=True, key="vocab_editor",
            column_config={"Word": st.column_config.TextColumn(),
                           "Definition": st.column_config.TextColumn(width="large")})
        name = st.text_input("List name", value=state.list_name, placeholder="words").strip() or "words"
        look_up = st.form_submit_button("Look up missing definitions")
        if viewing:
            save = st.form_submit_button("Save changes", type="primary")
            skip = False
            back = st.form_submit_button("Back to lists")
        else:
            save = st.form_submit_button("Save and practice", type="primary")
            skip = st.form_submit_button("Practice without saving")
            back = False
    if back:
        go("home")

    spelling_pairs = clean_rows(spelling_rows)
    vocab_pairs = clean_rows(vocab_rows)
    if look_up:
        with st.spinner("Looking up definitions..."):
            missing = [w for w, d in vocab_pairs if not d]
            found = {w: look_up_definition(w) for w in missing}
        state.spelling_words = [w for w, _ in spelling_pairs]
        state.vocab_words = [w for w, _ in vocab_pairs]
        state.definitions = {w: d or found.get(w, "") for w, d in vocab_pairs if d or found.get(w)}
        state.list_name = name if name != "words" else state.list_name
        not_found = [w for w in missing if not found[w]]
        state.notice = (f"Filled in {len(missing) - len(not_found)} definitions. "
                        "Check them against your book before saving.")
        if not_found:
            state.notice += " No definition found for: " + ", ".join(not_found) + "."
        forget_table_edits()  # Show the tables again with the new definitions
        st.rerun()
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
    if st.button("Practice again", type="primary"):
        start_practice()
    if st.button("Back to lists"):
        go("home")
