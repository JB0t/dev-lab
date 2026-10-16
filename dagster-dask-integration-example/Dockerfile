FROM ghcr.io/dask/dask:latest

# Establish the code directory
WORKDIR /opt/dagster/app

# 1. Force Pip installation completely inside the active Dask environment folder system
RUN /opt/conda/bin/python -m pip install --no-cache-dir \
    dagster \
    dagster-webserver \
    dagster-k8s \
    dagster-dask \
    dask-kubernetes \
    dagster-aws \
    psycopg2-binary \
    dagster-postgres

# 2. Wrap environment pathing variables to force the runtime to prioritize the dask env
ENV PATH=/opt/conda/envs/dask/bin:/opt/conda/bin:$PATH

# Copy only your core python code file into the image space
COPY repo.py .

