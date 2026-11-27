FROM python:3.12-slim

WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl openssl \
    && rm -rf /var/lib/apt/lists/* \
    && for name in russian_trusted_root_ca russian_trusted_sub_ca; do \
         curl -fsSL -o /tmp/${name}.cer https://gu-st.ru/content/Other/doc/${name}.cer; \
         if grep -q "BEGIN CERTIFICATE" /tmp/${name}.cer; then \
           cp /tmp/${name}.cer /usr/local/share/ca-certificates/${name}.crt; \
         else \
           openssl x509 -inform DER -in /tmp/${name}.cer \
             -out /usr/local/share/ca-certificates/${name}.crt; \
         fi; \
         rm -f /tmp/${name}.cer; \
       done \
    && update-ca-certificates

COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /code

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
