#!/bin/bash
# Automatically detects current environment and runs Streamlit in the background
nohup python3 -m streamlit run ui/streamlit_app.py --server.port 8501 --server.headless true > streamlit.log 2>&1 &
