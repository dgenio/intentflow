# A small, reproducible image for running IntentFlow in CI or trying it out.
# The runtime core is dependency-free and the simulate backend needs no keys, so
# the demo path works with no network. Add extras at run time if you need real
# backends: `pip install 'intentflow[llm]'`.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="IntentFlow" \
      org.opencontainers.image.description="An experimental language for governed LLM workflows." \
      org.opencontainers.image.source="https://github.com/dgenio/intentflow" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install the package first (better layer caching), then copy examples so the
# demo path is available inside the image.
COPY pyproject.toml README.md LICENSE ./
COPY intentflow ./intentflow
COPY schemas ./schemas
RUN pip install --no-cache-dir .

COPY examples ./examples

# Run as a non-root user.
RUN useradd --create-home --uid 1000 iflow && chown -R iflow:iflow /app
USER iflow

ENTRYPOINT ["intentflow"]
# Default: show help. Override with e.g.
#   docker run --rm intentflow run examples/opensource_triage.iflow --simulate
CMD ["--help"]
