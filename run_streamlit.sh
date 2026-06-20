#!/bin/bash
source /usr/local/google/home/kid/ai_stock_brain/venv/bin/activate
nohup python3 -m streamlit run /usr/local/google/home/kid/ai_stock_brain/streamlit_app.py --server.port 8501 --server.headless true > streamlit.log 2>&1 &
