# typst render service: FastAPI + the typst CLI (protocol Markdown -> PDF).
#
# The build installs typst from a pinned GitHub release binary. The binary is a
# static musl build, and the build checks its sha256. Everything a render
# needs ships in the image: the fonts, the HSRT design (the `src/` directory
# of the hsrtreport-typst submodule) and the mitex package. The container
# therefore needs no network at run time.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Pinned typst release (typst/typst). To bump: update the version and BOTH
# sha256 sums of the musl tarballs, then re-check the layout tests
# (`pytest -m integration`), because a compiler bump can move text.
ARG TYPST_VERSION=0.15.1
ARG TYPST_SHA256_AMD64=a6d077d0a95eed5a2eba715b2dae06be954f624ccbf85758a03f389ded33118c
ARG TYPST_SHA256_ARM64=5aa8d74a3d906e60ea12a66ac2f37f8eef1b14cbad7182a745e393a10c23dcee

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates xz-utils; \
    case "$(dpkg --print-architecture)" in \
        amd64) target="x86_64-unknown-linux-musl";  sha256="${TYPST_SHA256_AMD64}" ;; \
        arm64) target="aarch64-unknown-linux-musl"; sha256="${TYPST_SHA256_ARM64}" ;; \
        *) echo "unsupported arch: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${target}.tar.xz"; \
    curl --proto '=https' --tlsv1.2 -fsSL "$url" -o /tmp/typst.tar.xz; \
    echo "${sha256}  /tmp/typst.tar.xz" | sha256sum -c -; \
    tar -xJf /tmp/typst.tar.xz -C /tmp; \
    install -m 0755 "/tmp/typst-${target}/typst" /usr/local/bin/typst; \
    rm -rf /tmp/typst.tar.xz "/tmp/typst-${target}"; \
    apt-get purge -y --auto-remove curl xz-utils; \
    rm -rf /var/lib/apt/lists/*; \
    typst --version

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY fonts ./fonts
COPY packages ./packages
COPY vendor/hsrtreport-typst/src ./vendor/hsrtreport-typst/src
COPY template ./template
COPY typst_service ./typst_service

ENV TYPST_BIN=/usr/local/bin/typst \
    TYPST_FONT_DIRS=/app/fonts:/app/vendor/hsrtreport-typst/src/assets/fonts

# Render a sample protocol per variant. The build fails here, not in
# production, when a font, the design or the math package does not load.
RUN python -m typst_service.selftest

RUN useradd --create-home --uid 10001 typst
USER typst

EXPOSE 8099

CMD ["uvicorn", "typst_service.app:app", "--host", "0.0.0.0", "--port", "8099"]
