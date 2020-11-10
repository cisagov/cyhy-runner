FROM python:3
MAINTAINER Mark Feldhousen <mark.feldhousen@cisa.dhs.gov>
ENV CYHY_HOME="/home/cyhy" \
    CYHY_RUNNER_SRC="/usr/src/cyhy-runner"

RUN apt-get update && apt-get install -y nmap

RUN groupadd --system cyhy && useradd --system --gid cyhy cyhy

RUN mkdir -p ${CYHY_HOME}
RUN chown -R cyhy:cyhy ${CYHY_HOME}
VOLUME ${CYHY_HOME}

USER root
WORKDIR ${CYHY_RUNNER_SRC}

COPY . ${CYHY_RUNNER_SRC}
RUN pip install --no-cache-dir --requirement requirements.txt

#TODO run as cyhy (needed now for nmap)
USER root
WORKDIR ${CYHY_HOME}

# Use the JSON form of CMD or it will run in bash and not receive signals
CMD ["cyhy-runner", "--stdout-log", "--group", "cyhy", "runner"]
