FROM python:2
MAINTAINER Mark Feldhousen <mark.feldhousen@hq.dhs.gov>
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
RUN pip install --no-cache-dir -r requirements.txt

#TODO run as cyhy (needed now for nmap)
USER root
WORKDIR ${CYHY_HOME}

# Use the json form of CMD or it will run in bash and not recieve signals
CMD ["cyhy-runner", "--stdout-log", "--group", "cyhy", "runner"]
