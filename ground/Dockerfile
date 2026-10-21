# Ground station image (standard library only, no pip installs). It also carries cmd.py,
# decode.py and the procedures, for `docker compose exec station ...`.
# Build context: the repo root.
FROM python:3.13.14-slim
WORKDIR /app
COPY common/params.hpp common/params.hpp
COPY ground ground
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "ground/station.py"]
