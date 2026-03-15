FROM python:3.11-slim

RUN pip install --no-cache-dir \
        numpy pandas scipy matplotlib statsmodels \
    && pip uninstall -y pip setuptools \
    && rm -rf /root/.cache /tmp/*

COPY runner.py /opt/runner.py

WORKDIR /workspace
USER nobody

ENTRYPOINT ["python3", "/opt/runner.py"]
