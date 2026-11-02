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
state = st.session_state
state.setdefault("screen", "home")
state.setdefault("words", [])
state.setdefault("word_count", 0)
state.setdefault("current", 0)
state.setdefault("correct_count", 0)
state.setdefault("feedback", None)
state.setdefault("mistakes", [])
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
    state.feedback = None
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
        if st.button(name, key="list_" + name, use_container_width=True):
            with open(os.path.join(LISTS_DIR, name + ".txt")) as f:
                state.words = [line.strip() for line in f if line.strip()]
            start_practice()
    if st.button("Make a new list", type="primary"):
        go("count")

elif state.screen == "count":
    st.subheader("New list")
    with st.form("count_form"):
        count = st.number_input("How many words?", min_value=1, step=1)
        if st.form_submit_button("Next", type="primary"):
            state.word_count = int(count)
            state.words = []
            go("enter")
    if st.button("Cancel"):
        go("home")

elif state.screen == "enter":
    st.subheader(f"Enter word {len(state.words) + 1} of {state.word_count}")
    with st.form("word_form", clear_on_submit=True):
        word = st.text_input("Word").strip()
        if st.form_submit_button("Add word", type="primary"):
            # Only accept dictionary words, so typos don't end up in the list
            if not word or not spell.known([word]):
                st.error("That isn't a real word. Please enter a real word.")
            else:
                state.words.append(word)
                go("enter" if len(state.words) < state.word_count else "save")
    if state.words:
        st.write("Words so far: " + ", ".join(state.words))
    if st.button("Cancel"):
        go("home")

elif state.screen == "save":
    st.subheader("Would you like to save the words?")
    with st.form("save_form"):
        name = st.text_input("List name", placeholder="words").strip() or "words"
        save = st.form_submit_button("Save and practice", type="primary")
        skip = st.form_submit_button("Practice without saving")
        if save:
            # Only allow simple names so a list name can't point outside the lists folder
            if not re.fullmatch(r"[\w\- ]+", name):
                st.error("List names can only use letters, numbers, spaces, - and _.")
            else:
                with open(os.path.join(LISTS_DIR, name + ".txt"), "w") as f:
                    for word in state.words:
                        f.write(word + "\n")
                start_practice()
        elif skip:
            start_practice()

elif state.screen == "practice":
    word = state.words[state.current]
    st.subheader(f"Word {state.current + 1} of {len(state.words)}")

    if state.feedback is None:
        st.write("Press Enter with no answer to hear the word again.")
        with st.form("answer_form", clear_on_submit=True):
            answer = st.text_input("Your answer", autocomplete="off")
            submitted = st.form_submit_button("Check", type="primary")
        if st.button("Hear again") or not submitted or answer == "":
            say(word)
        elif answer == word:
            state.correct_count += 1
            state.feedback = (True, "Correct!")
            st.rerun()
        else:
            state.mistakes.append({"Your spelling": answer, "Correct spelling": word})
            state.feedback = (False, f"Incorrect. The correct word is: {word}")
            st.rerun()
    else:
        correct, message = state.feedback
        (st.success if correct else st.error)(message)
        last = state.current + 1 == len(state.words)
        if st.button("See score" if last else "Next word", type="primary"):
            state.feedback = None
            if last:
                go("results")
            state.current += 1
            st.rerun()

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
