import json
import os
import re

import streamlit as st
import streamlit.components.v1 as components
from spellchecker import SpellChecker

# Same folder practice.py uses, so lists are shared between the two apps
LISTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lists")
os.makedirs(LISTS_DIR, exist_ok=True)


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

state = st.session_state
state.setdefault("screen", "home")
state.setdefault("words", [])
state.setdefault("word_count", 0)
state.setdefault("current", 0)
state.setdefault("correct_count", 0)
state.setdefault("mistakes", [])
state.setdefault("list_name", "")
state.setdefault("speak_id", 0)


def go(screen):
    state.screen = screen
    st.rerun()


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


def start_practice():
    state.current = 0
    state.correct_count = 0
    state.mistakes = []
    go("practice")


st.title("Spelling Practice")
st.caption("Listen to each word and type how it's spelled.")

if state.screen == "home":
    st.subheader("Saved lists")
    saved_lists = sorted(f[:-4] for f in os.listdir(LISTS_DIR) if f.endswith(".txt"))
    if not saved_lists:
        st.write("No saved lists yet.")
    for name in saved_lists:
        practice_col, view_col = st.columns([4, 1])
        practice = practice_col.button(name, key="list_" + name, use_container_width=True)
        view = view_col.button("View list", key="view_" + name, use_container_width=True)
        if practice or view:
            with open(os.path.join(LISTS_DIR, name + ".txt")) as f:
                state.words = [line.strip() for line in f if line.strip()]
            if practice:
                start_practice()
            state.list_name = name
            state.pop("review_editor", None)  # Forget table edits from a previous list
            go("view")
    if st.button("Make a new list", type="primary"):
        go("count")

elif state.screen == "count":
    st.subheader("New list")
    with st.form("count_form"):
        count = st.number_input("How many words?", min_value=1, step=1)
        if st.form_submit_button("Next", type="primary"):
            state.word_count = int(count)
            state.words = []
            state.list_name = ""
            state.pop("review_editor", None)  # Forget table edits from a previous list
            go("enter")
    if st.button("Cancel"):
        go("home")

elif state.screen == "enter":
    # The total can be changed while entering words, but not below the words already entered
    state.word_count = int(st.number_input(
        "Total words in list", min_value=max(1, len(state.words)), value=state.word_count, step=1))
    if len(state.words) >= state.word_count:
        go("review")
    st.subheader(f"Enter word {len(state.words) + 1} of {state.word_count}")
    with st.form("word_form", clear_on_submit=True):
        word = " ".join(st.text_input("Word").split())
        if st.form_submit_button("Add word", type="primary"):
            # Only accept dictionary words, so typos don't end up in the list
            problem = check_entry(word)
            if problem:
                st.error(problem)
            else:
                state.words.append(word)
                go("enter" if len(state.words) < state.word_count else "review")
    if state.words:
        st.write("Words so far: " + ", ".join(state.words))
        if st.button("Finish list now"):
            go("review")
    if st.button("Cancel"):
        go("home")

elif state.screen in ("review", "view"):
    # "review" is the last step of making a new list; "view" opens a saved list from the home screen
    viewing = state.screen == "view"
    st.subheader(state.list_name if viewing else "Check your list")
    st.write("Click a word to fix it. Use the + below the table to add a word, "
             "or select a row and press Delete to remove it.")
    with st.form("review_form"):
        edited = st.data_editor(
            [{"Word": w} for w in state.words], num_rows="dynamic", hide_index=True,
            use_container_width=True, key="review_editor")
        name = st.text_input("List name", value=state.list_name, placeholder="words").strip() or "words"
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
    if save or skip:
        words = [" ".join((row.get("Word") or "").split()) for row in edited]
        words = [w for w in words if w]
        # Re-check every word, since edits could have added typos
        problems = [f"{w}: {p}" for w in words if (p := check_entry(w))]
        if not words:
            st.error("The list needs at least one word.")
        elif problems:
            for p in problems:
                st.error(p)
        elif save and not re.fullmatch(r"[\w\- ]+", name):
            # Only allow simple names so a list name can't point outside the lists folder
            st.error("List names can only use letters, numbers, spaces, - and _.")
        else:
            state.words = words
            if save:
                with open(os.path.join(LISTS_DIR, name + ".txt"), "w") as f:
                    for word in words:
                        f.write(word + "\n")
            if viewing:
                st.success(f"Saved {len(words)} words to {name}.")
            else:
                start_practice()

elif state.screen == "practice":
    word = state.words[state.current]
    st.subheader(f"Word {state.current + 1} of {len(state.words)}")

    st.write("Press Enter with no answer to hear the word again.")
    with st.form("answer_form", clear_on_submit=True):
        answer = st.text_input("Your answer", autocomplete="off")
        submitted = st.form_submit_button("Check", type="primary")
    if st.button("Hear again") or not submitted or answer == "":
        say(word)
    else:
        # Record the answer and move straight on; results are only shown at the end
        if answer == word:
            state.correct_count += 1
        else:
            state.mistakes.append({"Your spelling": answer, "Correct spelling": word})
        state.current += 1
        go("practice" if state.current < len(state.words) else "results")

elif state.screen == "results":
    st.subheader("Practice session completed")
    st.metric("Score", f"{state.correct_count} out of {len(state.words)} correct")
    if state.mistakes:
        st.write("Words to work on:")
        st.dataframe(state.mistakes, hide_index=True)
    else:
        st.success("You spelled every word correctly!")
    if st.button("Practice again", type="primary"):
        start_practice()
    if st.button("Back to lists"):
        go("home")
