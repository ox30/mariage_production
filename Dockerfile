FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway fournit $PORT. Une seule instance : SQLite n'accepte pas deux
# conteneurs écrivant sur le même fichier.
#
# `serveur:app` et non `main:app` : une ErreurConfiguration à l'import de `main`
# y est attrapée, et le service démarre en servant la page « configuration à
# corriger » au lieu de mourir en boucle. Mourir rendait le volume
# inatteignable, donc le fichier fautif incorrigible — blocage constaté le
# 25 août.
CMD ["sh", "-c", "uvicorn serveur:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
