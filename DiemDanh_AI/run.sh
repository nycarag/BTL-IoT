#!/bin/bash
cd /home/nycarag/DiemDanh_AI
echo "Dang khoi chay He thong Diem danh AI..."
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
