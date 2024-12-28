import streamlit as st

# Initialize session state to track button states
if 'button1_disabled' not in st.session_state:
    st.session_state.button1_disabled = False

def clear():
    for key in st.session_state.keys():
        del st.session_state[key]

    
# Callback function to disable Button 1
def disable_button1():
    st.session_state.button1_disabled = True

# Button 1, which disables itself after being clicked once
if st.button('Button 1', on_click=disable_button1, disabled=st.session_state.button1_disabled):
    pass
    #st.rerun()

# Button 2, disabled only if Button 1 is pressed
if st.button('Button 2', on_click=disable_button1, disabled=st.session_state.button1_disabled):
    pass
    
if st.button('Reset', on_click=clear):
    st.rerun()