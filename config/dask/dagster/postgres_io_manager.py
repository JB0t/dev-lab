"""Dagster IO manager that keeps op outputs as pickles in the Dagster PostgreSQL database.

With the Dask executor each op runs on a Dask worker, so an op's output must
be readable from other pods. The dev-lab has no shared filesystem or object
store, but the run pod and every worker already reach Dagster's PostgreSQL.
Outputs are kept until the table is cleared (``DELETE FROM devlab_op_outputs``)
or Dagster is disabled; fine for development data, not for large datasets.
"""

import os
import pickle

import dagster as dg

TABLE = "devlab_op_outputs"


class PostgresPickleIOManager(dg.ConfigurableIOManager):
    hostname: str = "dagster-postgresql"
    port: int = 5432
    username: str = "dagster"
    db_name: str = "dagster"
    # The password comes from the environment, like for the Dagster instance:
    # the chart sets it in run pods, and the Dask workers get it too
    password_env_var: str = "DAGSTER_PG_PASSWORD"

    def _execute(self, statement, parameters=()):
        import psycopg2

        connection = psycopg2.connect(host=self.hostname, port=self.port, user=self.username,
                                      password=os.environ[self.password_env_var], dbname=self.db_name)
        try:
            with connection, connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE TABLE IF NOT EXISTS {TABLE} "
                    "(key text PRIMARY KEY, value bytea NOT NULL, stored_at timestamptz DEFAULT now())"
                )
                cursor.execute(statement, parameters)
                return cursor.fetchone() if cursor.description else None
        finally:
            connection.close()

    def handle_output(self, context: dg.OutputContext, obj):
        import psycopg2

        data = pickle.dumps(obj)
        self._execute(
            f"INSERT INTO {TABLE} (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, stored_at = now()",
            ("/".join(context.get_identifier()), psycopg2.Binary(data)),
        )
        context.add_output_metadata({"pickled_bytes": len(data)})

    def load_input(self, context: dg.InputContext):
        key = "/".join(context.upstream_output.get_identifier())
        row = self._execute(f"SELECT value FROM {TABLE} WHERE key = %s", (key,))
        if row is None:
            raise dg.Failure(f"No stored output {key}; was the upstream op run?")
        return pickle.loads(bytes(row[0]))
