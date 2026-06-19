FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
ENV ARDUPILOT_ROOT=/opt/ardupilot
ENV OMNI_WORKSPACE=/workspace/omnitrainer-sitl

RUN ln -fs /usr/share/zoneinfo/Etc/UTC /etc/localtime \
    && echo "Etc/UTC" > /etc/timezone \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        tzdata \
        ca-certificates \
        git \
        lsb-release \
        python3 \
        python3-dev \
        python3-pip \
        python3-setuptools \
        python3-wheel \
        python3-venv \
        python3-pexpect \
        rsync \
        sudo \
        xterm \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git "${ARDUPILOT_ROOT}"

RUN useradd -m -s /bin/bash ardupilot \
    && chown -R ardupilot:ardupilot "${ARDUPILOT_ROOT}" \
    && echo "ardupilot ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ardupilot \
    && echo 'Defaults env_keep += "DEBIAN_FRONTEND TZ"' > /etc/sudoers.d/keep_env \
    && chmod 0440 /etc/sudoers.d/ardupilot /etc/sudoers.d/keep_env \
    && su - ardupilot -c "cd ${ARDUPILOT_ROOT} && export DEBIAN_FRONTEND=noninteractive && export TZ=Etc/UTC && ./Tools/environment_install/install-prereqs-ubuntu.sh -y"

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python3 -m pip install --no-cache-dir PyYAML pymavlink MAVProxy

COPY docker/entrypoint.sh /usr/local/bin/omni-docker-entrypoint
RUN chmod +x /usr/local/bin/omni-docker-entrypoint

WORKDIR /opt/ardupilot
ENTRYPOINT ["/usr/local/bin/omni-docker-entrypoint"]