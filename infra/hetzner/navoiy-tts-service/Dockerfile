# Navoiy TTS (CosyVoice2) inference mikroservisi — GPU'li Hetzner server
# uchun. TO'LIQ QURILMAGAN/SINALMAGAN — README.md dagi "OCHIQ E'LON
# QILINGAN HOLAT" bo'limiga qarang: bu Dockerfile mantiqan to'g'ri
# qadamlarni yozadi (WebSearch bilan tasdiqlangan commit/checkpoint
# nomlari), lekin GPU'siz bu sandbox'da HAQIQIY BUILD QILIB
# TEKSHIRILMAGAN.
#
# NEGA CUDA BAZA IMAGE. CosyVoice2 GPU'da ishlaydi — torch+CUDA runtime
# kerak. `nvidia/cuda` rasmiy image'lari shu uchun mo'ljallangan.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Python + git (CosyVoice repo klonlash uchun) + ffmpeg (ba'zi audio
# formatlar uchun zaxira, garchi asosiy kodlash PyAV orqali bo'lsa ham)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3-pip git ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

# 1-qadam: CosyVoice repo'ni belgilangan commit'ga klonlash
# (README.md manbalariga ko'ra tasdiqlangan commit hash).
RUN git clone https://github.com/FunAudioLLM/CosyVoice.git && \
    cd CosyVoice && \
    git checkout 074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc && \
    git submodule update --init --recursive

# 2-qadam: CosyVoice'ning o'z bog'liqliklari (torch+CUDA shu yerda,
# ularning requirements.txt'idan — versiyalarni ular belgilaydi).
RUN pip3 install --no-cache-dir -r /opt/CosyVoice/requirements.txt

# 3-qadam: bu servisning o'z HTTP qatlami.
COPY requirements.txt /opt/navoiy-tts-service/requirements.txt
RUN pip3 install --no-cache-dir -r /opt/navoiy-tts-service/requirements.txt

# DIQQAT: quyidagilar BUILD VAQTIDA emas, DEPLOY vaqtida, alohida
# volume/qadam sifatida amalga oshiriladi (image'ni keraksiz
# kattalashtirmaslik uchun — 1.88 GiB checkpoint + baza model):
#   huggingface-cli download FunAudioLLM/CosyVoice2-0.5B \
#       --local-dir /opt/CosyVoice/pretrained_models/CosyVoice2-0.5B
#   huggingface-cli download aisha-org/navoiy-tts --local-dir /opt/navoiy-tts
# (README.md 2-3-qadamlariga qarang — bu docker-compose.gpu.yml'da
# named volume sifatida bog'lanadi, image build'iga kirmaydi.)

COPY server.py /opt/navoiy-tts-service/server.py

EXPOSE 8100

CMD ["python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100", \
     "--app-dir", "/opt/navoiy-tts-service"]
