# Spacecraft simulator image. Multi-stage: compile on Rocky Linux 10, ship only the binary on
# Rocky Linux 10 minimal (which already has libstdc++). Build context: the repo root.
FROM rockylinux/rockylinux:10.2 AS build
RUN dnf install -y gcc-c++ cmake make && dnf clean all
WORKDIR /src
COPY CMakeLists.txt .
COPY common common
COPY sim sim
COPY fsw fsw
COPY tools tools
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    && cmake --build build --target sim -j

FROM rockylinux/rockylinux:10.2-minimal
COPY --from=build /src/build/sim/sim /usr/local/bin/sim
USER 1000
ENTRYPOINT ["/usr/local/bin/sim"]
CMD ["--orbits", "3", "--speed", "60"]
